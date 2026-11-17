来源：https://www.structguide.com/indicators/kdj
抓取：2026-11-06T00:31:05+08:00

# KDJ是什么指标？RSV、K、D、J计算公式与参数图解

KDJ先计算收盘价在一段高低范围中的相对位置，再做两次平滑，最后组合出J值。 三条曲线背后，分别对应不同的运算步骤。

KDJ通常称为随机指标。“随机”不表示算法会随机抽数；给定相同的数据、参数和初始化方式，计算结果是确定的。本页只说明数值与公式，不讨论操作用法。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 窗口最高价H、最低价L和本期收盘价C |
| 计算 | RSV＝100×(C－L)/(H－L)；先平滑为K，再平滑为D；J＝3K－2D |
| 参数与约定 | 本文两次平滑的新输入权重均为1/3；窗口包含本期 |
| 单位与边界 | H＞L时RSV为0—100；J不受0—100限制 |

公式来源：[富途KDJ说明的计算公式部分](https://support.futunn.com/topic149?from_platform=1&lang=zh-cn)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## KDJ计算公式速查

记C为本期收盘价，Hₙ为最近N根K线的最高价，Lₙ为最近N根K线的最低价，窗口包含本期。

| 步骤 | 本文采用的常见公式 | 计算对象 |
| --- | --- | --- |
| RSV | (C－Lₙ)÷(Hₙ－Lₙ)×100 | 收盘价在窗口范围中的位置 |
| K | 上期K×2/3＋本期RSV×1/3 | 对RSV做指数递推平滑 |
| D | 上期D×2/3＋本期K×1/3 | 对K再次平滑 |
| J | 3K－2D | 对K与D做线性组合 |

注意：Hₙ、Lₙ取自窗口内每根K线的最高价和最低价，不是只对收盘价求最大、最小值。计算D时使用的是本期K。

![KDJ计算图解：窗口低点10、高点20、收盘价18，RSV为80；给定上期K和D均为50，本期K为60、D约53.33、J约73.33](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDQwIiB2aWV3Qm94PSIwIDAgOTYwIDQ0MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPgo8dGl0bGUgaWQ9InRpdGxlIj5LRErku47nqpflj6PkvY3nva7liLDkuKTmrKHlubPmu5E8L3RpdGxlPjxkZXNjIGlkPSJkZXNjIj7nqpflj6PmnIDkvY4xMOOAgeacgOmrmDIw44CB5pS255uY5Lu3MTjvvIxSU1bkuLo4MOOAgue7meWumuS4iuacn0vlkoxE5Li6NTDvvIzmnKzmnJ9L5Li6NjDvvIxE57qmNTMuMzPvvIxK57qmNzMuMzPjgII8L2Rlc2M+CjxyZWN0IHdpZHRoPSI5NjAiIGhlaWdodD0iNDQwIiByeD0iMjAiIGZpbGw9IiNmMGY2ZmYiLz4KPGcgZm9udC1mYW1pbHk9Ik1pY3Jvc29mdCBZYUhlaSxzYW5zLXNlcmlmIiBmaWxsPSIjMTQyYzUwIj4KPHRleHQgeD0iMzYiIHk9IjUyIiBmb250LXNpemU9IjI4IiBmb250LXdlaWdodD0iYm9sZCI+S0RK77ya5YWI5om+55u45a+55L2N572u77yM5YaN6YCS5o6o6K6h566XPC90ZXh0Pgo8dGV4dCB4PSIzNiIgeT0iOTAiIGZvbnQtc2l6ZT0iMTgiPuiZmuaehOeul+S+i++9nOeql+WPo+acgOS9jjEw44CB5pyA6auYMjDvvIzmlLbnm5jku7cxODwvdGV4dD4KPHBhdGggZD0iTTgwIDE1NCBIODgwIiBzdHJva2U9IiNjNGQ2ZWYiIHN0cm9rZS13aWR0aD0iMTQiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8cGF0aCBkPSJNODAgMTU0IEg3MjAiIHN0cm9rZT0iIzI1NjNlYiIgc3Ryb2tlLXdpZHRoPSIxNCIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+CjxjaXJjbGUgY3g9IjcyMCIgY3k9IjE1NCIgcj0iMTMiIGZpbGw9IiM3YzNhZWQiLz4KPGcgZm9udC1zaXplPSIxOSIgdGV4dC1hbmNob3I9Im1pZGRsZSI+PHRleHQgeD0iODAiIHk9IjE5NCI+MTA8L3RleHQ+PHRleHQgeD0iNzIwIiB5PSIxMjYiPuaUtuebmDE4PC90ZXh0Pjx0ZXh0IHg9Ijg4MCIgeT0iMTk0Ij4yMDwvdGV4dD48L2c+Cjx0ZXh0IHg9IjI2MCIgeT0iMjI1IiBmb250LXNpemU9IjIxIj5SU1bvvJ0oMTjvvI0xMCnDtygyMO+8jTEwKcOXMTAw77ydODA8L3RleHQ+CjxnIGZpbGw9IndoaXRlIiBzdHJva2U9IiNiOGQwZjQiPjxyZWN0IHg9IjM2IiB5PSIyNTUiIHdpZHRoPSIyNzIiIGhlaWdodD0iMTAyIiByeD0iMTQiLz48cmVjdCB4PSIzNDQiIHk9IjI1NSIgd2lkdGg9IjI3MiIgaGVpZ2h0PSIxMDIiIHJ4PSIxNCIvPjxyZWN0IHg9IjY1MiIgeT0iMjU1IiB3aWR0aD0iMjcyIiBoZWlnaHQ9IjEwMiIgcng9IjE0Ii8+PC9nPgo8ZyB0ZXh0LWFuY2hvcj0ibWlkZGxlIj48ZyBmb250LXNpemU9IjI0IiBmb250LXdlaWdodD0iYm9sZCIgZmlsbD0iIzE3NWRkZCI+PHRleHQgeD0iMTcyIiB5PSIyOTMiPkvvvJ02MDwvdGV4dD48dGV4dCB4PSI0ODAiIHk9IjI5MyI+ROKJiDUzLjMzPC90ZXh0Pjx0ZXh0IHg9Ijc4OCIgeT0iMjkzIj5K4omINzMuMzM8L3RleHQ+PC9nPgo8ZyBmb250LXNpemU9IjE3Ij48dGV4dCB4PSIxNzIiIHk9IjMyOCI+NTDDlzIvM++8izgww5cxLzM8L3RleHQ+PHRleHQgeD0iNDgwIiB5PSIzMjgiPjUww5cyLzPvvIs2MMOXMS8zPC90ZXh0Pjx0ZXh0IHg9Ijc4OCIgeT0iMzI4Ij4zw5c2MO+8jTLDlzUzLjMzMzPigKY8L3RleHQ+PC9nPjwvZz4KPHRleHQgeD0iMzYiIHk9IjQwNCIgZm9udC1zaXplPSIxOCI+5bey57uZ5a6a5LiK5pyfS++8nTUw44CBRO+8nTUw77ybROS9v+eUqOacrOacn0vjgILmmL7npLrlgLzlm5voiI3kupTlhaXjgII8L3RleHQ+CjwvZz48L3N2Zz4K)

## 用一组数字算出RSV、K、D、J

假设某个完整窗口的最高价为20、最低价为10，本期收盘价为18。为演示一次递推，另给定上期K＝50、上期D＝50。所有数字均为虚构。

- RSV＝(18－10)÷(20－10)×100＝80。

- K＝50×2/3＋80×1/3＝60。

- D＝50×2/3＋60×1/3＝53.3333…。

- J＝3×60－2×53.3333…＝73.3333…。

若下一期窗口高低点仍为20和10，收盘价变为16，RSV便变为60。继续使用刚算出的K与D：

| 计算时刻 | RSV | K | D | J |
| --- | --- | --- | --- | --- |
| 给定的上一期 | — | 50.0000 | 50.0000 | 50.0000 |
| 本期 | 80.0000 | 60.0000 | 53.3333 | 73.3333 |
| 下一期 | 60.0000 | 60.0000 | 55.5556 | 68.8889 |

这次K保持60，D仍向60靠近，J因此变化。三条线的变化可以逐项用递推式解释。计算保留完整精度，表格仅在显示时四舍五入。

## 参数9、3、3是什么意思？

按本文口径，9表示RSV的高低价窗口取9根K线；后两个3分别表示K、D的平滑系数分母，新输入权重均为1/3。

这不是“连续取3个数求普通平均”。部分公式语言将这种递推写作SMA(X,3,1)，但这里的SMA也不能直接等同于英文文档里的简单移动平均。必须查看该平台函数定义。

日K线与周K线即使都填9、3、3，输入窗口仍不同。改变N会改变高低范围；改变平滑参数会改变新旧数据的权重，效果不能只用“线条更快”概括。

## J为什么会超过100，甚至小于0？

当窗口高低点不同、收盘价位于该范围内时，RSV在0到100之间。若K和D的种子也在这个范围内，按本文加权平均公式递推，K和D仍会留在范围内。

J不是加权平均。 将公式改写为J＝K＋2(K－D)，就能看到它把K与D的差放大后加回K。

例如，给定上期K＝80、D＝50，本期RSV＝100，可以算得本期K≈86.6667、D≈62.2222、J≈135.5556。反过来，给定上期K＝20、D＝50，本期RSV＝0，则本期J≈－35.5556。

所以，J越过0或100并不必然表示软件出错，也不表示一个超过100%的概率。它首先是线性组合的结果。

## 初始化与特殊数据怎么处理？

KDJ比较需统一窗口高低价、平滑权重及K、D初始值。本文两次新输入权重均为1/3，计算D使用本期K；窗口高低价相同造成零分母时，需要另行约定处理方式。

- 初始K、D：本文示例明确给了上一期数值；实际软件可能使用50或其他种子，不能省略这一步就要求结果完全相同。

- Hₙ＝Lₙ：RSV公式分母为0，数学上无法直接计算；返回空值、沿用前值或采用约定值，应以软件实现为准。

- 窗口不足N根：是否提前输出、使用多少有效数据，需要核对软件规则。

- 未结束K线：收盘价输入以及窗口最高、最低价都可能更新，后续K、D、J随之变化。

核对不同软件时，还应检查数据周期、复权口径、J的具体公式和是否限制显示范围。不能仅凭三条线的颜色判断对应关系。

## 相关阅读与公式来源

- [WR威廉指标](https://www.structguide.com/indicators/wr)：对照WR与RSV的刻度关系。

- [MA和EMA的区别](https://www.structguide.com/indicators/ma-vs-ema)：理解等权平均与递推平滑。

- [RSI怎么算](https://www.structguide.com/indicators/rsi)：比较另一种比例与平滑计算。

- [返回常见指标速查手册](https://www.structguide.com/indicators/)。

公式参考[富途KDJ说明的计算公式部分](https://support.futunn.com/topic149?from_platform=1&lang=zh-cn)，算例与图解为本站自拟。本文介绍通用指标，不表示Struct Guide插件提供KDJ功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
