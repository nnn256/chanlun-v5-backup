来源：https://www.structguide.com/indicators/ma-vs-ema
抓取：2026-11-06T00:31:05+08:00

# MA和EMA有什么区别？计算公式、权重与初始化图解

同样是5期均线，为什么MA和EMA有时重合，有时却分开？

区别在于数据的权重：简单MA把窗口内的数据等权平均；EMA给新数据较大的权重，再把上一期的结果带入计算。

上一篇[MA均线怎么算？用5个数字看懂移动平均](https://www.structguide.com/indicators/ma)，介绍了固定窗口的算法。这一篇沿用同一组数字，看看EMA怎样算，以及“反应更快”究竟指什么。

本文的MA特指等权的简单移动平均，英文简称SMA；EMA是指数移动平均。不同软件中的函数名称可能不同，比较时应核对公式。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 同一组收盘价C |
| 计算 | MA取窗口等权平均；EMA＝α×本期C＋(1－α)×上期EMA |
| 参数与约定 | 本文EMA取α＝2/(N＋1)；初始值在算例中单独约定 |
| 单位与边界 | 均与输入价格同单位；EMA保留递推历史影响 |

公式来源：[TradingView的EMA计算说明](https://www.tradingview.com/support/solutions/43000592270-exponential-moving-average/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## 先看区别：等权窗口与递推计算

| 对照项 | MA：简单移动平均 | EMA：指数移动平均 |
| --- | --- | --- |
| 基本方法 | 最近N个数据相加，再除以N | 新数据与上一期EMA加权相加 |
| 最新数据的权重 | 1/N | 常见取值为2/(N＋1) |
| 旧数据如何处理 | 超出窗口后退出计算 | 通过前一期结果保留，影响逐期衰减 |
| 计算起点 | 取得N个有效数据后，可直接求均值 | 需要约定一个初始值 |

以下均使用虚构的收盘价，采用常见EMA系数 α＝2/(N＋1)，并明确规定初始值。该递推形式可参阅[TradingView的EMA计算说明](https://www.tradingview.com/support/solutions/43000592270-exponential-moving-average/)。数字示例和对比推导为本站自拟。

## MA5：最近5个数字，每个占20%

先看前5期收盘价：

| 周期 | 第1期 | 第2期 | 第3期 | 第4期 | 第5期 |
| --- | --- | --- | --- | --- | --- |
| 收盘价 | 10 | 12 | 11 | 13 | 14 |

第5期MA5为：

(10＋12＋11＋13＋14)÷5＝12。

5个数据各占1/5，也就是20%。第6期收盘价为15时，10退出窗口，15加入，MA5变为：

(12＋11＋13＋14＋15)÷5＝13。

这是固定窗口、等权平均的计算。

## EMA5：本期价格占1/3，上期结果占2/3

EMA的常见计算式是：

本期EMA＝α×本期价格＋(1－α)×上期EMA

α＝2/(N＋1)

对于EMA5，N＝5，因此α＝2/6＝1/3。公式就变成：

本期EMA5＝本期价格×1/3＋上期EMA5×2/3。

这里的2/3乘的是上一期EMA结果，不是上一期的原始收盘价。EMA结果中已经包含了更早数据的影响。

为了从同一个起点比较，本文采用一种常见初始化方法：以前5期的简单平均值12，作为第5期EMA5的初始值。其他软件可能采用不同起点，这一点后面会说明。

第6期收盘价为15：

EMA5＝15×1/3＋12×2/3＝13。

此时MA5和EMA5恰好都等于13。这只是这一组数据下的巧合，不表示两种算法等价。

## 第7期，两条线为什么分开了？

假设第7期收盘价回到12。

MA5继续使用最近5个收盘价：

MA5＝(11＋13＋14＋15＋12)÷5＝13。

EMA5则使用本期价格12和上一期EMA值13：

EMA5＝12×1/3＋13×2/3≈12.67。

![同一组数据下的MA5与EMA5计算：第7期MA5为13，EMA5约为12.67](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNTQwIiB2aWV3Qm94PSIwIDAgOTYwIDU0MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPgogIDx0aXRsZSBpZD0idGl0bGUiPuesrDfmnJ/nmoRNQTXkuI5FTUE16K6h566X5a+55q+UPC90aXRsZT4KICA8ZGVzYyBpZD0iZGVzYyI+TUE15Y+WMTHjgIExM+OAgTE044CBMTXjgIExMueahOW5s+Wdh+WAvO+8jOS4ujEz44CCRU1BNeeUqOacrOacn+S7t+agvDEy5LmY5LiJ5YiG5LmL5LiA77yM5Yqg5LiK5LiK5pyfRU1BMTPkuZjkuInliIbkuYvkuozvvIznuqbkuLoxMi42N+OAguWIneWni0VNQeWPluWJjTXmnJ/lnYflgLwxMuOAgjwvZGVzYz4KICA8cmVjdCB3aWR0aD0iOTYwIiBoZWlnaHQ9IjU0MCIgcng9IjI0IiBmaWxsPSIjZjBmNmZmIi8+CiAgPGcgZm9udC1mYW1pbHk9Ik1pY3Jvc29mdCBZYUhlaSwgc2Fucy1zZXJpZiIgZmlsbD0iIzE1MmM1MCI+CiAgICA8dGV4dCB4PSIzNiIgeT0iNTYiIGZvbnQtc2l6ZT0iMzAiIGZvbnQtd2VpZ2h0PSI3MDAiPuWQjOagt+eahOS7t+agvOi+k+WFpe+8jOS4jeWQjOeahOiuoeeul+aWueW8jzwvdGV4dD4KICAgIDx0ZXh0IHg9IjM2IiB5PSI5MiIgZm9udC1zaXplPSIyMCIgZmlsbD0iIzUyNjY4MSI+6Jma5p6E5pWw5o2u77yaMTDjgIExMuOAgTEx44CBMTPjgIExNOOAgTE144CBMTI8L3RleHQ+CiAgICA8cmVjdCB4PSIyOCIgeT0iMTE4IiB3aWR0aD0iNDQwIiBoZWlnaHQ9IjMyNiIgcng9IjE4IiBmaWxsPSJ3aGl0ZSIvPgogICAgPHJlY3QgeD0iNDkyIiB5PSIxMTgiIHdpZHRoPSI0NDAiIGhlaWdodD0iMzI2IiByeD0iMTgiIGZpbGw9IndoaXRlIi8+CiAgICA8dGV4dCB4PSI1MiIgeT0iMTY1IiBmb250LXNpemU9IjI4IiBmb250LXdlaWdodD0iNzAwIiBmaWxsPSIjMjU2M2ViIj5NQTUgwrcg5pyA6L+RNeacn+etieadg+W5s+WdhzwvdGV4dD4KICAgIDx0ZXh0IHg9IjUxNiIgeT0iMTY1IiBmb250LXNpemU9IjI4IiBmb250LXdlaWdodD0iNzAwIiBmaWxsPSIjNzA1MGM1Ij5FTUE1IMK3IOS7t+agvOS4juWJjeWAvOWKoOadgzwvdGV4dD4KICAgIDxnIGZpbGw9IiNlOGYwZmMiPgogICAgICA8cmVjdCB4PSI1MiIgeT0iMjAwIiB3aWR0aD0iNjQiIGhlaWdodD0iNjIiIHJ4PSI4Ii8+PHJlY3QgeD0iMTMyIiB5PSIyMDAiIHdpZHRoPSI2NCIgaGVpZ2h0PSI2MiIgcng9IjgiLz48cmVjdCB4PSIyMTIiIHk9IjIwMCIgd2lkdGg9IjY0IiBoZWlnaHQ9IjYyIiByeD0iOCIvPjxyZWN0IHg9IjI5MiIgeT0iMjAwIiB3aWR0aD0iNjQiIGhlaWdodD0iNjIiIHJ4PSI4Ii8+PHJlY3QgeD0iMzcyIiB5PSIyMDAiIHdpZHRoPSI2NCIgaGVpZ2h0PSI2MiIgcng9IjgiLz4KICAgIDwvZz4KICAgIDxnIGZvbnQtc2l6ZT0iMjgiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtd2VpZ2h0PSI3MDAiPgogICAgICA8dGV4dCB4PSI4NCIgeT0iMjQwIj4xMTwvdGV4dD48dGV4dCB4PSIxNjQiIHk9IjI0MCI+MTM8L3RleHQ+PHRleHQgeD0iMjQ0IiB5PSIyNDAiPjE0PC90ZXh0Pjx0ZXh0IHg9IjMyNCIgeT0iMjQwIj4xNTwvdGV4dD48dGV4dCB4PSI0MDQiIHk9IjI0MCI+MTI8L3RleHQ+CiAgICA8L2c+CiAgICA8dGV4dCB4PSI1MiIgeT0iMzAxIiBmb250LXNpemU9IjIzIj7mr4/kuKrmlbDmja7ljaAxLzU8L3RleHQ+CiAgICA8dGV4dCB4PSI1MiIgeT0iMzc3IiBmb250LXNpemU9IjM0IiBmb250LXdlaWdodD0iNzAwIiBmaWxsPSIjMjU2M2ViIj42NcO3Ne+8nTEzPC90ZXh0PgogICAgPHJlY3QgeD0iNTE2IiB5PSIyMDAiIHdpZHRoPSIxODIiIGhlaWdodD0iMTA2IiByeD0iMTAiIGZpbGw9IiNmMmVkZmYiLz4KICAgIDxyZWN0IHg9IjcyMCIgeT0iMjAwIiB3aWR0aD0iMTg2IiBoZWlnaHQ9IjEwNiIgcng9IjEwIiBmaWxsPSIjZjJlZGZmIi8+CiAgICA8dGV4dCB4PSI1MzQiIHk9IjIzNCIgZm9udC1zaXplPSIyMCI+5pys5pyf5Lu35qC877yaMTI8L3RleHQ+CiAgICA8dGV4dCB4PSI3MzgiIHk9IjIzNCIgZm9udC1zaXplPSIyMCI+5LiK5pyfRU1B77yaMTM8L3RleHQ+CiAgICA8dGV4dCB4PSI1NzAiIHk9IjI4MCIgZm9udC1zaXplPSIyOCIgZm9udC13ZWlnaHQ9IjcwMCI+w5cxLzM8L3RleHQ+CiAgICA8dGV4dCB4PSI3NzQiIHk9IjI4MCIgZm9udC1zaXplPSIyOCIgZm9udC13ZWlnaHQ9IjcwMCI+w5cyLzM8L3RleHQ+CiAgICA8dGV4dCB4PSI1MTYiIHk9IjM3NyIgZm9udC1zaXplPSIzMiIgZm9udC13ZWlnaHQ9IjcwMCIgZmlsbD0iIzcwNTBjNSI+NO+8izguNjY24oCm4omIMTIuNjc8L3RleHQ+CiAgICA8dGV4dCB4PSIzNiIgeT0iNDgxIiBmb250LXNpemU9IjE5IiBmaWxsPSIjNTI2NjgxIj7liJ3lp4vljJbnuqblrprvvJrnrKw15pyfRU1B77yd5YmNNeacn+Wdh+WAvDEy77yM56ysNuacn0VNQe+8nTEz44CCPC90ZXh0PgogICAgPHRleHQgeD0iMzYiIHk9IjUxNCIgZm9udC1zaXplPSIxOSIgZmlsbD0iIzUyNjY4MSI+56ysN+acn+S4pOadoeWdh+e6v+WIhuW8gO+8jOadpeiHqueul+azleW3ruW8gu+8m+S4jeiDveeUseatpOWIpOaWreWTquadoeabtOWHhuehruOAgjwvdGV4dD4KICA8L2c+Cjwvc3ZnPgo=)

MA5没有变化，是因为本期加入的12，正好等于退出窗口的第2期收盘价12。EMA5下降，则是因为本期价格12低于上期EMA值13。

再假设第8期收盘价为16，计算得到：

| 周期 | 收盘价 | MA5 | EMA5 |
| --- | --- | --- | --- |
| 第5期 | 14 | 12.00 | 12.00（初始值） |
| 第6期 | 15 | 13.00 | 13.00 |
| 第7期 | 12 | 13.00 | 12.67 |
| 第8期 | 16 | 14.00 | 13.78 |

表格只在显示时保留两位小数，递推使用未舍入数值；如果每一步先四舍五入，再代入下一步，可能出现小的计算差异。

## “EMA反应更快”，准确地说是什么意思？

以5期为例，MA最新数据的权重为20%，EMA为约33.33%。

假设已有历史数据与上一期结果都固定，只把本期价格提高3：

- MA5增加：3×1/5＝0.6。

- EMA5增加：3×1/3＝1。

这说明在相同参数下，EMA对本期输入的变化赋予了更大的权重。

但不能把它理解成“EMA每一期的变化幅度都比MA大”，或“EMA永远更贴近价格”。MA还受到旧数据退出窗口的影响，EMA则取决于价格与上期EMA之间的差，两者的实际变化要结合历史输入计算。

同样，较大的新数据权重，也会让单次短暂波动更明显地进入结果。反应更敏感是一种数学特性，不是更准确的证明。

## 为什么叫“指数”移动平均？

把上一期EMA的公式继续展开，就能看见不同数据的权重。

对于EMA5，新加入的数据最初权重为1/3；下一期，它的权重再乘2/3；再下一期，再乘一次2/3：

| 距离加入的时间 | 该数据的权重 |
| --- | --- |
| 加入当期 | 1/3≈33.33% |
| 经过1期更新 | (1/3)×(2/3)≈22.22% |
| 经过2期更新 | (1/3)×(2/3)²≈14.81% |
| 经过3期更新 | (1/3)×(2/3)³≈9.88% |

这里展示的是递推开始后新加入数据的权重。每经过一期，它都按相同的比例衰减，这就是“指数”名称对应的计算特点。

因此，EMA5不是只保留最近5根K线。参数5决定平滑系数，较早数据仍可通过递推结果产生影响。在精确数学运算下，这种影响逐渐变小，而不是到第6根就统一清零；实际软件还受到数值精度和初始化方式影响。

## 为什么两个软件的EMA数值可能不同？

相同周期的EMA仍可能因初始值、起算历史、价格来源和精度而不同。本文采用α＝2/(N＋1)，不能把这一权重直接套到所有名为SMA或RMA的函数上。

先核对价格字段、周期、时段、数据来源和复权方式，再检查平滑系数、初始值和历史起算范围。

本文用前5期均值作为初始EMA。另一种实现可能从第一个有效价格开始递推。即使后续使用相同公式，初期数值也可能不同。

如果两种计算此后输入完全相同、系数也相同，仅初始值不同，经过k次更新后，差异为：

剩余差异＝初始差异×(1－α)ᵏ

对于EMA5，每更新一期，初始差异保留原来的2/3。计算越往后，初始值的影响通常越小。因此，核对EMA时，不能只拿屏幕上可见的5根K线就要求复算出相同结果。

## 学习均线，先核对这三个问题

输入是什么？权重怎么分？从哪里开始算？

简单MA的重点是固定窗口和等权平均；EMA的重点是递推计算和逐期衰减。理解了这两种机制，再看图上的曲线差异，就能回到具体数字寻找原因。

## MA、EMA、BOLL分别是什么意思？

这三个名称并不代表同一种计算：MA在本文中指简单移动平均，EMA是指数移动平均，BOLL是由中轨和上下轨组成的布林带。

| 名称 | 本文采用的计算口径 | 图上数值表达什么 |
| --- | --- | --- |
| MA / SMA | 最近N个价格等权平均 | 该窗口的平均水平 |
| EMA | 新价格与上期EMA加权递推 | 按指数衰减权重得到的平均水平 |
| BOLL | 中轨取MA，上下轨加减K倍标准差 | 窗口的平均水平与离散程度 |

因此，常见BOLL的中轨可以与同输入、同周期的MA重合，但BOLL的上下轨不是另外两条不同周期的均线。完整算例见[BOLL布林带计算公式](https://www.structguide.com/indicators/boll)。

若界面出现EXPMA、EMA2等名称，应查看该软件的公式说明，不能仅凭缩写认定它与本文EMA完全一致。

## 相关阅读

- [MACD是什么指标？DIF、DEA和柱状图的计算公式图解](https://www.structguide.com/indicators/macd)：查看EMA如何参与后续差值计算。

- [BOLL布林带怎么算？用一组数字看懂中轨、上轨和下轨](https://www.structguide.com/indicators/boll)：继续了解均值与标准差组成的区间。

- [MA均线怎么算？用5个数字看懂移动平均](https://www.structguide.com/indicators/ma)

- [返回常见指标速查手册](https://www.structguide.com/indicators/)

本文介绍通用指标计算，不表示Struct Guide插件提供MA或EMA绘制功能。插件的分型、笔、线段和中枢计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
