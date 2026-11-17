来源：https://chanlunzhan.com/learn/kline-basics/why-structure
采集时间：2026-11-08T02:32:27+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [看懂一张图](https://chanlunzhan.com/learn/kline-basics)

- 为什么缠论不看指标看结构

[阶段 0·看懂一张图](https://chanlunzhan.com/learn/kline-basics)·第 3 / 3 节·约 9 分钟

# 为什么缠论不看指标看结构

理解指标类方法的固有缺陷，说清缠论选择结构分解路线的理由。

这是阶段 0 的最后一课，讲的是取向问题：为什么要学缠论，而不是学均线金叉。

## 指标是价格的函数

打开任何行情软件，指标有几十个：均线、[MACD](https://chanlunzhan.com/glossary/macd)、KDJ、RSI、布林带。
它们的计算方式各不相同，但有一个共同的性质：

它们全都是价格序列的函数。

5 日均线是最近 5 天收盘价的平均，MACD 是两条指数移动平均的差再做平滑。
输入只有价格，没有任何额外信息。这意味着指标不可能包含价格之外的信息——
它只是把价格重新加工了一遍。

加工有价值：平滑掉噪音，让[趋势](https://chanlunzhan.com/glossary/qushi)更容易看见。但也有代价：

- 滞后。任何平滑都要用历史数据，均线拐头一定在价格拐头之后。

- 参数任意。为什么是 5 日不是 6 日？为什么 MACD 用 12、26、9？
这些数字没有理论依据，是经验值。换个参数结论就变。

- 无法穷尽。指标给的是「金叉」「死叉」这类信号，但走势本身有无穷多种形态，
信号无法覆盖全部情况。用了指标你只知道「现在有信号」，不知道「现在走势走到哪了」。

## 缠论换了个问法

缠论的思路是：先不问「该买还是该卖」，而是问：这段走势的结构是什么。

具体做法是自底向上地搭一套结构：

- 把有[包含关系](https://chanlunzhan.com/glossary/baohan)的 [K 线](https://chanlunzhan.com/glossary/kline)合并，消除噪音（这一步没有参数）

- 找出[分型](https://chanlunzhan.com/glossary/fenxing)——局部的转折点

- 把分型连成[笔](https://chanlunzhan.com/glossary/bi)

- 把笔组织成[线段](https://chanlunzhan.com/glossary/xianduan)

- 找出线段之间的重叠区间，得到[中枢](https://chanlunzhan.com/glossary/zhongshu)

- 由中枢的数[量](https://chanlunzhan.com/glossary/chengjiaoliang)和排列，把[走势分类](https://chanlunzhan.com/glossary/zoushileixing)为[盘整](https://chanlunzhan.com/glossary/panzheng)或趋势

到第 6 步，你得到的不是一个信号，而是对这段走势的[完全分类](https://chanlunzhan.com/glossary/zoushifenjie)。
原文有一句话把这个思路讲得很直接：

真正的预测，就是[不测而测](https://chanlunzhan.com/glossary/fenleibuyuce)……问题不是去预测什么，而是确定分段边界。

这是缠论和指标体系最根本的分歧。指标试图预测，缠论试图分类。

分类为什么比预测更可靠

预测要求你说对未来。分类只要求你说清现在——「当前这段走势属于第几种情况」，
这是可以在事后被严格检验的。

而缠论进一步主张：走势的分类是有限的，所有可能情况都能穷尽。
如果这个主张成立，那么虽然你不知道下一步走哪个，但你知道候选项只有这么几个。
这不是预测，但比什么都不知道强得多。

## 代价：说清楚很难

这条路线的代价也很实在。

指标的好处是没有歧义：MACD 金叉就是金叉，一行代码算完，一百个人算出来一样。
结构分解则处处需要判定：这三根 K 线算不算包含？这个分型成立吗？这个线段被破坏了吗？

而缠论原文对其中一部分判定给的定义并不完全封闭，最典型的是线段的划分。
结果就是不同流派、不同软件画出来的线段可能不一样——这不是有人算错了，
是原文留下的解释空间。

本站的态度

我们不假装存在唯一标准答案。站内所有结构标注都是本站算法按某一套具体口径的结果，
在[参数实验室](https://chanlunzhan.com/practice/lab)里你可以亲手切换口径，看同一段走势
在[严格笔](https://chanlunzhan.com/glossary/yangebi)和[宽松笔](https://chanlunzhan.com/glossary/kuansongbi)下的差异。

知道分歧在哪，比背下一套口径更重要。

## 那 MACD 呢

有意思的是，缠论并没有完全抛弃指标。判断[背驰](https://chanlunzhan.com/glossary/beichi)时，原文用了 MACD。

但用法不一样：MACD 在这里不是产生信号的，而是给「力度」一个可量化的代理指标。
判断的主体仍然是结构——先由中枢确认这是一段趋势，再比较趋势里前后两段的力度。
没有结构，MACD 的顶背离什么都不说明。

这个分工到第五阶会详细讲。

## 这一课的要点

- 指标是价格的函数，不含价格之外的信息，且必然滞后、参数任意

- 缠论把问题从「预测涨跌」换成「确定走势的结构分类」

- 分类可以被事后严格检验，而缠论主张分类是有限、可穷尽的

- 代价是判定复杂，且原文在线段等处留有解释空间，流派之间会有分歧

- MACD 在缠论里保留了一个位置：给「力度」提供代理指标，但判断主体是结构

## 本课术语

- [MACD](https://chanlunzhan.com/glossary/macd)

- [分类而非预测](https://chanlunzhan.com/glossary/fenleibuyuce)

## 对应原文

[第 1 课教你炒股票1：不会赢钱的经济人，只是废人！](https://chanlunzhan.com/108/1)[第 24 课教你炒股票24：MACD对背弛的辅助判断](https://chanlunzhan.com/108/24)

## 下一课

[缠论的世界观

走势终完美](https://chanlunzhan.com/learn/worldview/zoushi-zhong-wanmei)

[← 上一课 · 看懂一张图

周期与级别不是一回事](https://chanlunzhan.com/learn/kline-basics/periods-and-levels)[下一课 · 缠论的世界观 →

走势终完美](https://chanlunzhan.com/learn/worldview/zoushi-zhong-wanmei)
