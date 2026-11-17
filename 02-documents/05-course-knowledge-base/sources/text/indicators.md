来源：https://www.structguide.com/indicators/
抓取：2026-11-06T00:31:03+08:00

# 常见指标速查手册

透过现象看本质：从一条曲线，找到背后的数学公式。

按指标英文名称的字母序查阅。每个指标下列出中文名称、一句话概述、完整图解和相关问题，方便直接找到需要的计算说明。

快速索引： [ADX](https://www.structguide.com/indicators/#adx) · [ATR](https://www.structguide.com/indicators/#atr) · [BIAS](https://www.structguide.com/indicators/#bias) · [BOLL](https://www.structguide.com/indicators/#boll) · [CCI](https://www.structguide.com/indicators/#cci) · [DMI](https://www.structguide.com/indicators/#dmi) · [EMA](https://www.structguide.com/indicators/#ema) · [KDJ](https://www.structguide.com/indicators/#kdj) · [MA](https://www.structguide.com/indicators/#ma) · [MACD](https://www.structguide.com/indicators/#macd) · [OBV](https://www.structguide.com/indicators/#obv) · [PSY](https://www.structguide.com/indicators/#psy) · [ROC](https://www.structguide.com/indicators/#roc) · [RSI](https://www.structguide.com/indicators/#rsi) · [VOL](https://www.structguide.com/indicators/#vol) · [VWAP](https://www.structguide.com/indicators/#vwap) · [WR](https://www.structguide.com/indicators/#wr)

## [ADX｜平均方向指数](https://www.structguide.com/indicators/dmi-adx#adx)

将两条DI之差的绝对值相对其和的比例记为DX，再对DX序列平滑。

[阅读计算图解](https://www.structguide.com/indicators/dmi-adx#adx)

- [DX怎样计算并平滑成ADX？](https://www.structguide.com/indicators/dmi-adx#adx)

- [怎样从连续数据算出首个ADX？](https://www.structguide.com/indicators/dmi-adx#example)

- [DMI、DI、DX和ADX分别是什么？](https://www.structguide.com/indicators/dmi-adx#overview)

- [参数、初始化和ADXR怎样区分？](https://www.structguide.com/indicators/dmi-adx#differences)

## [ATR｜平均真实波幅](https://www.structguide.com/indicators/atr)

将本期高低价与前收盘价之间的距离纳入真实波幅TR，再对TR序列进行平滑。

[阅读全文：ATR平均真实波幅是什么？TR计算公式与平滑图解](https://www.structguide.com/indicators/atr)

- [TR与ATR的计算公式是什么？](https://www.structguide.com/indicators/atr#formula)

- [高低差只有2，真实波幅为什么是10？](https://www.structguide.com/indicators/atr#true-range)

- [怎样用连续数据算出ATR？](https://www.structguide.com/indicators/atr#example)

- [参数14是什么意思，ATR是数值还是百分比？](https://www.structguide.com/indicators/atr#parameters)

- [不同软件的ATR为什么不一样？](https://www.structguide.com/indicators/atr#differences)

## [BIAS｜乖离率](https://www.structguide.com/indicators/bias)

把价格与均线的差除以均线，用百分比表示价格相对均值的偏离程度。

[阅读全文：BIAS乖离率是什么？计算公式、周期与数字图解](https://www.structguide.com/indicators/bias)

- [BIAS的计算公式是什么？](https://www.structguide.com/indicators/bias#formula)

- [同样相差2元，BIAS为什么不同？](https://www.structguide.com/indicators/bias#example)

- [正值、负值与零分别表示什么？](https://www.structguide.com/indicators/bias#meaning)

- [不同周期的BIAS曲线怎样计算？](https://www.structguide.com/indicators/bias#parameters)

- [BIAS与BOLL的计算有什么区别？](https://www.structguide.com/indicators/bias#bias-boll)

- [均线为0或软件数值不同时，怎样核对？](https://www.structguide.com/indicators/bias#differences)

## [BOLL｜布林带](https://www.structguide.com/indicators/boll)

本文采用移动平均作为中轨，上下加减K倍标准差，描述窗口的平均水平与离散程度。

[阅读全文：BOLL布林带是什么？三条线计算公式、参数与图解](https://www.structguide.com/indicators/boll)

- [BOLL三条线怎么看，名称与公式怎样对应？](https://www.structguide.com/indicators/boll#read-chart)

- [中轨、上轨和下轨的公式是什么？](https://www.structguide.com/indicators/boll#formula)

- [标准差怎样一步步计算？](https://www.structguide.com/indicators/boll#standard-deviation)

- [均值相同，布林带为什么仍可能变宽或变窄？](https://www.structguide.com/indicators/boll#width)

- [布林带宽度与相对带宽怎么算？](https://www.structguide.com/indicators/boll#bandwidth)

- [参数20和2分别是什么意思？](https://www.structguide.com/indicators/boll#parameters)

- [两个软件的BOLL数值为什么不同？](https://www.structguide.com/indicators/boll#differences)

- [两倍标准差等于95%的概率保证吗？](https://www.structguide.com/indicators/boll#probability)

## [CCI｜顺势指标（商品通道指数）](https://www.structguide.com/indicators/cci)

将典型价格与窗口均值的差，除以0.015倍平均绝对偏差，得到缩放后的偏离数值。

[阅读全文：CCI顺势指标是什么？计算公式、平均偏差与0.015](https://www.structguide.com/indicators/cci)

- [CCI的公式和输入是什么？](https://www.structguide.com/indicators/cci#formula)

- [怎样用5个数字手算CCI？](https://www.structguide.com/indicators/cci#example)

- [0.015与正负100是什么意思？](https://www.structguide.com/indicators/cci#scale)

- [周期和输入价格怎样影响结果？](https://www.structguide.com/indicators/cci#parameters)

- [CCI、BIAS与BOLL的计算有何区别？](https://www.structguide.com/indicators/cci#comparison)

- [平均绝对偏差为0时怎么办？](https://www.structguide.com/indicators/cci#differences)

## [DMI｜动向指标](https://www.structguide.com/indicators/dmi-adx#overview)

筛选相邻高低价变化，与真实波幅分别平滑后求比，形成两条DI并继续计算ADX。

[阅读计算图解](https://www.structguide.com/indicators/dmi-adx#overview)

- [高低价变化怎样筛选成DM？](https://www.structguide.com/indicators/dmi-adx#dm)

- [两种变化相等时怎样处理？](https://www.structguide.com/indicators/dmi-adx#dm)

- [TR与DM怎样计算出DI？](https://www.structguide.com/indicators/dmi-adx#di)

- [怎样一步步手算DMI和ADX？](https://www.structguide.com/indicators/dmi-adx#example)

- [软件数值不同先核对什么？](https://www.structguide.com/indicators/dmi-adx#differences)

## [EMA｜指数移动平均](https://www.structguide.com/indicators/ma-vs-ema)

将新价格与上期平均值加权递推，让较早数据的影响按指数方式逐步衰减。

[阅读全文：MA和EMA有什么区别？计算公式、权重与初始化图解](https://www.structguide.com/indicators/ma-vs-ema)

- [EMA计算公式是什么？](https://www.structguide.com/indicators/ma-vs-ema#ema-formula)

- [EMA与MA的计算有什么区别？](https://www.structguide.com/indicators/ma-vs-ema#comparison)

- [输入相同，两条均线为什么会分开？](https://www.structguide.com/indicators/ma-vs-ema#example)

- [EMA对新数据更敏感，具体指什么？](https://www.structguide.com/indicators/ma-vs-ema#sensitivity)

- [EMA5只计算最近5根K线吗？](https://www.structguide.com/indicators/ma-vs-ema#weights)

- [初始值为什么会影响EMA？](https://www.structguide.com/indicators/ma-vs-ema#initialization)

- [MA、EMA、BOLL分别是什么意思？](https://www.structguide.com/indicators/ma-vs-ema#ma-ema-boll)

## [KDJ｜随机指标](https://www.structguide.com/indicators/kdj)

先计算收盘价在窗口高低范围中的相对位置，再经过两次平滑和线性组合得到K、D、J。

[阅读全文：KDJ是什么指标？RSV、K、D、J计算公式与参数图解](https://www.structguide.com/indicators/kdj)

- [RSV、K、D、J的公式分别是什么？](https://www.structguide.com/indicators/kdj#formula)

- [怎样用一组数字算出三条线的数值？](https://www.structguide.com/indicators/kdj#example)

- [参数9、3、3分别是什么意思？](https://www.structguide.com/indicators/kdj#parameters)

- [J为什么会大于100或小于0？](https://www.structguide.com/indicators/kdj#j-range)

- [初始值与零分母怎样处理？](https://www.structguide.com/indicators/kdj#differences)

## [MA｜移动平均线（本文采用简单平均）](https://www.structguide.com/indicators/ma)

将最近N个价格等权平均，每增加一个周期，窗口移出旧数据并加入新数据。

[阅读全文：MA均线是什么？计算公式、周期设置与数字图解](https://www.structguide.com/indicators/ma)

- [均线是什么意思，图上是哪条线，颜色代表什么？](https://www.structguide.com/indicators/ma#read-chart)

- [均线怎么设置，哪些选项会改变计算？](https://www.structguide.com/indicators/ma#settings)

- [5日均线怎样手算？](https://www.structguide.com/indicators/ma#five-numbers)

- [“移动”平均是什么意思？](https://www.structguide.com/indicators/ma#rolling-window)

- [价格下降时，均线为什么仍可能上升？](https://www.structguide.com/indicators/ma#change)

- [MA5一定代表5天吗？](https://www.structguide.com/indicators/ma#period)

- [周期越长，为什么通常越平滑？](https://www.structguide.com/indicators/ma#weight)

- [均线是不是平均持仓成本？](https://www.structguide.com/indicators/ma#cost)

- [盘中数值为什么会变化？](https://www.structguide.com/indicators/ma#live)

- [同样是MA5，两个软件为什么不同？](https://www.structguide.com/indicators/ma#differences)

- [MA与EMA有什么区别？](https://www.structguide.com/indicators/ma-vs-ema#comparison)

## [MACD｜指数平滑异同移动平均线](https://www.structguide.com/indicators/macd)

两条不同周期的EMA先求差得到DIF，再平滑得到DEA，最后用两者之差绘制柱值。

[阅读全文：MACD是什么指标？DIF、DEA与柱状图计算公式](https://www.structguide.com/indicators/macd)

- [DIF、DEA和柱值分别怎么算？](https://www.structguide.com/indicators/macd#formula)

- [参数12、26、9是什么意思？](https://www.structguide.com/indicators/macd#parameters)

- [怎样用4个数字手算一次？](https://www.structguide.com/indicators/macd#example)

- [零轴、曲线和柱子分别表示什么？](https://www.structguide.com/indicators/macd#read-chart)

- [不同软件的MACD数字为什么不一样？](https://www.structguide.com/indicators/macd#differences)

## [OBV｜能量潮指标](https://www.structguide.com/indicators/obv)

根据相邻收盘价的大小关系，将本期成交量加到或减去累计值，平价时保持不变。

[阅读全文：OBV能量潮是什么？计算公式、成交量累计与图解](https://www.structguide.com/indicators/obv)

- [OBV的加减公式是什么？](https://www.structguide.com/indicators/obv#formula)

- [收盘价不变，有成交量也不累计吗？](https://www.structguide.com/indicators/obv#example)

- [OBV为什么可以是负数？](https://www.structguide.com/indicators/obv#negative)

- [OBV是资金流入流出金额吗？](https://www.structguide.com/indicators/obv#quantity)

- [基础OBV有没有周期参数？](https://www.structguide.com/indicators/obv#parameters)

- [软件的OBV数值为什么不一样？](https://www.structguide.com/indicators/obv#differences)

## [PSY｜心理线](https://www.structguide.com/indicators/psy)

统计最近N次收盘价比较中严格上涨的次数占比，反映的是计数而不是心理测量。

[阅读计算图解](https://www.structguide.com/indicators/psy)

- [PSY的计数公式是什么？](https://www.structguide.com/indicators/psy#formula)

- [怎样用六个价格计算PSY5？](https://www.structguide.com/indicators/psy#example)

- [为什么上涨次数不等于上涨幅度？](https://www.structguide.com/indicators/psy#count-magnitude)

- [PSY60表示未来上涨概率60%吗？](https://www.structguide.com/indicators/psy#meaning)

- [N与PSYMA参数分别是什么？](https://www.structguide.com/indicators/psy#parameters)

- [平价、缺失值与软件差异怎样处理？](https://www.structguide.com/indicators/psy#differences)

## [ROC｜变动率指标](https://www.structguide.com/indicators/roc)

以N期前价格为基准，计算本期价格相对这一端点的变化比例。

[阅读计算图解](https://www.structguide.com/indicators/roc)

- [ROC公式是什么？](https://www.structguide.com/indicators/roc#formula)

- [计算ROC3需要几个价格？](https://www.structguide.com/indicators/roc#example)

- [ROC等于逐期涨跌幅相加吗？](https://www.structguide.com/indicators/roc#compound)

- [ROC、价差和BIAS有什么区别？](https://www.structguide.com/indicators/roc#comparison)

- [周期、零轴与数值范围怎样理解？](https://www.structguide.com/indicators/roc#parameters)

- [基准为0或软件数值不同时怎么办？](https://www.structguide.com/indicators/roc#differences)

## [RSI｜相对强弱指标](https://www.structguide.com/indicators/rsi)

将相邻收盘价的变化拆成上涨量和下跌量，分别平滑后计算两者的相对比例。

[阅读全文：RSI相对强弱指标是什么？计算公式、参数与平滑图解](https://www.structguide.com/indicators/rsi)

- [RSI计算公式是什么？](https://www.structguide.com/indicators/rsi#formula)

- [怎样用5个收盘价手算RSI？](https://www.structguide.com/indicators/rsi#example)

- [RSI为70表示什么，是70%的上涨概率吗？](https://www.structguide.com/indicators/rsi#meaning)

- [RSI的平滑与EMA有什么区别？](https://www.structguide.com/indicators/rsi#smoothing)

- [分母为0或软件数值不同时，怎样核对？](https://www.structguide.com/indicators/rsi#differences)

## [VOL｜成交量与均量线](https://www.structguide.com/indicators/vol)

显示每根K线周期的成交数量，并对最近N个周期的数量求简单平均形成均量线。

[阅读全文：VOL成交量是什么？MAVOL均量线公式与红绿柱图解](https://www.structguide.com/indicators/vol)

- [VOL与MAVOL的计算公式是什么？](https://www.structguide.com/indicators/vol#formula)

- [5期均量线怎样手算和更新？](https://www.structguide.com/indicators/vol#example)

- [成交量与成交额有什么区别？](https://www.structguide.com/indicators/vol#volume-amount)

- [红绿成交量柱代表什么？](https://www.structguide.com/indicators/vol#colors)

- [周期5、10与未结束K线怎样影响数值？](https://www.structguide.com/indicators/vol#parameters)

- [数量单位和软件口径怎样核对？](https://www.structguide.com/indicators/vol#differences)

## [VWAP｜成交量加权平均价](https://www.structguide.com/indicators/vwap)

累计价格与成交量的乘积，再除以累计量，并按明确的起点或重置规则更新。

[阅读全文：VWAP是什么？成交量加权均价公式、重置与MA区别](https://www.structguide.com/indicators/vwap)

- [VWAP计算公式是什么？](https://www.structguide.com/indicators/vwap#formula)

- [怎样用三组数字手算加权均价？](https://www.structguide.com/indicators/vwap#example)

- [K线VWAP为什么不一定等于逐笔均价？](https://www.structguide.com/indicators/vwap#source)

- [VWAP为什么重置，锚定VWAP是什么？](https://www.structguide.com/indicators/vwap#anchor)

- [VWAP、MA、VWMA有什么区别？](https://www.structguide.com/indicators/vwap#comparison)

- [零量与数据来源不同怎样处理？](https://www.structguide.com/indicators/vwap#differences)

## [WR｜威廉指标](https://www.structguide.com/indicators/wr)

将收盘价到窗口最高价的距离除以高低价差，并按软件口径使用正值或负值刻度。

[阅读计算图解](https://www.structguide.com/indicators/wr)

- [正值WR与负值Williams %R的公式是什么？](https://www.structguide.com/indicators/wr#formula)

- [同一组价格为什么得到20和负20？](https://www.structguide.com/indicators/wr#example)

- [WR与KDJ中的RSV是什么关系？](https://www.structguide.com/indicators/wr#rsv)

- [周期参数改变了什么？](https://www.structguide.com/indicators/wr#parameters)

- [零分母与不同软件的数值怎样核对？](https://www.structguide.com/indicators/wr#differences)

## 关于本手册

每篇文章说明输入、公式、参数、更新过程和计算局限，并使用虚构数字与图解逐步复算。“怎么看”仅指图例、数值与公式的对应关系，不介绍操作用法。

本手册介绍通用指标的计算原理，不表示Struct Guide插件提供这些指标。插件的分型、笔、线段和中枢计算另见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
