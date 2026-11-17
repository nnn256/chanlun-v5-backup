来源：https://chanlunzhan.com/learn/kline-basics/periods-and-levels
采集时间：2026-11-08T02:32:26+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [看懂一张图](https://chanlunzhan.com/learn/kline-basics)

- 周期与级别不是一回事

[阶段 0·看懂一张图](https://chanlunzhan.com/learn/kline-basics)·第 2 / 3 节·约 10 分钟

# 周期与级别不是一回事

说清日线和 30 分钟线的关系，并理解为什么周期只是级别的近似入口。

上一课说过，单根 [K 线](https://chanlunzhan.com/glossary/kline)丢掉了内部过程。想看过程，就换更小的[周期](https://chanlunzhan.com/glossary/zhouqi)。

## 周期是可以嵌套的

一根日线 K 线，如果拆成 30 分钟线，会得到 8 根（A 股每天 4 小时交易）。
这 8 根 30 分钟线的第一根开盘价，就是日线的开盘价；最后一根的收盘价，就是日线的收盘价；
8 根里最高的那个高点，就是日线的最高价。

换句话说，日线是 30 分钟线的汇总，信息完全一致，只是粒度不同。

常用的周期从大到小：月线、周线、日线、60 分钟、30 分钟、5 分钟、1 分钟。
本站的课程和数据基本都用日线，因为日线的数据[量](https://chanlunzhan.com/glossary/chengjiaoliang)适中、结构清晰，适合教学。

## 关键区分：周期不是级别

这里要说一件初学者几乎必然踩的坑。

缠论里到处都是「[级别](https://chanlunzhan.com/glossary/jibie)」这个词——本级别、[次级别](https://chanlunzhan.com/glossary/cijibie)、[级别递归](https://chanlunzhan.com/glossary/diguijibie)。
很多人自然而然地把它理解成 K 线周期：日线是一个级别，30 分钟是次级别。

这是错的，或者说，这只是一个粗糙的近似。

在缠论里，级别是走势结构的级别：由[笔](https://chanlunzhan.com/glossary/bi)构成[线段](https://chanlunzhan.com/glossary/xianduan)，由线段构成[中枢](https://chanlunzhan.com/glossary/zhongshu)，
由中枢构成更大的[走势类型](https://chanlunzhan.com/glossary/zoushileixing)，这个由小到大的构造过程定义了级别。它是从结构里
长出来的，和你打开软件时选的那个周期按钮没有必然关系。

为什么这个区别重要

如果级别就是周期，那么「日线级别的中枢」就等于「在日线图上画出来的中枢」，
两者永远一致。但实际上，30 分钟图上连续几个[中枢升级](https://chanlunzhan.com/glossary/zhongshuzhonghe)之后形成的结构，
可能就是日线级别的一段——而这个结构在日线图上只是几根 K 线，画不出中枢来。

把两者等同，会导致后面第七阶的[多级别联立](https://chanlunzhan.com/glossary/duojibielianli)分析完全做不对。

那为什么大家还是用周期来近似级别？因为方便，而且在多数情况下够用。
原文里也是这么操作的：用 1 分钟、5 分钟、30 分钟、日线这几个周期来对应不同级别，
承认这是近似。到第七阶我们会详细讲这个近似在什么时候会失效。

现在你只需要记住一件事：看到「级别」，想的是结构的大小，不是软件上的周期按钮。

## 同一段走势，不同粒度

下面这张图是日线，你可以先只看 K 线本身：

图表加载中…

显示

真实日线 sz002415，截取 200 根，数据截至 2025-01-03。仅用于结构演示，非实时行情。

如果把它换成 30 分钟线，K 线数量会变成 8 倍，图上会出现大量在日线上看不见的
小幅波动。反过来换成周线，K 线数量减少到五分之一，很多细节被抹平。

走势没有变，变的只是你观察它的分辨率。 缠论的一个核心主张是：
在任何分辨率下，走势都遵循同样的结构规律——这就是递归。

## 复权

最后补一个技术细节。股票分红送股时，价格会出现一个跳空缺口，
这个缺口不是市场行为，是除权造成的。

复权就是把这个人为缺口抹平，让价格序列连续。不复权的数据会在除权日
产生假的跳空，直接影响[分型](https://chanlunzhan.com/glossary/fenxing)和笔的判定。本站使用的数据已做[前复权](https://chanlunzhan.com/glossary/fuquan)处理。

## 这一课的要点

- 周期只是观察走势的分辨率，大周期是小周期的汇总，信息一致

- 缠论的「级别」指走势结构的级别，由笔→线段→中枢的构造过程定义

- 用周期近似级别是原文也采用的做法，但它是近似，第七阶会讲它何时失效

- 数据必须复权，否则除权缺口会造出假的结构

## 本课术语

- [周期](https://chanlunzhan.com/glossary/zhouqi)

- [级别](https://chanlunzhan.com/glossary/jibie)

- [次级别](https://chanlunzhan.com/glossary/cijibie)

## 对应原文

[第 29 课教你炒股票29：转折的力度与级别](https://chanlunzhan.com/108/29)[第 35 课教你炒股票35：给基础差的同学补补课](https://chanlunzhan.com/108/35)

## 下一课

[看懂一张图

为什么缠论不看指标看结构](https://chanlunzhan.com/learn/kline-basics/why-structure)

[← 上一课 · 看懂一张图

一根 K 线里有什么](https://chanlunzhan.com/learn/kline-basics/what-is-kline)[下一课 · 看懂一张图 →

为什么缠论不看指标看结构](https://chanlunzhan.com/learn/kline-basics/why-structure)
