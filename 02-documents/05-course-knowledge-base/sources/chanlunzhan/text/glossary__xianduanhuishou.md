来源：https://chanlunzhan.com/glossary/xianduanhuishou
采集时间：2026-11-08T02:32:50+08:00
资料层：本站课程/词典/说明
归档范围：静态正文与链接；交互图表、测验状态与浏览器学习进度未离线复现。

- [首页](https://chanlunzhan.com/)

- [词典](https://chanlunzhan.com/glossary)

- 线段回收

# 线段回收

又称 线段取消

新线段尚未确立自身分界就反向击穿起点，原先的分界撤销，前后合为一段。

假设在某点分出了新[线段](https://chanlunzhan.com/glossary/xianduan)，但这条新线段还没有形成自己的分界点就反向破掉了起点（比如向下的新线段跌破了原向上[笔](https://chanlunzhan.com/glossary/bi)的低点），说明当初的分界假设不成立。此时要撤销这个分界，让原线段继续延续，从原起点重新寻找更晚的分界。

这是第 78 课的处理。算法实现上需要回溯，是线段划分里最容易写错的部分。

系统学习

这个概念属于 [阶段 3·线段](https://chanlunzhan.com/learn/xianduan)。绝大多数自学者卡住的地方，所以单独成阶、节奏最慢。特征序列、两种情况、破坏与确认、取消与回收。

## 原文出处

[第 78 课教你炒股票78：继续说线段的划分](https://chanlunzhan.com/108/78)[第 81 课教你炒股票81：图例、更正及分型、走势类型的哲学本质](https://chanlunzhan.com/108/81)

## 相关术语

- [线段](https://chanlunzhan.com/glossary/xianduan)

- [第二种情况](https://chanlunzhan.com/glossary/dierzhongqingkuang)
