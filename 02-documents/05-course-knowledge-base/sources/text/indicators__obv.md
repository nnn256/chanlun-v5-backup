来源：https://www.structguide.com/indicators/obv
抓取：2026-11-06T00:31:06+08:00

# OBV能量潮是什么？计算公式、成交量累计与图解

OBV根据本期与上期收盘价的大小关系，把本期成交量加到或减去累计值；收盘价相同时，累计值不变。 OBV是On Balance Volume的缩写，常称能量潮指标。

这个算法将价格关系转成符号，再累计数量。本文只解释这一步步运算，不将名称中的“能量”理解为真实测得的资金金额。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 相邻收盘价与本期成交量V |
| 计算 | 收盘上涨加V，下跌减V，相等时保持上期OBV |
| 参数与约定 | 本文从0开始；基础累计式不设滚动窗口N |
| 单位与边界 | 单位随成交量，可为负数；不是资金净流入金额 |

公式来源：[TradingView OBV计算说明](https://www.tradingview.com/support/solutions/43000502593-on-balance-volume-obv/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## OBV计算公式

设本期成交量为V、本期收盘价为C、上期收盘价为Cₚ：

| 条件 | 本期OBV |
| --- | --- |
| C＞Cₚ | 上期OBV＋V |
| C＜Cₚ | 上期OBV－V |
| C＝Cₚ | 上期OBV，不加不减 |

即：OBVₜ＝OBVₜ₋₁＋sₜ×Vₜ，其中s按收盘价变化取＋1、－1或0。

这里比较的是相邻两期收盘价，不是本期开盘价与收盘价。涨了0.1和涨了1，只要都属于C＞Cₚ，在成交量相同的情况下，本期增加的OBV相同。

![OBV图解：从0开始，按收盘价变化依次加100、减150、平价不变、再加80，累计值为0、100、负50、负50、30](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiB2aWV3Qm94PSIwIDAgOTYwIDQ2MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPjx0aXRsZSBpZD0idGl0bGUiPk9CVu+8muWFiOi1i+S6iOato+i0n+WPt++8jOWGjemAkOacn+e0r+iuoTwvdGl0bGU+PGRlc2MgaWQ9ImRlc2MiPui1t+eCuTDvvIzkvp3mrKHlop7liqAxMDDjgIHlh4/ljrsxNTDjgIHlubPku7fkuI3lj5jjgIHlop7liqA4MO+8jOe0r+iuoeWIsDMw44CCPC9kZXNjPjxyZWN0IHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiByeD0iMjAiIGZpbGw9IiNmMGY2ZmYiLz48ZyBmb250LWZhbWlseT0iTWljcm9zb2Z0IFlhSGVpLHNhbnMtc2VyaWYiPjx0ZXh0IHg9IjM2IiB5PSI1MCIgZm9udC1zaXplPSIyNyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9InN0YXJ0IiBmb250LXdlaWdodD0iYm9sZCI+T0JW77ya5YWI6LWL5LqI5q2j6LSf5Y+377yM5YaN6YCQ5pyf57Sv6K6hPC90ZXh0Pjx0ZXh0IHg9IjM2IiB5PSI4NiIgZm9udC1zaXplPSIxOCIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9InN0YXJ0Ij7omZrmnoTnrpfkvovvvZzliY3mlLbnm5jku7cxMO+9nOmaj+WQjuaUtuebmOS7tzEx44CBMTAuNeOAgTEwLjXjgIExMjwvdGV4dD48cmVjdCB4PSIzNiIgeT0iMTEyIiB3aWR0aD0iODg4IiBoZWlnaHQ9IjI3MCIgcng9IjE0IiBmaWxsPSJ3aGl0ZSIgc3Ryb2tlPSIjYjhkMGY0Ii8+PHBhdGggZD0iTTkwIDI1MyBIODcyIiBzdHJva2U9IiNhN2JiZDgiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWRhc2hhcnJheT0iNiA1Ii8+PHBvbHlsaW5lIHBvaW50cz0iMTAwLDI1My4wIDI5MCwxNzguMCA0ODAsMjkwLjUgNjcwLDI5MC41IDg2MCwyMzAuNSIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjMjU2M2ViIiBzdHJva2Utd2lkdGg9IjQiLz48Y2lyY2xlIGN4PSIxMDAiIGN5PSIyNTMuMCIgcj0iNyIgZmlsbD0iIzdjM2FlZCIvPjx0ZXh0IHg9IjEwMCIgeT0iMjM3LjAiIGZvbnQtc2l6ZT0iMjEiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtd2VpZ2h0PSJib2xkIj4wPC90ZXh0Pjx0ZXh0IHg9IjEwMCIgeT0iMzU0IiBmb250LXNpemU9IjE3IiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7otbfngrk8L3RleHQ+PGNpcmNsZSBjeD0iMjkwIiBjeT0iMTc4LjAiIHI9IjciIGZpbGw9IiM3YzNhZWQiLz48dGV4dCB4PSIyOTAiIHk9IjE2Mi4wIiBmb250LXNpemU9IjIxIiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXdlaWdodD0iYm9sZCI+MTAwPC90ZXh0Pjx0ZXh0IHg9IjI5MCIgeT0iMzU0IiBmb250LXNpemU9IjE3IiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7nrKwx5pyfPC90ZXh0PjxjaXJjbGUgY3g9IjQ4MCIgY3k9IjI5MC41IiByPSI3IiBmaWxsPSIjN2MzYWVkIi8+PHRleHQgeD0iNDgwIiB5PSIyNzQuNSIgZm9udC1zaXplPSIyMSIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC13ZWlnaHQ9ImJvbGQiPi01MDwvdGV4dD48dGV4dCB4PSI0ODAiIHk9IjM1NCIgZm9udC1zaXplPSIxNyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+56ysMuacnzwvdGV4dD48Y2lyY2xlIGN4PSI2NzAiIGN5PSIyOTAuNSIgcj0iNyIgZmlsbD0iIzdjM2FlZCIvPjx0ZXh0IHg9IjY3MCIgeT0iMjc0LjUiIGZvbnQtc2l6ZT0iMjEiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtd2VpZ2h0PSJib2xkIj4tNTA8L3RleHQ+PHRleHQgeD0iNjcwIiB5PSIzNTQiIGZvbnQtc2l6ZT0iMTciIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPuesrDPmnJ88L3RleHQ+PGNpcmNsZSBjeD0iODYwIiBjeT0iMjMwLjUiIHI9IjciIGZpbGw9IiM3YzNhZWQiLz48dGV4dCB4PSI4NjAiIHk9IjIxNC41IiBmb250LXNpemU9IjIxIiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXdlaWdodD0iYm9sZCI+MzA8L3RleHQ+PHRleHQgeD0iODYwIiB5PSIzNTQiIGZvbnQtc2l6ZT0iMTciIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPuesrDTmnJ88L3RleHQ+PHRleHQgeD0iMTk1IiB5PSIxNDMiIGZvbnQtc2l6ZT0iMTgiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPu+8izEwMDwvdGV4dD48dGV4dCB4PSIzODUiIHk9IjE0MyIgZm9udC1zaXplPSIxOCIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+77yNMTUwPC90ZXh0Pjx0ZXh0IHg9IjU3NSIgeT0iMTQzIiBmb250LXNpemU9IjE4IiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7lubPku7fvvJrvvIswPC90ZXh0Pjx0ZXh0IHg9Ijc2NSIgeT0iMTQzIiBmb250LXNpemU9IjE4IiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7vvIs4MDwvdGV4dD48dGV4dCB4PSIzNiIgeT0iNDI1IiBmb250LXNpemU9IjE4IiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ic3RhcnQiPuaAu+aIkOS6pOmHjzUzMO+8jE9CVue0r+iuoeWAvDMw77yb5Lik6ICF5LiN5piv5ZCM5LiA5Liq57uf6K6h6YeP44CCPC90ZXh0PjwvZz48L3N2Zz4=)

## 用四个周期手算OBV

给定起点OBV＝0、前收盘价10，随后输入以下虚构数据，数量单位保持一致：

| 期数 | 前收盘价 | 本期收盘价 | 本期量V | 本期增量 | 本期OBV |
| --- | --- | --- | --- | --- | --- |
| 1 | 10 | 11 | 100 | ＋100 | 100 |
| 2 | 11 | 10.5 | 150 | －150 | －50 |
| 3 | 10.5 | 10.5 | 200 | 0 | －50 |
| 4 | 10.5 | 12 | 80 | ＋80 | 30 |

第3期有成交量200，但由于收盘价没有变化，按本文公式它对OBV增量的贡献为0。这不表示本期没有成交。

四期总成交量为530，而OBV只累计到30。两者计算不同：一个是非负数量相加，另一个是先赋予符号，再相加。

## OBV为什么可以是负数？

负的是累计结果，不是原始成交数量。上例第2期从100减去150得到－50，算式完全成立。

若把起点从0改成1000，使用相同后续数据，整段OBV就变为1100、950、950、1030。每期增量没有变化，只是累计基准整体增加了1000。

因此，比较两套OBV的绝对数值前，必须先对齐起算点和初始值；不能仅凭正负号判断算法是否正确。

## OBV是资金流入流出金额吗？

按本文公式，OBV只读取收盘价之间的大小关系和成交数量，没有读取每笔成交金额，也没有识别参与者身份。

加100并不表示测得某类资金流入100元，减150也不表示测得其流出150元。它只是按既定条件给整期数量加正负号。

这也解释了它与[VWAP](https://www.structguide.com/indicators/vwap)的区别：VWAP将价格乘以成交量再求平均，OBV只把价格关系用于决定加减号。

## OBV有没有周期参数？

本文基础OBV是逐期累计式，没有“最近N期后移出旧数据”的窗口。图表本身仍有周期：日K线与小时K线的收盘价、成交量分组不同，计算结果可能不同。

某些界面还叠加OBV的均线并提供周期N，这是对OBV结果再次平均，不应与原始OBV混淆。看见参数时，要先确定它控制的是累计输入还是附加曲线。

## 不同软件的OBV为什么不一样？

OBV是累计值，起点和初始值会影响绝对数值。仅改变初始常数而输入完全相同，两组OBV相差固定常数；若差值随时间变化，还应核对数量单位、数据范围和平价处理。

核对顺序为：起算数据与种子、相同收盘价时的处理、成交量单位、周期与复权口径、是否显示原始累计值或其平滑结果。

没有上期收盘价的第一条记录、缺失的成交量都需要明确约定，不能擅自当作0。未结束K线的收盘价相对上期的位置与累计量也可能变化，使本期OBV更新。

## 相关阅读与公式来源

- [VOL成交量与均量线](https://www.structguide.com/indicators/vol)：区分原始数量与其平均值。

- [VWAP成交量加权均价](https://www.structguide.com/indicators/vwap)：比较另一种数量参与计算的方式。

- [返回指标速查手册](https://www.structguide.com/indicators/)。

公式参考[TradingView OBV计算说明](https://www.tradingview.com/support/solutions/43000502593-on-balance-volume-obv/)。起点、数字与图解为本站自拟。本文不表示Struct Guide插件提供OBV功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
