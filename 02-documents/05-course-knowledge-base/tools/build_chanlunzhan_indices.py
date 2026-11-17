"""Build source-linked lesson cards, glossary and a complete static-page catalog."""
from __future__ import annotations

import json
import posixpath
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources/chanlunzhan"
STAGES = ["kline-basics", "worldview", "fenxing-bi", "xianduan", "zhongshu", "beichi", "maimaidian", "recursion"]
CARDS = [
    ("what-is-kline", "区分开高低收、实体和影线；一根K线不能恢复内部路径。", "解释两条不同价格路径为何可有相同OHLC。"),
    ("periods-and-levels", "周期是采样，级别来自结构；固定复权、时区和数据截止点。", "解释日线图上的一笔为什么不必然是日线级别走势类型。"),
    ("why-structure", "从价格结构与分类前提开始，指标用于辅助检验。", "指出仅凭MACD金叉无法回答的三个结构问题。"),
    ("zoushi-zhong-wanmei", "完成指结构条件补全，未完成时保留互斥路径。", "写出延续、延伸、转折的候选，不能承诺价格方向。"),
    ("classify-not-predict", "固定级别、边界规则和分解协议，再讨论分类。", "区分完全分类、多义性及实时未完成；不无条件声称分解唯一。"),
    ("levels-and-recursion", "理解自底向上构造与自顶向下检查的对应关系。", "说清线段代理与完整次级别走势类型的区别。"),
    ("baohan", "判定包含后顺既定方向取高高或低低，连续处理并保留来源索引。", "分别手算向上、向下包含；说明开头方向未知的处理政策。"),
    ("fenxing", "去包含后三元素，高低点同时最高为顶、同时最低为底。", "标出端点发生时间与最早确认时间，不把分型直接当反转。"),
    ("bi", "异性分型连接，处理同性极值；明确严格/宽松与间隔口径。", "用中心索引差明确写出本站严格≥4、宽松≥3的约定。"),
    ("tezheng-xulie", "向上段取向下笔，向下段取向上笔；先标准化特征序列。", "给每个特征元素对应的原始笔编号。"),
    ("two-cases", "第一、第二特征元素有无缺口，决定直接确认或等待反向确认。", "分别画无缺口、有缺口、待确认后创新极值的三幅草图。"),
    ("destroy-and-confirm", "区分延续、候选破坏、确认结束，保存确认事件。", "不能把笔破坏、线段破坏、线段终结三个术语混成一件事。"),
    ("cancel-and-recover", "候选失效后归还笔、撤销依赖并重建特征序列。", "向上原段回收向下候选段时，哪些方向的笔进入原段特征序列？"),
    ("zhongshu-define", "中枢严格由至少三个连续次级别走势类型重叠定义。", "分别计算ZD/ZG、DD/GG；另行标注三笔/三线段代理。"),
    ("zhongshu-evolve", "区分原核心延伸、新中枢形成、波动范围重叠与升级。", "核心不重叠但外部波动重叠时，还缺什么检验？"),
    ("panzheng-qushi", "按同级别有效中枢组织判断盘整、上涨和下跌。", "指出只用ZG/ZD核心分离判趋势可能遗漏的扩展情况。"),
    ("macd-as-tool", "MACD是力度代理；固定参数、符号、积分区间和初始化。", "比较面积前说明结构可比性，不能只比较两根柱子的高低。"),
    ("beichi-define", "先确定趋势，再确定相邻相关中枢周围的同向可比段。", "以a+A+b+B+c说明为何不能总拿最初a与末尾c比较。"),
    ("panzheng-vs-qushi-beichi", "先区分一个中枢的盘整语境与多中枢趋势语境。", "说明盘整背驰后仍可能形成第三类点，而非必回旧中枢。"),
    ("first-type", "一类点来自同级别趋势背驰及转折定位。", "补齐趋势、可比段、完成证据后才能给候选升级。"),
    ("second-type", "一买后一上一次级别回试，核对第一次测试和结构完成。", "没有一买上下文的高低点抬高，应保留为普通回抽候选。"),
    ("third-type", "次级别离开后第一次完成回试不回原核心。", "三买对照ZG，三卖对照ZD；触边和未完成回试不算本站严格确认。"),
    ("level-recursion", "完整走势类型才可进入严格递归；有限数据必须声明截断层。", "写明definition_mode及近似损失。"),
    ("multi-level", "大级别定位置背景，小级别检验同一时间区间的内部完成。", "用相同截止时刻对齐，防止事后未来数据进入确认。"),
    ("qujiantao", "逐层限制转折候选区间，每一级都须有可检验的结构。", "数据不足或条件不满足就停止；本站无多周期区间套实证演示。"),
    ("complete-decomposition", "形成包含来源、级别、结构、候选、确认和失效条件的说明。", "给陌生图写一页说明，并用遮挡未来的逐根回放复核。"),
]


def local(rec, from_dir="notes"):
    return posixpath.relpath(rec["text_file"], from_dir)


def safe(text):
    return text.replace("|", "\\|").replace("\n", " ").strip()


def paragraphs_after_title(rec):
    text = (ROOT / rec["text_file"]).read_text(encoding="utf-8")
    start = re.search(r"^# .+$", text, re.M)
    return [p.strip() for p in text[start.end():].split("\n\n") if p.strip()] if start else []


def brief(rec):
    for p in paragraphs_after_title(rec):
        if p.startswith(("又称", "系统学习", "#", "- ")):
            continue
        return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", p).replace("\n", " ")
    return "查看来源正文。"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    records = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    accepted = [r for r in records if r["status"] == "ok"]
    lessons = {r["url"].split("/")[-1]: r for r in accepted if r["category"] == "lesson"}
    if set(lessons) != {x[0] for x in CARDS}:
        raise ValueError("The real lesson catalog differs from the planned 26 cards")
    stage_names = {r["url"].split("/")[-1]: r["title"] for r in accepted if r["category"] == "stage"}
    lines = ["# 缠论站26课学习卡片", "", "整理日期：2026-11-08。每张卡片的‘掌握/自检’为本库整理；课程正文、目录和原文链接来自真实归档。先读[口径核对](15-缠论站口径差异与原文核对.md)，再把网站表述用于研究。", "", "先后顺序是0阶预备加1—7阶；本站称‘七阶’，共8个阶段。", ""]
    current = None
    for number, (slug, concept, check) in enumerate(CARDS, 1):
        rec = lessons[slug]
        stage = urlsplit(rec["url"]).path.split("/")[2]
        if stage != current:
            lines += ["## " + str(STAGES.index(stage)) + "阶：" + stage_names[stage], ""]
            current = stage
        refs = []
        for url in rec["original_refs"]:
            key = urlsplit(url).path.split("/")[-1]
            refs.append(f"[{key}课/篇](../sources/chanlunzhan/text/108__{key}.md)")
        lines += [f"### {number:02d} {rec['title']}", "", f"掌握：{concept}", "", f"自检：{check}", "",
                  f"[本地课程]({local(rec)}) · [在线课程]({rec['url']})", "",
                  "原文对照：" + ("、".join(refs) if refs else "本课为基础入门，页面未列单独原文课号。"), ""]
    (ROOT / "notes/13-缠论站26课学习卡片.md").write_text("\n".join(lines), encoding="utf-8")

    glossaries = [r for r in accepted if r["category"] == "glossary"]
    lines = ["# 缠论站52词条速查", "", "下表释义为原站词典开头的摘要，用于定位资料，不将它们无条件采纳为严格定义。课程与词典之间的冲突见[口径核对](15-缠论站口径差异与原文核对.md)。笔中枢、三段代理、力度阈值等尤其需要区分口径。", "", "| 术语 | 原站摘要 | 归档 | 在线 |", "| --- | --- | --- | --- |"]
    for rec in sorted(glossaries, key=lambda r: r["url"]):
        lines.append(f"| {safe(rec['title'])} | {safe(brief(rec))} | [正文]({local(rec)}) | [原页]({rec['url']}) |")
    lines += ["", "## 按问题找词", "", "- 构件：K线、包含关系、分型、同性分型、笔、严格笔、宽松笔、线段、特征序列、两种情况、线段破坏与回收。", "- 组织：走势中枢、ZG/ZD、GG/DD、进入/离开、延伸、新生、扩展、升级、盘整、趋势、走势类型。", "- 动力学：力度、MACD、回拉零轴、背驰、盘整背驰、趋势背驰。", "- 联立：周期、级别、次级别、递归、多义性、分解、区间套、多级别联立、连接点、未完成。", "- 位置：三类买卖点及其一类、二类、三类。", "", "这52项是该网站的词典覆盖范围，不等同全部缠论概念的穷尽清单。小转大、同级别分解、走势连接、结合律、时点与失效管理，还要结合原文及本库其他笔记继续读。", ""]
    (ROOT / "notes/14-缠论站52词条速查.md").write_text("\n".join(lines), encoding="utf-8")

    originals = [r for r in accepted if r["category"] == "original_reprint"]
    originals.sort(key=lambda r: (0, int(r["url"].split("/")[-1])) if r["url"].split("/")[-1].isdigit() else (1, r["url"]))
    lines = ["# 缠论站113篇原文与补充来源索引", "", "范围：编号1—108课及5篇补充，均为本站转载与导读。本库原有作者站来源保持单独记录，见[原有课号索引](04-原文课程索引.md)。", "", "来源等级：转载正文可以用于定位和交叉阅读；未经逐字版本校勘。页面中的‘导读’由网站编写；评论区、疑似作者回复和正文分别看待，不能因同在一页就全部当作作者定论。", "", "| 编号 | 标题 | 本地正文与导读 | 原页 |", "| --- | --- | --- | --- |"]
    for rec in originals:
        key = rec["url"].split("/")[-1]
        lines.append(f"| {key.upper()} | {safe(rec['title'])} | [归档]({local(rec)}) | [原页]({rec['url']}) |")
    lines += ["", "## 两轮阅读方法", "", "第一轮按26课把框架搭好，只追相应课号；第二轮按1—108的时间顺序阅读，把定义的增补、更正、图例与历史行情区分记录。后续补充不能只看摘要，关键定义要读上下文。", "", "五篇补充的本网站编号为W3、W4、W5、X0596、X0912，属于本站整理目录，不称第109—113课。历史行情、宏观判断及确定收益措辞按历史材料保存。", ""]
    (ROOT / "notes/17-缠论站113篇原文与补充索引.md").write_text("\n".join(lines), encoding="utf-8")

    summary = json.loads((SOURCE / "collection-summary.json").read_text(encoding="utf-8"))
    lines = ["# 缠论站来源归档", "", "来源：https://chanlunzhan.com/。采集日期：2026-11-08（Asia/Shanghai）。", "", f"实际成功{summary['ok']}页：26课、8阶段、52词条、113篇转载/补充、3个目录和3个网站说明页。", "", f"原始静态配图成功{summary.get('static_images_ok', 0)}张；正文图片链接指向本地，原始HTML保留远程引用。", "", "[系统学习总纲](../../notes/12-缠论站系统学习总纲.md) · [26课卡片](../../notes/13-缠论站26课学习卡片.md) · [52词条](../../notes/14-缠论站52词条速查.md) · [口径核对](../../notes/15-缠论站口径差异与原文核对.md) · [练习](../../notes/16-缠论站学习计划与自测.md) · [113篇索引](../../notes/17-缠论站113篇原文与补充索引.md)", "", "## 阅读边界", "", "- 已归档的是静态正文和静态原图。课程客户端生成的图表、训练出题状态、浏览器进度与错题本未离线复现。", "- 根据robots，不批量采集 /practice/、/stocks/、/data/；[跟练](https://chanlunzhan.com/practice)、[拆图](https://chanlunzhan.com/practice/decompose)、[参数实验室](https://chanlunzhan.com/practice/lab)、[个股实验室](https://chanlunzhan.com/stocks)留在线使用。", "- 课程中23页包含图表加载占位，且有合成图和历史日线图；不能将静态文字归档说成已实际核验全部画线。", "- 课程提到的算法行为记录为网站声明，未执行其源码及第81课图例测试。", "- Markdown文本含链接标记及部分评论，字符量不当作作者正文纯字数或学习完成度。", "", "## 完整静态页面目录", "", "| 类别 | 标题 | 本地正文 | 原页 |", "| --- | --- | --- | --- |"]
    for rec in accepted:
        lines.append(f"| {rec['category']} | {safe(rec['title'])} | [正文]({posixpath.relpath(rec['text_file'], 'sources/chanlunzhan')}) | [原页]({rec['url']}) |")
    lines += ["", "## 采集与完整性", "", "[网站清单与SHA-256](manifest.json) · [原图清单](images-manifest.json) · [采集结果](collection-summary.json) · [robots](robots.txt) · [网站地图](sitemap.xml)", "", "复现：在知识库目录运行 `python tools/collect_chanlunzhan.py`（复用哈希一致的现有文件），再运行 `python tools/build_chanlunzhan_indices.py`。", ""]
    (SOURCE / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"lesson_cards": len(lessons), "glossary_entries": len(glossaries), "original_reprints": len(originals), "catalog_pages": len(accepted)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
