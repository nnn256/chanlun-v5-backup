来源：https://www.structguide.com/indicators/cci
抓取：2026-11-06T00:31:04+08:00

# CCI顺势指标是什么？计算公式、平均偏差与0.015

CCI先求价格与窗口均值的差，再除以“0.015×平均绝对偏差”。 CCI是Commodity Channel Index的缩写，中文常称顺势指标或商品通道指数。

它与BIAS一样涉及“偏离均值”，但分母不同；它与BOLL一样涉及离散程度，但使用的统计量也不同。本页只解释这些计算差异。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 典型价格TP＝(H＋L＋C)/3 |
| 计算 | CCI＝(本期TP－窗口均值)/(0.015×MD) |
| 参数与约定 | MD为窗口内各TP相对同一个窗口均值的平均绝对偏差 |
| 单位与边界 | 无价格单位，不限于正负100；MD不得为0 |

公式来源：[TradingView CCI说明](https://www.tradingview.com/support/solutions/43000502001-commodity-channel-index-cci/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## CCI计算公式

本文采用典型价格TP＝(最高价H＋最低价L＋收盘价C)÷3。窗口包含本期，共N个有效TP。

| 步骤 | 公式 | 含义 |
| --- | --- | --- |
| 典型价格TP | (H＋L＋C)÷3 | 每根K线选取一个代表价格 |
| 窗口均值M | 最近N个TP之和÷N | 同一窗口的平均值 |
| 平均绝对偏差MD | 最近N个\|TPᵢ－M\|之和÷N | 到这个均值的平均绝对距离 |
| CCI | (本期TP－M)÷(0.015×MD) | 经离散程度和常数缩放后的偏离 |

计算MD时，每个TP都减去同一个本期窗口均值M，不是各自所在时刻的滚动均值。MD也不是先求平方、再开根号的标准差。

![CCI计算图解：典型价格10、12、11、13、14，均值12，绝对偏差为2、0、1、1、2，MD为1.2，CCI约111.11](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiB2aWV3Qm94PSIwIDAgOTYwIDQ2MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPjx0aXRsZSBpZD0idGl0bGUiPkNDSe+8mueUqOW5s+Wdh+e7neWvueWBj+W3ruihoemHj+WBj+emuzwvdGl0bGU+PGRlc2MgaWQ9ImRlc2MiPuWFuOWei+S7t+agvDEw44CBMTLjgIExMeOAgTEz44CBMTTvvIzlnYflgLwxMu+8jOW5s+Wdh+e7neWvueWBj+W3rjEuMu+8jOacrOacn0NDSee6pjExMS4xMeOAgjwvZGVzYz48cmVjdCB3aWR0aD0iOTYwIiBoZWlnaHQ9IjQ2MCIgcng9IjIwIiBmaWxsPSIjZjBmNmZmIi8+PGcgZm9udC1mYW1pbHk9Ik1pY3Jvc29mdCBZYUhlaSxzYW5zLXNlcmlmIj48dGV4dCB4PSIzNiIgeT0iNTAiIGZvbnQtc2l6ZT0iMjciIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJzdGFydCIgZm9udC13ZWlnaHQ9ImJvbGQiPkNDSe+8mueUqOW5s+Wdh+e7neWvueWBj+W3ruihoemHj+WBj+emuzwvdGV4dD48dGV4dCB4PSIzNiIgeT0iODYiIGZvbnQtc2l6ZT0iMTgiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJzdGFydCI+6Jma5p6EVFDluo/liJfvvZxO77ydNe+9nOaYvuekuue7k+aenOWbm+iIjeS6lOWFpTwvdGV4dD48cmVjdCB4PSIzNiIgeT0iMTE1IiB3aWR0aD0iODg4IiBoZWlnaHQ9IjE2NSIgcng9IjE0IiBmaWxsPSJ3aGl0ZSIgc3Ryb2tlPSIjYjhkMGY0Ii8+PHRleHQgeD0iNjQiIHk9IjE1NiIgZm9udC1zaXplPSIyMCIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9InN0YXJ0IiBmb250LXdlaWdodD0iYm9sZCI+5YW45Z6L5Lu35qC8VFA8L3RleHQ+PHRleHQgeD0iMzYwIiB5PSIxNTYiIGZvbnQtc2l6ZT0iMjMiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPjEwPC90ZXh0Pjx0ZXh0IHg9IjQ3MCIgeT0iMTU2IiBmb250LXNpemU9IjIzIiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj4xMjwvdGV4dD48dGV4dCB4PSI1ODAiIHk9IjE1NiIgZm9udC1zaXplPSIyMyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+MTE8L3RleHQ+PHRleHQgeD0iNjkwIiB5PSIxNTYiIGZvbnQtc2l6ZT0iMjMiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiPjEzPC90ZXh0Pjx0ZXh0IHg9IjgwMCIgeT0iMTU2IiBmb250LXNpemU9IjIzIiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj4xNDwvdGV4dD48dGV4dCB4PSI2NCIgeT0iMjAwIiBmb250LXNpemU9IjIwIiBmaWxsPSIjMTQyYzUwIiB0ZXh0LWFuY2hvcj0ic3RhcnQiIGZvbnQtd2VpZ2h0PSJib2xkIj7lkIzkuIDnqpflj6PlnYflgLw8L3RleHQ+PHRleHQgeD0iMzEzIiB5PSIyMDAiIGZvbnQtc2l6ZT0iMjMiIGZpbGw9IiMxNzVkZGQiIHRleHQtYW5jaG9yPSJzdGFydCI+Te+8nTEyPC90ZXh0Pjx0ZXh0IHg9IjY0IiB5PSIyNDYiIGZvbnQtc2l6ZT0iMjAiIGZpbGw9IiMxNDJjNTAiIHRleHQtYW5jaG9yPSJzdGFydCIgZm9udC13ZWlnaHQ9ImJvbGQiPuWIsOWdh+WAvOeahOe7neWvuei3neemuzwvdGV4dD48dGV4dCB4PSIzNjAiIHk9IjI0NiIgZm9udC1zaXplPSIyMyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+MjwvdGV4dD48dGV4dCB4PSI0NzAiIHk9IjI0NiIgZm9udC1zaXplPSIyMyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+MDwvdGV4dD48dGV4dCB4PSI1ODAiIHk9IjI0NiIgZm9udC1zaXplPSIyMyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+MTwvdGV4dD48dGV4dCB4PSI2OTAiIHk9IjI0NiIgZm9udC1zaXplPSIyMyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+MTwvdGV4dD48dGV4dCB4PSI4MDAiIHk9IjI0NiIgZm9udC1zaXplPSIyMyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+MjwvdGV4dD48dGV4dCB4PSI0ODAiIHk9IjMyNCIgZm9udC1zaXplPSIyMyIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9Im1pZGRsZSI+TUTvvJ0oMu+8izDvvIsx77yLMe+8izIpw7c177ydMS4yPC90ZXh0Pjx0ZXh0IHg9IjQ4MCIgeT0iMzcxIiBmb250LXNpemU9IjI1IiBmaWxsPSIjMTc1ZGRkIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXdlaWdodD0iYm9sZCI+Q0NJ77ydKDE077yNMTIpw7coMC4wMTXDlzEuMiniiYgxMTEuMTE8L3RleHQ+PHRleHQgeD0iMzYiIHk9IjQyNSIgZm9udC1zaXplPSIxOCIgZmlsbD0iIzE0MmM1MCIgdGV4dC1hbmNob3I9InN0YXJ0Ij7mr4/kuKpUUOWHj+WOu+WQjOS4gOS4queql+WPo+Wdh+WAvO+8m+W5s+Wdh+e7neWvueWBj+W3ruS4jeaYr+agh+WHhuW3ruOAgjwvdGV4dD48L2c+PC9zdmc+)

## 用5个数字手算CCI

假设5根K线已经分别算出TP＝10、12、11、13、14。它们是虚构的典型价格序列；例如本期H＝15、L＝13、C＝14，就得到TP＝14。取N＝5仅为便于手算。

M＝(10＋12＋11＋13＋14)÷5＝12。

| TP | TP－M | 绝对偏差 |
| --- | --- | --- |
| 10 | －2 | 2 |
| 12 | 0 | 0 |
| 11 | －1 | 1 |
| 13 | ＋1 | 1 |
| 14 | ＋2 | 2 |

MD＝(2＋0＋1＋1＋2)÷5＝1.2。

CCI＝(14－12)÷(0.015×1.2)＝2÷0.018≈111.1111。

如果误用标准差√2代替MD，得到的将是另一种计算，并非本文CCI口径。平均绝对偏差为1.2与标准差约1.4142不能互换。

## 0.015与正负100是什么意思？

0.015是这套公式采用的缩放常数，不是概率，也不是价格变化率。它让同一个“偏离÷MD”得到特定刻度下的数值。

当MD＞0时，CCI＝100等价于本期TP－M＝1.5×MD；CCI＝－100等价于本期TP－M＝－1.5×MD。

正负100不是数值边界。 上例已经得到111.1111，超出100并不表示运算错误。CCI也不是固定限制在0到100之间的百分比。

## 参数与输入价格怎样影响结果？

N决定窗口内取多少个数据，同时影响均值M与偏差MD。修改N后，两者都要重算，不能只把原分母换成另一个数字。

一些软件允许把输入改成收盘价等其他序列。即使都写“CCI”，使用TP与只使用收盘价，也可能得到不同结果。本文明确采用TP，不假定所有平台默认如此。

图表周期、数据来源和复权口径也要对齐。颜色与线宽只改变显示，不改变公式。

## CCI、BIAS和BOLL的计算区别

| 指标 | 本文相关口径 | 分母或离散统计量 |
| --- | --- | --- |
| CCI | 典型价格偏离窗口均值 | 0.015×平均绝对偏差 |
| BIAS | 收盘价偏离简单均线 | 均线本身 |
| BOLL | 均值上下加减K倍标准差 | 使用标准差构造带宽 |

三者即使周期相同，也不是同一公式的不同画法。比较时应先区分输入价格和归一化方式，不能只比线条外观。

## MD为0时怎么办？

CCI的MD是平均绝对偏差，不是标准差，也不是各期价格分别减各期滚动均线后的平均。核对TP输入、同一窗口均值、0.015系数和零分母处理后，才能比较不同软件。

窗口内所有TP相同，MD就为0，此时CCI公式出现0/0。显示空值、约定为0或其他处理，需要查看具体软件实现，不能直接做除法。

不足N根数据、缺失数据与显示精度也可能造成差异。未结束K线的高、低、收盘价更新时，TP、窗口均值、MD和CCI都可能变化。

## 相关阅读与公式来源

- [BIAS乖离率](https://www.structguide.com/indicators/bias)：以均值作分母的相对距离。

- [BOLL布林带](https://www.structguide.com/indicators/boll)：标准差的完整手算过程。

- [返回指标速查手册](https://www.structguide.com/indicators/)。

公式参考[TradingView CCI说明](https://www.tradingview.com/support/solutions/43000502001-commodity-channel-index-cci/)，输入价格按本文约定使用TP，算例与图解为本站自拟。本文不表示Struct Guide插件提供CCI功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
