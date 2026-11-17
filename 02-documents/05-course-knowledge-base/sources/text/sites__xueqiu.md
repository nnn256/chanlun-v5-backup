来源：https://www.structguide.com/sites/xueqiu
抓取：2026-11-06T00:31:11+08:00

# 雪球缠论插件：自动画笔、线段和中枢

想找雪球缠论指标，让图表自动显示笔、线段和中枢？Struct Guide 可以在雪球受支持的单品种网页 K 线上识别并绘制这些结构，使用时无需粘贴公式源码。 它安装到浏览器，图层由插件提供，不是雪球 App 内的指标。

[安装说明](https://www.structguide.com/download/) · [雪球缠论画线教程](https://www.structguide.com/tutorial/xueqiu) · [画笔、线段与中枢效果](https://www.structguide.com/sites/xueqiu#layers)

画线规则公开： 包含处理、分型、笔、线段和中枢怎样计算，见[Struct Guide 画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

## 雪球自动画笔、线段和中枢是什么效果？

Struct Guide 在详情页的原始 K 线上增加分型标记、笔与线段的连接线、中枢区间，保留网页已有的 K 线、均线和成交量。可在插件面板中分别显示或隐藏四类图层，也可选择严格笔或宽松笔。

![雪球网页上的 Struct Guide 结构图层](https://www.structguide.com/assets/images/demos/xueqiu-structure-layers-20261105.avif)
放大查看

雪球网页上的 Struct Guide 结构图层雪球日 K 实际截图：分型、笔、线段和中枢叠加在原始图表上，右侧为 Struct Guide v2.1.2 控制面板，包含结构快照和结构回放入口。截图采用宽松笔、全部分型设置，四个结构图层均开启；结构图层由插件绘制。

雪球网页上的 Struct Guide 结构图层原始尺寸×

从自选列表找到品种后，需要进入详情页打开 K 线，插件才有对应图表可处理。操作位置见[雪球缠论画线教程的K线入口](https://www.structguide.com/tutorial/xueqiu#open-chart)。

笔和线段用实线表示已确认、虚线表示待确认；中枢没有独立确认状态标签。图层开启后是否出现对象，仍取决于输入是否满足识别条件。

### 雪球的画笔、线段和中枢在哪里添加？

它们在网页上的 Struct Guide 面板中开启，不是在雪球 App 里添加指标。打开“笔”可显示笔连接线，打开“线段”可同时查看线段；“中枢”独立控制矩形显示。需要只看中枢时，隐藏其他结构图层即可，内部计算仍会保留必要的笔和线段结果。

先确认已打开单品种详情页的 K 线，再按[雪球缠论画线教程的图层设置](https://www.structguide.com/tutorial/xueqiu#settings)操作。矩形上下沿的计算方式另见[中枢画线公式图解](https://www.structguide.com/concept/central-zone#definition)。

## 找雪球缠论指标，先确认是网页还是 App

| 你打开的位置 | Struct Guide 的使用范围 |
| --- | --- |
| A股、港股、美股单品种详情页的 K 线 | 在受支持浏览器和周期内绘制 |
| 雪球信息流、自选列表、行情排行 | 不作为结构识别输入 |
| 雪球手机 App | 不能安装浏览器扩展 |
| 安卓 Edge 内的雪球网页 | 按同样的页面和周期要求核对 |

从列表进入详情页，再打开 K 线。安装插件不会在信息流或自选列表中批量生成结构结果，也不会替你选择品种。

## 支持市场、周期和浏览器

| 核对项 | 支持范围 |
| --- | --- |
| 市场 | A股、港股、美股 |
| 周期 | 1分、5分、15分、30分、60分、120分、日线、周线、月线、季线、年线 |
| 页面 | 单品种详情页的 K 线视图；信息流、自选列表和行情排行页不在识别范围内。 |

网页上出现某个周期按钮，并不代表 Struct Guide 已适配该周期；请按本页列出的市场、页面与周期范围核对。

支持桌面版 Chrome、Edge、360 浏览器，以及安卓手机上的 Edge。其他手机浏览器、原生行情 App 和桌面客户端不在插件运行范围内。

## 自动画线怎么打开和设置？

- 从[安装说明](https://www.structguide.com/download/)添加 Struct Guide，在扩展管理页确认已启用。

- 打开[雪球网页](https://xueqiu.com/)，进入上述范围内的独立 K 线图，等待数据加载。

- 在 Struct Guide 面板中分别开启分型、笔、线段和中枢；不需要点击浏览器工具栏图标触发绘图。

- 需要更换笔模式时，在选项中选择严格笔或宽松笔，等待重新计算。

更换输入或参数后，等待重新计算，再核对显示结果。参数细则见[Struct Guide 画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

安装后未显示时，见雪球教程中的[安装后不显示，怎么排查？](https://www.structguide.com/tutorial/xueqiu#troubleshooting)。

## 常见问题

### 雪球里的缠论图层是网站自带的吗？

本页介绍的图层由 Struct Guide 浏览器扩展绘制，不代表雪球原生提供同样的功能。插件与雪球账户权限是不同事项。

### A股、港股和美股都能自动画线吗？

在受支持的单品种网页 K 线与周期中可以使用。具体能加载哪些数据，仍取决于雪球页面；插件不提供额外行情。

### 切换品种后需要重新安装或点击插件吗？

不需要重新安装。保持扩展启用，等待新图表加载后重新计算；切换期间的旧图层不能作为新页面结果。

### 雪球 BK 板块代码在哪里查？

可用[雪球板块代码列表](https://www.structguide.com/sites/xueqiu/boards)按名称或代码定位页面。该列表是代码目录，不代表每个板块图表都经过 Struct Guide 适配；图层支持仍以本页范围为准。

### 网页和手机 App 的画线能同步吗？

Struct Guide 不读取雪球 App 的图表或设置，也不将网页图层同步进 App。需要复查网页结果时，可记录数据范围和工具参数。

## 数据范围与使用边界

Struct Guide 只处理当前网页已经加载并展示的 K 线，不提供行情数据。待确认笔或线段可能随输入延伸或调整，端点所在时间不等于取得确认依据的时间；详见[笔的确认与更新规则](https://www.structguide.com/concept/stroke#confirmation)。

雪球仅为兼容性说明，与本产品无隶属或合作关系。

[支持网站与周期](https://www.structguide.com/sites/) · [缠论自动画线软件怎么选](https://www.structguide.com/faq/chanlun-indicator) · [安装说明](https://www.structguide.com/download/)

Struct Guide 用于结构识别、学习与复盘，不提供投资建议，不预测行情，也不承诺任何投资收益。
