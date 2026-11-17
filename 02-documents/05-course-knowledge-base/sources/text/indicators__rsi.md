来源：https://www.structguide.com/indicators/rsi
抓取：2026-11-06T00:31:07+08:00

# RSI相对强弱指标是什么？计算公式、参数与平滑图解

RSI把相邻收盘价的变化拆成上涨量与下跌量，分别平滑，再计算两者的相对比例。 RSI是Relative Strength Index的缩写，常称相对强弱指标；本文只介绍其数学计算。

这里的“相对”是同一组输入中上涨量与下跌量的比较，不是与另一只品种或某个指数直接作比。RSI为70也不表示后一期有70%的上涨概率。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 相邻收盘价变化；上涨量U和非负下跌量D |
| 计算 | 分别平滑得到A、B；RSI＝100×A/(A＋B) |
| 参数与约定 | 本文采用Wilder平滑，新输入权重1/N；初始值见算例 |
| 单位与边界 | A＋B＞0时取0—100；不是未来概率 |

公式来源：[TradingView RSI说明](https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## RSI计算公式速查

记本期收盘价为Cₜ，上期为Cₜ₋₁。本文采用Wilder平滑，也常写作RMA，新输入权重为1/N。

| 步骤 | 公式 |
| --- | --- |
| 价格变化Δ | Cₜ－Cₜ₋₁ |
| 上涨量U | max(Δ,0) |
| 下跌量D | max(－Δ,0)，取非负数 |
| 平滑上涨量A | (上期A×(N－1)＋本期U)÷N |
| 平滑下跌量B | (上期B×(N－1)＋本期D)÷N |
| RSI | 100×A÷(A＋B)，要求A＋B＞0 |

当B＞0时，也可以先算RS＝A/B，再算RSI＝100－100/(1＋RS)，两种写法等价。

![RSI计算图解：价格变化分为上涨量与非负下跌量，分别平滑，再计算A除以A加B的百分比](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDQwIiB2aWV3Qm94PSIwIDAgOTYwIDQ0MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPgo8dGl0bGUgaWQ9InRpdGxlIj5SU0nmiorku7fmoLzlj5jljJbmi4blvIDjgIHlubPmu5Hlho3msYLmr5Tkvos8L3RpdGxlPjxkZXNjIGlkPSJkZXNjIj7omZrmnoTku7fmoLwxMOOAgTEy44CBMTHjgIExM+S6p+eUn+WPmOWMluatozLjgIHotJ8x44CB5q2jMuOAguS4iua2qOmHj+S4ujLjgIEw44CBMu+8jOS4i+i3jOmHj+S4ujDjgIEx44CBMO+8jOS7pTPmnJ/lnYflgLzliJ3lp4vljJbvvIxSU0nkuLo4MOOAgjwvZGVzYz4KPHJlY3Qgd2lkdGg9Ijk2MCIgaGVpZ2h0PSI0NDAiIHJ4PSIyMCIgZmlsbD0iI2YwZjZmZiIvPgo8ZyBmb250LWZhbWlseT0iTWljcm9zb2Z0IFlhSGVpLHNhbnMtc2VyaWYiIGZpbGw9IiMxNDJjNTAiPgo8dGV4dCB4PSIzNiIgeT0iNTIiIGZvbnQtc2l6ZT0iMjgiIGZvbnQtd2VpZ2h0PSJib2xkIj5SU0nvvJrliIbmi4blj5jljJbvvIzlho3mr5TovoPlubPmu5HlkI7nmoTmr5Tkvos8L3RleHQ+Cjx0ZXh0IHg9IjM2IiB5PSI5MCIgZm9udC1zaXplPSIxOCI+6Jma5p6E566X5L6L772cTu+8nTPvvIzku6XmnIDliJ0z5Liq5Y+Y5YyW55qE5Z2H5YC85Yid5aeL5YyWPC90ZXh0Pgo8cmVjdCB4PSIzNiIgeT0iMTIwIiB3aWR0aD0iODg4IiBoZWlnaHQ9IjYwIiByeD0iMTQiIGZpbGw9IndoaXRlIi8+Cjx0ZXh0IHg9IjY1IiB5PSIxNTgiIGZvbnQtc2l6ZT0iMjIiPuS7t+agvO+8mjEwIOKGkiAxMiDihpIgMTEg4oaSIDEzPC90ZXh0Pjx0ZXh0IHg9IjU2MCIgeT0iMTU4IiBmb250LXNpemU9IjIyIj7lj5jljJbvvJrvvIsy44CB77yNMeOAge+8izI8L3RleHQ+CjxnIGZpbGw9IndoaXRlIiBzdHJva2U9IiNiOGQwZjQiPjxyZWN0IHg9IjM2IiB5PSIyMDIiIHdpZHRoPSI0MjYiIGhlaWdodD0iOTgiIHJ4PSIxNCIvPjxyZWN0IHg9IjQ5OCIgeT0iMjAyIiB3aWR0aD0iNDI2IiBoZWlnaHQ9Ijk4IiByeD0iMTQiLz48L2c+CjxnIGZvbnQtc2l6ZT0iMjEiIHRleHQtYW5jaG9yPSJtaWRkbGUiPjx0ZXh0IHg9IjI0OSIgeT0iMjM5Ij7kuIrmtqjph49V77yaMuOAgTDjgIEyPC90ZXh0Pjx0ZXh0IHg9IjI0OSIgeT0iMjc3IiBmaWxsPSIjMTc1ZGRkIj7liJ3lp4tB77ydNC8zPC90ZXh0Pjx0ZXh0IHg9IjcxMSIgeT0iMjM5Ij7kuIvot4zph49E77yaMOOAgTHjgIEwPC90ZXh0Pjx0ZXh0IHg9IjcxMSIgeT0iMjc3IiBmaWxsPSIjMTc1ZGRkIj7liJ3lp4tC77ydMS8zPC90ZXh0PjwvZz4KPHRleHQgeD0iNDgwIiB5PSIzNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMjUiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMTc1ZGRkIj5SU0nvvJ0xMDDDl0HDtyhB77yLQinvvJ04MDwvdGV4dD4KPHRleHQgeD0iMzYiIHk9IjQwNCIgZm9udC1zaXplPSIxOCI+5a6D5piv5Lik56eN5bmz5ruR6YeP55qE5q+U5L6L77yM5LiN5piv5ZCO5LiA5pyf5LiK5rao55qE5qaC546H44CCPC90ZXh0Pgo8L2c+PC9zdmc+Cg==)

## 用5个收盘价手算RSI

用虚构收盘价10、12、11、13、12演示。为方便手算取N＝3，仅为教学参数。约定用最初3个价格变化的简单平均初始化A、B，之后再递推。

| 期数 | 收盘价 | 与上期之差Δ | U | D |
| --- | --- | --- | --- | --- |
| 1 | 10 | — | — | — |
| 2 | 12 | ＋2 | 2 | 0 |
| 3 | 11 | －1 | 0 | 1 |
| 4 | 13 | ＋2 | 2 | 0 |
| 5 | 12 | －1 | 0 | 1 |

第4期已有3个变化值，初始化：

- A＝(2＋0＋2)÷3＝4/3。

- B＝(0＋1＋0)÷3＝1/3。

- RSI＝100×(4/3)÷(5/3)＝80。

第5期加入U＝0、D＝1：

- A＝((4/3)×2＋0)÷3＝8/9。

- B＝((1/3)×2＋1)÷3＝5/9。

- RSI＝100×(8/9)÷(13/9)≈61.5385。

3个价格变化需要4个收盘价。 若只取3个收盘价，就只有2个相邻变化。也不能只对上涨的那些期数取平均、对下跌的那些期数另取平均；本例的零值同样参与各自序列的初始化和平滑。

## RSI为70到底表示什么？

在上述定义下，RSI＝70表示A/(A＋B)＝0.7，也就是平滑上涨量占两种平滑量之和的70%。若B＞0，等价于A/B＝7/3。

这不是上涨期数占比，也不是后一期价格方向的概率。上涨1次但幅度较大，与上涨多次但每次幅度较小，不能只按次数比较RSI。

## RSI周期与EMA有什么区别？

常见RSI周期是14。按本文Wilder口径，新数据权重为1/14；常见EMA14的新数据权重则为2/15。即使周期编号相同，两种平滑公式也不同。

Wilder平滑在初始化后使用上期状态，不是每次都重新取最近N个变化做简单平均。历史输入的影响沿递推逐渐衰减。只替换平滑方式，即使输入完全一致，也可能算出不同的RSI。

更完整的权重比较见[MA与EMA计算图解](https://www.structguide.com/indicators/ma-vs-ema)。

## 分母为0与软件差异

RSI的数值差异可能来自平滑权重、初始值、输入和起算历史。本文使用Wilder平滑，并在A＋B＞0时计算100×A/(A＋B)；两种平滑量都为0时，不能由这一比例公式直接得到唯一显示值。

| 条件 | 本文比例公式的结果 |
| --- | --- |
| A＞0、B＝0 | RSI＝100 |
| A＝0、B＞0 | RSI＝0 |
| A＝0、B＝0 | 0/0未定义，需由软件规定处理方式 |

全程不变的价格可能涉及第三种情形，不能脱离软件实现断言一定显示50、0或100。除此之外，还应核对初始化方法、起算数据量、输入价格、图表周期和显示精度。

日K线尚未结束时，输入收盘价尚未固定，U、D及RSI可能更新。图中颜色和水平参考线属于显示设置，不改变上述公式。

## 相关阅读与公式来源

- [PSY心理线](https://www.structguide.com/indicators/psy)：区分上涨次数占比与平滑幅度。

- [KDJ怎么算](https://www.structguide.com/indicators/kdj)：窗口位置、两次平滑与J值。

- [ATR怎么算](https://www.structguide.com/indicators/atr)：另一种采用Wilder平滑的指标。

- [返回常见指标速查手册](https://www.structguide.com/indicators/)。

计算口径参考[TradingView RSI说明](https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/)。数字算例与图解为本站自拟，种子约定已在算例中注明。本文不表示Struct Guide插件提供RSI功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
