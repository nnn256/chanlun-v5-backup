来源：https://www.structguide.com/indicators/vwap
抓取：2026-11-06T00:31:08+08:00

# VWAP是什么？成交量加权均价公式、重置与MA区别

VWAP先将价格乘以对应成交量，分别累计乘积和数量，再用两者相除。 VWAP是Volume Weighted Average Price的缩写，中文常称成交量加权平均价。

与简单平均不同，成交量较大的那条输入在结果中占更大权重。不过，要复算软件曲线，还必须知道价格来自哪里，以及从哪个时刻开始累计。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 各期价格P与成交量V，以及累计起点 |
| 计算 | VWAP＝Σ(P×V)/ΣV |
| 参数与约定 | 先约定价格来源与重置规则；累计量须大于0 |
| 单位与边界 | 与价格同单位；K线近似值不必等于逐笔成交均价 |

公式来源：[TradingView VWAP说明](https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/)、[TradingView VWMA说明](https://www.tradingview.com/support/solutions/43000592293-volume-weighted-moving-average-vwma/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## VWAP计算公式

记第i条输入的价格为Pᵢ、成交量为Vᵢ，从选定起点a累计到本期t：

VWAPₜ＝Σ(Pᵢ×Vᵢ)÷ΣVᵢ，i从a到t，要求累计量大于0。

这里Σ表示求和。若使用逐笔记录，P是每笔成交价格；若使用K线，P是每根K线选取的代表价格，两种输入粒度不能混为一谈。

![VWAP手算图解：价格10、12、11，数量100、300、100；乘积之和5700除以总量500，得到VWAP为11.4，而价格简单平均为11](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiB2aWV3Qm94PSIwIDAgOTYwIDQ2MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPjx0aXRsZSBpZD0idGl0bGUiPlZXQVDvvJrlkIzmoLfnmoTkuInkuKrku7fmoLzvvIzmlbDph4/lhrPlrprmnYPph408L3RpdGxlPjxkZXNjIGlkPSJkZXNjIj7ku7fmoLwxMOOAgTEy44CBMTHlr7nlupTmlbDph48xMDDjgIEzMDDjgIExMDDvvIxWV0FQMTEuNO+8jOeugOWNleW5s+WdhzEx44CCPC9kZXNjPjxyZWN0IHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiByeD0iMjAiIGZpbGw9IiNmMGY2ZmYiLz48ZyBmb250LWZhbWlseT0iTWljcm9zb2Z0IFlhSGVpLHNhbnMtc2VyaWYiPjx0ZXh0IHg9IjM2IiB5PSI1MCIgZm9udC1zaXplPSIyNyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9InN0YXJ0IiBmb250LXdlaWdodD0iYm9sZCI+VldBUO+8muWQjOagt+eahOS4ieS4quS7t+agvO+8jOaVsOmHj+WGs+Wumuadg+mHjTwvdGV4dD48dGV4dCB4PSIzNiIgeT0iODYiIGZvbnQtc2l6ZT0iMTgiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJzdGFydCI+6Jma5p6E6K6w5b2V772c5ZCM5LiA57uf6K6h5Yy66Ze0772c5Lu35qC85LiO5pWw6YeP5YiG5Yir5L2/55So5LiA6Ie05Y2V5L2NPC90ZXh0PjxyZWN0IHg9IjM2IiB5PSIxMTkiIHdpZHRoPSIyODgiIGhlaWdodD0iMTY2IiByeD0iMTQiIGZpbGw9IndoaXRlIiBzdHJva2U9IiNiOGQwZjQiLz48dGV4dCB4PSIxODAiIHk9IjE1NyIgZm9udC1zaXplPSIyMiIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC13ZWlnaHQ9ImJvbGQiPuS7t+agvDEwIMOXIOaVsOmHjzEwMDwvdGV4dD48dGV4dCB4PSIxODAiIHk9IjE5OSIgZm9udC1zaXplPSIyMiIgZmlsbD0iIzE3NWRkZCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+5LmY56ev77ydMTAwMDwvdGV4dD48dGV4dCB4PSIxODAiIHk9IjI0NSIgZm9udC1zaXplPSIxOSIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+5p2D6YeNIDIwJTwvdGV4dD48cmVjdCB4PSIzMzYiIHk9IjExOSIgd2lkdGg9IjI4OCIgaGVpZ2h0PSIxNjYiIHJ4PSIxNCIgZmlsbD0id2hpdGUiIHN0cm9rZT0iI2I4ZDBmNCIvPjx0ZXh0IHg9IjQ4MCIgeT0iMTU3IiBmb250LXNpemU9IjIyIiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXdlaWdodD0iYm9sZCI+5Lu35qC8MTIgw5cg5pWw6YePMzAwPC90ZXh0Pjx0ZXh0IHg9IjQ4MCIgeT0iMTk5IiBmb250LXNpemU9IjIyIiBmaWxsPSIjMTc1ZGRkIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7kuZjnp6/vvJ0zNjAwPC90ZXh0Pjx0ZXh0IHg9IjQ4MCIgeT0iMjQ1IiBmb250LXNpemU9IjE5IiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7mnYPph40gNjAlPC90ZXh0PjxyZWN0IHg9IjYzNiIgeT0iMTE5IiB3aWR0aD0iMjg4IiBoZWlnaHQ9IjE2NiIgcng9IjE0IiBmaWxsPSJ3aGl0ZSIgc3Ryb2tlPSIjYjhkMGY0Ii8+PHRleHQgeD0iNzgwIiB5PSIxNTciIGZvbnQtc2l6ZT0iMjIiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtd2VpZ2h0PSJib2xkIj7ku7fmoLwxMSDDlyDmlbDph48xMDA8L3RleHQ+PHRleHQgeD0iNzgwIiB5PSIxOTkiIGZvbnQtc2l6ZT0iMjIiIGZpbGw9IiMxNzVkZGQiIHRleHQtYW5jaG9yPSJtaWRkbGUiPuS5mOenr++8nTExMDA8L3RleHQ+PHRleHQgeD0iNzgwIiB5PSIyNDUiIGZvbnQtc2l6ZT0iMTkiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPuadg+mHjSAyMCU8L3RleHQ+PHRleHQgeD0iNDgwIiB5PSIzMzgiIGZvbnQtc2l6ZT0iMjUiIGZpbGw9IiMxNzVkZGQiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtd2VpZ2h0PSJib2xkIj5WV0FQ77ydKDEwMDDvvIszNjAw77yLMTEwMCnDtzUwMO+8nTExLjQ8L3RleHQ+PHRleHQgeD0iNDgwIiB5PSIzNzciIGZvbnQtc2l6ZT0iMjEiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPueugOWNleW5s+Wdh++8nSgxMO+8izEy77yLMTEpw7cz77ydMTE8L3RleHQ+PHRleHQgeD0iMzYiIHk9IjQyNSIgZm9udC1zaXplPSIxOCIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9InN0YXJ0Ij5L57q/5Luj6KGo5Lu35qC85Yqg5p2D5LiN5LiA5a6a562J5LqO6YCQ56yU5Z2H5Lu377yb6L+Y6KaB5qC45a+56LW354K55LiO6YeN572u44CCPC90ZXh0PjwvZz48L3N2Zz4=)

## 用三组数字手算VWAP

以下虚构记录使用同一价格单位与数量单位，第三条记录结束后比较两种平均：

| 序号 | 价格P | 数量V | P×V | 累计P×V | 累计V | 累计VWAP |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 10 | 100 | 1000 | 1000 | 100 | 10.0000 |
| 2 | 12 | 300 | 3600 | 4600 | 400 | 11.5000 |
| 3 | 11 | 100 | 1100 | 5700 | 500 | 11.4000 |

价格的简单平均为(10＋12＋11)÷3＝11。

VWAP为5700÷500＝11.4，因为价格12对应的数量占总量的60%，另两个价格各占20%。这里改变结果的是权重，不是凭空增加了一种价格。

## K线VWAP为什么不一定等于逐笔均价？

图表常见口径使用典型价格TP＝(最高价H＋最低价L＋收盘价C)÷3，也可能允许选收盘价等其他输入。

将TP乘以整根K线的成交量，是用一个代表价格概括这一段数据。它通常不等于逐笔价格乘数量的真实总和。

例如，一根虚构K线内只有两笔记录：价格10成交100单位，价格12成交300单位。逐笔均价为4600÷400＝11.5；此时H＝12、L＝10、C＝12，TP＝34/3≈11.3333。只使用这一根K线的TP加权，结果就是11.3333，而不是11.5。

因此，不能一边使用K线TP近似，一边声称得到了精确的逐笔均价。不同图表周期会改变聚合方式，也可能使近似值不同。

## 为什么VWAP会重置？锚定VWAP是什么？

重置意味着清空累计价格乘量之和、累计数量，从新起点重新相加。起点或重置周期是公式的一部分，而不仅是外观设置。

例如上表结束后，新统计区间首条输入是价格13、数量200：重置后VWAP＝13；若继续累计，则为(5700＋2600)÷(500＋200)≈11.8571。

按会话、周、月等周期重置，与从用户指定位置开始累计，会包含不同的样本。后者通常称锚定VWAP。选定起点不同，数值不同，本页不推荐具体起点。

## VWAP、MA和VWMA有什么区别？

| 名称 | 权重 | 样本范围 |
| --- | --- | --- |
| MA（简单平均） | 每个输入等权 | 最近N个有效输入 |
| VWMA | 按成交量加权 | 最近N个有效输入，窗口滚动 |
| 本文VWAP | 按成交量加权 | 从指定起点累计，到约定时刻重置 |

如果价格来源和样本范围完全相同，VWMA与VWAP的加权商可以相同；持续更新时，是否移出旧样本会让结果分开。更多平均算法见[MA与EMA图解](https://www.structguide.com/indicators/ma-vs-ema)。

## 零成交量与数据差异

VWAP比较必须同时对齐价格来源、成交量和累计起点。用K线典型价格乘该根成交量只是明确口径下的计算，并不保证等于逐笔成交额除以成交量；不同重置时间也会改变结果。

累计成交量为0时不能做除法；若已有正的累计量，新增一条零量记录不会改变该加权结果。缺失成交量不等于0，应按数据源和软件实现处理。

比较数值时，要同时核对价格来源、数量单位、统计时段、重置规则与K线周期。用数量加权得到的历史均价，也不能等同于所有现有持有者的平均成本。

## 相关阅读与公式来源

- [VOL与均量线](https://www.structguide.com/indicators/vol)：认识作为权重的数量。

- [MA均线](https://www.structguide.com/indicators/ma)：比较等权平均。

- [返回指标速查手册](https://www.structguide.com/indicators/)。

K线计算与重置口径参考[TradingView VWAP说明](https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/)，滚动加权平均参考[TradingView VWMA说明](https://www.tradingview.com/support/solutions/43000592293-volume-weighted-moving-average-vwma/)。算例与图解为本站自拟。本文不表示Struct Guide插件提供VWAP功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
