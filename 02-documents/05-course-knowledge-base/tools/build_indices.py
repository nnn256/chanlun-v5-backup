"""Build source catalogues from collected evidence, without invented course data."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def title_of(item):
    return re.sub(r"\s*\(\d{4}-\d{2}-\d{2}.*", "", re.sub(r"\s+", " ", item.get("title", ""))).strip()


def main():
    site = json.loads((ROOT / "sources/manifest.json").read_text(encoding="utf-8"))
    originals = json.loads((ROOT / "sources/originals/manifest.json").read_text(encoding="utf-8"))
    primary_good = {item["number"]: item for item in originals if item.get("status") == "ok" and item.get("number")}
    supplement_path = ROOT / "sources/supplements/manifest.json"
    supplements = json.loads(supplement_path.read_text(encoding="utf-8")) if supplement_path.exists() else []
    reprints = {item["number"]: item for item in supplements if item.get("status") == "ok"}
    good = {**reprints, **primary_good}
    discovered = {}
    for item in originals:
        for link in item.get("discovered", []):
            discovered[link["number"]] = link
    themes = [
        ("理论基础与走势终完美", [17,18,19,102], "先看完成与延伸的区别，再看中枢与走势类型。"),
        ("中枢、趋势与级别扩张", [17,18,20,63], "核心区间、外围范围、输入对象及结构级别分开。"),
        ("包含与分型", [62,65,77,79,81,82], "方向与比较条件、结合规则及图例修正。"),
        ("笔及后续补充", [62,65,77], "另读2007-09-18新笔补充博文。"),
        ("线段", [62,65,67,71,77,78,81,83], "特征序列、缺口、笔破坏及81课对71课图例的更正。"),
        ("背驰与盘整背驰", [15,24,25,27,37,43], "比较对象与结构前提优先于指标。"),
        ("六类买卖点", [17,20,21,53,101], "前序、首次性、回试结束及边界口径。"),
        ("转折力度、区间套与小转大", [27,29,44,61], "逐级定位与末次级中枢三类点必要条件。"),
        ("多义性、结合性、同级别分解", [33,36,38,39,40], "固定规则后再讨论连接和层次。"),
        ("资金、节奏与操作模型", [26,31,41,45,49,50,103,105], "结构与执行约束分开。"),
        ("心理与学习方法", [1,2,3,19,23,42,52,95,96], "历史观点与可验证结构区别记录。"),
        ("图解示范", [56,57,58,59,60,61,70,88], "正文归档并不等于所有图像已核验。"),
        ("中阴、表里与监视器", [90,91,92,93,99], "观察状态、辅助估计与明确确认分层。"),
        ("几何、动力、均线与轮动", [104,106], "经验、比喻与可计算公式区别记录。"),
        ("短线反弹与底部构造", [107,108], "底部作为过程，分级别并保留失败分支。"),
    ]
    lines = ["# 作者原文课程索引（1—108课）", "", "建立于2026-11-06；作者新浪博客为主要来源。标题和正文状态来自实际采集，不根据课号猜测内容。", "",
             f"当前覆盖**{len(good)}/108课正文**：**{len(primary_good)}课来自作者站**，**{len(reprints)}课以第三方转载补齐**，另有**{sum(i.get('status') == 'ok' and not i.get('number') for i in originals)}篇补充博文**。转载不冒充作者站版本；作者站尚未取到正文的课号：" + "、".join(str(n) for n in range(1,109) if n not in primary_good) + "。", "",
             "主站分类目录提供93课入口；部分课程链接HTTP 200但内容是维护提示，缺少原文容器。移动页抽样也存在不稳定或无正文情况。未将这类返回计为成功，未推断文章永久删除。", "",
             "缺文转载来自公开仓库lufanglei/chanlun，ZIP与各篇原始文本均留存哈希。正文覆盖、主题学习、逐字版本校勘与逐图复现是不同状态；转载仍需与作者版本继续校核。", "", "## 主题阅读路线", "", "| 主题 | 课号 | 核对重点 |", "| --- | --- | --- |"]
    for name, numbers, note in themes:
        refs = "、".join(f"[{n}](../{good[n]['text_file']})" if n in good else str(n) for n in numbers)
        lines.append(f"| {name} | {refs} | {note} |")
    lines += ["", "## 逐课状态", "", "| 课号 | 经采集核对的标题/入口 | 状态 | 本地正文 |", "| --- | --- | --- | --- |"]
    for number in range(1,109):
        item = good.get(number)
        if item:
            title = title_of(item).replace("|", "\\|")
            state = "转载补齐，待作者版本校核" if item.get("source_type") == "third_party_reprint" else "作者站正文已归档"
            lines.append(f"| {number} | [{title}]({item['url']}) | {state} | [阅读](../{item['text_file']}) |")
        elif number in discovered:
            entry = discovered[number]
            title = entry["title"].replace("|", "\\|")
            lines.append(f"| {number} | [{title}]({entry['url']})（由课程内链接定位） | 主站未取得原文正文；待补 | — |")
        else:
            lines.append(f"| {number} | 本次未定位到可用的作者正文入口，不补写未核对标题 | 待补来源与正文 | — |")
    lines += ["", "## 非编号补充", ""]
    for item in originals:
        if item.get("status") == "ok" and not item.get("number"):
            lines.append(f"- [{title_of(item)}]({item['url']})：[本地正文](../{item['text_file']})。2007-09-18发表，补充笔的条件；不能遗漏于编号课程之外。")
    lines += ["", "## 进一步补齐的标准", "", "待补条目只有在取得实际正文、核对作者/课号/日期并记录来源后，才能改成成功。引用第三方整理版时另注明转载来源及与作者版本的差异；本次未自动用来源不明的转载填空。原图缺失、后续更正与版本问题须分别处理。", ""]
    (ROOT / "notes/04-原文课程索引.md").write_text("\n".join(lines), encoding="utf-8")
    lines = ["# 来源目录", "", "采集日期：2026-11-06，Asia/Shanghai。原始HTML、正文抽取与清单为本地学习核对材料，原始权利归作者/站点。", "",
             f"网站学习相关页：{len(site)}篇，成功{sum(i['status']=='ok' for i in site)}篇。课程正文共{len(good)}篇：作者站{len(primary_good)}篇，转载补齐{len(reprints)}篇；另有补充博文1篇。", "",
             "网站范围为sitemap中的中文学习/工具页面；排除首页、英繁体重复、隐私与协议。网站正文已抓取，核心规则及关键原文主题已核对；兼容与软件行为是文档声明，未逐个平台运行验证。", "",
             "## 网站页面", "", "| 编号 | 主题 | 在线原页 | 本地正文 | 抓取状态 |", "| --- | --- | --- | --- | --- |"]
    for i, item in enumerate(site, 1):
        if item["status"] == "ok":
            title = item["title"].replace("|", "\\|")
            lines.append(f"| SG{i:02} | {title} | [原页]({item['url']}) | [正文]({item['text_file']}) | HTTP {item['http_status']}，正文已归档 |")
        else:
            lines.append(f"| SG{i:02} | — | [原页]({item['url']}) | — | {item.get('error')} |")
    lines += ["", "## 作者课程与采集证据", "", "- [逐课索引](notes/04-原文课程索引.md)", "- [网站清单与哈希](sources/manifest.json)", "- [作者原文清单与哈希](sources/originals/manifest.json)", "- [作者分类目录入口](sources/originals/catalog-links.json)", "- [主站/移动页访问抽样](sources/originals/access-probes.json)", "- [B站公开接口结果](sources/bilibili-public-metadata.json)", "", "主站返回维护页与移动页出现正文/空白的现象均有实际采集记录，不能仅按HTTP状态码判断正文可用。", "", "## 既有本地资料", "", "上层目录的原学习材料、课程转写与算法均保留；它们的来源和实现口径按各自说明，不与本网站5集课程合并计数。", ""]
    (ROOT / "来源目录.md").write_text("\n".join(lines), encoding="utf-8")
    stats = {"site_pages": len(site), "site_ok": sum(i['status']=="ok" for i in site), "course_texts": len(good), "original_courses": len(primary_good), "reprint_courses": len(reprints), "original_supplements": sum(i.get("status")=="ok" and not i.get("number") for i in originals), "missing_courses": [n for n in range(1,109) if n not in good], "missing_author_site_courses": [n for n in range(1,109) if n not in primary_good], "video_scope": "official companion text and links; no full video viewing or transcription"}
    (ROOT / "sources/coverage.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
