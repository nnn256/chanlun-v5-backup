来源：https://www.structguide.com/indicators/ma
抓取：2026-11-06T00:31:05+08:00

# MA均线是什么？计算公式、周期设置与数字图解

MA均线的基础算法，是把最近N个周期的价格相加，再除以N。 每新增一个周期，窗口移出最早的数据，加入最新的数据；把各期平均值连起来，就得到均线。

本文讨论等权的简单移动平均，英文为Simple Moving Average（SMA）。一些软件将其简称为MA；不同软件的函数命名可能不同，应核对算法而不只看缩写。以下使用虚构收盘价，仅演示计算。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 每根K线的收盘价C |
| 计算 | MA＝最近N个收盘价之和÷N |
| 参数与约定 | N为窗口长度；本文采用简单平均 |
| 单位与边界 | 与输入价格同单位；不把均线等同于平均持仓成本 |

公式来源：[TradingView：简单移动平均的计算与参数](https://www.tradingview.com/support/solutions/43000696841-simple-moving-average/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## 均线是什么意思，图上是哪条线？

均线把一串价格变成一串平均值，再按时间连接起来。它的每一个点，都能追溯到参与计算的数据。本文的MA使用等权平均；“均线”也可以泛指其他加权方式，因此还要看具体算法。

看图时，先核对指标名称、周期和数值。例如图例显示“MA5：12”，表示该位置的5期简单平均值为12。MA10和MA20则分别使用10个和20个数据。多条均线只是不同窗口的计算结果叠加在同一张图上。

均线颜色不是统一定义。 黄色、白色或紫色对应哪一个周期，要看软件图例和颜色设置，不能只凭颜色认线。

## 均线怎么设置？先认清三个计算选项

| 选项 | 改变的内容 | 例子 |
| --- | --- | --- |
| 图表周期 | 一个数据对应的时间长度 | 日K线与周K线的MA5不是同一组输入 |
| 均线周期N | 平均窗口的数据个数 | 5改为10，窗口内每个数的权重从1/5变为1/10 |
| 价格来源 | 每根K线取哪一个数 | 收盘价与开盘价会得到不同结果 |

线宽与颜色只改变外观，不改变计算。不同软件入口不同，核对设置时应以字段含义和公式为准。本页说明这些设置如何参与计算，不推荐具体参数组合。

## 计算公式速查

| 项目 | 含义 |
| --- | --- |
| 输入 | 本文使用每根K线的收盘价C |
| 周期N | 参与平均的数据个数，取正整数 |
| MA数值 | MAₜ＝(Cₜ＋Cₜ₋₁＋…＋Cₜ₋ₙ₊₁)÷N |
| 权重 | 窗口内每个数据均占1/N |
| 更新 | 新数据进入，最早的数据退出 |

其中t表示计算所在的周期。这里按数据齐全、已取得N个有效数值计算；不足N个时，不同软件的初始显示可能不同。

## 用5个数字算出MA5

假设连续5个交易日的收盘价如下：

| 日期 | 第1天 | 第2天 | 第3天 | 第4天 | 第5天 |
| --- | --- | --- | --- | --- | --- |
| 收盘价 | 10 | 12 | 11 | 13 | 14 |

先相加：10＋12＋11＋13＋14＝60。

再除以5：60÷5＝12。

因此，第5天的5日均线值为12。当天收盘价是14，均线值是12：一个描述单个周期的收盘价，一个汇总最近5个周期的收盘价。

## 为什么叫“移动”平均？

假设第6天收盘价为15。我们仍然只取最近5天，因此第1天的10退出，第6天的15进入。

![5期移动平均的窗口更新：10退出，15进入，均值从12变为13](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDcwIiB2aWV3Qm94PSIwIDAgOTYwIDQ3MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPgogIDx0aXRsZSBpZD0idGl0bGUiPjXmnJ/np7vliqjlubPlnYfnmoTmu5rliqjnqpflj6M8L3RpdGxlPgogIDxkZXNjIGlkPSJkZXNjIj7nrKw15aSp5L2/55SoMTDjgIExMuOAgTEx44CBMTPjgIExNO+8jOWdh+WAvDEy44CC56ysNuWkqeS9v+eUqDEy44CBMTHjgIExM+OAgTE044CBMTXvvIzlnYflgLwxM+OAgjEw6YCA5Ye677yMMTXov5vlhaXjgII8L2Rlc2M+CiAgPHJlY3Qgd2lkdGg9Ijk2MCIgaGVpZ2h0PSI0NzAiIHJ4PSIyNCIgZmlsbD0iI2YwZjZmZiIvPgogIDxnIGZvbnQtZmFtaWx5PSJNaWNyb3NvZnQgWWFIZWksIHNhbnMtc2VyaWYiIGZpbGw9IiMxNTJjNTAiPgogICAgPHRleHQgeD0iNDAiIHk9IjU3IiBmb250LXNpemU9IjMwIiBmb250LXdlaWdodD0iNzAwIj7nqpflj6Pkv53mjIE15Liq5pWw77yM5q+P5qyh5ZCR5ZCO56e75Yqo5LiA5qC8PC90ZXh0PgogICAgPHRleHQgeD0iNDAiIHk9IjkwIiBmb250LXNpemU9IjE4IiBmaWxsPSIjNTI2NjgxIj7omZrmnoTmlLbnm5jku7cgwrcg562J5p2D5bmz5Z2HIMK3IOavj+S4quaVsOWtl+eahOadg+mHjeS4ujEvNTwvdGV4dD4KICAgIDxyZWN0IHg9IjMyIiB5PSIxMTYiIHdpZHRoPSI4OTYiIGhlaWdodD0iMTMyIiByeD0iMTYiIGZpbGw9IndoaXRlIi8+CiAgICA8cmVjdCB4PSIzMiIgeT0iMjY2IiB3aWR0aD0iODk2IiBoZWlnaHQ9IjEzMiIgcng9IjE2IiBmaWxsPSJ3aGl0ZSIvPgogICAgPHRleHQgeD0iNTQiIHk9IjE4OCIgZm9udC1zaXplPSIyNCIgZm9udC13ZWlnaHQ9IjcwMCI+56ysNeWkqTwvdGV4dD4KICAgIDx0ZXh0IHg9IjU0IiB5PSIzMzgiIGZvbnQtc2l6ZT0iMjQiIGZvbnQtd2VpZ2h0PSI3MDAiPuesrDblpKk8L3RleHQ+CiAgICA8ZyBmaWxsPSIjZThmMGZjIj4KICAgICAgPHJlY3QgeD0iMTc2IiB5PSIxNDIiIHdpZHRoPSI4NCIgaGVpZ2h0PSI2NCIgcng9IjEwIi8+CiAgICAgIDxyZWN0IHg9IjI4MCIgeT0iMTQyIiB3aWR0aD0iODQiIGhlaWdodD0iNjQiIHJ4PSIxMCIvPgogICAgICA8cmVjdCB4PSIzODQiIHk9IjE0MiIgd2lkdGg9Ijg0IiBoZWlnaHQ9IjY0IiByeD0iMTAiLz4KICAgICAgPHJlY3QgeD0iNDg4IiB5PSIxNDIiIHdpZHRoPSI4NCIgaGVpZ2h0PSI2NCIgcng9IjEwIi8+CiAgICAgIDxyZWN0IHg9IjU5MiIgeT0iMTQyIiB3aWR0aD0iODQiIGhlaWdodD0iNjQiIHJ4PSIxMCIvPgogICAgICA8cmVjdCB4PSIxNzYiIHk9IjI5MiIgd2lkdGg9Ijg0IiBoZWlnaHQ9IjY0IiByeD0iMTAiLz4KICAgICAgPHJlY3QgeD0iMjgwIiB5PSIyOTIiIHdpZHRoPSI4NCIgaGVpZ2h0PSI2NCIgcng9IjEwIi8+CiAgICAgIDxyZWN0IHg9IjM4NCIgeT0iMjkyIiB3aWR0aD0iODQiIGhlaWdodD0iNjQiIHJ4PSIxMCIvPgogICAgICA8cmVjdCB4PSI0ODgiIHk9IjI5MiIgd2lkdGg9Ijg0IiBoZWlnaHQ9IjY0IiByeD0iMTAiLz4KICAgICAgPHJlY3QgeD0iNTkyIiB5PSIyOTIiIHdpZHRoPSI4NCIgaGVpZ2h0PSI2NCIgcng9IjEwIiBmaWxsPSIjMjU2M2ViIi8+CiAgICA8L2c+CiAgICA8ZyBmb250LXNpemU9IjMwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXdlaWdodD0iNzAwIj4KICAgICAgPHRleHQgeD0iMjE4IiB5PSIxODUiPjEwPC90ZXh0Pjx0ZXh0IHg9IjMyMiIgeT0iMTg1Ij4xMjwvdGV4dD48dGV4dCB4PSI0MjYiIHk9IjE4NSI+MTE8L3RleHQ+PHRleHQgeD0iNTMwIiB5PSIxODUiPjEzPC90ZXh0Pjx0ZXh0IHg9IjYzNCIgeT0iMTg1Ij4xNDwvdGV4dD4KICAgICAgPHRleHQgeD0iMjE4IiB5PSIzMzUiPjEyPC90ZXh0Pjx0ZXh0IHg9IjMyMiIgeT0iMzM1Ij4xMTwvdGV4dD48dGV4dCB4PSI0MjYiIHk9IjMzNSI+MTM8L3RleHQ+PHRleHQgeD0iNTMwIiB5PSIzMzUiPjE0PC90ZXh0Pjx0ZXh0IHg9IjYzNCIgeT0iMzM1IiBmaWxsPSJ3aGl0ZSI+MTU8L3RleHQ+CiAgICA8L2c+CiAgICA8ZyBmb250LXNpemU9IjE3IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjNTI2NjgxIj4KICAgICAgPHRleHQgeD0iMjE4IiB5PSIyMzIiPuS4i+acn+mAgOWHujwvdGV4dD48dGV4dCB4PSI2MzQiIHk9IjM4MiI+5paw5Yqg5YWlPC90ZXh0PgogICAgPC9nPgogICAgPGcgZm9udC1zaXplPSIyOCIgZmlsbD0iIzI1NjNlYiIgZm9udC13ZWlnaHQ9IjcwMCI+CiAgICAgIDx0ZXh0IHg9IjcxNiIgeT0iMTg2Ij42MMO3Ne+8nTEyPC90ZXh0Pjx0ZXh0IHg9IjcxNiIgeT0iMzM2Ij42NcO3Ne+8nTEzPC90ZXh0PgogICAgPC9nPgogICAgPHRleHQgeD0iNDAiIHk9IjQ0MyIgZm9udC1zaXplPSIyMSI+5Z2H5YC85Y+Y5YyW77ydKDE177yNMTApw7c177ydMTwvdGV4dD4KICA8L2c+Cjwvc3ZnPgo=)

| 计算时间 | 参与计算的5个数 | 合计 | MA5 |
| --- | --- | --- | --- |
| 第5天 | 10、12、11、13、14 | 60 | 12 |
| 第6天 | 12、11、13、14、15 | 65 | 13 |

窗口大小没有变化，只是由第1—5天移到第2—6天。如果把6个数字全部相加再除以6，算出的就不再是5期均值。

## 价格下降，均线为什么仍可能上升？

换一个假设：第6天收盘价为13，而不是15。

价格由第5天的14降到了13，但新的均线值为：

(12＋11＋13＋14＋13)÷5＝12.6。

均线反而由12上升到12.6。原因是进入窗口的13，大于退出窗口的10。

对连续更新、数据齐全的N期简单移动平均，前后两个窗口中间的N－1个数据相同，相减后抵消，因此：

本期均线－上期均线＝(新加入的价格－移出的旧价格)÷N

代入本例：(13－10)÷5＝0.6，正好等于均线的变化量。判断均线本期如何变化，应比较新加入与被移出的数据，不能只比较本期和上期收盘价。

## MA5一定代表5天吗？

“5”表示5个计算周期。如果使用当前图表周期的收盘价：

| 图表周期 | MA5的输入 |
| --- | --- |
| 日线 | 最近5根日K线的收盘价 |
| 周线 | 最近5根周K线的收盘价 |
| 60分钟线 | 最近5根60分钟K线的收盘价 |

5日均线取最近5个交易日的数据，而非简单取5个自然日。休市日没有新增日K线，就不会多出一个收盘价。有些软件或脚本允许单独指定指标周期，需按实际设置核对。

## 周期越长，为什么通常越平滑？

5期均线中，每个数据占1/5；20期均线中，每个数据占1/20。

假设窗口内其他数据不变，只把其中一个数提高5：

| 周期 | 均值增加 |
| --- | --- |
| 5期 | 5÷5＝1 |
| 20期 | 5÷20＝0.25 |

同样的单点变化，在更长窗口中的影响更小。这解释了较长周期均线通常更平滑的一个原因。更多历史数据也会摊薄新数据的影响；参数改变的是汇总方式，不能仅凭线条平滑程度判断它是否更适合某项用途。

## 均线是不是平均持仓成本？

本文的MA只使用收盘价，没有输入成交量、每笔成交价格、持仓数量或换手信息。

即使两天的成交量不同，两个收盘价在简单移动平均中的权重仍然相同。它表达的是指定价格序列的等权平均，不能直接当作所有参与者的平均持仓成本。

## 盘中均线为什么会变化？

日K线尚未结束时，最终收盘价还没有确定。如果软件用这根K线的最新价格参与计算，价格更新后，均线数值也会更新。

假设此前4个收盘价合计46，盘中价格为14，则MA5＝(46＋14)÷5＝12；价格变为15后，MA5＝(46＋15)÷5＝12.2。

这来自输入变化，不一定是计算错误。K线结束后才获得该周期最终的收盘价输入；后续数据修订或复权调整，也可能影响历史结果。

## 同样是MA5，两个软件为什么不同？

相同的MA周期不保证数值相同：还需统一K线周期、输入价格、复权口径、缺失数据处理及窗口是否已满。本文MA指等权的简单平均。

依次核对以下条件：

- 算法：是否都使用等权简单移动平均，而不是其他加权或平滑方法。

- 价格字段：是否都使用收盘价，还是开盘价、高低价平均值等。

- 周期与时段：K线周期、时区及纳入的时段是否一致。

- 数据口径：报价来源、复权方式、缺失值处理与历史数据是否相同。

- 计算状态：是否包含尚未结束的K线，显示的小数位是否一致。

理解一个指标，可以从三个问题开始：用什么数据、怎样计算、何时更新。MA的每一个数值，都可以沿着这条路径复算。

## 资料与相关阅读

- [VOL成交量与均量线](https://www.structguide.com/indicators/vol)：把简单平均的输入从价格换成数量。

- [VWAP成交量加权均价](https://www.structguide.com/indicators/vwap)：比较等权与数量加权。

- [BOLL布林带怎么算？用一组数字看懂中轨、上轨和下轨](https://www.structguide.com/indicators/boll)：从MA中轨继续计算标准差与上下轨。

- [MA和EMA有什么区别？用一组数字看懂两种均线](https://www.structguide.com/indicators/ma-vs-ema)：继续比较权重、递推和初始值。

- [TradingView：简单移动平均的计算与参数](https://www.tradingview.com/support/solutions/43000696841-simple-moving-average/)。本文的数字与窗口示例为本站自拟。

- [返回常见指标速查手册](https://www.structguide.com/indicators/)。

- [Struct Guide画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)：分型、笔、线段和中枢的工具实现。本文MA原理不表示插件新增了MA绘制功能。

本文仅介绍指标计算与数据展示，不提供投资建议。
