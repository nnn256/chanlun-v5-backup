来源：https://www.structguide.com/indicators/bias
抓取：2026-11-06T00:31:03+08:00

# BIAS乖离率是什么？计算公式、周期与数字图解

BIAS把本期价格与均线的差，除以均线，再用百分比表示。 它常称乖离率，回答的是“价格相对这个平均值偏离了多少”，而不只是“相差多少元”。

同样相差2元，均线为10元时是20%，均线为100元时只有2%。分母让差值有了相对尺度。

编写：[Struct Guide](https://www.structguide.com/) · 更新：2026-11-03

## 一分钟速查

| 项目 | 本文口径 |
| --- | --- |
| 输入 | 本期价格C及对应N期简单均线MA |
| 计算 | BIAS＝(C－MA)/MA×100% |
| 参数与约定 | 本文均线采用最近N期收盘价简单平均 |
| 单位与边界 | 以百分比表示；MA不得为0 |

公式来源：[东方财富BIAS说明的计算公式](https://qhweb.eastmoney.com/videos/10/1889158.html)。以下数字算例与图解为本站自拟；具体初始化与特殊值处理见后文。

## BIAS计算公式速查

本文使用本期收盘价C，以及包含本期在内的最近N个收盘价的简单移动平均MAₙ：

BIASₙ＝(C－MAₙ)÷MAₙ×100%

| 项目 | 含义 |
| --- | --- |
| 分子C－MAₙ | 价格与窗口均值的绝对差 |
| 分母MAₙ | 用作比较基准的窗口均值，要求不为0 |
| N | 简单平均窗口的数据个数 |
| 百分比 | 无价格单位的相对差值 |

若软件公式写“×100”并显示16.67，通常需要按16.67%理解；未乘100的比值则约为0.1667。核对数值时要先对齐单位。

![BIAS图解：均线10、价格12时偏离20%；均线100、价格102时偏离2%，绝对差均为2，相对比例不同](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NjAiIGhlaWdodD0iNDAwIiB2aWV3Qm94PSIwIDAgOTYwIDQwMCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsbGVkYnk9InRpdGxlIGRlc2MiPgo8dGl0bGUgaWQ9InRpdGxlIj5CSUFT5ZCM5qC355qE5beu5YC85LiO5LiN5ZCM55qE5YiG5q+NPC90aXRsZT48ZGVzYyBpZD0iZGVzYyI+5Lu35qC8MTLjgIHlnYfnur8xMO+8jOW3ruWAvDLvvIxCSUFT5Li6MjAl77yb5Lu35qC8MTAy44CB5Z2H57q/MTAw77yM5beu5YC85Lmf5Li6Mu+8jEJJQVPkuLoyJeOAgjwvZGVzYz4KPHJlY3Qgd2lkdGg9Ijk2MCIgaGVpZ2h0PSI0MDAiIHJ4PSIyMCIgZmlsbD0iI2YwZjZmZiIvPgo8ZyBmb250LWZhbWlseT0iTWljcm9zb2Z0IFlhSGVpLHNhbnMtc2VyaWYiIGZpbGw9IiMxNDJjNTAiPgo8dGV4dCB4PSIzNiIgeT0iNTIiIGZvbnQtc2l6ZT0iMjgiIGZvbnQtd2VpZ2h0PSJib2xkIj7lkIzmoLfnm7jlt64y77yMQklBU+S4uuS7gOS5iOS4jeWQjO+8nzwvdGV4dD4KPHRleHQgeD0iMzYiIHk9IjkwIiBmb250LXNpemU9IjE4Ij5CSUFT77ydKOS7t+agvO+8jeWdh+e6vynDt+Wdh+e6v8OXMTAwJe+9nOiZmuaehOaVsOWtl+ekuuS+izwvdGV4dD4KPGcgZmlsbD0id2hpdGUiIHN0cm9rZT0iI2I4ZDBmNCI+PHJlY3QgeD0iMzYiIHk9IjEyMiIgd2lkdGg9IjQyNiIgaGVpZ2h0PSIxODQiIHJ4PSIxNiIvPjxyZWN0IHg9IjQ5OCIgeT0iMTIyIiB3aWR0aD0iNDI2IiBoZWlnaHQ9IjE4NCIgcng9IjE2Ii8+PC9nPgo8ZyB0ZXh0LWFuY2hvcj0ibWlkZGxlIj48ZyBmb250LXNpemU9IjIzIj48dGV4dCB4PSIyNDkiIHk9IjE2NiI+5Lu35qC8MTLvvIzlnYfnur8xMDwvdGV4dD48dGV4dCB4PSI3MTEiIHk9IjE2NiI+5Lu35qC8MTAy77yM5Z2H57q/MTAwPC90ZXh0PjwvZz4KPGcgZm9udC1zaXplPSIyMCI+PHRleHQgeD0iMjQ5IiB5PSIyMDciPuW3ruWAvO+8nTI8L3RleHQ+PHRleHQgeD0iNzExIiB5PSIyMDciPuW3ruWAvO+8nTI8L3RleHQ+PC9nPgo8ZyBmb250LXNpemU9IjI3IiBmaWxsPSIjMTc1ZGRkIiBmb250LXdlaWdodD0iYm9sZCI+PHRleHQgeD0iMjQ5IiB5PSIyNjMiPjLDtzEw77ydMjAlPC90ZXh0Pjx0ZXh0IHg9IjcxMSIgeT0iMjYzIj4yw7cxMDDvvJ0yJTwvdGV4dD48L2c+PC9nPgo8dGV4dCB4PSIzNiIgeT0iMzU5IiBmb250LXNpemU9IjIwIj7liIbmr43mj5Dkvpvnm7jlr7nlsLrluqbjgILnmb7liIbmr5Tmj4/ov7Dot53nprvvvIzkuI3mmK/ku7fmoLzlkI7nu63lj5jljJbnmoTmpoLnjofjgII8L3RleHQ+CjwvZz48L3N2Zz4K)

## 用5个数字计算BIAS

取虚构收盘价10、12、11、13、14，N＝5：

- MA5＝(10＋12＋11＋13＋14)÷5＝12。

- 本期收盘价C＝14，价格差为14－12＝2。

- BIAS5＝2÷12×100%≈16.6667%。

下一期收盘价为15，窗口移出10，变成12、11、13、14、15。MA5变为13，BIAS5＝(15－13)÷13×100%≈15.3846%。

| 时刻 | 收盘价 | MA5 | 差值 | BIAS5 |
| --- | --- | --- | --- | --- |
| 本期 | 14 | 12 | 2 | 16.6667% |
| 下一期 | 15 | 13 | 2 | 15.3846% |

价格升高了，BIAS却减小了，因为差值同为2而分母变大。BIAS同时取决于价格和均线，不能只看价格变化去推断指标数值。

## 正值、负值与零表示什么？

在MA为正的前提下，BIAS为正表示价格大于均线，为负表示价格小于均线；等于0表示价格与均线相等。

例如价格9、均线10，则BIAS＝－10%；价格11、均线10，则BIAS＝＋10%。这里的百分比仅描述相对距离，不代表价格后续必须回到均线，也不提供完成这一变化的时间。

BIAS不是价格的涨跌幅。涨跌幅通常以上一期价格为分母，而这里以选定周期的均线为分母。

## BIAS参数和多条曲线

一些软件同时显示6、12、24等周期，它们是对同一收盘价分别使用不同窗口均值计算的乖离率，不是对同一个BIAS数值乘不同倍率。本文的5期只是便于手算。

修改N会同时改变分子和分母，因此不能保证N越大，BIAS的绝对值就一定越大或越小。日K线和周K线的同名周期，也不能当作相同输入。

颜色和线宽不参与公式。识别不同周期的BIAS，应看图例名称和参数。

## BIAS与BOLL有什么区别？

| 指标 | 本文口径 | 是否使用标准差 |
| --- | --- | --- |
| BIAS | (价格－MA)÷MA | 不使用 |
| BOLL | MA及其上下K倍标准差 | 使用 |

BIAS除以的是均值，不是标准差。它不等于“偏离了几个标准差”，也不能把某个BIAS百分比直接换成布林带的上轨或下轨。

继续阅读[BOLL布林带公式](https://www.structguide.com/indicators/boll)，可以看到离散程度是如何单独进入计算的。

## 特殊数据与软件口径

BIAS比较需要统一价格与均线定义。本文分母是N期简单均线而非历史某一期价格；输入、窗口、均线类型或复权口径不同都会改变结果，MA为0时比例未定义。

MA＝0时，BIAS分母为0，不能直接计算；MA接近0时，结果可能非常大。若输入允许负价格，公式仍需逐项计算，不能沿用“正值即高于均线”的正分母解释。

不同软件若使用了不同价格来源、复权数据、均线算法或不足N根时的处理规则，结果可能不同。未结束K线的输入更新时，均线和BIAS也可能变化。

## 相关阅读与公式来源

- [ROC变动率](https://www.structguide.com/indicators/roc)：区分历史端点与均线基准。

- [CCI计算图解](https://www.structguide.com/indicators/cci)：比较以均值和离散程度作为分母的区别。

- [MA均线怎么算](https://www.structguide.com/indicators/ma)：理解BIAS所用的平均值。

- [BOLL布林带怎么算](https://www.structguide.com/indicators/boll)：比较均值与标准差。

- [返回常见指标速查手册](https://www.structguide.com/indicators/)。

公式参考[东方财富BIAS说明的计算公式](https://qhweb.eastmoney.com/videos/10/1889158.html)。本站仅引用计算定义，数字算例与图解为自拟。本文不表示Struct Guide插件提供BIAS功能；插件结构计算见[画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

本文仅介绍指标计算与数据展示，不提供投资建议。
