来源：https://www.structguide.com/indicators/macd
抓取：2026-11-06T00:31:05+08:00

# MACD是什么指标？DIF、DEA与柱状图计算公式

MACD的常见计算过程，是先算两条不同周期的EMA，求差，再对这个差值做一次平滑，最后画出两者的差。 看起来是两条曲线和一组柱子，背后是一串可以逐步复算的运算。

MACD是Moving Average Convergence Divergence的缩写，中文常称指数平滑异同移动平均线。本文只解释图上的数值从哪里来，以及参数怎样改变计算，不讨论操作用法。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 收盘价C |
| 计算 | DIF＝短期EMA－长期EMA；DEA＝DIF的EMA；柱值＝DIF－DEA |
| 参数与约定 | 常见周期12、26、9；本文三次平滑均用EMA |
| 单位与边界 | 曲线和柱值与价格同单位；本文柱值不乘2 |

公式来源：[TradingView MACD说明](https://www.tradingview.com/support/solutions/43000502344-moving-average-convergence-divergence-macd-indicator/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## MACD计算公式速查

本文使用收盘价C作为输入，三次平滑均采用EMA。记短周期为S、长周期为L、差值平滑周期为M。

| 图上元素 | 计算公式 | 含义 |
| --- | --- | --- |
| DIF | EMA(C,S)－EMA(C,L) | 两种周期平均值的差 |
| DEA | EMA(DIF,M) | 对DIF序列再次做指数平滑 |
| 柱状图H | DIF－DEA | DIF与其平滑值的差 |

这里用DIF、DEA作为本文的统一标签。TradingView将第一条线标为MACD；对照软件时应核对公式，不要只按名称认线。

![MACD计算过程：收盘价分别计算两条EMA，相减得到DIF，再平滑得到DEA，最后用DIF减DEA得到柱值](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDAwIiB2aWV3Qm94PSIwIDAgOTYwIDQwMCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPgo8dGl0bGUgaWQ9InRpdGxlIj5NQUNE77ya5LuO5Lu35qC85Yiw5Lik5qyh5beu5YC8PC90aXRsZT48ZGVzYyBpZD0iZGVzYyI+5Lu35qC85YiG5Yir6K6h566X55+t5ZGo5pyf5ZKM6ZW/5ZGo5pyfRU1B77yM55u45YeP5b6X5YiwRElG77yb5a+5RElG6L+b6KGMRU1B5bmz5ruR5b6X5YiwREVB77ybRElG5YePREVB5b6X5Yiw5p+x5YC8SOOAguacrOaWh+mHh+eUqOS4gOWAjeW3ruWAvOWPo+W+hOOAgjwvZGVzYz4KPHJlY3Qgd2lkdGg9Ijk2MCIgaGVpZ2h0PSI0MDAiIHJ4PSIyMCIgZmlsbD0iI2YwZjZmZiIvPgo8ZyBmb250LWZhbWlseT0iTWljcm9zb2Z0IFlhSGVpLCBzYW5zLXNlcmlmIiBmaWxsPSIjMTQyYzUwIj4KPHRleHQgeD0iMzYiIHk9IjUyIiBmb250LXNpemU9IjI4IiBmb250LXdlaWdodD0iYm9sZCI+TUFDROeahOacrOi0qO+8muW5s+WdhyDihpIg5rGC5beuIOKGkiDlubPmu5Eg4oaSIOWGjeaxguW3rjwvdGV4dD4KPHRleHQgeD0iMzYiIHk9Ijg4IiBmb250LXNpemU9IjE4Ij7kuKTmnaHnur/lkozkuIDnu4Tmn7HlrZDvvIzpg73og73msr/nnYDorqHnrpfmraXpqqTlpI3nrpc8L3RleHQ+CjxnIGZpbGw9IndoaXRlIiBzdHJva2U9IiNiOGQwZjQiIHN0cm9rZS13aWR0aD0iMiI+CjxyZWN0IHg9IjM2IiB5PSIxNDIiIHdpZHRoPSIxNDAiIGhlaWdodD0iMTI0IiByeD0iMTYiLz4KPHJlY3QgeD0iMjE2IiB5PSIxMjQiIHdpZHRoPSIyMDAiIGhlaWdodD0iMTYwIiByeD0iMTYiLz4KPHJlY3QgeD0iNDU2IiB5PSIxNDIiIHdpZHRoPSIyMDAiIGhlaWdodD0iMTI0IiByeD0iMTYiLz4KPHJlY3QgeD0iNjk2IiB5PSIxNDIiIHdpZHRoPSIyMjgiIGhlaWdodD0iMTI0IiByeD0iMTYiLz4KPC9nPgo8ZyBmb250LXNpemU9IjIyIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj4KPHRleHQgeD0iMTA2IiB5PSIxOTAiIGZvbnQtd2VpZ2h0PSJib2xkIj7mlLbnm5jku7dDPC90ZXh0Pjx0ZXh0IHg9IjEwNiIgeT0iMjI2IiBmb250LXNpemU9IjE3Ij7ovpPlhaXluo/liJc8L3RleHQ+Cjx0ZXh0IHg9IjMxNiIgeT0iMTYzIj7nn63lkajmnJ9FTUE8L3RleHQ+PHRleHQgeD0iMzE2IiB5PSIxOTgiPu+8jTwvdGV4dD48dGV4dCB4PSIzMTYiIHk9IjIzMiI+6ZW/5ZGo5pyfRU1BPC90ZXh0Pjx0ZXh0IHg9IjMxNiIgeT0iMjY1IiBmb250LXNpemU9IjE4IiBmaWxsPSIjMTc1ZGRkIj7lvpfliLBESUY8L3RleHQ+Cjx0ZXh0IHg9IjU1NiIgeT0iMTkwIiBmb250LXdlaWdodD0iYm9sZCI+RU1BKERJRixNKTwvdGV4dD48dGV4dCB4PSI1NTYiIHk9IjIyOCIgZm9udC1zaXplPSIxOCIgZmlsbD0iIzE3NWRkZCI+5b6X5YiwREVBPC90ZXh0Pgo8dGV4dCB4PSI4MTAiIHk9IjE5MCIgZm9udC13ZWlnaHQ9ImJvbGQiPkRJRu+8jURFQTwvdGV4dD48dGV4dCB4PSI4MTAiIHk9IjIyOCIgZm9udC1zaXplPSIxOCIgZmlsbD0iIzE3NWRkZCI+5b6X5Yiw5p+x5YC8SDwvdGV4dD4KPC9nPgo8ZyBmb250LXNpemU9IjMwIiBmaWxsPSIjMTc1ZGRkIj48dGV4dCB4PSIxODIiIHk9IjIxMiI+4oaSPC90ZXh0Pjx0ZXh0IHg9IjQyMiIgeT0iMjEyIj7ihpI8L3RleHQ+PHRleHQgeD0iNjYyIiB5PSIyMTIiPuKGkjwvdGV4dD48L2c+Cjx0ZXh0IHg9IjM2IiB5PSIzMzMiIGZvbnQtc2l6ZT0iMTkiPuW4uOingeWPguaVsO+8muefreWRqOacnzEy77yM6ZW/5ZGo5pyfMjbvvIxESUblubPmu5HlkajmnJ8544CCPC90ZXh0Pgo8dGV4dCB4PSIzNiIgeT0iMzY4IiBmb250LXNpemU9IjE3IiBmaWxsPSIjNTM2NzgwIj7mnKzlm77kvb/nlKhI77ydRElG77yNREVB44CC6Iul6L2v5Lu26aKd5aSW5LmYMu+8jOafseWAvOWQjOavlOS+i+aUvuWkp+OAgjwvdGV4dD4KPC9nPjwvc3ZnPgo=)

EMA每一步使用：本期EMA＝α×本期输入＋(1－α)×上期EMA，α＝2÷(N＋1)。计算DEA时，“本期输入”是DIF，不再是收盘价。权重与初始值的详细解释见[MA和EMA的区别](https://www.structguide.com/indicators/ma-vs-ema)。

## MACD参数12、26、9是什么意思？

常见设置为S＝12、L＝26、M＝9，对应短周期EMA、长周期EMA、DIF的平滑周期。它们是计算参数，不是三条线的颜色编号。

| 参数 | 对应递推权重 |
| --- | --- |
| 12 | 新收盘价占2/13，其余权重留给上期短周期EMA |
| 26 | 新收盘价占2/27，其余权重留给上期长周期EMA |
| 9 | 新DIF占2/10，其余权重留给上期DEA |

“12期”随计算所用的K线周期变化：日K线使用12期参数，周K线也可以使用12期参数，但输入序列不同。EMA也不是只保留最近12或26个数，较早数据的影响会沿递推逐步衰减。

修改参数就是修改权重，不能从公式本身推出一套适合所有数据的参数。

## 用4个数字手算一次

为了让分数容易核对，以下教学例子改用3、5、3，不是参数推荐。输入虚构收盘价10、12、11、13。

约定第一期两条EMA都取首个价格10，因此首个DIF＝0，DEA也从0开始。软件可能采用其他初始化方式，本表不代表所有软件的起算方法。

短周期EMA的α＝1/2，长周期EMA的α＝1/3，DEA的α＝1/2。第二期输入12：

- 短周期EMA＝12×1/2＋10×1/2＝11。

- 长周期EMA＝12×1/3＋10×2/3＝10.6667（显示值）。

- DIF＝11－10.6667≈0.3333。

- DEA＝DIF×1/2＋0×1/2≈0.1667。

- 柱值H＝DIF－DEA≈0.1667。

继续递推，得到：

| 期数 | 输入 | EMA3 | EMA5 | DIF | DEA3 | H＝DIF－DEA |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 10 | 10.0000 | 10.0000 | 0.0000 | 0.0000 | 0.0000 |
| 2 | 12 | 11.0000 | 10.6667 | 0.3333 | 0.1667 | 0.1667 |
| 3 | 11 | 11.0000 | 10.7778 | 0.2222 | 0.1944 | 0.0278 |
| 4 | 13 | 12.0000 | 11.5185 | 0.4815 | 0.3380 | 0.1435 |

计算保留完整精度，表格仅显示四位小数。直接用已经四舍五入的表格数值继续计算，末位可能出现差异。

## MACD指标怎么看？认清零轴、线和柱

这里的“看”是把图形还原成数值关系：

- DIF在零轴上方：短周期EMA数值大于长周期EMA。

- DIF在零轴下方：短周期EMA数值小于长周期EMA。

- 柱值为正：DIF大于DEA；柱值为负则相反。

- 柱值为零：DIF与DEA相等，不要求两者本身等于零。

例如DIF＝－1、DEA＝－2，柱值仍为＋1。所以“柱在零轴上方”与“两条线在零轴上方”不是同一件事。

颜色属于显示规则。有的软件同时用正负与相邻柱值的增减决定颜色，不能看到一种颜色就认定数值一定为正。核对图例、零轴位置和具体数字，比记颜色更直接。

## 为什么两个软件的MACD数字不一样？

MACD柱值有DIF－DEA和2×(DIF－DEA)等显示口径。只有两条线、输入、平滑与初始化均一致时，才能把柱值相差两倍归因于倍数；还应按公式核对MACD、DIF、DEA等字段名称。

先逐项核对：

- 输入是否同一组数据：周期、价格来源、复权口径与数据起点是否一致。

- 参数是否一致：短周期、长周期和平滑周期都要核对。

- 平滑方式是否一致：本页使用EMA，部分实现允许选择其他平均算法。

- 初始值是否一致：从首个输入起算，或先取一段均值作种子，会影响后续数值。

- 柱值是否另有倍率：若公式写成2×(DIF－DEA)，柱高会是本文口径的两倍，但两条线数值不因此改变。

因此，看到差异不应只比较截图长度，应先对齐公式和刻度。未结束K线的输入变化时，两条EMA、DIF、DEA及柱值也可能随之更新。

## 继续读懂指标背后的计算

- [MA均线怎么算](https://www.structguide.com/indicators/ma)：从等权平均开始。

- [MA和EMA的区别](https://www.structguide.com/indicators/ma-vs-ema)：理解递推与历史权重。

- [BOLL布林带怎么算](https://www.structguide.com/indicators/boll)：理解均值与标准差。

- [常见指标速查手册](https://www.structguide.com/indicators/)：按计算问题查阅。

公式与显示字段参考[TradingView MACD说明](https://www.tradingview.com/support/solutions/43000502344-moving-average-convergence-divergence-macd-indicator/)。数字算例与流程图为本站自拟。本文介绍通用指标，不表示Struct Guide插件提供MACD功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
