来源：https://chanlunzhan.com/learn/recursion/multi-level
采集时间：2026-11-08T02:32:39+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [递归与联立](https://chanlunzhan.com/learn/recursion)

- 多级别联立

[阶段 7·递归与联立](https://chanlunzhan.com/learn/recursion)·第 2 / 4 节·约 13 分钟

# 多级别联立

用两个级别对同一段走势做联立分析，并说清各级别的结论如何相互约束。

单[级别](https://chanlunzhan.com/glossary/jibie)分析能告诉你「在这个级别上，走势走到哪了」。
[多级别联立](https://chanlunzhan.com/glossary/duojibielianli)要回答的是：这个结论在更大和更小的尺度上意味着什么。

## 为什么需要联立

因为单一级别的信息不完整。

举个具体的情况：日线级别看是一段上涨[趋势](https://chanlunzhan.com/glossary/qushi)的[中枢震荡](https://chanlunzhan.com/glossary/zhongshuyanshen)。
这个描述本身没问题，但它不告诉你震荡还要持续多久、
下一步最可能往哪个方向突破。

换到 30 分钟级别看同一段震荡，你会看到它内部有自己的结构：
可能是一个完整的 30 分钟下跌趋势，也可能是几个 30 分钟[盘整](https://chanlunzhan.com/glossary/panzheng)的叠加。
这个信息在日线上是看不到的。

反过来，如果只看 30 分钟，你会陷入细节——
看到一个 30 分钟的下跌趋势，却不知道它在日线上只是[中枢](https://chanlunzhan.com/glossary/zhongshu)内部的一次回踩。

联立的本质

大级别定性质，小级别定位置。

大级别告诉你「当前处在什么结构里」，小级别告诉你
「这个结构内部走到了哪一步」。两者结合，描述才完整。

## 怎么联立

标准做法是取相邻的两到三个级别，通常是本级别和[次级别](https://chanlunzhan.com/glossary/cijibie)。

流程：

- 先做大级别。在大级别上完成完整分析：[划笔](https://chanlunzhan.com/glossary/bi)、划[线段](https://chanlunzhan.com/glossary/xianduan)、找中枢、定[走势类型](https://chanlunzhan.com/glossary/zoushileixing)。

- 确定当前所处的结构位置。是在中枢内部？在[离开段](https://chanlunzhan.com/glossary/lijinzoushi)？在[进入段](https://chanlunzhan.com/glossary/jinruduan)？

- 切到小级别，只看对应的那一段。不要看整张图，
只看大级别当前这一段对应的小级别走势。

- 在小级别上做完整分析。这一段在小级别上是什么走势类型？走完了吗？

- 把小级别的结论回代。小级别走完了，意味着大级别的这一段可能也走完了。

第 3 步的「只看对应的那一段」很关键，也最容易被忽略。

最常见的错误：级别串台

在日线上看到一个结构，然后在 30 分钟图上找另一个位置的结构，
把两者当成同一件事来推理。

这个错误很隐蔽，因为两个结论单独看都对，只是它们说的不是同一段走势。

防止的办法是每次切换级别都先对齐时间范围：
明确「我现在看的是大级别哪一段对应的小级别走势」。

## 结论如何相互约束

联立分析的价值在于约束：不同级别的结论不能互相矛盾。

几条常用的约束关系：

- 大级别的一段完成，当且仅当小级别在这一段内走出了完整的走势类型

- 大级别处于中枢内部时，小级别通常表现为若干个来回的走势类型

- 大级别的[背驰](https://chanlunzhan.com/glossary/beichi)，往往对应小级别在最后一段的背驰

- 小级别的[一买](https://chanlunzhan.com/glossary/diyileimaimaidian)，可能是大级别某一段的起点，也可能只是中枢内部的震荡

最后一条特别重要：小级别的[买卖点](https://chanlunzhan.com/glossary/sanleimaimaidian)，级别就是小的。
不能因为在 5 分钟上看到一买，就说日线要涨了。

## 在图上练习

图表加载中…

线段段中枢走势类型

显示笔线段笔中枢段中枢走势类型买卖点

合成数据，619 根，数据截至 2026-05-15。仅用于结构演示，非实时行情。

用这张图做一次联立练习：

- 先只开「线段 + 段中枢 + 走势类型」，这是大级别视角。
找到一段标为「趋势」的走势，确定它的中枢在哪。

- 关掉这些，打开「笔 + [笔中枢](https://chanlunzhan.com/glossary/biZhongshu)」，这是小级别视角。
在刚才那段趋势对应的位置，数一数有几个笔中枢。

- 对照：大级别的一个段中枢，对应小级别的几个笔中枢？
大级别的连接段，在小级别上是什么结构？

这个练习做熟了，联立分析的手感就有了。

## 联立到几个级别为止

理论上可以无限递归，实际上两到三个级别就够了。

原因很实际：

- 每多一个级别，需要同时维护的信息量翻倍

- 级别相差太远时，小级别的细节对大级别没有意义
（日线和 1 分钟之间隔着好几层，1 分钟的一个买点对日线毫无影响）

- 数据长度限制：要在日线上看到高级别结构，需要很多年的数据

常见的组合是「日线 + 30 分钟」或「30 分钟 + 5 分钟」。

走势多义性在这里落地

阶段 1 提过走势多义性——同一段走势有多种合法分解。

多级别联立恰恰是利用多义性，而不是消除它：
你在两个级别上分别做分解，得到两套都成立的描述，
然后用它们互相印证。

如果两套描述冲突，那不是多义性，是有一边算错了。

## 这一课的要点

- 大级别定性质（处在什么结构里），小级别定位置（走到哪一步）

- 流程：大级别完整分析 → 定位当前段 → 只看对应的小级别走势 → 回代

- 最常见错误是级别串台：两个级别看的不是同一段走势

- 小级别的买卖点，级别就是小的，不能外推到大级别

- 两到三个相邻级别足够，更多只会增加噪音

## 本课术语

- [多级别联立](https://chanlunzhan.com/glossary/duojibielianli)

- [次级别](https://chanlunzhan.com/glossary/cijibie)

- [级别](https://chanlunzhan.com/glossary/jibie)

- [走势多义性](https://chanlunzhan.com/glossary/zoushiduoyixing)

## 对应原文

[第 35 课教你炒股票35：给基础差的同学补补课](https://chanlunzhan.com/108/35)[第 43 课教你炒股票43：有关背驰的补习课](https://chanlunzhan.com/108/43)[第 84 课教你炒股票84：本ID理论一些必须注意的问题](https://chanlunzhan.com/108/84)

## 下一课

[递归与联立

区间套](https://chanlunzhan.com/learn/recursion/qujiantao)

[← 上一课 · 递归与联立

级别递归的严格表述](https://chanlunzhan.com/learn/recursion/level-recursion)[下一课 · 递归与联立 →

区间套](https://chanlunzhan.com/learn/recursion/qujiantao)
