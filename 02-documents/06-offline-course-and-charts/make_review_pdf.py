from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "缠论大白话复习总结.pdf"
FONT = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")

pdfmetrics.registerFont(TTFont("CJK", str(FONT), subfontIndex=0))
pdfmetrics.registerFont(TTFont("CJK-Bold", str(FONT_BOLD), subfontIndex=0))

INK = colors.HexColor("#19333C")
TEAL = colors.HexColor("#187A72")
CORAL = colors.HexColor("#C65B42")
MIST = colors.HexColor("#EEF4F1")
PALE = colors.HexColor("#F4F7F6")
MUTED = colors.HexColor("#52666B")
LINE = colors.HexColor("#D4E0DC")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="TitleCN", fontName="CJK-Bold", fontSize=25, leading=32,
                          textColor=INK, alignment=TA_LEFT, spaceAfter=5 * mm, wordWrap="CJK"))
styles.add(ParagraphStyle(name="SubtitleCN", fontName="CJK", fontSize=11, leading=17,
                          textColor=MUTED, spaceAfter=5 * mm, wordWrap="CJK"))
styles.add(ParagraphStyle(name="SectionCN", fontName="CJK-Bold", fontSize=16, leading=22,
                          textColor=INK, spaceBefore=2 * mm, spaceAfter=3 * mm, wordWrap="CJK"))
styles.add(ParagraphStyle(name="CardTitleCN", fontName="CJK-Bold", fontSize=11, leading=16,
                          textColor=TEAL, spaceAfter=1.2 * mm, wordWrap="CJK"))
styles.add(ParagraphStyle(name="BodyCN", fontName="CJK", fontSize=9.5, leading=15,
                          textColor=INK, spaceAfter=1.5 * mm, wordWrap="CJK"))
styles.add(ParagraphStyle(name="SmallCN", fontName="CJK", fontSize=8, leading=12,
                          textColor=MUTED, wordWrap="CJK"))
styles.add(ParagraphStyle(name="StepNumCN", fontName="CJK-Bold", fontSize=13, leading=18,
                          textColor=TEAL, alignment=TA_CENTER, wordWrap="CJK"))
styles.add(ParagraphStyle(name="StepTitleCN", fontName="CJK-Bold", fontSize=9.5, leading=14,
                          textColor=INK, wordWrap="CJK"))
styles.add(ParagraphStyle(name="CalloutCN", fontName="CJK-Bold", fontSize=10, leading=16,
                          textColor=INK, wordWrap="CJK"))
styles.add(ParagraphStyle(name="TableCN", fontName="CJK", fontSize=8.2, leading=12,
                          textColor=INK, wordWrap="CJK"))
styles.add(ParagraphStyle(name="TableHeadCN", fontName="CJK-Bold", fontSize=8.2, leading=12,
                          textColor=colors.white, wordWrap="CJK"))


def p(text, style="BodyCN"):
    return Paragraph(text, styles[style])


def card(title, body, accent=TEAL):
    data = [[p(title, "CardTitleCN")], [p(body, "BodyCN")]]
    box = Table(data, colWidths=[174 * mm])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, 0), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0.5 * mm),
        ("TOPPADDING", (0, 1), (-1, 1), 0.5 * mm),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 2.5 * mm),
    ]))
    return box


def step_row(number, title, body):
    row = Table([[p(number, "StepNumCN"), p(title, "StepTitleCN"), p(body, "BodyCN")]],
                colWidths=[12 * mm, 37 * mm, 125 * mm])
    row.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), MIST if int(number) % 2 else PALE),
        ("BOX", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
    ]))
    return row


def bullet(text):
    return p("<font color='#187A72'>•</font>  " + text)


def header_footer(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(INK)
    canvas.rect(0, height - 7 * mm, width, 7 * mm, stroke=0, fill=1)
    canvas.setFillColor(TEAL)
    canvas.rect(0, height - 7 * mm, 43 * mm, 7 * mm, stroke=0, fill=1)
    canvas.setFont("CJK", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 9 * mm, "缠论学习复习卡 | 大白话版")
    canvas.drawRightString(width - 18 * mm, 9 * mm, f"{doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4,
                        rightMargin=18 * mm, leftMargin=18 * mm,
                        topMargin=15 * mm, bottomMargin=16 * mm,
                        title="缠论大白话复习总结",
                        author="OpenAI")
story = []

# Page 1: the full structure chain in plain language.
story.extend([
    Spacer(1, 7 * mm),
    p("缠论，简单说", "TitleCN"),
    p("先把行情拆成结构，再比较力量。结构没确认，就先观察；背驰是提醒减速，不是马上掉头。", "SubtitleCN"),
    card("一条主线", "K线整理 -> 分型 -> 笔 -> 线段 -> 中枢 -> 盘整/趋势 -> 背驰 -> 买卖点 -> 小级别确认", TEAL),
    Spacer(1, 4 * mm),
    p("从原始K线到买卖点，按这个顺序学", "SectionCN"),
    step_row("1", "整理K线", "相邻K线互相包含时，按已经形成的方向合并。方向不明就保留不确定，不能看完后面再倒推。"),
    Spacer(1, 1.5 * mm),
    step_row("2", "找分型", "三根整理后的K线里，中间一根高点和低点都高于两边是顶；都低于两边是底。要等右边证据出现才确认。"),
    Spacer(1, 1.5 * mm),
    step_row("3", "连成笔", "底接顶是上笔，顶接底是下笔。两端要交替、隔开，且满足固定的笔规则。笔只是结构，不是买卖点。"),
    Spacer(1, 1.5 * mm),
    step_row("4", "组成线段", "不是每数三笔就切段。程序读取特征序列：无缺口分型、有缺口第二序列、首笔破坏三条路径分别确认；新证据可修订旧端点。"),
    Spacer(1, 1.5 * mm),
    step_row("5", "找中枢", "每个递归层级，只接受连续、完整、同级的下级走势类型重叠；中枢有组件清单和可重算凭据。"),
    Spacer(1, 1.5 * mm),
    step_row("6", "分走势", "一个中枢附近来回，多看作盘整；多个同级别中枢逐步抬高/降低，才有趋势候选。级别要固定。"),
    Spacer(1, 1.5 * mm),
    step_row("7", "比力度", "价格还在往前走，但后段结构或动力变弱，才谈背驰候选。MACD只是证据之一，强趋势可以连续背离。"),
    Spacer(1, 1.5 * mm),
    step_row("8", "等买卖点", "一买试转折，二买看第一次回抽，三买看离开中枢后回拉不进。每个点都要写确认、失效和下一观察位置。"),
])

story.extend([PageBreak(), Spacer(1, 5 * mm),
              p("中枢与走势，抓住这几个区别", "TitleCN"),
              p("中枢就是某一级别里，几段次级别走势反复重叠的价格区域。看它之前，先确认组成它的结构真的是同一级别。", "SubtitleCN"),
              card("中枢四个边界", "ZD = 核心重叠区的下沿；ZG = 核心重叠区的上沿。DD/GG 是整个构造过程中更外侧的最低/最高范围。延伸时外沿可以变，核心不能随意滚动改窄。", TEAL),
              Spacer(1, 4 * mm),
              p("离开中枢后会怎样？", "SectionCN"),
              step_row("1", "延伸", "价格离开又回到原中枢，继续围绕旧核心活动。先当盘整延续看。"),
              Spacer(1, 2 * mm),
              step_row("2", "新生", "价格离开后不回，在外面形成一个新的、与旧核心分离的中枢。两个中枢的位置关系才开始支持趋势判断。"),
              Spacer(1, 2 * mm),
              step_row("3", "扩展", "外面的新中枢又碰到旧中枢，说明在更大级别上可能仍是一个更大的整理区域。"),
              Spacer(1, 5 * mm),
              card("判断趋势别跳级", "上涨中枢常见‘下-上-下’，下跌中枢常见‘上-下-上’。方向来自更大级别背景和组件顺序，不能只看中枢矩形的斜率。", CORAL),
              Spacer(1, 4 * mm),
              card("一个中枢不是趋势", "先固定你正在看的级别。一个中枢里反复来回，先标盘整；两个以上同级别中枢逐步抬高或降低，才是趋势候选。中枢重叠、级别不清时就标‘过渡/不明’。", TEAL),
              Spacer(1, 4 * mm),
              bullet("MACD、成交量、周期倍数都不能替代中枢的级别定义。"),
              bullet("三笔/三段的价格重叠只是几何条件；严格中枢还要求次级别走势组件。")])

story.extend([PageBreak(), Spacer(1, 5 * mm),
              p("背驰和买卖点，不要混为一谈", "TitleCN"),
              p("背驰说的是力量可能变弱；买卖点说的是结构到了某种位置。一个是证据，一个是结构分类。", "SubtitleCN"),
              card("背驰怎么比", "先找两段同方向、同级别、能说清楚的走势。若价格继续创新高/低，但后段线段、内部笔、斜率、MACD或量价动力减弱，记为背驰候选。", TEAL),
              Spacer(1, 4 * mm),
              p("三类买点", "SectionCN"),
              step_row("1", "一买：试转折", "下跌趋势末端出现力度衰减和反向结构。风险高；光有MACD底背离或一个底分型不够。"),
              Spacer(1, 2 * mm),
              step_row("2", "二买：第一次测试", "一买后先有向上运动，再看第一次回调是否守住约定的结构低点；确认关系成立后才是二买候选。"),
              Spacer(1, 2 * mm),
              step_row("3", "三买：离开后不回", "向上离开有效中枢，回拉完成且没有重新进入中枢，再等低级别转强。只有突破、还没回拉验证，不算确认。"),
              Spacer(1, 4 * mm),
              p("卖点是反过来的镜像", "SectionCN"),
              step_row("1", "一卖", "上涨末端的力度衰减和反向结构候选。"),
              Spacer(1, 2 * mm),
              step_row("2", "二卖", "一卖后第一次反弹守不住约定的结构高点。"),
              Spacer(1, 2 * mm),
              step_row("3", "三卖", "向下离开中枢，反弹不重新进入中枢，再等低级别转弱。"),
              Spacer(1, 4 * mm),
              card("背驰是提醒，不是掉头命令", "趋势里MACD可以连续背离。背驰出现后，先等次级别反向结构；如果价格继续延伸、又形成新中枢，原先的背驰候选可能失效。", CORAL)])

story.extend([PageBreak(), Spacer(1, 5 * mm),
              p("多级别与算法：看背景，等确认", "TitleCN"),
              p("不要把周线、30分钟和1分钟的信号拼在一起当成一个结论。每个周期各做一件事。", "SubtitleCN"),
              card("区间套的简单分工", "大级别看方向 -> 操作级别看结构 -> 次级别做确认 -> 更小级别找时点。五倍周期和1分钟进场是课程经验，不是固定公理；关键是结构真的嵌套。", TEAL),
              Spacer(1, 4 * mm),
              card("小转大", "小级别动作突然变得又急又快，可能很快改写大级别结构。重要位置加上低级别力度衰减，只能先记风险候选；要确认更大级别转折，还需原结构被破坏、反向结构站稳并且回拉修复失败。", CORAL),
              Spacer(1, 4 * mm),
              p("现在，整条规则链都能计算", "SectionCN"),
              bullet("基础结构：包含、分型、严格笔；线段按无缺口特征分型、有缺口第二特征序列或首笔破坏确认，并保留修订证据。"),
              bullet("递归结构：确认线段是L0边界；完整、连续、同秩的下级走势类型才可组成上级中枢，逐层保存组成ID和证书。"),
              bullet("走势与信号：同级分解、趋势/盘整、背驰、六类候选、中枢延伸/新生/扩展及小转大诊断。完成分解不等于反转。"),
              bullet("跨周期：先核对证券、复权、收盘时间和OHLCV，再查下级反向中枢破坏/不返回，最后等确认之后的新细级笔触发。"),
              Spacer(1, 3 * mm),
              card("记住最重要的三句话", "1. 先定级别，再认结构。<br/>2. 背驰只报警，结构确认才升级。<br/>3. 结构不清就观察；任何判断都要写确认时间和失效条件。", TEAL),
              Spacer(1, 4 * mm),
              p("本摘要依据课程转写和固定规则规范整理。完整的是已声明profile下的计算链；没有证明所有原著与流派争议均唯一等价。MACD/零轴阈值为辅助研究约定。合成样例不是行情历史，信号不自动执行。", "SmallCN")])

doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
print(OUTPUT)
