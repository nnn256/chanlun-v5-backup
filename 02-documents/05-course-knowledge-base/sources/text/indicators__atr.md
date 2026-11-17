来源：https://www.structguide.com/indicators/atr
抓取：2026-11-06T00:31:03+08:00

# ATR平均真实波幅是什么？TR计算公式与平滑图解

ATR先计算每根K线的真实波幅TR，再将TR序列平滑。 ATR是Average True Range的缩写，常称平均真实波幅。它保留的是幅度大小，不保留价格变化的正负方向。

如果只算本期最高价减最低价，前一期收盘价到本期价格范围之间的间隔就可能被遗漏。本页用虚构数据解释如何把这部分纳入计算。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 本期最高H、最低L和前收盘Cₚ |
| 计算 | TR＝max(H－L,abs(H－Cₚ),abs(L－Cₚ))；再平滑为ATR |
| 参数与约定 | 本文采用Wilder平滑，新输入权重1/N |
| 单位与边界 | 与价格同单位，非负；ATR本身不是百分比 |

公式来源：[TradingView ATR说明](https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## TR与ATR计算公式

记本期最高价为H、最低价为L、前一期收盘价为Cₚ：

TR＝max(H－L，|H－Cₚ|，|L－Cₚ|)

竖线表示绝对值；先算三个非负数，再取其中最大的一个。在H≥L的有效数据下，也等价于max(H,Cₚ)－min(L,Cₚ)。

本文ATR采用Wilder平滑：

本期ATR＝(上期ATR×(N－1)＋本期TR)÷N。

它的新输入权重为1/N。以下约定先用最初N个有效TR的简单平均作为种子，再逐期递推；不同初始化方式需另行核对。

![ATR图解：前收盘价100、本期最低108、最高110，高低差为2但真实波幅为10；TR包含前收盘价到本期价格范围的距离](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDQwIiB2aWV3Qm94PSIwIDAgOTYwIDQ0MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPgo8dGl0bGUgaWQ9InRpdGxlIj5UUue6s+WFpeWJjeS4gOacn+aUtuebmOS7tzwvdGl0bGU+PGRlc2MgaWQ9ImRlc2MiPuiZmuaehOWJjeaUtuebmOS7tzEwMOOAgeacrOacn+acgOS9jjEwOOOAgeacgOmrmDExMOOAgumrmOS9juW3ruS4ujLvvIzmnIDpq5jku7fkuI7liY3mlLbnm5jku7flt67kuLoxMO+8jOacgOS9juS7t+S4juWJjeaUtuebmOS7t+W3ruS4ujjvvIzlj5bmnIDlpKflgLzlvpdUUuS4ujEw44CCPC9kZXNjPgo8cmVjdCB3aWR0aD0iOTYwIiBoZWlnaHQ9IjQ0MCIgcng9IjIwIiBmaWxsPSIjZjBmNmZmIi8+CjxnIGZvbnQtZmFtaWx5PSJNaWNyb3NvZnQgWWFIZWksc2Fucy1zZXJpZiIgZmlsbD0iIzE0MmM1MCI+Cjx0ZXh0IHg9IjM2IiB5PSI1MiIgZm9udC1zaXplPSIyOCIgZm9udC13ZWlnaHQ9ImJvbGQiPumrmOS9juW3ruWPquaciTLvvIznnJ/lrp7ms6LluYVUUuWNtOaYrzEwPC90ZXh0Pgo8dGV4dCB4PSIzNiIgeT0iOTAiIGZvbnQtc2l6ZT0iMTgiPuiZmuaehOeul+S+i++9nOWJjeaUtuebmOS7tzEwMO+8jOacrOacn+acgOS9jjEwOOOAgeacgOmrmDExMDwvdGV4dD4KPHBhdGggZD0iTTEwMCAxNjAgSDg2MCIgc3Ryb2tlPSIjYjhkMGY0IiBzdHJva2Utd2lkdGg9IjMiLz4KPHBhdGggZD0iTTcwOCAxNjAgSDg2MCIgc3Ryb2tlPSIjN2MzYWVkIiBzdHJva2Utd2lkdGg9IjE2IiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KPGNpcmNsZSBjeD0iMTAwIiBjeT0iMTYwIiByPSI4IiBmaWxsPSIjMTc1ZGRkIi8+CjxnIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTkiPjx0ZXh0IHg9IjEwMCIgeT0iMTMyIj7liY3mlLbnm5gxMDA8L3RleHQ+PHRleHQgeD0iNzA4IiB5PSIxMzIiPuacgOS9jjEwODwvdGV4dD48dGV4dCB4PSI4NjAiIHk9IjEzMiI+5pyA6auYMTEwPC90ZXh0PjwvZz4KPHBhdGggZD0iTTEwMCAxODUgVjIxMiBIODYwIFYxODUiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzE3NWRkZCIgc3Ryb2tlLXdpZHRoPSIyIi8+Cjx0ZXh0IHg9IjQ4MCIgeT0iMjQ1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjIxIiBmaWxsPSIjMTc1ZGRkIj7opobnm5bliY3mlLbnm5jku7fkuI7mnKzmnJ/pq5jkvY7ojIPlm7TvvJoxMDwvdGV4dD4KPHJlY3QgeD0iMzYiIHk9IjI3MiIgd2lkdGg9Ijg4OCIgaGVpZ2h0PSI2NyIgcng9IjE0IiBmaWxsPSJ3aGl0ZSIvPgo8dGV4dCB4PSI0ODAiIHk9IjMxNSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIyNCIgZm9udC13ZWlnaHQ9ImJvbGQiPlRS77ydbWF4KDExMO+8jTEwOO+8jHwxMTDvvI0xMDB877yMfDEwOO+8jTEwMHwp77ydMTA8L3RleHQ+Cjx0ZXh0IHg9IjM2IiB5PSIzODkiIGZvbnQtc2l6ZT0iMTkiPuWFiOmAkOacn+iuoeeul1RS77yM5YaN55So5piO56Gu55qE5bmz5ruR5pa55rOV5b6X5YiwQVRS44CCPC90ZXh0Pgo8L2c+PC9zdmc+Cg==)

## K线高低差只有2，TR为什么是10？

设前一期收盘价为100，本期最低价为108、最高价为110：

| 候选值 | 计算 | 结果 |
| --- | --- | --- |
| 本期高低差 | 110－108 | 2 |
| 最高价与前收盘价的距离 | \|110－100\| | 10 |
| 最低价与前收盘价的距离 | \|108－100\| | 8 |

最大值为10，所以TR＝10，而不是2。

若本期最高价为92、最低价为90，前收盘价仍为100，三个候选值是2、8、10，TR仍为10。两个例子方向不同，TR相同，说明这个公式测量的是距离。

若前收盘价位于本期高低范围内，最大的候选值就是H－L，此时TR与普通高低差相同。

## 用连续数据算出ATR

下面是一组自拟、相互衔接的价格数据。教学参数取N＝3，不是参数推荐。第1期之前已有收盘价100。

| 期数 | 前收盘价 | 最高价H | 最低价L | 本期收盘价 | TR |
| --- | --- | --- | --- | --- | --- |
| 1 | 100 | 103 | 99 | 102 | 4 |
| 2 | 102 | 106 | 101 | 105 | 5 |
| 3 | 105 | 110 | 108 | 109 | 5 |
| 4 | 109 | 112 | 108 | 111 | 4 |

第3期收集到3个TR，以简单平均初始化ATR：

ATR₃＝(4＋5＋5)÷3＝14/3≈4.6667。

第4期递推：

ATR₄＝((14/3)×2＋4)÷3＝40/9≈4.4444。

此时若改用最近3个TR的简单平均，结果为(5＋5＋4)÷3≈4.6667，与Wilder结果不同。“平均真实波幅”中的平均方式，需要明确。

## ATR参数14、单位与百分比

常见周期为14。按本文Wilder口径，新TR占1/14，上期ATR占13/14。14期不等于固定14天，要结合计算所用的K线周期。

ATR与输入价格具有相同单位：价格以元计，ATR也以元计；指数以点计，ATR也以点计。ATR＝4不表示4%。

有些指标会进一步将ATR除以某个价格基准，转换为百分比。若约定基准为本期收盘价111，则本例第4期为(40/9)÷111×100%≈4.0040%。这是额外的归一化计算，比较软件时需核对分母与名称，不能把所有带“%”的显示视为同一定义。

## 不同软件的ATR为什么不一样？

ATR不是唯一固定的平均算法：Wilder、简单平均和常见EMA会产生不同结果。对比软件时需同时核对前收盘价、平滑方式、周期及初始化，不能只看参数是否同为14。

- 平滑方式：Wilder/RMA、简单平均、EMA等可能不同。EMA14的系数2/15不等于Wilder14的1/14。

- 种子与起算点：本文先取N个TR作平均，其他实现需核对。

- 第一根K线：缺少前收盘价时，有的软件取H－L，有的暂不输出；这会影响后续初始化。

- 数据口径：高低价与前收盘价应来自一致的周期和复权口径，不能混用不连续的数据。

- 未结束K线：最高价、最低价仍可能变化，TR及ATR也可能更新。

ATR把TR平滑后的结果显示成曲线，但不会由公式产生价格方向或后续幅度的概率保证。

## 相关阅读与公式来源

- [DMI与ADX](https://www.structguide.com/indicators/dmi-adx)：查看TR怎样参与DI归一化。

- [RSI怎么算](https://www.structguide.com/indicators/rsi)：查看Wilder平滑在另一类输入中的使用。

- [MA和EMA的区别](https://www.structguide.com/indicators/ma-vs-ema)：比较平滑权重。

- [BOLL布林带怎么算](https://www.structguide.com/indicators/boll)：区分真实波幅与标准差。

- [返回常见指标速查手册](https://www.structguide.com/indicators/)。

TR与平滑口径参考[TradingView ATR说明](https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/)，数字算例与图解为本站自拟。本文不表示Struct Guide插件提供ATR功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
