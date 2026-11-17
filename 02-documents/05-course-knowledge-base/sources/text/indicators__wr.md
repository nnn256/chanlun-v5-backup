来源：https://www.structguide.com/indicators/wr
抓取：2026-11-06T00:31:08+08:00

# WR威廉指标是什么？计算公式、正负刻度与参数

威廉指标计算收盘价距离窗口最高价有多远，再用整个窗口的高低价差归一化。 它可能显示为WR、WMSR、WPR或Williams %R；核对数值时，除了看名称，还要看公式的符号与纵轴刻度。

本文同时展示0—100和－100—0两种数值口径，只解释数学关系，不讨论操作用法。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 窗口最高H、最低L和本期收盘价C |
| 计算 | 正值WR＝100×(H－C)/(H－L)；负值%R为其相反数 |
| 参数与约定 | 窗口包含本期；须满足H＞L |
| 单位与边界 | 正值刻度0—100；负值刻度－100—0 |

公式来源：[富途WMSR说明](https://support.futunn.com/hant/topic256)、[IBKR Williams指标说明](https://www.interactivebrokers.com/campus/glossary-terms/williams-oscillator/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## WR计算公式与两种刻度

记最近N根K线的最高价为Hₙ、最低价为Lₙ，本期收盘价为C。窗口包含本期，且Hₙ＞Lₙ。

| 本文记号 | 公式 | 数值范围 |
| --- | --- | --- |
| WR正值口径 | (Hₙ－C)÷(Hₙ－Lₙ)×100 | 0到100 |
| Williams %R负值口径 | (Hₙ－C)÷(Hₙ－Lₙ)×(－100) | －100到0 |

两者在输入和窗口一致时互为相反数。例如正值口径20对应负值口径－20。具体界面是否翻转纵轴，是另外一个显示设置，不能仅凭线条朝向认定算法不同。

![WR刻度图解：窗口最低10、最高20、收盘18，距离最高点为2；正值WR为20，负值Williams %R为负20，RSV为80](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiB2aWV3Qm94PSIwIDAgOTYwIDQ2MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPjx0aXRsZSBpZD0idGl0bGUiPldS77ya5ZCM5LiA5Liq5Yy66Ze05L2N572u77yM5Lik56eN5pWw5YC85Yi75bqmPC90aXRsZT48ZGVzYyBpZD0iZGVzYyI+6auY5L2O6IyD5Zu0MTDoh7MyMO+8jOaUtuebmDE444CC5q2j5YC8V1IyMO+8jOi0n+WAvCVS6LSfMjDvvIxSU1Y4MOOAgjwvZGVzYz48cmVjdCB3aWR0aD0iOTYwIiBoZWlnaHQ9IjQ2MCIgcng9IjIwIiBmaWxsPSIjZjBmNmZmIi8+PGcgZm9udC1mYW1pbHk9Ik1pY3Jvc29mdCBZYUhlaSxzYW5zLXNlcmlmIj48dGV4dCB4PSIzNiIgeT0iNTAiIGZvbnQtc2l6ZT0iMjciIHRleHQtYW5jaG9yPSJzdGFydCIgZmlsbD0iIzE0MmM1MCIgZm9udC13ZWlnaHQ9ImJvbGQiPldS77ya5ZCM5LiA5Liq5Yy66Ze05L2N572u77yM5Lik56eN5pWw5YC85Yi75bqmPC90ZXh0Pjx0ZXh0IHg9IjM2IiB5PSI4OCIgZm9udC1zaXplPSIxOCIgdGV4dC1hbmNob3I9InN0YXJ0IiBmaWxsPSIjMTQyYzUwIj7omZrmnoTnrpfkvovvvZznqpflj6PmnIDpq5gyMOOAgeacgOS9jjEw44CB5pS255uYMTg8L3RleHQ+PHBhdGggZD0iTTEwMCAxNjMgSDg2MCIgc3Ryb2tlPSIjYjhkMGY0IiBzdHJva2Utd2lkdGg9IjEyIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz48cGF0aCBkPSJNNzA4IDE2MyBIODYwIiBzdHJva2U9IiM3YzNhZWQiIHN0cm9rZS13aWR0aD0iMTIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPjxjaXJjbGUgY3g9IjcwOCIgY3k9IjE2MyIgcj0iMTAiIGZpbGw9IiMyNTYzZWIiLz48dGV4dCB4PSIxMDAiIHk9IjEzNSIgZm9udC1zaXplPSIxOSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE0MmM1MCI+5pyA5L2OMTA8L3RleHQ+PHRleHQgeD0iNzA4IiB5PSIxMzUiIGZvbnQtc2l6ZT0iMTkiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiPuaUtuebmDE4PC90ZXh0Pjx0ZXh0IHg9Ijg2MCIgeT0iMTM1IiBmb250LXNpemU9IjE5IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTQyYzUwIj7mnIDpq5gyMDwvdGV4dD48dGV4dCB4PSI3ODQiIHk9IjIwNyIgZm9udC1zaXplPSIxOSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE0MmM1MCI+6Led56a777ydMjwvdGV4dD48cmVjdCB4PSIzNiIgeT0iMjQwIiB3aWR0aD0iMjg4IiBoZWlnaHQ9IjEyNSIgcng9IjE0IiBmaWxsPSJ3aGl0ZSIgc3Ryb2tlPSIjYjhkMGY0Ii8+PHRleHQgeD0iMTgwIiB5PSIyODEiIGZvbnQtc2l6ZT0iMjMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiIGZvbnQtd2VpZ2h0PSJib2xkIj7mraPlgLxXUjwvdGV4dD48dGV4dCB4PSIxODAiIHk9IjMyNyIgZm9udC1zaXplPSIxOCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE3NWRkZCI+MsO3MTDDlzEwMO+8nTIwPC90ZXh0PjxyZWN0IHg9IjMzNiIgeT0iMjQwIiB3aWR0aD0iMjg4IiBoZWlnaHQ9IjEyNSIgcng9IjE0IiBmaWxsPSJ3aGl0ZSIgc3Ryb2tlPSIjYjhkMGY0Ii8+PHRleHQgeD0iNDgwIiB5PSIyODEiIGZvbnQtc2l6ZT0iMjMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiIGZvbnQtd2VpZ2h0PSJib2xkIj7otJ/lgLwlUjwvdGV4dD48dGV4dCB4PSI0ODAiIHk9IjMyNyIgZm9udC1zaXplPSIxOCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE3NWRkZCI+MsO3MTDDlyjvvI0xMDAp77yd77yNMjA8L3RleHQ+PHJlY3QgeD0iNjM2IiB5PSIyNDAiIHdpZHRoPSIyODgiIGhlaWdodD0iMTI1IiByeD0iMTQiIGZpbGw9IndoaXRlIiBzdHJva2U9IiNiOGQwZjQiLz48dGV4dCB4PSI3ODAiIHk9IjI4MSIgZm9udC1zaXplPSIyMyIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE0MmM1MCIgZm9udC13ZWlnaHQ9ImJvbGQiPuWQjOeql+WPo1JTVjwvdGV4dD48dGV4dCB4PSI3ODAiIHk9IjMyNyIgZm9udC1zaXplPSIxOCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE3NWRkZCI+OMO3MTDDlzEwMO+8nTgwPC90ZXh0Pjx0ZXh0IHg9IjM2IiB5PSI0MjUiIGZvbnQtc2l6ZT0iMTciIHRleHQtYW5jaG9yPSJzdGFydCIgZmlsbD0iIzE0MmM1MCI+6L6T5YWl5LiO56qX5Y+j5LiA6Ie05pe277ya5q2j5YC8V1LvvJ0xMDDvvI1SU1bvvJvotJ/lgLwlUu+8nVJTVu+8jTEwMOOAgjwvdGV4dD48L2c+PC9zdmc+)

## 用三个价格数值手算

假设完整窗口内最高价20、最低价10，本期收盘价18，均为虚构数字：

- 距离窗口最高价：20－18＝2。

- 窗口高低价差：20－10＝10。

- 正值WR＝2÷10×100＝20。

- 负值%R＝2÷10×(－100)＝－20。

| 收盘价位置 | 正值WR | 负值%R |
| --- | --- | --- |
| 等于窗口最高价20 | 0 | 0 |
| 位于中间15 | 50 | －50 |
| 等于窗口最低价10 | 100 | －100 |

这些数值描述收盘价在已给定范围中的相对位置，不表示后一期价格变化的概率。

## WR与KDJ中的RSV是什么关系？

在相同窗口与输入下，RSV＝(C－Lₙ)÷(Hₙ－Lₙ)×100。因此：

正值WR＝100－RSV；负值%R＝RSV－100。

上例RSV＝80，正值WR＝20，负值%R＝－20。这是同一个区间位置的不同写法。

但KDJ中的K、D是在RSV之后又做了平滑，J还包含线性组合，不能直接用100－K替代本文WR。完整步骤见[KDJ计算图解](https://www.structguide.com/indicators/kdj)。

## 周期参数改变了什么？

N控制最高价、最低价的取值窗口。N越大，包含的K线越多，但WR数值并不因此保证更大或更小；变化取决于高低边界如何更新。

即使本期收盘价不变，旧的最高价或最低价移出窗口后，WR也可能变化。日K线和分钟K线使用相同N，输入范围也不同。

Hₙ、Lₙ来自窗口内每根K线的最高、最低价，不能擅自改为收盘价序列的最大、最小值。

## 为什么软件结果不同？

WR有0—100与－100—0两种刻度。只有输入和窗口相同、H＞L时，两种数值才互为相反数；高低范围为0时，公式未定义，需要核对软件约定。

先核对正负号，再核对窗口长度、是否包含本期、图表周期和数据口径。若平台对原始WR还做了平滑或其他变换，也要分开查看。

Hₙ＝Lₙ时分母为0，公式未定义；返回空值、沿用前值或给出约定值，要以软件实现为准。窗口不足N根或缺失数据时，也不能默认所有软件采用相同处理。

未结束K线的最高、最低与收盘价都可能更新，所以当前显示值可能随输入变化。

## 相关阅读与公式来源

- [KDJ怎么算](https://www.structguide.com/indicators/kdj)：RSV及后续平滑。

- [RSI怎么算](https://www.structguide.com/indicators/rsi)：另一种比例计算。

- [返回指标速查手册](https://www.structguide.com/indicators/)。

正值刻度参考[富途WMSR说明](https://support.futunn.com/hant/topic256)，负值范围参考[IBKR Williams指标说明](https://www.interactivebrokers.com/campus/glossary-terms/williams-oscillator/)。两种公式的代数关系、数字算例与图解为本站推导和自拟。本文不表示Struct Guide插件提供WR功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
