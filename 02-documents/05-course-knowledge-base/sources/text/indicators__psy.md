来源：https://www.structguide.com/indicators/psy
抓取：2026-11-06T00:31:06+08:00

# PSY心理线是什么？计算公式、参数与数字示例

PSY统计最近N个周期中，收盘价高于上期收盘价的次数，再除以N。 名称是心理线（Psychological Line），基础公式实际读取的是价格比较结果，并没有直接测量人的心理。

本页把公式拆成“逐期比较、记为0或1、窗口求和”三个步骤，只说明数量关系。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | N次相邻收盘价比较，需要N＋1个连续价格 |
| 计算 | PSY＝严格上涨次数÷N×100% |
| 参数与约定 | 平价不计上涨，但仍计入分母；PSYMA另做平均 |
| 单位与边界 | 取0—100%；反映历史次数占比，不是心理测量 |

公式来源：[富途PSY公式说明](https://www.futuhk.com/cn/hant/support/topic1_656)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## PSY计算公式

本文约定：本期收盘价严格大于上期时记1，否则记0。相等也记0，但该期仍留在分母N中。

PSYₙ＝最近N个比较结果之和÷N×100%。

也可以写成COUNT(C＞前一期C,N)÷N×100%。这里COUNT表示数出条件成立的次数，不是把上涨幅度相加。

在数据齐全的连续序列中，N次比较需要N＋1个收盘价；第一个比较也需要知道它之前的收盘价。

![PSY图解：六个虚构收盘价10、11、10、10、12、13，五次比较记为1、0、0、1、1，PSY5为60%](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiB2aWV3Qm94PSIwIDAgOTYwIDQ2MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPjx0aXRsZSBpZD0idGl0bGUiPlBTWe+8muW/g+eQhue6v+eahOWfuuehgOiuoeeul++8jOWFtuWunuaYr+iuoeaVsDwvdGl0bGU+PGRlc2MgaWQ9ImRlc2MiPuWFreS4quaUtuebmOS7t+W9ouaIkOS6lOS4quavlOi+g++8jOiusOS4ujHjgIEw44CBMOOAgTHjgIEx77yMUFNZNeS4ujYwJeOAgjwvZGVzYz48cmVjdCB3aWR0aD0iOTYwIiBoZWlnaHQ9IjQ2MCIgcng9IjIwIiBmaWxsPSIjZjBmNmZmIi8+PGcgZm9udC1mYW1pbHk9Ik1pY3Jvc29mdCBZYUhlaSxzYW5zLXNlcmlmIj48dGV4dCB4PSIzNiIgeT0iNTAiIGZvbnQtc2l6ZT0iMjciIHRleHQtYW5jaG9yPSJzdGFydCIgZmlsbD0iIzE0MmM1MCIgZm9udC13ZWlnaHQ9ImJvbGQiPlBTWe+8muW/g+eQhue6v+eahOWfuuehgOiuoeeul++8jOWFtuWunuaYr+iuoeaVsDwvdGV4dD48dGV4dCB4PSIzNiIgeT0iODgiIGZvbnQtc2l6ZT0iMTgiIHRleHQtYW5jaG9yPSJzdGFydCIgZmlsbD0iIzE0MmM1MCI+6Jma5p6E566X5L6L772c5Lil5qC85LiK5rao6K6wMe+8jOWQpuWImeiusDDvvJvlubPku7fku43orqHlhaXliIbmr408L3RleHQ+PHJlY3QgeD0iMzYiIHk9IjExNiIgd2lkdGg9Ijg4OCIgaGVpZ2h0PSIyNDQiIHJ4PSIxNCIgZmlsbD0id2hpdGUiIHN0cm9rZT0iI2I4ZDBmNCIvPjx0ZXh0IHg9IjY1IiB5PSIxNTMiIGZvbnQtc2l6ZT0iMjQiIHRleHQtYW5jaG9yPSJzdGFydCIgZmlsbD0iIzE0MmM1MCI+5pS255uY5Lu377yaMTAg4oaSIDExIOKGkiAxMCDihpIgMTAg4oaSIDEyIOKGkiAxMzwvdGV4dD48dGV4dCB4PSIxMjIiIHk9IjIwOCIgZm9udC1zaXplPSIyMSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE0MmM1MCI+MTDihpIxMTwvdGV4dD48dGV4dCB4PSIxMjIiIHk9IjI1NCIgZm9udC1zaXplPSIyOSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE3NWRkZCIgZm9udC13ZWlnaHQ9ImJvbGQiPjE8L3RleHQ+PHRleHQgeD0iMzAxIiB5PSIyMDgiIGZvbnQtc2l6ZT0iMjEiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiPjEx4oaSMTA8L3RleHQ+PHRleHQgeD0iMzAxIiB5PSIyNTQiIGZvbnQtc2l6ZT0iMjkiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNzVkZGQiIGZvbnQtd2VpZ2h0PSJib2xkIj4wPC90ZXh0Pjx0ZXh0IHg9IjQ4MCIgeT0iMjA4IiBmb250LXNpemU9IjIxIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTQyYzUwIj4xMOKGkjEwPC90ZXh0Pjx0ZXh0IHg9IjQ4MCIgeT0iMjU0IiBmb250LXNpemU9IjI5IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTc1ZGRkIiBmb250LXdlaWdodD0iYm9sZCI+MDwvdGV4dD48dGV4dCB4PSI2NTkiIHk9IjIwOCIgZm9udC1zaXplPSIyMSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE0MmM1MCI+MTDihpIxMjwvdGV4dD48dGV4dCB4PSI2NTkiIHk9IjI1NCIgZm9udC1zaXplPSIyOSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE3NWRkZCIgZm9udC13ZWlnaHQ9ImJvbGQiPjE8L3RleHQ+PHRleHQgeD0iODM4IiB5PSIyMDgiIGZvbnQtc2l6ZT0iMjEiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiPjEy4oaSMTM8L3RleHQ+PHRleHQgeD0iODM4IiB5PSIyNTQiIGZvbnQtc2l6ZT0iMjkiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNzVkZGQiIGZvbnQtd2VpZ2h0PSJib2xkIj4xPC90ZXh0Pjx0ZXh0IHg9IjQ4MCIgeT0iMzIzIiBmb250LXNpemU9IjIzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTQyYzUwIiBmb250LXdlaWdodD0iYm9sZCI+UFNZNe+8nSgx77yLMO+8izDvvIsx77yLMSnDtzXDlzEwMCXvvJ02MCU8L3RleHQ+PHRleHQgeD0iMzYiIHk9IjQyNSIgZm9udC1zaXplPSIxNyIgdGV4dC1hbmNob3I9InN0YXJ0IiBmaWxsPSIjMTQyYzUwIj42MCXmmK/ov5k15qyh5q+U6L6D55qE5Y6G5Y+y5Y2g5q+U77yM5LiN5piv5ZCO5LiA5pyf5LiK5rao5qaC546H44CCPC90ZXh0PjwvZz48L3N2Zz4=)

## 用六个价格算出PSY5

取虚构收盘价10、11、10、10、12、13，得到：

| 本期收盘价 | 上期收盘价 | 是否严格上升 | 记数 |
| --- | --- | --- | --- |
| 11 | 10 | 是 | 1 |
| 10 | 11 | 否 | 0 |
| 10 | 10 | 相等，按本文约定不计上涨 | 0 |
| 12 | 10 | 是 | 1 |
| 13 | 12 | 是 | 1 |

PSY5＝(1＋0＋0＋1＋1)÷5×100%＝60%。

若下一期收盘价为12，新比较记0，最早的1移出窗口，得到0、0、1、1、0，PSY5变为40%。它是固定长度的滚动计数，不是从起点一直累计。

## 为什么PSY不等于上涨幅度？

公式只看是否上升，涨0.1和涨2都记1；下跌幅度不同，也都记0。

例如另一组虚构收盘价10、10.1、5、5、5.1、5.2，五次比较同样是1、0、0、1、1，PSY5同样为60%。但这组首尾价格从10变为5.2，上一组则从10变为13。

相同的上涨次数占比，可以对应完全不同的首尾价格变化。端点变动率的计算见[ROC图解](https://www.structguide.com/indicators/roc)。

## PSY60是未来上涨概率60%吗？

不是。这里的60%只表示所选历史窗口中，5次比较有3次符合条件。公式没有建立后一期价格的概率模型，也没有调查参与者的心理状态。

PSY与RSI也不能混用：PSY对“是否上升”计数，RSI分别处理上涨量、下跌量并平滑。详见[RSI计算图解](https://www.structguide.com/indicators/rsi)。

## N和PSYMA参数分别是什么？

N控制比较次数。在本页不加额外平滑的定义下，PSY5只能取0%、20%、40%、60%、80%、100%这六种值；计数增加1，结果相差100/N个百分点。

PSYMA是对PSY序列再求平均。若约定为M期简单平均，连续三个PSY值为60、40、80，则PSYMA3＝60。先求每期PSY，再对这些结果平均，与直接把N改大不是同一计算。

图表周期会决定一次比较对应多长时间；颜色与线宽不参与计数。

## 平价、缺失值与软件差异

PSY差异应先检查平价和分母：本文严格上涨记1，其余记0，平价仍占一个比较周期。还需区分原始PSY与另行平滑的PSYMA，不能把上涨次数比例当作上涨幅度。

本文平价不计上涨，但不缩短分母。若某实现采用不同平价约定，结果需要重新核对，不能直接比较。

不足N次有效比较、前收盘价缺失或数据中断时，应按明确规则处理，不能自动将缺失比较当成0。还需核对复权、图表周期及是否额外平滑。

未结束K线的收盘价可能跨过上期收盘价，使本期记数在0与1之间变化；这属于输入尚未固定。

## 相关阅读与公式来源

- [ROC变动率](https://www.structguide.com/indicators/roc)：比较两个端点的相对变化。

- [RSI相对强弱指标](https://www.structguide.com/indicators/rsi)：比较平滑后的幅度。

- [返回指标速查手册](https://www.structguide.com/indicators/)。

计数与PSYMA定义参考[富途PSY公式说明](https://www.futuhk.com/cn/hant/support/topic1_656)，本文已明确平价与窗口约定。数字算例与图解为本站自拟。本文不表示Struct Guide插件提供PSY功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
