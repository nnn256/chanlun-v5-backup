来源：https://chanlunzhan.com/learn/beichi/beichi-define
采集时间：2026-11-08T02:32:36+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [动力学与背驰](https://chanlunzhan.com/learn/beichi)

- 背驰的判断

[阶段 5·动力学与背驰](https://chanlunzhan.com/learn/beichi)·第 2 / 3 节·约 12 分钟

# 背驰的判断

在一段趋势里判断是否发生背驰，并说明依据。

上一课讲了[力度](https://chanlunzhan.com/glossary/lidu)怎么[量](https://chanlunzhan.com/glossary/chengjiaoliang)化。这一课用它来定义[背驰](https://chanlunzhan.com/glossary/beichi)。

## 定义

在一段[趋势](https://chanlunzhan.com/glossary/qushi)中，如果离开最后一个[中枢](https://chanlunzhan.com/glossary/zhongshu)的那一段，力度小于进入第一个中枢的那一段，
就构成背驰。

拆开看有三个要素：

- 前提是趋势——必须已经确认这是趋势（两个及以上同向中枢），
[盘整](https://chanlunzhan.com/glossary/panzheng)里不谈[趋势背驰](https://chanlunzhan.com/glossary/qushibeichi)

- 比较的对象是特定的两段——最后的[离开段](https://chanlunzhan.com/glossary/lijinzoushi) vs 最初的[进入段](https://chanlunzhan.com/glossary/jinruduan)

- 比较的内容是力度——用 [MACD](https://chanlunzhan.com/glossary/macd) 面积代理

## 为什么比较这两段

因为它们代表趋势的起点动能和终点动能。

一段上涨趋势的过程是：一股力量把价格推上去（进入段），
在某个位置盘整形成中枢，然后再推上去（离开段），
到更高位置再形成中枢……最后一次推升就是最后的离开段。

如果最后这次推升的力度已经不如最开始那一次，
说明推动这段趋势的力量在衰竭。

背驰说的是什么

背驰是对已发生的力度对比的描述，不是对未来的预言。

「力量在衰竭」是一个关于过去的观察：确实，后一段推得没前一段有力。
至于衰竭之后会怎样——转折、盘整、还是重新加速——背驰本身不回答。

## 判定流程

机械化的步骤：

- 确认这是一段趋势（数中枢，检查依次同向）

- 找到第一个中枢的进入段，计算它的 MACD 面积 S₁

- 找到最后一个中枢的离开段，计算它的 MACD 面积 S₂

- 如果 S₂ < S₁，构成背驰

配合两个辅助条件（不同实现的采纳程度不同）：

- 价格创新高（低）：离开段的极值要超过前一段，否则谈不上「更弱地推到更远」

- DIF [回拉零轴](https://chanlunzhan.com/glossary/huilalingzhou)：趋势中间 DIF 曾回到零轴附近，说明中枢确实起到了动能重置的作用

回拉零轴是工程近似

第二个条件在原文里的表述不够形式化，本站算法用的是近似实现：
检查[中枢区间](https://chanlunzhan.com/glossary/zg-zd)内 DIF 是否穿越或接近过零轴。

不同实现在这里差异较大，也有实现完全不检查这个条件。
这是背驰判定结果不一致的主要来源之一。

## 在图上看

图表加载中…

线段段中枢买卖点

显示线段段中枢买卖点走势类型

真实日线 sz000333，截取 800 根，数据截至 2026-08-28。仅用于结构演示，非实时行情。

图上的标记就是算法识别出的背驰位置和买卖点。

对照下方的 MACD 观察：在标记处，价格往往创了新高（或新低），
但 MACD 柱子围出的面积明显小于趋势开始时那一段。

## 背驰之后会怎样

按定义，背驰只说明力度衰竭。但在缠论体系里，背驰有一个结构性的后果：

趋势背驰意味着这段趋势的结束，后面会走出一个「至少是[次级别](https://chanlunzhan.com/glossary/cijibie)」的反向走势。

注意这句话的两个限定：

- 「至少是次级别」——反向走势可能很小，只是次[级别](https://chanlunzhan.com/glossary/jibie)的一段回抽，
远不到反转的程度

- 「趋势结束」不等于「反向趋势开始」——趋势结束后可能进入盘整，
在原地震荡很久

背驰不是买卖信号

把背驰当成「见顶了可以卖」是最典型的误用。理由：

- 背驰之后可能只是次级别回抽，然后继续原方向

- 背驰的判定依赖 MACD 面积，而面积的算法有多种口径，
同一段走势不同工具会给出不同结论

- 背驰的确认需要离开段走完，而离开段走完时价格已经在那个位置了

本站讲背驰，讲的是它作为走势结构的一个性质，
不涉及任何操作含义。

## 一个思维练习

看一段趋势，问自己三个问题：

- 这真的是趋势吗？（数中枢，至少两个，依次同向）

- 进入段和离开段分别是哪两段？（在图上指出来）

- 哪一段的 MACD 面积更大？（目测即可）

三个问题都能回答，就掌握了背驰的判定。第 1 问回答不了的，
说明阶段 4 需要回炉。

## 这一课的要点

- 背驰 = 趋势中，最后一个中枢的离开段力度 < 第一个中枢的进入段力度

- 前提必须是已确认的趋势，盘整里不谈趋势背驰

- 辅助条件：价格创新高（低）、DIF 回拉零轴（后者是工程近似）

- 背驰意味着趋势结束，后面至少有次级别反向走势——但不等于反转

- 背驰是对已发生力度的描述，不预言未来，更不是买卖信号

## 本课术语

- [背驰](https://chanlunzhan.com/glossary/beichi)

- [力度](https://chanlunzhan.com/glossary/lidu)

- [趋势](https://chanlunzhan.com/glossary/qushi)

- [回拉零轴](https://chanlunzhan.com/glossary/huilalingzhou)

- [走势中枢](https://chanlunzhan.com/glossary/zhongshu)

## 对应原文

[第 24 课教你炒股票24：MACD对背弛的辅助判断](https://chanlunzhan.com/108/24)[第 27 课教你炒股票27： 盘整背驰与历史性底部](https://chanlunzhan.com/108/27)[第 37 课教你炒股票37：背驰的再分辨](https://chanlunzhan.com/108/37)

## 下一课

[动力学与背驰

盘整背驰与趋势背驰](https://chanlunzhan.com/learn/beichi/panzheng-vs-qushi-beichi)

[← 上一课 · 动力学与背驰

MACD 只是辅助工具](https://chanlunzhan.com/learn/beichi/macd-as-tool)[下一课 · 动力学与背驰 →

盘整背驰与趋势背驰](https://chanlunzhan.com/learn/beichi/panzheng-vs-qushi-beichi)
