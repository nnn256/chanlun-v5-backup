来源：https://www.structguide.com/sites/tradingview
抓取：2026-11-06T00:31:11+08:00

# TradingView 缠论插件：自动画笔、线段和中枢

TradingView 怎么自动画缠论的笔、线段和中枢？除了使用具体的 Pine 指标，也可以安装 Struct Guide 浏览器插件，在受支持的网页完整图表上显示这些结构。

Struct Guide 在 TradingView 网页的单品种 Full Chart 完整图表上自动识别并绘制结构，不需要编写或导入 Pine Script。 图层在网页上的 Struct Guide 面板中设置。它是浏览器插件，不提供可导入 Pine 编辑器的源码；需要编辑 Pine 指标时，应另行核对对应脚本。

[安装说明](https://www.structguide.com/download/) · [画笔、线段与中枢效果](https://www.structguide.com/sites/tradingview#layers) · [TradingView 缠论画线教程](https://www.structguide.com/tutorial/tradingview)

画线规则公开： 包含处理、分型、笔、线段和中枢怎样计算，见[Struct Guide 画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

## TradingView 自动画笔、线段和中枢是什么效果？

Struct Guide 在原图上叠加分型标记、笔与线段的连接线、中枢区间。四类图层可以分别开关，例如只显示笔和中枢；网页原有的 K 线、均线与成交量保留。笔模式可选择严格笔或宽松笔。

笔和线段用实线与虚线区分已确认和待确认；中枢没有独立确认状态标签。这里展示的是工具按网页数据计算的对象；开启图层不会强制生成尚不满足识别条件的结构。

![TradingView 完整图表上的 Struct Guide 结构图层](https://www.structguide.com/assets/images/demos/tradingview-structure-layers-20261105.avif)
放大查看

TradingView 完整图表上的 Struct Guide 结构图层标普 500 指数（SPX）日 K 实际截图：分型、笔、线段和中枢叠加在 TradingView 完整图表上，右侧为 Struct Guide v2.1.2 控制面板，包含结构快照和结构回放入口。截图采用宽松笔、全部分型设置，四个结构图层均开启；结构图层由插件绘制。

TradingView 完整图表上的 Struct Guide 结构图层原始尺寸×

### 为什么指标列表里找不到，应该在哪里打开图层？

Struct Guide 的四类图层在网页上的插件面板里开启，不是在 TradingView 的 Indicators 列表里加载。进入单品种 Full Chart 后，可分别打开“笔”“线段”和“中枢”；只想看中枢时隐藏其余结构图层，原始 K 线继续保留。

具体入口见[TradingView 缠论画线教程的完整图表设置](https://www.structguide.com/tutorial/tradingview#open-chart)与[图层设置](https://www.structguide.com/tutorial/tradingview#settings)。如果需要核对矩形的位置，可查看[中枢画线公式图解](https://www.structguide.com/concept/central-zone#definition)；无需为使用插件另找一份 Pine 中枢源码。

## TradingView 缠论指标、Pine 脚本和插件有什么区别？

| 核对项 | Pine 指标方案 | Struct Guide |
| --- | --- | --- |
| 安装位置 | TradingView 的脚本与指标环境 | 浏览器扩展管理环境 |
| 源码 | 是否公开、能否修改取决于具体脚本 | 不提供可导入 Pine 编辑器的源码 |
| 图层内容 | 由具体脚本实现决定 | 分型、笔、线段、中枢 |
| 设置入口 | 相应指标的设置界面 | 网页上的 Struct Guide 控制面板 |
| 使用前核对 | 脚本说明、图表与账户权限 | Full Chart 页面、已加载数据及浏览器适配 |

脚本环境的说明可查阅 [TradingView 官方 Pine Script 文档](https://www.tradingview.com/pine-script-docs/welcome/)。

两种方式的运行环境不同，不能把浏览器扩展文件粘贴到 Pine 编辑器运行。插件不会增加 TradingView 的数据权限或历史数据长度。

## 支持市场、周期和浏览器

| 核对项 | 支持范围 |
| --- | --- |
| 市场 | 全球市场、外汇 |
| 周期 | 取决于当前图表可展示的数据 |
| 页面 | 支持 tradingview.com 的 Full Chart 完整图表页。 单品种 Full Chart 完整图表；列表预览、筛选页和多图表分屏不在稳定适配范围内。 |

网页上出现某个周期按钮，并不代表 Struct Guide 在所有页面布局中均已适配；请使用单品种 Full Chart 完整图表，并以当前图表实际可展示的数据为前提。

支持桌面版 Chrome、Edge、360 浏览器，以及安卓手机上的 Edge。其他手机浏览器、原生行情 App 和桌面客户端不在插件运行范围内。

## 自动画线怎么打开和设置？

- 从[安装说明](https://www.structguide.com/download/)添加 Struct Guide，在扩展管理页确认已启用。

- 打开[TradingView网页](https://www.tradingview.com/)，进入上述范围内的独立 K 线图，等待数据加载。

- 在 Struct Guide 面板中分别开启分型、笔、线段和中枢；不需要点击浏览器工具栏图标触发绘图。

- 需要更换笔模式时，在选项中选择严格笔或宽松笔，等待重新计算。

更换输入或参数后，等待重新计算，再核对显示结果。参数细则见[Struct Guide 画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

显示问题见[TradingView 缠论画线教程的“安装后不显示”一节](https://www.structguide.com/tutorial/tradingview#troubleshooting)。

## 常见问题

### 这些缠论结构是 TradingView 自带的吗？

本页介绍的结构由 Struct Guide 浏览器插件绘制，不能据此理解为 TradingView 自身提供了相同功能。TradingView 的原生功能、Pine 指标与插件图层属于不同来源。

### 为什么多图表分屏没有显示结构？

Struct Guide 以单品种 Full Chart 完整图表为适配范围。多图表分屏、列表预览和筛选页不在稳定适配范围内；请打开单图后再核对显示。

### 所有市场和周期都能用吗？

支持范围覆盖网页可展示的全球市场与外汇图表，但实际可用周期、报价来源及历史长度取决于图表数据和账户权限。TradingView 账户类型会影响日内周期图表可加载的历史数据长度，插件只处理已加载的部分，不补充其他行情源。具体限制见 [TradingView 历史数据说明](https://www.tradingview.com/support/solutions/43000480679-historical-intraday-data-bars-and-limits-explained/)。

### TradingView 手机 App 能装这个缠论插件吗？

不能在原生 App 内安装。手机使用路径是安卓 Edge 扩展加受支持的网页版完整图表，其他手机环境不在上述兼容范围。

### 切换报价来源后，画线为什么不同？

同名品种也可能使用不同报价源。先核对来源、周期、图表时段、复权方式及历史范围，再比较工具参数。不同输入不保证产生相同端点。

### 需要额外下载 Pine 缠论源码吗？

使用 Struct Guide 不需要。若必须在 Pine 编辑器中查看或修改程序，本插件不提供这种源码文件。

## 数据范围与使用边界

Struct Guide 只处理当前网页已经加载并展示的 K 线，不提供行情数据。待确认笔或线段可能随输入延伸或调整，端点所在时间不等于取得确认依据的时间；详见[笔的确认与更新规则](https://www.structguide.com/concept/stroke#confirmation)。

TradingView 仅为兼容性说明，与本产品无隶属或合作关系。

[支持网站与周期](https://www.structguide.com/sites/) · [缠论自动画线软件怎么选](https://www.structguide.com/faq/chanlun-indicator) · [安装说明](https://www.structguide.com/download/)

Struct Guide 用于结构识别、学习与复盘，不提供投资建议，不预测行情，也不承诺任何投资收益。
