来源：https://chanlunzhan.com/learn/recursion/qujiantao
采集时间：2026-11-08T02:32:39+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [递归与联立](https://chanlunzhan.com/learn/recursion)

- 区间套

[阶段 7·递归与联立](https://chanlunzhan.com/learn/recursion)·第 3 / 4 节·约 12 分钟

# 区间套

理解区间套的原理，能手工在两三个级别上做一次逼近。

这一课没有演示图

站内的结构标注覆盖[分型](https://chanlunzhan.com/glossary/fenxing)、[笔](https://chanlunzhan.com/glossary/bi)、[线段](https://chanlunzhan.com/glossary/xianduan)、[中枢](https://chanlunzhan.com/glossary/zhongshu)、[背驰](https://chanlunzhan.com/glossary/beichi)和[买卖点](https://chanlunzhan.com/glossary/sanleimaimaidian)，
但不包括[区间套](https://chanlunzhan.com/glossary/qujiantao)——它需要同一只标的的多个[周期](https://chanlunzhan.com/glossary/zhouqi)数据，站内目前只有日线。

所以本课只讲原理和手工做法。这一点照实说明，不用演示图凑数。

## 问题：背驰点是个区间

上一阶讲背驰时留了个尾巴：背驰的位置不是一个点，是一段范围。

原因是判定需要「[离开段](https://chanlunzhan.com/glossary/lijinzoushi)走完」。而离开段是一段走势，
它有几十根 [K 线](https://chanlunzhan.com/glossary/kline)的跨度。你只能说「背驰发生在这一段里」，
不能说「就是这一根 K 线」。

对学习者来说这个精度够了。但缠论提供了一个把范围缩小的方法。

## 区间套的原理

原理来自数学里的区间套定理：一列层层嵌套、长度趋于零的闭区间，
必然收敛到唯一一个点。

缠论的应用方式是：

- 在大级别上判定背驰，得到一个范围 —— 比如日线[级别](https://chanlunzhan.com/glossary/jibie)的最后一段

- 把这个范围切到次级别看。在[次级别](https://chanlunzhan.com/glossary/cijibie)上，这一段本身是一个完整的[走势类型](https://chanlunzhan.com/glossary/zoushileixing)

- 在次级别上再判定一次背驰，得到一个更小的范围

- 继续切到次次级别，重复

每往下一级，范围就缩小一个数[量](https://chanlunzhan.com/glossary/chengjiaoliang)级。三到四级之后，
范围已经小到可以看作一个点。

为什么每一级都能判背驰

因为[递归](https://chanlunzhan.com/glossary/diguijibie)。大级别的最后一段，在次级别上是一个完整的走势类型；
既然是完整的走势类型，它就有自己的中枢、自己的[进入段](https://chanlunzhan.com/glossary/jinruduan)和离开段，
自然可以判定自己的背驰。

这正是级别递归最漂亮的应用：同一套判定规则，
在每一层上重复使用。

## 手工做法

假设你在日线上判定了一个趋势背驰：

第一层（日线）：最后一个中枢的离开段，跨度约 30 根日 K 线。
背驰点在这 30 根之内。

第二层（30 分钟）：把这 30 根日 K 展开成 30 分钟，
得到约 240 根。在这 240 根上，那一段日线离开段是一个完整的
30 分钟级别走势类型。对它做完整分析：划笔、划线段、找中枢。
如果它也构成趋势且发生背驰，背驰点落在它的最后一段里——
可能只有 20 根 30 分钟 K 线，相当于 2.5 个交易日。

第三层（5 分钟）：继续展开，范围可能缩小到几个小时。

三层下来，范围从「一个多月」缩小到「几个小时」。

## 收敛条件

区间套不总是能一路收敛下去。两个终止条件：

次级别不构成趋势。如果展开后发现它是个盘整，
那么谈不上趋势背驰，逼近到此为止。这时可以用盘整背驰，
但结论的强度弱一些。

级别太小失去意义。1 分钟以下的结构受成交细节影响太大，
噪音超过信号。实践中降到 1 分钟或 5 分钟就该停。

别把区间套当精确制导

区间套能把范围缩小，但不能消除不确定性。

每一层的背驰判定本身都有口径问题（MACD 参数、面积算法、回拉零轴），
层层叠加之后，误差不会因为范围变小而消失。

而且最关键的一点：每一层的判定都需要该层的走势走完。
所以区间套和背驰一样，是事后确认的工具，不是实时定位的工具。

## 为什么它值得学

即使不用于实操，区间套也值得理解，因为它是缠论内部逻辑一致性的最好证明。

一套理论如果只在某个特定尺度上成立，那它就是一堆经验规则。
而区间套展示的是：同一套定义，在任意尺度上重复应用，
结果是相容的、可以层层嵌套的。

这是缠论区别于经验型技术分析的地方——它是一个有内部结构的体系，
不是规则的集合。

## 这一课的要点

- 背驰的位置是一个范围（离开段的跨度），不是一个点

- 区间套：在次级别上重新判定背驰，逐级缩小范围

- 每级都能判定是因为递归——大级别的一段在次级别上是完整走势类型

- 终止条件：次级别不构成趋势，或级别小到失去意义

- 它和背驰一样是事后确认的工具，缩小范围不等于消除不确定性

## 本课术语

- [区间套](https://chanlunzhan.com/glossary/qujiantao)

- [背驰](https://chanlunzhan.com/glossary/beichi)

- [多级别联立](https://chanlunzhan.com/glossary/duojibielianli)

- [级别递归](https://chanlunzhan.com/glossary/diguijibie)

## 对应原文

[第 43 课教你炒股票43：有关背驰的补习课](https://chanlunzhan.com/108/43)[第 84 课教你炒股票84：本ID理论一些必须注意的问题](https://chanlunzhan.com/108/84)

## 下一课

[递归与联立

走势分解的完全分类](https://chanlunzhan.com/learn/recursion/complete-decomposition)

[← 上一课 · 递归与联立

多级别联立](https://chanlunzhan.com/learn/recursion/multi-level)[下一课 · 递归与联立 →

走势分解的完全分类](https://chanlunzhan.com/learn/recursion/complete-decomposition)
