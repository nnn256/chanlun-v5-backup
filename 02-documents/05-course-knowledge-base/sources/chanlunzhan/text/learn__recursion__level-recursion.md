来源：https://chanlunzhan.com/learn/recursion/level-recursion
采集时间：2026-11-08T02:32:38+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [递归与联立](https://chanlunzhan.com/learn/recursion)

- 级别递归的严格表述

[阶段 7·递归与联立](https://chanlunzhan.com/learn/recursion)·第 1 / 4 节·约 13 分钟

# 级别递归的严格表述

用严格概念说清级别递归，并指出这套体系里判定最松的环节。

阶段 1 的第三课用「文章—段落—句子」的类比讲了[递归](https://chanlunzhan.com/glossary/diguijibie)。
现在你已经有了[笔](https://chanlunzhan.com/glossary/bi)、[线段](https://chanlunzhan.com/glossary/xianduan)、[中枢](https://chanlunzhan.com/glossary/zhongshu)、[走势类型](https://chanlunzhan.com/glossary/zoushileixing)这些概念，可以把那个类比换成定义了。

## 递归的严格表述

一个本[级别](https://chanlunzhan.com/glossary/jibie)走势类型，由若干个[次级别](https://chanlunzhan.com/glossary/cijibie)[走势类型连接](https://chanlunzhan.com/glossary/lianjiedian)而成。

具体地：

- 本级别的中枢，由三个连续的次级别走势类型重叠构成

- 本级别的连接段，本身就是一个次级别走势类型

- 因此，本级别走势类型 = 次级别走势类型的有限序列

反过来：任何一个走势类型，都可以作为更高一级的「一段」。

## 和前面学的对不上？

细心的话你会发现一个不一致。

阶段 4 讲中枢时，我们说的是「三段线段的重叠」。
现在说的是「三个次级别走势类型的重叠」。

这两者一样吗？

在多数情况下一样，在级别边界处不一样。

一个线段，如果它内部包含了完整的中枢结构，那它确实是一个次级别走势类型。
但如果它只是几笔的简单连接，内部没有中枢，那它严格说不构成一个走势类型——
它只是一段走势。

为什么实操里用「三段重叠」

因为它可计算、可自动化，而且在大部分情况下和严格定义一致。

严格定义要求先确定次级别的走势类型，而这又需要先确定次次级别……
递归下去没有终点。实际实现必须在某一层截断，用「段」代替「走势类型」
就是最常见的截断方式。

本站算法也是这么做的。这是一个明确的近似，不是 bug。

## 级别升级

递归往上走的机制是[中枢升级](https://chanlunzhan.com/glossary/zhongshuzhonghe)：

当若干个同级别中枢在价格上有重叠、且它们的整体结构满足中枢的定义时，
它们可以合并成一个更高级别的中枢。级别就升了一层。

这听起来清晰，但判定标准是整个缠论体系里最松的一处：

- 几个中枢算够？原文有「三个」的说法，也有更宽松的表述

- 重叠到什么程度算重叠？

- 升级之后，原来的中枢还算不算数？

不同流派在这里的差异最大，也是各种缠论软件结果不一致的主要来源。

本站的保守口径

本站算法只在明确满足重叠条件时才判定升级。

后果是我们可能低估级别：一段实际上已经升级的结构，
在本站可能仍被当作多个低级别中枢处理。

选择保守是有意的：低估级别导致的错误是「看得太细」，
高估级别导致的错误是「看到不存在的大结构」。前者代价小得多。

## 在图上对照两个级别

图表加载中…

笔笔中枢

显示笔线段笔中枢段中枢走势类型

合成数据，619 根，数据截至 2026-05-15。仅用于结构演示，非实时行情。

这张图可以同时显示两个级别的结构：

- 笔 + [笔中枢](https://chanlunzhan.com/glossary/biZhongshu) = 较低级别

- 线段 + 段中枢 = 较高级别

先只看笔中枢，数一数有几个。然后切换到段中枢，再数一遍。

你会发现：几个笔中枢的位置，往往对应一个段中枢。
这就是级别升级在图上的样子——低级别的多个中枢，
在高级别上被合并成一个。

## 用周期近似级别

阶段 0 提过这个问题，现在可以说清楚了。

理论上级别是从结构里长出来的：笔中枢 → 段中枢 → 更高级中枢……
但这个链条依赖中枢升级的判定，而判定是松的。

实操中大家改用[周期](https://chanlunzhan.com/glossary/zhouqi)来近似：

| 近似级别 | 周期 |
| --- | --- |
| 1 分钟级别 | 1 分钟 K 线 |
| 5 分钟级别 | 5 分钟 K 线 |
| 30 分钟级别 | 30 分钟 K 线 |
| 日线级别 | 日 K 线 |

优点是判定完全客观——切换周期就行，没有任何解释空间。

缺点是它和结构级别不严格对应：
30 分钟图上的一个中枢，未必就是「30 分钟级别中枢」，
它可能只是 5 分钟级别的，也可能已经升级到日线级别了。

这个近似什么时候会失效

两种典型情况：

结构远小于周期：日线图上的一个中枢只有几根 K 线，
它的实际级别可能远低于日线。

结构远大于周期：30 分钟图上一个持续几个月的巨大中枢，
它的实际级别已经超过日线。

看到这两种情况，就该切换周期重新看。

## 这一课的要点

- 严格递归：本级别走势类型 = 若干次级别走势类型的连接

- 实操用「三段重叠」代替「三个次级别走势类型重叠」，这是明确的近似

- 级别升级靠中枢合并，判定标准是整个体系最松的一处

- 本站采用保守口径，宁可低估级别也不虚报

- 用周期近似级别的好处是完全客观，代价是在结构与周期不匹配时失效

## 本课术语

- [级别递归](https://chanlunzhan.com/glossary/diguijibie)

- [级别](https://chanlunzhan.com/glossary/jibie)

- [次级别](https://chanlunzhan.com/glossary/cijibie)

- [中枢升级](https://chanlunzhan.com/glossary/zhongshuzhonghe)

- [走势类型](https://chanlunzhan.com/glossary/zoushileixing)

## 对应原文

[第 35 课教你炒股票35：给基础差的同学补补课](https://chanlunzhan.com/108/35)[第 36 课教你炒股票36：走势类型连接结合性的简单运用](https://chanlunzhan.com/108/36)[第 43 课教你炒股票43：有关背驰的补习课](https://chanlunzhan.com/108/43)

## 下一课

[递归与联立

多级别联立](https://chanlunzhan.com/learn/recursion/multi-level)

[← 上一课 · 三类买卖点

第三类买卖点](https://chanlunzhan.com/learn/maimaidian/third-type)[下一课 · 递归与联立 →

多级别联立](https://chanlunzhan.com/learn/recursion/multi-level)
