来源：https://www.structguide.com/sites/tonghuashun
抓取：2026-11-06T00:31:10+08:00

# 同花顺缠论自动画线插件：画笔、线段和中枢

同花顺可以自动画缠论的笔、线段和中枢吗？在受支持的同花顺网页 K 线上，安装 Struct Guide 浏览器插件后，就能自动显示这些结构，无需导入指标公式。 下方有实际效果和图层设置说明。

插件运行在受支持的同花顺网页中，不在同花顺桌面客户端或手机 App 内运行。原图仍是同花顺网页，结构图层由插件绘制。

[下载 Struct Guide 浏览器插件](https://www.structguide.com/download/)

[自动画笔与线段](https://www.structguide.com/sites/tonghuashun#stroke-lines) · [只显示中枢](https://www.structguide.com/sites/tonghuashun#central-zone) · [同花顺安装与设置教程](https://www.structguide.com/tutorial/tonghuashun) · [支持的市场与周期](https://www.structguide.com/sites/tonghuashun#supported-periods)

画线规则公开： 包含处理、分型、笔、线段和中枢怎样计算，见[Struct Guide 画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

## 同花顺自动画笔、线段和中枢的实际效果

![同花顺网页上的 Struct Guide 结构图层](https://www.structguide.com/assets/images/demos/tonghuashun-structure-layers-20261105.avif)
放大查看

同花顺网页上的 Struct Guide 结构图层上证指数日 K 实际截图：分型、笔、线段和中枢叠加在同花顺原始图表上，右侧为 Struct Guide v2.1.2 控制面板，包含结构快照和结构回放入口。截图采用宽松笔、全部分型设置，四个结构图层均开启；结构图层由插件绘制。

同花顺网页上的 Struct Guide 结构图层原始尺寸×

Struct Guide 将结构叠加到原始 K 线图上，保留网页原有的 K 线、均线、成交量和其他图层。控制面板可以分别显示或隐藏以下内容：

| 图层 | Struct Guide 的显示内容 | 可用设置 |
| --- | --- | --- |
| 分型 | 顶分型、底分型标记 | 显示或隐藏分型图层 |
| 笔 | 笔的连接线 | 显示或隐藏；选择严格笔或宽松笔 |
| 线段 | 线段连接线 | 显示或隐藏线段图层 |
| 中枢 | 中枢区间 | 显示或隐藏中枢图层 |

笔和线段以实线表示已确认、虚线表示待确认。中枢没有独立确认状态标签。这里说明的是工具输出与显示方式；具体参数统一查阅[Struct Guide 画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

### 自动画笔、画线段，分别在哪里设置？

在网页上的 Struct Guide 面板里分别开启“笔”和“线段”。只想看笔时可以隐藏线段，想同时看两层则都开启；不是在同花顺客户端的指标列表里添加两份公式。

严格笔、宽松笔从面板“选项”中选择，模式改变会重算笔以及后续结构。具体操作见[同花顺安装与设置教程的图层设置](https://www.structguide.com/tutorial/tonghuashun#settings)；想核对某一笔为什么出现或没有出现，见[笔的连接条件](https://www.structguide.com/concept/stroke#conditions)和[两种笔模式的计数方式](https://www.structguide.com/concept/stroke#modes)。

### 同花顺中枢怎么显示，可以只保留中枢吗？

在 Struct Guide 面板开启“中枢”，并隐藏不需要的分型、笔和线段图层即可。隐藏连接线只改变画面，内部仍使用线段结果计算中枢；开启中枢也不会保证每段 K 线都有矩形。

如果需要核对矩形上下沿，查看[中枢画线公式图解](https://www.structguide.com/concept/central-zone#definition)；三段看起来重叠却没有矩形时，再核对[成员选择条件](https://www.structguide.com/concept/central-zone#members)。

## 同花顺缠论画线工具怎么安装、怎么设置？

- 从[安装说明](https://www.structguide.com/download/)选择对应浏览器的扩展商店，安装并启用 Struct Guide。

- 在浏览器中打开[同花顺网页](https://10jqka.com.cn/)，进入[支持范围](https://www.structguide.com/sites/tonghuashun#supported-periods)内的独立 K 线图。

- 选择受支持的周期，等待 K 线加载；插件会自动绘制，无需点击浏览器工具栏图标触发。

- 在 Struct Guide 控制面板中开关分型、笔、线段和中枢；需要更换笔模式时，选择严格笔或宽松笔，等待重新计算。

详细步骤见[同花顺安装与设置教程](https://www.structguide.com/tutorial/tonghuashun#settings)；如果安装后没有显示，直接查看[按现象排查](https://www.structguide.com/tutorial/tonghuashun#troubleshooting)。

## 支持同花顺哪些市场和 K 线周期？

| 页面类型 | 支持周期 |
| --- | --- |
| A股 | 1分、15分、30分、60分、120分、日线、周线、月线、季线、年线 |
| 港股 | 日线、周线、月线 |
| 概念板块、行业板块、地域板块 | 日线、周线、月线 |
| 指数 | 日线、周线、月线 |

请使用有独立 K 线主图的页面。同花顺首页、自选列表和没有独立 K 线主图的汇总页不在支持范围内。网页上出现某个周期按钮，并不代表 Struct Guide 已适配该周期；例如同花顺 A股的 5分周期未列入上表。

浏览器支持桌面版 Chrome、Edge、360 浏览器及安卓手机上的 Edge。其他手机浏览器、原生行情 App 和桌面行情客户端不在插件运行范围内。其他网站的兼容范围见[支持网站与周期](https://www.structguide.com/sites/)。

## 同花顺缠论指标、公式、源码与自动画线插件有什么区别？

搜索“同花顺缠论指标”时，先区分使用位置：你需要的是客户端里的公式文件，还是网页 K 线上的结构图层。两者的安装入口和运行环境不同，不能互相导入。

| 核对项目 | 客户端指标公式方案 | Struct Guide 网页插件 |
| --- | --- | --- |
| 运行位置 | 取决于公式适用的客户端及版本 | 同花顺受支持的网页 K 线图 |
| 安装内容 | 对应公式文件或源码 | 浏览器扩展 |
| 是否需要导入公式 | 按具体公式的说明操作 | 不需要 |
| 可以显示哪些结构 | 取决于具体公式实现 | 分型、笔、线段、中枢，可分别开关 |
| 使用前要核对什么 | 公式语言、函数与软件版本 | 浏览器、网页类型、市场和周期 |
| 手机使用 | 按相应 App 的实际功能核对 | 安卓手机上的 Edge 浏览器；不在同花顺 App 内运行 |

Struct Guide 不提供可导入同花顺客户端的缠论公式或指标源码。若你的需求是在网页上自动画线，可按本页核对兼容范围；其他软件环境的区别见[缠论自动画线软件怎么选](https://www.structguide.com/faq/chanlun-indicator)。

## 常见问题

### 同花顺网页版可以自动画笔、线段和中枢吗？

在本页列出的受支持图表中，安装并启用 Struct Guide 后可以显示这些结构。它们由浏览器插件绘制，不能据此理解为同花顺自身提供了相同功能。

### 同花顺手机版能使用这个缠论画线工具吗？

Struct Guide 支持安卓手机上的 Edge 浏览器，需要安装扩展并打开同花顺受支持的网页 K 线。它不能安装进同花顺手机 App；iPhone、iPad 及其他手机浏览器不在上述支持范围内。

### 下载插件后，还需要下载同花顺缠论公式或源码吗？

不需要。Struct Guide 使用浏览器扩展方式叠加图层，不要求你在同花顺公式编辑器中粘贴源码。如果目的是获取客户端公式文件，本插件不提供该类文件。

### 为什么切换周期后，画线和原来不同？

周期改变会改变输入 K 线，Struct Guide 会重新计算。品种、复权方式、已加载的历史范围及笔模式变化也可能使结果不同。核对两个图表时，应先固定这些条件，而不是把不同输入下的图形当作同一份结果。

### 为什么最后一笔还会移动？

待确认笔的端点可能随新 K 线延伸或调整。网页补载、修订历史数据或工具参数变化也可能触发重算；端点所在时间与工具取得确认依据的时间可能不同。具体显示机制见[笔的确认与更新规则](https://www.structguide.com/concept/stroke#confirmation)。

### 可以只显示中枢，隐藏其他画线吗？

可以，按上方[只显示中枢的设置](https://www.structguide.com/sites/tonghuashun#central-zone)操作。它只改变图层显示，不修改网页行情数据。

### 同花顺网页和客户端的画线为什么不一致？

Struct Guide 不读取客户端图表，也不将客户端参数或画线同步到网页。应分别核对数据来源、图表时段、复权方式、历史范围及各工具的实现规则；不能仅凭图形不同就认定其中一方有误。

## 安装前核对与使用边界

先确认浏览器和页面，再确认市场、周期与所需图层，最后按[同花顺安装与设置教程](https://www.structguide.com/tutorial/tonghuashun)操作。Struct Guide 只处理当前网页已经加载并展示的 K 线，不提供行情数据；网站自身要求登录才能查看的内容仍受其账户权限约束。

同花顺仅为兼容性说明，与本产品无隶属或合作关系。

Struct Guide 用于结构识别、学习与复盘，不提供投资建议，不预测行情，也不承诺任何投资收益。
