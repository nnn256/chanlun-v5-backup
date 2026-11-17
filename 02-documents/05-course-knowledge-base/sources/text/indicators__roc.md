来源：https://www.structguide.com/indicators/roc
抓取：2026-11-06T00:31:06+08:00

# ROC变动率是什么？计算公式、周期与涨跌幅区别

ROC比较本期价格与N期前价格，用N期前价格作分母，计算相对变化。 ROC是Rate of Change的缩写，常称变动率指标。

它用到两个相隔N个周期的端点，不会先把窗口内所有价格求平均。本页只解释计算、单位和数据范围。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 本期收盘价Cₜ与N期前收盘价Cₜ₋ₙ |
| 计算 | ROC＝(Cₜ－Cₜ₋ₙ)/Cₜ₋ₙ×100% |
| 参数与约定 | N为两端间隔；计算需要N＋1个连续价格 |
| 单位与边界 | 百分比；历史基准不得为0 |

公式来源：[TradingView ROC说明](https://www.tradingview.com/support/solutions/43000502343-rate-of-change-roc/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## ROC计算公式

设本期收盘价为Cₜ，N期前为Cₜ₋ₙ：

ROCₙ＝(Cₜ－Cₜ₋ₙ)÷Cₜ₋ₙ×100%。

公式通常写成“×100”，软件显示20时按20%理解；若未乘100，显示的是0.2这一比值。输入价格、显示单位都应核对。

N＝1时，在同一数据口径下，ROC就是本期相对上期的收盘价涨跌幅。N＞1时，它比较的是更早的端点。

![ROC图解：虚构收盘价10、11、9、12，间隔3期，ROC3为20%；本期相对上期的ROC1约33.33%](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiB2aWV3Qm94PSIwIDAgOTYwIDQ2MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPjx0aXRsZSBpZD0idGl0bGUiPlJPQ++8muavlOi+g+S4pOS4querr+eCue+8jOS4jeaYr+WFiOaxguW5s+WdhzwvdGl0bGU+PGRlc2MgaWQ9ImRlc2MiPuWbm+S4quaUtuebmOS7tzEw44CBMTHjgIE544CBMTLvvJtST0Mz5Li6MjAl77yMUk9DMee6pjMzLjMzJeOAgjwvZGVzYz48cmVjdCB3aWR0aD0iOTYwIiBoZWlnaHQ9IjQ2MCIgcng9IjIwIiBmaWxsPSIjZjBmNmZmIi8+PGcgZm9udC1mYW1pbHk9Ik1pY3Jvc29mdCBZYUhlaSxzYW5zLXNlcmlmIj48dGV4dCB4PSIzNiIgeT0iNTAiIGZvbnQtc2l6ZT0iMjciIHRleHQtYW5jaG9yPSJzdGFydCIgZmlsbD0iIzE0MmM1MCIgZm9udC13ZWlnaHQ9ImJvbGQiPlJPQ++8muavlOi+g+S4pOS4querr+eCue+8jOS4jeaYr+WFiOaxguW5s+WdhzwvdGV4dD48dGV4dCB4PSIzNiIgeT0iODgiIGZvbnQtc2l6ZT0iMTgiIHRleHQtYW5jaG9yPSJzdGFydCIgZmlsbD0iIzE0MmM1MCI+6Jma5p6E5pS255uY5Lu3772cMTDjgIExMeOAgTnjgIExMjwvdGV4dD48cmVjdCB4PSIzNiIgeT0iMTE2IiB3aWR0aD0iODg4IiBoZWlnaHQ9IjEyMCIgcng9IjE0IiBmaWxsPSJ3aGl0ZSIgc3Ryb2tlPSIjYjhkMGY0Ii8+PHRleHQgeD0iMTIwIiB5PSIxNTYiIGZvbnQtc2l6ZT0iMTgiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiPuesrDHmnJ88L3RleHQ+PHRleHQgeD0iMTIwIiB5PSIyMDciIGZvbnQtc2l6ZT0iMzAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNzVkZGQiIGZvbnQtd2VpZ2h0PSJib2xkIj4xMDwvdGV4dD48dGV4dCB4PSIzNjAiIHk9IjE1NiIgZm9udC1zaXplPSIxOCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE0MmM1MCI+56ysMuacnzwvdGV4dD48dGV4dCB4PSIzNjAiIHk9IjIwNyIgZm9udC1zaXplPSIzMCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE3NWRkZCIgZm9udC13ZWlnaHQ9ImJvbGQiPjExPC90ZXh0Pjx0ZXh0IHg9IjYwMCIgeT0iMTU2IiBmb250LXNpemU9IjE4IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTQyYzUwIj7nrKwz5pyfPC90ZXh0Pjx0ZXh0IHg9IjYwMCIgeT0iMjA3IiBmb250LXNpemU9IjMwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTc1ZGRkIiBmb250LXdlaWdodD0iYm9sZCI+OTwvdGV4dD48dGV4dCB4PSI4NDAiIHk9IjE1NiIgZm9udC1zaXplPSIxOCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE0MmM1MCI+56ysNOacnzwvdGV4dD48dGV4dCB4PSI4NDAiIHk9IjIwNyIgZm9udC1zaXplPSIzMCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE3NWRkZCIgZm9udC13ZWlnaHQ9ImJvbGQiPjEyPC90ZXh0PjxwYXRoIGQ9Ik0xMjAgMjQ3IFYyNzAgSDg0MCBWMjQ3IiBmaWxsPSJub25lIiBzdHJva2U9IiMyNTYzZWIiIHN0cm9rZS13aWR0aD0iMiIvPjx0ZXh0IHg9IjQ4MCIgeT0iMjk5IiBmb250LXNpemU9IjIwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTQyYzUwIj7nrKwx5pyf5Yiw56ysNOacn++8mumXtOmalDPmnJ/vvIzpnIDopoE05Liq5Lu35qC8PC90ZXh0Pjx0ZXh0IHg9IjQ4MCIgeT0iMzQzIiBmb250LXNpemU9IjI1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTc1ZGRkIiBmb250LXdlaWdodD0iYm9sZCI+Uk9DM++8nSgxMu+8jTEwKcO3MTDDlzEwMCXvvJ0yMCU8L3RleHQ+PHRleHQgeD0iNDgwIiB5PSIzODEiIGZvbnQtc2l6ZT0iMjIiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiPlJPQzHvvJ0oMTLvvI05KcO3OcOXMTAwJeKJiDMzLjMzJTwvdGV4dD48dGV4dCB4PSIzNiIgeT0iNDI1IiBmb250LXNpemU9IjE3IiB0ZXh0LWFuY2hvcj0ic3RhcnQiIGZpbGw9IiMxNDJjNTAiPuWRqOacn+WPguaVsOWGs+WumuavlOi+g+WTquS4gOS4quWOhuWPsuerr+eCue+8m+S4jeaYr+aKiumAkOacn+a2qOi3jOW5heebtOaOpeebuOWKoOOAgjwvdGV4dD48L2c+PC9zdmc+)

## 用四个收盘价手算ROC3

给定虚构序列10、11、9、12：

| 期数 | 收盘价 |
| --- | --- |
| 1 | 10 |
| 2 | 11 |
| 3 | 9 |
| 4 | 12 |

第4期距离第1期恰好3个周期，ROC3＝(12－10)÷10×100%＝20%。

同一时刻ROC1＝(12－9)÷9×100%≈33.3333%。两个结果都可以正确，因为比较基准不同。

计算N期变化，需要本期和N期前的数据。 对连续序列而言，需要至少N＋1个价格才能找到两个端点；不能把“最近3个价格”误认为“间隔3期”。

## ROC等于逐期涨跌幅相加吗？

一般不等于。上例三个单期变化分别为10%、约－18.1818%、约33.3333%，直接相加约25.1515%，并不是20%。

在分母非零、价格比值有定义时，应将价格比相乘：

(11÷10)×(9÷11)×(12÷9)－1＝12÷10－1＝20%。

中间价格在乘积中约去，最终留下两个端点的比例。这是价格比的代数关系，不是把三个百分数直接相加。

## ROC、BIAS与价差有什么区别？

用同一序列的第4期举例，最近3个价格为11、9、12，MA3＝32/3：

| 统计量 | 基准 | 结果 |
| --- | --- | --- |
| 3期间隔价差 | 12－10 | 2个价格单位 |
| ROC3 | 相对3期前价格10 | 20% |
| BIAS3 | 相对最近3个价格的均值32/3 | 12.5% |

ROC与BIAS都用了除法，但分母分别是历史端点和窗口均值；即使参数都为3，也不是同一个公式。详见[BIAS乖离率](https://www.structguide.com/indicators/bias)。

## 周期、零轴和数值范围

N按图表计算周期计数。日K线的ROC5与小时K线的ROC5，比较的时间间隔不同。

在基准价格为正时，ROC为正表示本期价格高于该基准，为负表示低于该基准，等于0表示两个端点相等。它并不逐一说明中间每一期是升还是降。

如果价格始终非负、基准为正，最低可以到－100%，但向上不限定为100%。例如从10变为25，ROC＝150%，不是计算错误。

## 数据差异与特殊情况

ROC的N是两端间隔，不是总共取N个价格。核对N期前基准、输入与百分比显示后，再检查软件是否额外平滑；基准为0时公式未定义，负基准需另行解释。

基准价格为0时不能直接相除；若输入允许负价格，不能机械沿用正分母下的解释。缺失的第N期前数据也不能补成0后计算。

核对软件时，应确认是否输出百分比、是否使用收盘价、是否额外平滑，以及复权与数据周期是否一致。未结束K线的收盘价尚未固定，本期ROC也可能更新。

## 相关阅读与公式来源

- [BIAS怎么算](https://www.structguide.com/indicators/bias)：与均线作比较。

- [PSY心理线怎么算](https://www.structguide.com/indicators/psy)：统计上涨次数，而非端点变化幅度。

- [返回指标速查手册](https://www.structguide.com/indicators/)。

公式参考[TradingView ROC说明](https://www.tradingview.com/support/solutions/43000502343-rate-of-change-roc/)。算例、图解与代数展开为本站自拟。本文不表示Struct Guide插件提供ROC功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
