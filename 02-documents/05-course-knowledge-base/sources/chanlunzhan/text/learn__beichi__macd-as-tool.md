来源：https://chanlunzhan.com/learn/beichi/macd-as-tool
采集时间：2026-11-08T02:32:35+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [动力学与背驰](https://chanlunzhan.com/learn/beichi)

- MACD 只是辅助工具

[阶段 5·动力学与背驰](https://chanlunzhan.com/learn/beichi)·第 1 / 3 节·约 10 分钟

# MACD 只是辅助工具

说清 MACD 在缠论里的定位，避免把指标背离当成缠论背驰。

阶段 0 说过缠论不看指标看结构。但到了这一阶，[MACD](https://chanlunzhan.com/glossary/macd) 出现了。这不矛盾，
只是分工不同。

## MACD 是什么

快速回顾一下算法，因为后面要用到它的细节：

- DIF = 12 [周期](https://chanlunzhan.com/glossary/zhouqi) EMA − 26 周期 EMA

- DEA = DIF 的 9 周期 EMA

- 柱子（MACD 值） = (DIF − DEA) × 2

DIF 反映短期均线偏离长期均线的程度，DEA 是它的平滑，
柱子是两者的差——柱子由正转负就是所谓「死叉」。

参数 12、26、9 是经验值，没有理论依据。这一点要一直记着。

## 缠论用它做什么

给「[力度](https://chanlunzhan.com/glossary/lidu)」一个可计算的代理指标。

阶段 4 结束时，你能判断一段走势是[趋势](https://chanlunzhan.com/glossary/qushi)还是[盘整](https://chanlunzhan.com/glossary/panzheng)。趋势由两个以上[中枢](https://chanlunzhan.com/glossary/zhongshu)构成，
中枢之间有连接段。现在的问题是：这两段推进，哪一段更有力？

「有力」是个直觉概念，要变成可判定的东西，需要一个[量](https://chanlunzhan.com/glossary/chengjiaoliang)化代理。
缠论选了 MACD 柱子围成的面积：

某一段走势的力度 ≈ 这段区间内 MACD 柱子的面积（同号部分求和）

面积大表示这段推进过程中，短期均线持续大幅偏离长期均线，动能强；
面积小表示推进无力。

为什么是面积不是最高值

用柱子的最高值（峰值）也是一种做法，但面积更能反映「整段推进的累积动能」。

一段快速拉升可能峰值很高但持续时间短，面积不大；
一段缓慢但持续的上涨峰值不高，面积却可能更大。
缠论关心的是整段的力度，所以用面积。

## MACD 顶背离 ≠ 缠论背驰

这是本课最重要的一点。

MACD 顶背离：价格创新高，但 MACD 指标（DIF 或柱子峰值）没有创新高。
这是纯指标层面的观察，任何时候都能算，不需要任何结构前提。

缠论[背驰](https://chanlunzhan.com/glossary/beichi)：在一段已确认的趋势中，离开最后一个中枢的那一段，
力度小于进入第一个中枢的那一段。

差别在于缠论背驰有三个结构前提：

- 必须先确认这是一段趋势（至少两个同向中枢）

- 比较的是特定的两段——不是随便两个高点

- 比较的区间由中枢的位置决定，不是由指标形态决定

这是最常见的误用

很多人把「MACD 出现顶背离」直接当成「缠论背驰」，然后困惑于
为什么背驰之后价格还在涨。

原因就是没有结构前提。在一个盘整里，MACD 顶背离可以出现无数次，
每一次都不构成缠论意义上的背驰。

## 在图上对照

图表加载中…

线段段中枢

显示线段段中枢买卖点

真实日线 sz000333，截取 800 根，数据截至 2026-08-28。仅用于结构演示，非实时行情。

图下方是 MACD。打开「[买卖点](https://chanlunzhan.com/glossary/sanleimaimaidian)」层，看看算法标出的位置——
然后对照 MACD，你会发现：并不是每个 MACD 顶背离处都有标记，
标记的位置也不一定是 MACD 最极端的地方。

因为判定的主体是结构，MACD 只是在结构确定之后用来比较力度。

## MACD 的局限

必须承认几件事：

参数是任意的。 换成 (5, 35, 5) 结果会不同。原文用的是默认参数，
后世实现基本沿用，但这是约定不是定理。

面积的计算方式有多种。 从哪根 [K 线](https://chanlunzhan.com/glossary/kline)开始算、算到哪根、
遇到柱子变号怎么处理，不同实现有不同选择。

「回拉零轴」的严格定义。 原文提到过背驰判定中 DIF [回拉零轴](https://chanlunzhan.com/glossary/huilalingzhou)的作用，
但表述不够形式化。包括本站在内，多数实现用的是工程近似。

本站的口径

本站算法：用 MACD 柱子的同号面积作为力度代理，
比较区间由中枢的[进入段](https://chanlunzhan.com/glossary/jinruduan)和[离开段](https://chanlunzhan.com/glossary/lijinzoushi)确定，回拉零轴用工程近似而非原文严格定义。

这些选择会影响背驰的判定结果。到[参数实验室](https://chanlunzhan.com/practice/lab)
可以看不同参数下的差异。

## 一个态度问题

MACD 在缠论里的地位，可以类比为温度计之于医生。

温度计给出一个数，但诊断不是看数字大小决定的——是医生先根据症状
判断可能是什么病，然后用体温这个指标去佐证或排除。

反过来，只看体温计就下诊断，那不叫医学。

## 这一课的要点

- MACD 在缠论里的唯一作用：给「力度」提供可计算的代理指标

- 力度 ≈ 该段区间内 MACD 柱子的同号面积

- MACD 顶背离是纯指标观察；缠论背驰要求先有已确认的趋势

- 比较哪两段由中枢的位置决定，不是由指标形态决定

- MACD 参数任意、面积算法多样、回拉零轴多用工程近似——都是已知的不严格处

## 本课术语

- [MACD](https://chanlunzhan.com/glossary/macd)

- [力度](https://chanlunzhan.com/glossary/lidu)

- [背驰](https://chanlunzhan.com/glossary/beichi)

## 对应原文

[第 24 课教你炒股票24：MACD对背弛的辅助判断](https://chanlunzhan.com/108/24)[第 27 课教你炒股票27： 盘整背驰与历史性底部](https://chanlunzhan.com/108/27)

## 下一课

[动力学与背驰

背驰的判断](https://chanlunzhan.com/learn/beichi/beichi-define)

[← 上一课 · 走势中枢

盘整与趋势](https://chanlunzhan.com/learn/zhongshu/panzheng-qushi)[下一课 · 动力学与背驰 →

背驰的判断](https://chanlunzhan.com/learn/beichi/beichi-define)
