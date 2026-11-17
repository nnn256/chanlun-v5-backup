来源：https://chanlunzhan.com/learn/worldview/levels-and-recursion
采集时间：2026-11-08T02:32:28+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [缠论的世界观](https://chanlunzhan.com/learn/worldview)

- 级别与递归的直觉

[阶段 1·缠论的世界观](https://chanlunzhan.com/learn/worldview)·第 3 / 3 节·约 10 分钟

# 级别与递归的直觉

建立级别递归的直觉，理解为什么缠论的定义只写一遍就够用。

这是阶段 1 的最后一课，讲缠论最漂亮的一个性质。

## 一个熟悉的类比

一篇文章由段落组成，段落由句子组成，句子由词组成。

现在换个角度看：一个段落，对文章来说是「一个组成部分」，
但你单独把它拿出来，它自己也有开头、发展、结尾——它自己就是一篇小文章。

缠论的[级别](https://chanlunzhan.com/glossary/jibie)结构是一样的。

## 自底向上：小的构成大的

从最小的单位开始往上搭：

- [K 线](https://chanlunzhan.com/glossary/kline)是原材料

- 三根 K 线构成一个[分型](https://chanlunzhan.com/glossary/fenxing)

- 两个相邻的反向分型构成一[笔](https://chanlunzhan.com/glossary/bi)

- 若干笔构成一[线段](https://chanlunzhan.com/glossary/xianduan)

- 三段有重叠区间的线段构成一个[中枢](https://chanlunzhan.com/glossary/zhongshu)

- 中枢加上进出它的段，构成一个[走势类型](https://chanlunzhan.com/glossary/zoushileixing)

到这里搭出了一个完整的走势类型。关键的一步来了：

这个走势类型，可以当作更高一个级别的「一段」，去参与更高级别的中枢构造。

这就是[递归](https://chanlunzhan.com/glossary/diguijibie)。

## 自顶向下：大的展开是小的

反过来看同样成立。

拿一个日线级别的走势类型，它由几个中枢和连接段构成。
把其中任意一段单独拿出来放到 30 分钟图上看，它不再是「一段」——
它自己就是一个完整的 30 分钟级别走势类型，有自己的中枢、自己的分段。

所以级别是相对的

「一段」和「一个完整走势」不是两种东西，是同一个东西在两个观察尺度下的名字。

这也解释了上一课提到的[走势多义性](https://chanlunzhan.com/glossary/zoushiduoyixing)：你选择在哪个尺度上看，
决定了哪些东西被叫做「段」、哪些被叫做「走势类型」。

## 递归带来了什么

最大的好处是定义只需要写一遍。

均线体系里，5 日均线和 60 日均线的用法要分别总结经验，
日线的金叉和 30 分钟的金叉含义不同，得分别记。

缠论不需要。分型的定义、笔的定义、中枢的定义，在任何级别上完全一样。
你学会在日线上找中枢，就自动学会了在 5 分钟上找中枢——
因为那是同一套定义作用在不同的输入上。

下面这张图可以直观感受一下。它同时画出了[笔中枢](https://chanlunzhan.com/glossary/biZhongshu)（小级别）和段中枢（大级别）：

图表加载中…

笔笔中枢

显示笔线段笔中枢段中枢走势类型

合成数据，619 根，数据截至 2026-05-15。仅用于结构演示，非实时行情。

先只看「笔」和「笔中枢」——你会看到很多小的框。
然后关掉这两层，打开「线段」和「段中枢」——框变少了、变大了，但形态是同类的。

同一套规则，作用在不同层级的输入上，得到同构的结果。 这就是递归的全部含义。

## 一个必须警惕的陷阱

递归听起来很美，但实操上有个坑：级别不是无限清晰的。

理论上可以一直往上递归，实际上受两个限制：

- 数据长度。要在日线上看到一个高级别中枢，可能需要好几年的数据。

- 判定的模糊性。级别升级的判定（几个中枢算升级成一个更大的中枢）
在原文里的表述留有解释空间，不同实现结果不同。

所以实践中大家用[周期](https://chanlunzhan.com/glossary/zhouqi)来近似级别（1 分钟 / 5 分钟 / 30 分钟 / 日线 / 周线），
这个近似在多数时候够用，在级别边界处会失真。第七阶会专门讲这件事。

不要跳级

知道了递归很诱人，但请不要现在就去做多级别分析。

递归的前提是你能在单个级别上准确画出分型、笔、线段、中枢。
这些还不熟就去做[多级别联立](https://chanlunzhan.com/glossary/duojibielianli)，结果是在三个周期上同时画错。

先把阶段 2 到 4 走完。多级别在阶段 7。

## 这一课的要点

- 自底向上：K 线 → 分型 → 笔 → 线段 → 中枢 → 走势类型 → 更高级别的一段

- 自顶向下：任何一段展开都是[次级别](https://chanlunzhan.com/glossary/cijibie)的完整走势类型

- 「段」和「走势类型」是同一个东西在不同尺度下的名字，级别是相对的

- 递归让定义只需写一遍，在所有级别上通用

- 实操中级别受数据长度和判定模糊性限制，用周期近似，边界处会失真

## 本课术语

- [级别](https://chanlunzhan.com/glossary/jibie)

- [次级别](https://chanlunzhan.com/glossary/cijibie)

- [级别递归](https://chanlunzhan.com/glossary/diguijibie)

- [连接点](https://chanlunzhan.com/glossary/lianjiedian)

## 对应原文

[第 29 课教你炒股票29：转折的力度与级别](https://chanlunzhan.com/108/29)[第 35 课教你炒股票35：给基础差的同学补补课](https://chanlunzhan.com/108/35)[第 43 课教你炒股票43：有关背驰的补习课](https://chanlunzhan.com/108/43)

## 下一课

[基本构件

包含处理](https://chanlunzhan.com/learn/fenxing-bi/baohan)

[← 上一课 · 缠论的世界观

分类而非预测](https://chanlunzhan.com/learn/worldview/classify-not-predict)[下一课 · 基本构件 →

包含处理](https://chanlunzhan.com/learn/fenxing-bi/baohan)
