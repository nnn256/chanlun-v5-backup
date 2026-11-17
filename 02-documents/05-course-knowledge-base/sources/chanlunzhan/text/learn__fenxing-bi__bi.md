来源：https://chanlunzhan.com/learn/fenxing-bi/bi
采集时间：2026-11-08T02:32:30+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [基本构件](https://chanlunzhan.com/learn/fenxing-bi)

- 笔

[阶段 2·基本构件](https://chanlunzhan.com/learn/fenxing-bi)·第 3 / 3 节·约 14 分钟

# 笔

在一段陌生 K 线上正确划出所有笔，并说清自己用的是哪种口径。

[分型](https://chanlunzhan.com/glossary/fenxing)太多、太碎，大部分是噪音。[笔](https://chanlunzhan.com/glossary/bi)要解决的就是这个问题：
把密集的分型筛掉一部分，只留下真正划分走势的那些。

## 定义

一笔由一个顶分型和一个底分型连接而成：

- 顶分型在前、底分型在后 → 向下笔

- 底分型在前、顶分型在后 → 向上笔

笔的两个端点分别是两个分型的顶点和底点。所有的笔首尾相接，
上一笔的终点就是下一笔的起点，方向严格交替。

如果只有这条规则，那么每两个相邻的异性分型都能连成一笔，
图上会密密麻麻全是笔——和直接用分型没区别。所以还需要约束。

## 约束一：分型不能共用 K 线

两个分型如果共用了 [K 线](https://chanlunzhan.com/glossary/kline)，不能连成一笔。

顶分型占据三根 K 线，底分型也占据三根。如果顶分型的第三根就是底分型的第一根，
两者重叠，这中间根本没有走出一段像样的走势。

这条约束基本没有争议，各家实现都有。

## 约束二：中间要有独立 K 线

这条就是分歧的来源。

[严格笔](https://chanlunzhan.com/glossary/yangebi)要求：两个分型之间，除去各自占用的三根 K 线，
至少还要有一根独立的 K 线。也就是说，从顶分型的顶点到底分型的底点，
处理后的 K 线序列上至少间隔 4 根。

[宽松笔](https://chanlunzhan.com/glossary/kuansongbi)不要这个额外的独立 K 线，只要求两个分型不共用 K 线，间隔 3 根即可。

为什么会有两种口径

原文对这个问题的表述在连载过程中变过。[第 62 课《分型、笔与线段》](https://chanlunzhan.com/108/62) 和 [第 77 课《一些概念的再分辨》](https://chanlunzhan.com/108/77)
的说法偏严格，[第 79 课《分型的辅助操作与一些问题的再解答》](https://chanlunzhan.com/108/79) 和 [第 80 课《市场没有同情、不信眼泪》](https://chanlunzhan.com/108/80) 的补充说明则给出了更宽松的处理。

后世的实现者读到哪一版、怎么理解，就形成了不同的口径。
这不是谁算错了，是原文本身留下的空间。

## 亲手对比一下

下面这张图可以直接切换两种口径。先看严格笔，再切到宽松笔，
注意笔的数[量](https://chanlunzhan.com/glossary/chengjiaoliang)和位置怎么变：

图表加载中…

分型笔

显示分型笔

笔的口径严格笔宽松笔顶底之间至少隔一根独立 K 线（62 / 77 课）

真实日线 sz002415，截取 200 根，数据截至 2025-01-03。仅用于结构演示，非实时行情。

你会看到：宽松笔明显更多、更碎。在震荡区间里差别最大，
在单边[趋势](https://chanlunzhan.com/glossary/qushi)里两者往往一致。

这不是「哪个更好」的问题

两种口径各有代价。严格笔更干净，但会漏掉一些真实的短转折；
宽松笔捕捉得更全，但噪音更多，往上构造[线段](https://chanlunzhan.com/glossary/xianduan)时容易出现频繁的破坏与回收。

本站默认使用严格笔，因为教学上「先看清骨架」比「捕捉全部细节」重要。
到[参数实验室](https://chanlunzhan.com/practice/lab)可以在真实个股上系统对比。

## 同性分型怎么处理

上一课提到分型不严格交替。划笔时遇到连续的[同性分型](https://chanlunzhan.com/glossary/tongxingfenxing)，规则是
保留更极端的那个：连续两个顶分型保留高的，连续两个底分型保留低的。

道理很直接：笔要刻画的是这一段走势到达的极值，中间那些没能创新高的
局部高点对结构没有贡献。

## 一个常见的判定顺序错误

很多人划笔时是这样做的：从左往右扫，遇到一个分型就试着和上一个连成笔。

这样做在多数情况下对，但在后面出现更极端的同性分型时会错——
你已经画好的笔需要撤销重画。

正确的做法是边扫描边回溯：确认下一个分型时，要检查它是否让之前的判定失效。
本站算法就是这么做的，这也是为什么笔的构造不是一次简单的遍历。

手工画的时候，实用的办法是先把所有分型标出来，再整体划笔，
而不是走一步画一步。

## 笔的意义

划完笔，你手上第一次有了结构：一串首尾相接、方向交替的线段，
每一段都有明确的起点、终点、方向和幅度。

后面所有东西都建立在这上面：

- 若干笔构成线段（阶段 3）

- 若干线段的重叠区间构成[中枢](https://chanlunzhan.com/glossary/zhongshu)（阶段 4）

- 笔本身也可以直接构成[笔中枢](https://chanlunzhan.com/glossary/biZhongshu)，用于观察更小的[级别](https://chanlunzhan.com/glossary/jibie)

所以笔画错了，后面全错。这一阶的通关标准是「给一段陌生 K 线，
能正确划出所有笔」，请务必达到再往下走。

## 这一课的要点

- 一笔连接一个顶分型和一个底分型，方向交替，首尾相接

- 两个分型不能共用 K 线

- 严格笔额外要求中间至少一根独立 K 线，宽松笔不要求——这是真实存在的[口径分歧](https://chanlunzhan.com/glossary/koujingfenqi)

- 连续同性分型保留更极端的那个

- 划笔需要回溯，不能一遍扫过去就定稿

### 试一道

刚学的东西趁热做一道，比读第二遍有用。答错可以重试，也可以直接看解析。

出题

## 本课术语

- [笔](https://chanlunzhan.com/glossary/bi)

- [严格笔](https://chanlunzhan.com/glossary/yangebi)

- [宽松笔](https://chanlunzhan.com/glossary/kuansongbi)

- [分型](https://chanlunzhan.com/glossary/fenxing)

- [口径分歧](https://chanlunzhan.com/glossary/koujingfenqi)

## 对应原文

[第 62 课教你炒股票62：分型、笔与线段](https://chanlunzhan.com/108/62)[第 77 课教你炒股票77：一些概念的再分辨](https://chanlunzhan.com/108/77)[第 79 课教你炒股票79：分型的辅助操作与一些问题的再解答](https://chanlunzhan.com/108/79)[第 80 课教你炒股票80：市场没有同情、不信眼泪](https://chanlunzhan.com/108/80)

## 下一课

[线段

特征序列：线段划分的工具](https://chanlunzhan.com/learn/xianduan/tezheng-xulie)

[← 上一课 · 基本构件

分型](https://chanlunzhan.com/learn/fenxing-bi/fenxing)[下一课 · 线段 →

特征序列：线段划分的工具](https://chanlunzhan.com/learn/xianduan/tezheng-xulie)
