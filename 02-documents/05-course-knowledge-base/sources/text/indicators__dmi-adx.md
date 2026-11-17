来源：https://www.structguide.com/indicators/dmi-adx
抓取：2026-11-06T00:31:04+08:00

# DMI与ADX是什么？计算公式、参数与逐步计算图解

DMI先比较相邻K线的高低价变化，筛选出两组非负数，再与真实波幅一起平滑、求比；ADX则对后续差异比值再做一次平滑。 把这条计算链拆开，就能理解各条线从哪里来。

DMI通常称动向指标，ADX称平均方向指数。本文采用Wilder平滑，只讲公式和数值关系，不讨论操作用法。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 相邻K线高低价及前收盘价 |
| 计算 | 筛选＋DM和－DM→分别与TR平滑→求两条DI→计算DX→平滑为ADX |
| 参数与约定 | DI周期N、ADX周期M；本文均用Wilder平滑 |
| 单位与边界 | DI、DX、ADX均无价格单位；零分母需单独处理 |

公式来源：[TradingView DMI说明](https://www.tradingview.com/support/solutions/43000502250-directional-movement-dmi/)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## 先认清DMI、DI、DX与ADX

| 名称 | 本文含义 |
| --- | --- |
| DMI | 这组高低价变化与平滑计算的统称 |
| ＋DI / PDI | 正向DM平滑值相对TR平滑值的比例 |
| －DI / MDI | 负向DM平滑值相对TR平滑值的比例 |
| DX | 两条DI之差的绝对值相对其和的比例 |
| ADX | DX序列的平滑值 |

这里“正向、负向”是两组计算的名称；＋DM、－DM、＋DI和－DI本身均为非负值，负号不是要求数值小于0。

![DMI与ADX计算链：高低价变化筛选DM，结合TR分别平滑，得到两条DI，再计算DX并平滑为ADX](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDYwIiB2aWV3Qm94PSIwIDAgOTYwIDQ2MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPjx0aXRsZSBpZD0idGl0bGUiPkRNSeS4jkFEWO+8muetm+mAiSDihpIg5bmz5ruRIOKGkiDmsYLmr5Qg4oaSIOWGjeW5s+a7kTwvdGl0bGU+PGRlc2MgaWQ9ImRlc2MiPuetm+mAiemrmOS9juS7t+WPmOWMluaIkERN77yM5bCGRE3kuI5UUuW5s+a7keW+l0RJ77yM5YaN5bCGREnlt67lvILmr5TorrDkuLpEWO+8jOW5s+a7keW+l+WIsEFEWOOAgjwvZGVzYz48cmVjdCB3aWR0aD0iOTYwIiBoZWlnaHQ9IjQ2MCIgcng9IjIwIiBmaWxsPSIjZjBmNmZmIi8+PGcgZm9udC1mYW1pbHk9Ik1pY3Jvc29mdCBZYUhlaSxzYW5zLXNlcmlmIj48dGV4dCB4PSIzNiIgeT0iNTAiIGZvbnQtc2l6ZT0iMjciIHRleHQtYW5jaG9yPSJzdGFydCIgZmlsbD0iIzE0MmM1MCIgZm9udC13ZWlnaHQ9ImJvbGQiPkRNSeS4jkFEWO+8muetm+mAiSDihpIg5bmz5ruRIOKGkiDmsYLmr5Qg4oaSIOWGjeW5s+a7kTwvdGV4dD48dGV4dCB4PSIzNiIgeT0iODgiIGZvbnQtc2l6ZT0iMTgiIHRleHQtYW5jaG9yPSJzdGFydCIgZmlsbD0iIzE0MmM1MCI+5pys5paH6K+05piO6K6h566X6ZO+5LiO5Yid5aeL5YyW77yM5LiN6K6o6K665pON5L2c55So5rOVPC90ZXh0PjxyZWN0IHg9IjM2IiB5PSIxMTkiIHdpZHRoPSIyODgiIGhlaWdodD0iMTMzIiByeD0iMTQiIGZpbGw9IndoaXRlIiBzdHJva2U9IiNiOGQwZjQiLz48dGV4dCB4PSIxODAiIHk9IjE1NiIgZm9udC1zaXplPSIyMyIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE0MmM1MCIgZm9udC13ZWlnaHQ9ImJvbGQiPuetm+mAiURNPC90ZXh0Pjx0ZXh0IHg9IjE4MCIgeT0iMTk1IiBmb250LXNpemU9IjE3IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTc1ZGRkIj7mr5TovoPpq5jkvY7ku7flj5jljJY8L3RleHQ+PHRleHQgeD0iMTgwIiB5PSIyMzAiIGZvbnQtc2l6ZT0iMTYiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiPuebuOetieaXtuS4pOe7hERN5Z2H5Li6MDwvdGV4dD48cmVjdCB4PSIzMzYiIHk9IjExOSIgd2lkdGg9IjI4OCIgaGVpZ2h0PSIxMzMiIHJ4PSIxNCIgZmlsbD0id2hpdGUiIHN0cm9rZT0iI2I4ZDBmNCIvPjx0ZXh0IHg9IjQ4MCIgeT0iMTU2IiBmb250LXNpemU9IjIzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTQyYzUwIiBmb250LXdlaWdodD0iYm9sZCI+5YiG5Yir5bmz5ruRPC90ZXh0Pjx0ZXh0IHg9IjQ4MCIgeT0iMTk1IiBmb250LXNpemU9IjE3IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTc1ZGRkIj7vvItETeOAge+8jURN44CBVFI8L3RleHQ+PHRleHQgeD0iNDgwIiB5PSIyMzAiIGZvbnQtc2l6ZT0iMTYiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiPuacrOaWh+mHh+eUqFdpbGRlcuW5s+WdhzwvdGV4dD48cmVjdCB4PSI2MzYiIHk9IjExOSIgd2lkdGg9IjI4OCIgaGVpZ2h0PSIxMzMiIHJ4PSIxNCIgZmlsbD0id2hpdGUiIHN0cm9rZT0iI2I4ZDBmNCIvPjx0ZXh0IHg9Ijc4MCIgeT0iMTU2IiBmb250LXNpemU9IjIzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTQyYzUwIiBmb250LXdlaWdodD0iYm9sZCI+6K6h566X5Lik5p2hREk8L3RleHQ+PHRleHQgeD0iNzgwIiB5PSIxOTUiIGZvbnQtc2l6ZT0iMTciIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNzVkZGQiPjEwMMOX5bmz5ruRRE3Dt+W5s+a7kVRSPC90ZXh0Pjx0ZXh0IHg9Ijc4MCIgeT0iMjMwIiBmb250LXNpemU9IjE2IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjMTQyYzUwIj7kuKTmnaFESeWdh+S4uumdnui0n+WAvDwvdGV4dD48dGV4dCB4PSI0ODAiIHk9IjI5NiIgZm9udC1zaXplPSIyNSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE3NWRkZCIgZm9udC13ZWlnaHQ9ImJvbGQiPkRY77ydMTAww5d85Lik5p2hREnkuYvlt658w7fkuKTmnaFESeS5i+WSjDwvdGV4dD48dGV4dCB4PSI0ODAiIHk9IjMzNyIgZm9udC1zaXplPSIyNCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzE0MmM1MCIgZm9udC13ZWlnaHQ9ImJvbGQiPuWGjeW5s+a7kURYIOKGkiBBRFg8L3RleHQ+PHRleHQgeD0iNDgwIiB5PSIzNzYiIGZvbnQtc2l6ZT0iMjAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiMxNDJjNTAiPuaVmeWtpueul+S+i07vvJ0z44CBTe+8nTPvvJrnrKw15pyfQURY4omIMzkuMzkzOTwvdGV4dD48dGV4dCB4PSIzNiIgeT0iNDI1IiBmb250LXNpemU9IjE3IiB0ZXh0LWFuY2hvcj0ic3RhcnQiIGZpbGw9IiMxNDJjNTAiPkRJ5ZGo5pyfTuS4jkFEWOWRqOacn03liIbliKvorr7lrprvvJvpppbkuKpBRFjpnIDopoHnrYnlvoXotrPlpJ/nmoREWOagt+acrOOAgjwvdGV4dD48L2c+PC9zdmc+)

## 第一步：高低价变化怎样筛选为DM？

设本期最高、最低为H、L，上期为Hₚ、Lₚ：

- U＝H－Hₚ。

- D＝Lₚ－L。

- 若U＞D且U＞0，＋DM＝U；否则＋DM＝0。

- 若D＞U且D＞0，－DM＝D；否则－DM＝0。

因此同一期不会同时保留两个正的DM。U＝D时，两组DM都取0，即使两者都大于0，也不会各保留一个。

例如上期H＝13、L＝8，本期H＝14、L＝7，则U＝1、D＝1，两组DM均为0。但本期高低价差仍为7，DM为0不等于没有价格范围。

## 第二步：TR与DM分别平滑，得到DI

记上期收盘价为Cₚ，TR＝max(H－L，|H－Cₚ|，|L－Cₚ|)。完整解释见[ATR真实波幅公式](https://www.structguide.com/indicators/atr#formula)。

设DM与TR的平滑周期为N，本文使用Wilder平均：

Sₜ＝((N－1)×Sₜ₋₁＋Xₜ)÷N。

分别令X为＋DM、－DM、TR，得到平滑值A、B、T；当T＞0时：

＋DI＝100×A/T；－DI＝100×B/T。

本文先取最初N个有效输入的简单平均作种子，随后递推。有的软件写成平滑“和”而非平滑“均值”；若种子和后续更新都严格保持相差N倍，比例会相同，不能只因中间数字不同就断定结果有误。

## 第三步：DX怎样变成ADX？

两条DI之和大于0时：

DX＝100×|＋DI－(－DI)|÷(＋DI＋(－DI))。

括号中的“－DI”是第二条线的名称。先求两条线数值之差的绝对值，再除以它们的和。

设ADX平滑周期为M，本文先取最初M个有效DX的简单平均作ADX种子，再按以下方式更新：

ADXₜ＝((M－1)×ADXₜ₋₁＋DXₜ)÷M。

DI平滑周期N与ADX平滑周期M是两个参数，可以相同，也可以不同。DX使用绝对值，因此对调两条DI后，DX不变；ADX也不会仅凭自身数值给出正负方向。

## 用一组连续数据手算

以下取N＝3、M＝3，仅为教学便于复算。初始第0期H＝10、L＝8、C＝9，后续高低收盘价均为虚构：

| 期数 | H | L | C | ＋DM | －DM | TR |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 12 | 9 | 11 | 2 | 0 | 3 |
| 2 | 11 | 7 | 8 | 0 | 2 | 4 |
| 3 | 13 | 8 | 12 | 2 | 0 | 5 |
| 4 | 14 | 7 | 13 | 0 | 0 | 7 |
| 5 | 15 | 8 | 14 | 1 | 0 | 7 |
| 6 | 14 | 6 | 7 | 0 | 2 | 8 |

到第3期，已有3组输入，可以初始化：

- A＝(2＋0＋2)÷3＝4/3。

- B＝(0＋2＋0)÷3＝2/3。

- T＝(3＋4＋5)÷3＝4。

- ＋DI＝100×(4/3)÷4≈33.3333；－DI≈16.6667。

- DX＝100×(33.3333…－16.6666…)÷50≈33.3333。

接着逐期递推，得到下表。所有运算保留完整精度，只在显示时保留四位小数：

| 期数 | 平滑A | 平滑B | 平滑T | ＋DI | －DI | DX | ADX |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3 | 1.3333 | 0.6667 | 4.0000 | 33.3333 | 16.6667 | 33.3333 | 尚不足3个DX |
| 4 | 0.8889 | 0.4444 | 5.0000 | 17.7778 | 8.8889 | 33.3333 | 尚不足3个DX |
| 5 | 0.9259 | 0.2963 | 5.6667 | 16.3399 | 5.2288 | 51.5152 | 39.3939 |
| 6 | 0.6173 | 0.8642 | 6.4444 | 9.5785 | 13.4100 | 16.6667 | 31.8182 |

第5期才得到首个ADX＝(DX₃＋DX₄＋DX₅)÷3≈39.3939；第6期则为(上期ADX×2＋DX₆)÷3≈31.8182。

按本例种子方式，首个DI在第N个有效DM/TR输入处出现，首个ADX还需累计M个DX。数据起点与种子不同，首次显示位置也可能不同。

## 参数、ADXR与软件差异

DMI与ADX比较需要统一DM筛选、平滑周期、初始化和起算历史。本文高低价两种变化相等时DM均为0；首个ADX须积累M个有效DX后初始化，不与首个DI同时出现。

核对软件时，应分别确认DM/TR的周期、ADX的周期、平滑算法、种子与数据起算点，而不只是看界面上一个数字。

有些DMI界面还显示ADXR，其计算方式是把本期ADX与某个滞后期ADX再取平均；滞后期数需看具体公式。它不等于本文的ADX，不能直接替换比较。

T＝0时DI存在零分母；两条DI之和为0时DX也存在零分母。显示0、空值或其他处理都需要明确的软件约定，本文不对这些未定义算式直接赋值。

复权口径、缺失数据、首期前收盘价与未结束K线变化，也可能影响后续计算。算法含多次平滑，不意味着它给出了后续价格变化的概率。

## 相关阅读与公式来源

- [ATR怎么算](https://www.structguide.com/indicators/atr)：TR与Wilder平滑。

- [RSI怎么算](https://www.structguide.com/indicators/rsi)：Wilder平滑在另一类输入中的使用。

- [返回指标速查手册](https://www.structguide.com/indicators/)。

DM筛选、DI与DX关系参考[TradingView DMI说明](https://www.tradingview.com/support/solutions/43000502250-directional-movement-dmi/)。本站明确采用上述平滑与初始化口径，数字算例和图解为自拟。本文不表示Struct Guide插件提供DMI或ADX功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
