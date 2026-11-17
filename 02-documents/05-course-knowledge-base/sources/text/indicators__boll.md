来源：https://www.structguide.com/indicators/boll
抓取：2026-11-06T00:31:04+08:00

# BOLL布林带是什么？三条线计算公式、参数与图解

常见的BOLL布林带由三条线组成：中轨为N期简单移动平均，上轨为中轨加K倍标准差，下轨为中轨减K倍标准差。

如果已经读过[MA均线的计算原理](https://www.structguide.com/indicators/ma)，你就理解了中轨的基础。这篇继续用一组虚构数字，说明标准差是什么，以及另外两条线如何得到。

本文采用收盘价、简单移动平均和除以N的总体标准差口径；计算结果展示到两位小数，中间步骤保留精度。不同软件可以有不同设置，需核对具体公式。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 最近N期收盘价 |
| 计算 | 中轨M＝MA；上轨＝M＋Kσ；下轨＝M－Kσ |
| 参数与约定 | N为窗口长度；K为正的标准差倍数；σ采用除以N的总体标准差 |
| 单位与边界 | 三条轨道与价格同单位；绝对宽度＝2Kσ |

公式来源：[MetaTrader 5官方布林带公式](https://www.metatrader5.com/en/terminal/help/indicators/trend_indicators/bb)、[TradingView的BOLL说明](https://www.tradingview.com/support/solutions/43000501840-bollinger-bands-bb/)、[布林带规则说明](https://www.bollingerbands.com/bollinger-band-rules)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## BOLL计算公式速查

| 项目 | 计算或含义 |
| --- | --- |
| N | 计算窗口内的数据个数 |
| K | 标准差倍数，本文取正数 |
| 中轨M | 最近N个收盘价相加，再除以N |
| 标准差σ | 各数据减去同一个窗口均值，差值平方后求平均，再开平方 |
| 上轨 | M＋K×σ |
| 下轨 | M－K×σ |
| 上下轨的价格距离 | 2×K×σ |

把窗口内的数据记作x₁至xₙ，标准差可以写成：

σ＝√{[(x₁－M)²＋(x₂－M)²＋…＋(xₙ－M)²]÷N}

这里所有差值都使用该窗口同一个均值M，不是分别减去各数据当时对应的滚动均线值。计算依据可对照[MetaTrader 5官方布林带公式](https://www.metatrader5.com/en/terminal/help/indicators/trend_indicators/bb)。

## 第一步：用5个数字算出中轨

为方便手算，设N＝5、K＝2，使用以下虚构收盘价：

| 周期 | 第1期 | 第2期 | 第3期 | 第4期 | 第5期 |
| --- | --- | --- | --- | --- | --- |
| 收盘价 | 10 | 12 | 11 | 13 | 14 |

中轨就是这5个数的简单平均值：

M＝(10＋12＋11＋13＋14)÷5＝12。

每新增一个周期，就移出最早的数据、加入最新的数据，再计算新的窗口均值。因此，日线、周线或分钟线中的N表示对应计算周期的个数，不固定等于天数。

## 第二步：标准差怎样计算？

均值告诉我们这组数据的平均水平，标准差描述它们围绕均值的分散程度。

先把每个数减去均值12，再将差值平方：

| 收盘价 | 减去均值12 | 差值的平方 |
| --- | --- | --- |
| 10 | −2 | 4 |
| 12 | 0 | 0 |
| 11 | −1 | 1 |
| 13 | 1 | 1 |
| 14 | 2 | 4 |
| 合计 | 0 | 10 |

为什么不能直接把正负差值相加？因为相对于均值的差值会抵消，本例的总和为0，但数据显然并不全等于12。

平方后，再求平均，得到方差：

方差＝10÷5＝2。

最后开平方，得到标准差：

σ＝√2≈1.4142。

平方和开平方之后，标准差回到与原始价格相同的单位，便于和中轨相加减。

## 第三步：上轨和下轨怎么算？

中轨为12，标准差为√2，倍数K＝2：

- 上轨＝12＋2×√2≈14.83。

- 下轨＝12－2×√2≈9.17。

此窗口的三个数值分别为：中轨12、上轨约14.83、下轨约9.17。

这只是三条线在一个周期上的取值。每个窗口重新计算一次，再把各期的中轨、上轨和下轨分别连接，才构成图表中的三条曲线。

## 均值一样，布林带为什么仍可能不同？

把原来的数字围绕12放得更分散一些：

| 对比项 | A组 | B组 |
| --- | --- | --- |
| 数据 | 10、12、11、13、14 | 8、12、10、14、16 |
| 均值 | 12 | 12 |
| 标准差（除以5） | √2≈1.41 | √8≈2.83 |
| 上轨（K＝2） | 约14.83 | 约17.66 |
| 下轨（K＝2） | 约9.17 | 约6.34 |
| 上下轨价格距离 | 约5.66 | 约11.31 |

![同一价格刻度下，两组数据均值均为12，B组分散程度更大，标准差和上下轨价格距离均为A组的两倍](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNTgwIiB2aWV3Qm94PSIwIDAgOTYwIDU4MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPgogPHRpdGxlIGlkPSJ0aXRsZSI+5Z2H5YC855u45ZCM77yM5qCH5YeG5beu5LiN5ZCM55qEQk9MTOWMuumXtDwvdGl0bGU+CiA8ZGVzYyBpZD0iZGVzYyI+Qee7hDEw44CBMTLjgIExMeOAgTEz44CBMTTvvIzlnYflgLwxMu+8jOagh+WHhuW3rue6pjEuNDHvvIzkuIrkuIvovajnuqYxNC44M+WSjDkuMTfjgIJC57uEOOOAgTEy44CBMTDjgIExNOOAgTE277yM5Z2H5YC8MTLvvIzmoIflh4blt67nuqYyLjgz77yM5LiK5LiL6L2o57qmMTcuNjblkow2LjM044CC5Lik57uE5L2/55So5ZCM5LiA5Lu35qC85Yi75bqm77yMTuetieS6jjXvvIxL562J5LqOMuOAgjwvZGVzYz4KIDxyZWN0IHdpZHRoPSI5NjAiIGhlaWdodD0iNTgwIiByeD0iMjQiIGZpbGw9IiNmMGY2ZmYiLz4KIDxnIGZvbnQtZmFtaWx5PSJNaWNyb3NvZnQgWWFIZWksIHNhbnMtc2VyaWYiIGZpbGw9IiMxNTJjNTAiPgogIDx0ZXh0IHg9IjM2IiB5PSI1NiIgZm9udC1zaXplPSIzMCIgZm9udC13ZWlnaHQ9IjcwMCI+5Z2H5YC85ZCM5Li6MTLvvIzliIbmlaPnqIvluqblhrPlrprljLrpl7Tlrr3luqY8L3RleHQ+CiAgPHRleHQgeD0iMzYiIHk9IjkyIiBmb250LXNpemU9IjE5IiBmaWxsPSIjNTI2NjgxIj7omZrmnoTmlbDmja4gwrcgTu+8nTXvvIxL77ydMiDCtyDmgLvkvZPmoIflh4blt64gwrcg5Lik57uE5L2/55So55u45ZCM5Lu35qC85Yi75bqmPC90ZXh0PgogIDxyZWN0IHg9IjI4IiB5PSIxMTgiIHdpZHRoPSI5MDQiIGhlaWdodD0iMTQ2IiByeD0iMTYiIGZpbGw9IndoaXRlIi8+CiAgPHJlY3QgeD0iMjgiIHk9IjI4MiIgd2lkdGg9IjkwNCIgaGVpZ2h0PSIxNDYiIHJ4PSIxNiIgZmlsbD0id2hpdGUiLz4KICA8dGV4dCB4PSI0OCIgeT0iMTUzIiBmb250LXNpemU9IjIyIiBmb250LXdlaWdodD0iNzAwIj5B57uE44CAMTDjgIExMuOAgTEx44CBMTPjgIExNDwvdGV4dD4KICA8dGV4dCB4PSI2OTIiIHk9IjE1MyIgZm9udC1zaXplPSIyMCI+5qCH5YeG5beu4omIMS40MTwvdGV4dD4KICA8dGV4dCB4PSI0OCIgeT0iMzE3IiBmb250LXNpemU9IjIyIiBmb250LXdlaWdodD0iNzAwIj5C57uE44CAOOOAgTEy44CBMTDjgIExNOOAgTE2PC90ZXh0PgogIDx0ZXh0IHg9IjY5MiIgeT0iMzE3IiBmb250LXNpemU9IjIwIj7moIflh4blt67iiYgyLjgzPC90ZXh0PgogIDxyZWN0IHg9IjM1MC4yOTQiIHk9IjE3OCIgd2lkdGg9IjMzOS40MTIiIGhlaWdodD0iNDQiIGZpbGw9IiNkYmVhZmUiIHN0cm9rZT0iIzI1NjNlYiIgc3Ryb2tlLXdpZHRoPSIyIi8+CiAgPHJlY3QgeD0iMTgwLjU4OSIgeT0iMzQyIiB3aWR0aD0iNjc4LjgyMiIgaGVpZ2h0PSI0NCIgZmlsbD0iI2VkZTlmZSIgc3Ryb2tlPSIjNzk1NWM4IiBzdHJva2Utd2lkdGg9IjIiLz4KICA8cGF0aCBkPSJNNTIwIDE3MVYyMjkgTTUyMCAzMzVWMzkzIiBzdHJva2U9IiMxNTJjNTAiIHN0cm9rZS13aWR0aD0iMyIvPgogIDxnIGZpbGw9IiMyNTYzZWIiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiI+CiAgIDxjaXJjbGUgY3g9IjQwMCIgY3k9IjIwMCIgcj0iNyIvPjxjaXJjbGUgY3g9IjUyMCIgY3k9IjIwMCIgcj0iNyIvPjxjaXJjbGUgY3g9IjQ2MCIgY3k9IjIwMCIgcj0iNyIvPjxjaXJjbGUgY3g9IjU4MCIgY3k9IjIwMCIgcj0iNyIvPjxjaXJjbGUgY3g9IjY0MCIgY3k9IjIwMCIgcj0iNyIvPgogIDwvZz4KICA8ZyBmaWxsPSIjNzk1NWM4IiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPgogICA8Y2lyY2xlIGN4PSIyODAiIGN5PSIzNjQiIHI9IjciLz48Y2lyY2xlIGN4PSI1MjAiIGN5PSIzNjQiIHI9IjciLz48Y2lyY2xlIGN4PSI0MDAiIGN5PSIzNjQiIHI9IjciLz48Y2lyY2xlIGN4PSI2NDAiIGN5PSIzNjQiIHI9IjciLz48Y2lyY2xlIGN4PSI3NjAiIGN5PSIzNjQiIHI9IjciLz4KICA8L2c+CiAgPGcgZm9udC1zaXplPSIxOCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+CiAgIDx0ZXh0IHg9IjM1MCIgeT0iMjQ5Ij7kuIvovag5LjE3PC90ZXh0Pjx0ZXh0IHg9IjUyMCIgeT0iMjQ5Ij7kuK3ovagxMjwvdGV4dD48dGV4dCB4PSI2OTAiIHk9IjI0OSI+5LiK6L2oMTQuODM8L3RleHQ+CiAgIDx0ZXh0IHg9IjE4MSIgeT0iNDEzIj7kuIvovag2LjM0PC90ZXh0Pjx0ZXh0IHg9IjUyMCIgeT0iNDEzIj7kuK3ovagxMjwvdGV4dD48dGV4dCB4PSI4NTkiIHk9IjQxMyI+5LiK6L2oMTcuNjY8L3RleHQ+CiAgPC9nPgogIDxwYXRoIGQ9Ik0xNjAgNDU4SDg4MCBNMTYwIDQ1M1Y0NjMgTTI4MCA0NTNWNDYzIE00MDAgNDUzVjQ2MyBNNTIwIDQ1M1Y0NjMgTTY0MCA0NTNWNDYzIE03NjAgNDUzVjQ2MyBNODgwIDQ1M1Y0NjMiIHN0cm9rZT0iIzk0YTNiOCIvPgogIDxnIGZvbnQtc2l6ZT0iMTgiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiM1MjY2ODEiPgogICA8dGV4dCB4PSIxNjAiIHk9IjQ4NiI+NjwvdGV4dD48dGV4dCB4PSIyODAiIHk9IjQ4NiI+ODwvdGV4dD48dGV4dCB4PSI0MDAiIHk9IjQ4NiI+MTA8L3RleHQ+PHRleHQgeD0iNTIwIiB5PSI0ODYiPjEyPC90ZXh0Pjx0ZXh0IHg9IjY0MCIgeT0iNDg2Ij4xNDwvdGV4dD48dGV4dCB4PSI3NjAiIHk9IjQ4NiI+MTY8L3RleHQ+PHRleHQgeD0iODgwIiB5PSI0ODYiPjE4PC90ZXh0PgogIDwvZz4KICA8dGV4dCB4PSIzNiIgeT0iNTI2IiBmb250LXNpemU9IjE5Ij7lnIbngrnkuLrnqpflj6PlhoXnmoTku7fmoLzlgLzvvJvoibLluKbkuLror6Xnqpflj6PnmoTkuIvovajoh7PkuIrovajljLrpl7TjgII8L3RleHQ+CiAgPHRleHQgeD0iMzYiIHk9IjU1NyIgZm9udC1zaXplPSIxOSIgZmlsbD0iIzUyNjY4MSI+6L+Z5piv5ZCM5LiA5pe254K555qE5pWw5YC85a+55q+U77yM5bm26Z2e6ZqP5pe26Ze05bGV5byA55qE5LiJ5p2h5oyH5qCH5puy57q/44CCPC90ZXh0PgogPC9nPgo8L3N2Zz4K)

B组每个数与均值的距离，都是A组对应距离的两倍，因此标准差也为两倍。在K不变的条件下，上下轨价格距离随之成为两倍。

对于这套公式，K固定时，带的绝对宽度由窗口内价格的标准差决定。中轨同时可能移动，因此不能只看某一条边线的方向来判断带宽变化。

这里的宽度指“上轨减下轨”的价格距离。有些软件另设归一化的BandWidth指标，例如再除以中轨并转为百分数；那是不同的数值表达，比较时应先核对定义。

## 参数20和2分别是什么意思？

20期和2倍标准差是常见默认组合，并非唯一允许的设置。[TradingView的BOLL说明](https://www.tradingview.com/support/solutions/43000501840-bollinger-bands-bb/)也给出了这一组合。

- N＝20：取最近20个周期的数据，同时用于本文的均值与标准差计算。

- K＝2：在中轨上下各取2个标准差的距离。

固定窗口数据和均线类型，只改变K，中轨不变，上下轨到中轨的距离按比例变化。

改变N则不同：纳入的数据改变，均值和标准差都可能变化。不能简单说“周期越长，布林带一定越宽”或“一定越窄”。

有些软件支持其他中轨类型。若改用EMA等变体，需继续核对离散程度的计算方式，不能假定只替换中轨后就与其他实现完全相同。MA与EMA的差异见[两种均线的计算对比](https://www.structguide.com/indicators/ma-vs-ema)。

## 为什么两个软件的BOLL数值不同？

BOLL数值比较必须先统一价格输入、窗口、均线类型、标准差分母和倍数。本文以简单平均作中轨，标准差除以N；换成除以N－1，即使价格相同也会改变上下轨。

在品种相同的前提下，可以按这个顺序核对：

| 核对项 | 具体内容 |
| --- | --- |
| 数据与周期 | 来源、复权、K线周期、时段是否相同 |
| 输入字段 | 收盘价，还是其他价格字段 |
| 参数 | N、K及中轨类型是否相同 |
| 标准差口径 | 平方差之和除以N，还是除以N－1 |
| 计算状态 | 是否包含未结束K线，窗口数据是否齐全 |
| 显示精度 | 中间结果是否提前舍入，最终保留几位小数 |

例如，本文平方差之和为10。除以N＝5，标准差为√2≈1.41；若改用除以N－1＝4的样本标准差，结果为√2.5≈1.58，对应上下轨约为15.16和8.84。

因此，“都使用标准差”还不够，分母等实现细节也要一致。以上是在比较算法口径，不表示某个软件一定采用其中某一种。

日K线尚未结束时，如果软件用最新价格代替该根K线尚未确定的收盘价，窗口均值和标准差都会随输入更新，三条线也可能变化。

## 两倍标准差等于95%的概率保证吗？

不能直接这样理解。 正态分布中，已知总体均值上下两个总体标准差约覆盖95.45%的概率质量，这是带有分布前提的数学结论。

布林带使用有限滚动窗口估计均值和标准差；价格序列也不天然满足独立、同分布的正态假设。因此，不能把上面这个概率直接套用为“下一期价格有95%的概率留在布林带内”，也不能说历史数据一定有95%处于带内。

John Bollinger在[布林带规则说明](https://www.bollingerbands.com/bollinger-band-rules)中也明确提示，不应仅因使用标准差就对价格分布作统计假定。

对计算原理而言，可以确定的是：三条线汇总了指定窗口内的平均水平和价格离散程度。它们没有为后续价格提供概率保证。

## BOLL指标怎么看？先把三条线与公式对上

BOLL通常指布林带，英文全称是Bollinger Bands。按本文口径，中轨是窗口均值，上轨是“均值＋K倍标准差”，下轨是“均值－K倍标准差”；上下轨之间的区域也常被称为布林带通道。

图例可能使用MID、UPPER、LOWER等标签，各软件名称和颜色不一定相同。先确认标签，再读同一时刻的数值，才能与公式核对。

以本文算例为例，中轨12、上轨约14.83、下轨约9.17：上下轨到中轨的距离均约2.83。这里的三条线来自同一个窗口，不是分别计算了三个周期的均值。

“布林带怎么看”在本页仅指读懂图例、数值与公式的关系。带宽收窄表示该口径下标准差减小，变宽表示标准差增大；这些是窗口数据的统计描述。

## 布林带宽度怎么算？

绝对宽度＝上轨－下轨＝2Kσ。还可以把宽度除以中轨，得到相对宽度；若采用百分比显示，再乘以100%。

本文示例的绝对宽度约5.6569，相对宽度为5.6569÷12≈0.4714，百分比约47.14%。软件若显示0.4714或47.14，需要先核对是否乘了100%，不能直接比较显示数字。

中轨为0时不能做该除法；中轨接近0时，相对宽度会很大。查看“布林带宽度”时，应先区分绝对差值与相对比值。

## 相关阅读

- [CCI计算图解](https://www.structguide.com/indicators/cci)：区分平均绝对偏差与标准差。

- [MA均线怎么算？用5个数字看懂移动平均](https://www.structguide.com/indicators/ma)：理解BOLL中轨的基础。

- [MA和EMA有什么区别？用一组数字看懂两种均线](https://www.structguide.com/indicators/ma-vs-ema)：核对等权和指数加权。

- [返回常见指标速查手册](https://www.structguide.com/indicators/)。

本文的数字与图解为本站自拟，介绍通用指标计算，不表示Struct Guide插件新增BOLL功能。插件的分型、笔、线段和中枢计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
