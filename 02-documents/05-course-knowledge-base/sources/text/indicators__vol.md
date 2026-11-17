来源：https://www.structguide.com/indicators/vol
抓取：2026-11-06T00:31:07+08:00

# VOL成交量是什么？MAVOL均量线公式与红绿柱图解

VOL通常显示每个周期的成交数量；均量线则对连续多个周期的成交数量取平均。 看起来是一组柱子加几条曲线，实际包含“数量统计”和“移动平均”两层计算。

VOL来自Volume的缩写。图上的数字究竟以股、手、张还是其他单位显示，需要看数据说明。本页只解释统计口径、公式和图例。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 各K线周期的成交数量V |
| 计算 | VOL显示本期量；MAVOL＝最近N期量之和÷N |
| 参数与约定 | 本文均量线采用简单平均；N为周期数 |
| 单位与边界 | 单位依数据源可能为股、手或张；成交量不等于成交额 |

公式来源：[TradingView平均成交量说明](https://www.tradingview.com/support/solutions/43000745917-how-do-we-calculate-average-volume/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## VOL与MAVOL计算公式

设Vₜ为第t根K线对应周期的成交量。本文均量线采用简单平均，包含本期数据：

MAVOLₙ＝(Vₜ＋Vₜ₋₁＋…＋Vₜ₋ₙ₊₁)÷N。

| 图上元素 | 输入与计算 | 单位 |
| --- | --- | --- |
| VOL柱 | 该根K线周期内统计的成交量 | 数据源标注的数量单位 |
| MAVOL曲线 | 最近N个周期成交量的简单平均 | 与VOL相同 |
| 颜色 | 由平台或用户的配色规则决定 | 不参与平均值计算 |

有些界面写MA5、MA10，有些写MAVOL1、MAVOL2；应查看它们对应的输入和参数，不能仅凭名称认定是价格均线。

![VOL与均量线图解：五个虚构成交量100、200、150、250、300，平均为200；新量400加入并移出100后，均量变为260](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiB2aWV3Qm94PSIwIDAgOTYwIDQ2MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPjx0aXRsZSBpZD0idGl0bGUiPlZPTOS4juWdh+mHj+e6v++8muafseWtkOaYr+aVsOmHj++8jOabsue6v+aYr+W5s+WdhzwvdGl0bGU+PGRlc2MgaWQ9ImRlc2MiPuiZmuaehOaVsOmHjzEwMOOAgTIwMOOAgTE1MOOAgTI1MOOAgTMwMO+8jOWdh+mHjzIwMO+8m+aNouWFpTQwMOenu+WHujEwMOWQju+8jOWdh+mHjzI2MOOAgjwvZGVzYz48cmVjdCB3aWR0aD0iOTYwIiBoZWlnaHQ9IjQ2MCIgcng9IjIwIiBmaWxsPSIjZjBmNmZmIi8+PGcgZm9udC1mYW1pbHk9Ik1pY3Jvc29mdCBZYUhlaSxzYW5zLXNlcmlmIj48dGV4dCB4PSIzNiIgeT0iNTAiIGZvbnQtc2l6ZT0iMjciIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJzdGFydCIgZm9udC13ZWlnaHQ9ImJvbGQiPlZPTOS4juWdh+mHj+e6v++8muafseWtkOaYr+aVsOmHj++8jOabsue6v+aYr+W5s+WdhzwvdGV4dD48dGV4dCB4PSIzNiIgeT0iODYiIGZvbnQtc2l6ZT0iMTgiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJzdGFydCI+6Jma5p6E5pWw6YeP772c57uf5LiA5Y2V5L2N772c6Jma57q/5Y+q5qCH5rOo6L+ZNeacn+eahOWdh+WAvDIwMDwvdGV4dD48cmVjdCB4PSIzNiIgeT0iMTEyIiB3aWR0aD0iODg4IiBoZWlnaHQ9IjI3MCIgcng9IjE0IiBmaWxsPSJ3aGl0ZSIgc3Ryb2tlPSIjYjhkMGY0Ii8+PHJlY3QgeD0iODQiIHk9IjI3OC4wIiB3aWR0aD0iNTQiIGhlaWdodD0iNTQuMCIgcng9IjQiIGZpbGw9IiM0YjgzZWUiLz48dGV4dCB4PSIxMTEiIHk9IjI2Ni4wIiBmb250LXNpemU9IjE4IiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj4xMDA8L3RleHQ+PHRleHQgeD0iMTExIiB5PSIzNTciIGZvbnQtc2l6ZT0iMTYiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPjHmnJ88L3RleHQ+PHJlY3QgeD0iMTg4IiB5PSIyMjQuMCIgd2lkdGg9IjU0IiBoZWlnaHQ9IjEwOC4wIiByeD0iNCIgZmlsbD0iIzRiODNlZSIvPjx0ZXh0IHg9IjIxNSIgeT0iMjEyLjAiIGZvbnQtc2l6ZT0iMTgiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPjIwMDwvdGV4dD48dGV4dCB4PSIyMTUiIHk9IjM1NyIgZm9udC1zaXplPSIxNiIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+MuacnzwvdGV4dD48cmVjdCB4PSIyOTIiIHk9IjI1MS4wIiB3aWR0aD0iNTQiIGhlaWdodD0iODEuMCIgcng9IjQiIGZpbGw9IiM0YjgzZWUiLz48dGV4dCB4PSIzMTkiIHk9IjIzOS4wIiBmb250LXNpemU9IjE4IiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj4xNTA8L3RleHQ+PHRleHQgeD0iMzE5IiB5PSIzNTciIGZvbnQtc2l6ZT0iMTYiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPjPmnJ88L3RleHQ+PHJlY3QgeD0iMzk2IiB5PSIxOTcuMCIgd2lkdGg9IjU0IiBoZWlnaHQ9IjEzNS4wIiByeD0iNCIgZmlsbD0iIzRiODNlZSIvPjx0ZXh0IHg9IjQyMyIgeT0iMTg1LjAiIGZvbnQtc2l6ZT0iMTgiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPjI1MDwvdGV4dD48dGV4dCB4PSI0MjMiIHk9IjM1NyIgZm9udC1zaXplPSIxNiIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+NOacnzwvdGV4dD48cmVjdCB4PSI1MDAiIHk9IjE3MC4wIiB3aWR0aD0iNTQiIGhlaWdodD0iMTYyLjAiIHJ4PSI0IiBmaWxsPSIjNGI4M2VlIi8+PHRleHQgeD0iNTI3IiB5PSIxNTguMCIgZm9udC1zaXplPSIxOCIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+MzAwPC90ZXh0Pjx0ZXh0IHg9IjUyNyIgeT0iMzU3IiBmb250LXNpemU9IjE2IiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj415pyfPC90ZXh0PjxwYXRoIGQ9Ik02NCAyMjQgSDU4OCIgc3Ryb2tlPSIjN2MzYWVkIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1kYXNoYXJyYXk9IjcgNSIvPjx0ZXh0IHg9IjY0NSIgeT0iMTcwIiBmb250LXNpemU9IjIzIiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ic3RhcnQiIGZvbnQtd2VpZ2h0PSJib2xkIj415pyf566A5Y2V5bmz5Z2HPC90ZXh0Pjx0ZXh0IHg9IjY0NSIgeT0iMjExIiBmb250LXNpemU9IjIyIiBmaWxsPSIjMTc1ZGRkIiB0ZXh0LWFuY2hvcj0ic3RhcnQiPjEwMDDDtzXvvJ0yMDA8L3RleHQ+PHRleHQgeD0iNjQ1IiB5PSIyNzQiIGZvbnQtc2l6ZT0iMTgiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJzdGFydCI+5Yqg5YWlNDAw77yM56e75Ye6MTAwPC90ZXh0Pjx0ZXh0IHg9IjY0NSIgeT0iMzE1IiBmb250LXNpemU9IjIyIiBmaWxsPSIjMTc1ZGRkIiB0ZXh0LWFuY2hvcj0ic3RhcnQiPjEzMDDDtzXvvJ0yNjA8L3RleHQ+PHRleHQgeD0iMzYiIHk9IjQyNSIgZm9udC1zaXplPSIxOCIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9InN0YXJ0Ij7lnYfph4/nur/lr7nmr4/kuKrlkajmnJ/nrYnmnYPlubPlnYfvvJvmn7HlrZDpopzoibLkuI3lj4LkuI7orqHnrpfjgII8L3RleHQ+PC9nPjwvc3ZnPg==)

## 用5个成交量算出均量线

假设连续5个周期的成交数量为100、200、150、250、300，统一使用同一种数量单位：

MAVOL5＝(100＋200＋150＋250＋300)÷5＝200。

下一期成交量为400，移出最早的100：

MAVOL5＝(200＋150＋250＋300＋400)÷5＝260。

本期柱子的高度对应300，均量线的高度对应200；下一期柱子对应400，均量线对应260。它们使用同一纵轴单位，但不是同一个统计量。

这与[MA价格均线](https://www.structguide.com/indicators/ma)使用同样的等权平均方法，只是输入从价格换成成交数量。窗口内每个周期的权重都是1/5，不是“成交量越大，该周期权重越大”。

## 成交量和成交额有什么区别？

数量与金额不能混用。以普通、无合约乘数的虚构成交记录为例：100股按每股10元成交，200股按每股12元成交，总量为300股，总额为3400元。

成交额÷成交量＝3400÷300≈11.3333元/股，是这组记录的数量加权均价，不是均量线。若数量显示成“手”、金额显示成“万元”，相除前必须统一单位；涉及合约乘数时，还要先核对计量规则。

完整的价格加权过程见[VWAP计算图解](https://www.structguide.com/indicators/vwap)。

## 红绿成交量柱代表什么？

颜色不是数量的正负号。 普通成交数量本身是非负值；配色可以依据本期收盘价与开盘价的关系，也可以依据本期与上期收盘价的关系，具体以平台设置为准。

因此，红柱不能直接理解成“只统计某一方的数量”，绿柱也不能直接理解成另一方的数量。VOL的总量柱没有凭颜色把一笔成交拆成两份统计。

看图时先确认三个字段：VOL单位、均量线周期、柱子的配色依据。同样的数字可以使用不同颜色显示。

## 周期5、10与盘中更新

5期均量是5根K线的平均数量。日K线对应5个日周期，5分钟K线则对应5个5分钟周期，两者不能直接比较。

若当前K线还未结束，本期累计数量尚不完整，VOL和包含本期的均量线都可能更新。已经过的半个周期与完整周期也不是相同时长的统计。

部分“平均成交量”字段使用特定时段或排除本期；部分相对量字段还会再除以某个基准量。它们不一定等于本文的MAVOL，应先核对定义。

## 软件数值不同，先核对什么？

VOL应先对齐统计范围与数量单位，再比较数值。MAVOL还要统一窗口和缺失值处理；柱子颜色由显示规则决定，不能据红绿颜色把总成交量解释成资金净流入或净流出。

- 数据单位与缩放：股、手、张，以及千、万等显示倍率。

- 周期与统计范围：是否包含额外时段、是否汇总相同来源的数据。

- 平均算法：简单平均、其他平滑，以及是否包含本期。

- 缺失数据：缺少成交量不等于真实成交量为0，不能任意补0后求平均。

- 不足N个有效周期：是否暂不显示，或改用已有样本计算。

某些数据源提供的数量字段可能是报价更新次数等其他计数，不能直接当作实际成交数量。

## 相关阅读与公式来源

- [MA均线怎么算](https://www.structguide.com/indicators/ma)：等权平均与滚动窗口。

- [VWAP是什么](https://www.structguide.com/indicators/vwap)：把成交量作为价格权重。

- [OBV怎么算](https://www.structguide.com/indicators/obv)：按收盘价变化给成交量加上正负号。

- [返回指标速查手册](https://www.structguide.com/indicators/)。

均量的简单平均口径参考[TradingView平均成交量说明](https://www.tradingview.com/support/solutions/43000745917-how-do-we-calculate-average-volume/)，本站算例采用上述明确的窗口约定。图解与数字均为自拟。本文不表示Struct Guide插件新增VOL功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
