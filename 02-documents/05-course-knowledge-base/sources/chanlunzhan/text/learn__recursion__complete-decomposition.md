来源：https://chanlunzhan.com/learn/recursion/complete-decomposition
采集时间：2026-11-08T02:32:40+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [课程](https://chanlunzhan.com/learn)

- [递归与联立](https://chanlunzhan.com/learn/recursion)

- 走势分解的完全分类

[阶段 7·递归与联立](https://chanlunzhan.com/learn/recursion)·第 4 / 4 节·约 15 分钟

# 走势分解的完全分类

对一张陌生日线图完成自上而下的完整分解，并写出结构说明。

最后一课。把前面所有东西合成一个可执行的流程。

## 完全分类说的是什么

任何一段走势，都可以被唯一地分解为[盘整](https://chanlunzhan.com/glossary/panzheng)和[趋势](https://chanlunzhan.com/glossary/qushi)的有限序列。

三个词都要注意：

- 唯一：在给定[级别](https://chanlunzhan.com/glossary/jibie)下唯一。换级别会得到不同的分解，
这是[多义性](https://chanlunzhan.com/glossary/zoushiduoyixing)，不是不唯一

- 有限：分解的段数是有限的，不会无限细分下去

- 序列：段与段首尾相接，不重叠、不留空

这个定理是缠论的终点，也是前面所有内容的目的。

## 完整分解流程

拿到一张图，按这个顺序做：

### 第一步：确定级别

选一个[周期](https://chanlunzhan.com/glossary/zhouqi)作为本级别。日线是最常用的起点。

同时确认数据长度够不够：至少要能看到两三个[中枢](https://chanlunzhan.com/glossary/zhongshu)，
否则谈不上分类。日线通常需要一到两年的数据。

### 第二步：自底向上搭结构

- 包含处理——合并所有[包含关系](https://chanlunzhan.com/glossary/baohan)，注意连续包含要循环处理

- 分型——在处理后的序列上标出所有顶[底分型](https://chanlunzhan.com/glossary/fenxing)

- [笔](https://chanlunzhan.com/glossary/bi)——连接分型，注意[同性分型](https://chanlunzhan.com/glossary/tongxingfenxing)取极值，注意口径（严格/宽松）

- [线段](https://chanlunzhan.com/glossary/xianduan)——[特征序列](https://chanlunzhan.com/glossary/tezhengxulie)、两种情况、破坏与确认、取消与回收

- 中枢——三段重叠，算出 [ZG](https://chanlunzhan.com/glossary/zg-zd)/ZD/[GG](https://chanlunzhan.com/glossary/gg-dd)/DD

到这里，图上的结构骨架就有了。

### 第三步：分类

- 数中枢，检查排列

- 切分：一个中枢的范围划为一个盘整段，
两个及以上依次同向的中枢及其连接段划为一个趋势段

- 标注每一段的类型

### 第四步：动力学

- 对每一个趋势段，找出[进入段](https://chanlunzhan.com/glossary/jinruduan)和离开段，比较 [MACD](https://chanlunzhan.com/glossary/macd) 面积

- 标出背驰的位置

- 由背驰导出一买一卖，再找二买二卖、三买三卖

### 第五步：联立次级别

- 对当前未完成的那一段，切到次级别做完整分析

- 判断次级别是否走完，回代到本级别

### 第六步：写结构说明

把结论写成文字。这一步不能省——能写出来才算真的会。

## 结构说明的模板

一份完整的结构说明应该包含：

```text
级别：日线
数据范围：2024-01-02 至 2025-12-31

分解结果：
  段 1（2024-01 至 2024-05）：盘整，中枢区间 [42.10, 48.30]
  段 2（2024-05 至 2024-11）：上涨趋势，两个中枢
      中枢 A [48.50, 53.20]，中枢 B [58.90, 64.10]
      离开段力度 < 进入段力度，构成趋势背驰
      一卖位于 2024-11 的高点附近
  段 3（2024-11 至今）：未完成
      当前处于新中枢的形成过程中，已有两段重叠
      次级别（30 分钟）看，最近一段下跌尚未走完

未确认部分：段 3 的中枢是否成立，取决于第三段是否与前两段重叠
```

注意最后一项：明确标出哪些是未确认的。
一份不区分确认与未确认的结构说明是不合格的。

## 在图上完整走一遍

图表加载中…

分型

显示分型笔线段笔中枢段中枢买卖点走势类型

笔的口径严格笔宽松笔顶底之间至少隔一根独立 K 线（62 / 77 课）

合成数据，619 根，数据截至 2026-05-15。仅用于结构演示，非实时行情。

这张图打开了所有图层的开关。按上面的流程，
从只显示「分型」开始，一层一层往上加：

分型 → 笔 → 线段 → 段中枢 → 走势类型 → 买卖点

每加一层，问自己「这一层是怎么从上一层推出来的」。
如果某一层答不上来，回到对应的阶段重看。

顺便切一下笔的口径，看看严格笔和宽松笔下最终的走势分类
会不会不同——多数情况下不会，这说明结构分类对底层口径
有一定的稳健性。

## 通关标准

阶段 7 的通关标准是：拿到一张陌生的完整走势图，
能自上而下做完整分解并写出结构说明。

去[拆图闯关](https://chanlunzhan.com/practice/decompose)做一次完整的。
那里会给你一张没见过的图，逐层要求你标注：
先分型、再笔、再中枢，每层单独判分。

## 学完之后

如果你走到了这里，你现在具备的能力是：

能把任意一段走势，用缠论的语言精确地描述出来。

这是一种描述能力，不是预测能力。你知道当前处在什么结构里、
有哪几种可能的演化、每种演化的确认条件是什么。
你不知道明天涨还是跌——没有人知道，
缠论从一开始也没打算回答这个问题。

关于「精通」

课程标题写的是「从入门到精通」，但要说清楚：
这里的精通指的是对缠论这套描述体系的精通。

它不等于能在市场里赚钱。技术分析能力和交易结果之间隔着
风险管理、资金管理、心理控制、以及大量运气——
本站一样都不涉及。

学完这八阶，你掌握的是一门语言，不是一台印钞机。

## 接下来可以做什么

- 去[参数实验室](https://chanlunzhan.com/practice/lab)，
在真实个股上对比不同口径的差异，理解口径分歧的实际影响

- 去[读原文](https://chanlunzhan.com/108)。学完体系之后再读，
会看到完全不同的东西——第一遍读时那些莫名其妙的句子，
现在每一个名词你都知道确切含义

- 重读[第 62 课《分型、笔与线段》](https://chanlunzhan.com/108/62)。这是原文里定义分型的那一课，
也是最适合作为「第二遍起点」的一课

## 这一课的要点

- 完全分类：任何走势可唯一分解为盘整与趋势的有限序列（给定级别下唯一）

- 分解流程：定级别 → 搭结构 → 分类 → 动力学 → 联立次级别 → 写说明

- 结构说明必须明确区分「已确认」和「未确认」的部分

- 能写出结构说明才算真的会，看懂不算

- 精通的是描述体系，不是预测能力——这两件事没有必然联系

## 本课术语

- [走势分解](https://chanlunzhan.com/glossary/zoushifenjie)

- [分解定理](https://chanlunzhan.com/glossary/fenjieddingli)

- [走势多义性](https://chanlunzhan.com/glossary/zoushiduoyixing)

- [走势终完美](https://chanlunzhan.com/glossary/zoushizhongwanmei)

- [连接点](https://chanlunzhan.com/glossary/lianjiedian)

## 对应原文

[第 84 课教你炒股票84：本ID理论一些必须注意的问题](https://chanlunzhan.com/108/84)[第 100 课教你炒股票100：中医、兵法、诗歌、操作3](https://chanlunzhan.com/108/100)[第 108 课教你炒股票108：何谓底部？从月线看中期走势演化](https://chanlunzhan.com/108/108)

[← 上一课 · 递归与联立

区间套](https://chanlunzhan.com/learn/recursion/qujiantao)
