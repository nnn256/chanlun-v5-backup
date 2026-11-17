来源：https://www.structguide.com/tutorial/tradingview
抓取：2026-11-06T00:31:12+08:00

# TradingView 缠论插件怎么安装：Full Chart、画线设置与不显示排查

Struct Guide 安装到浏览器后，会在 TradingView 受支持的网页 K 线上自动绘制结构。 本教程说明从打开正确页面到设置图层的操作顺序。如果尚未确认使用环境，可先看[TradingView 缠论自动画线支持说明](https://www.structguide.com/sites/tradingview)。

## 1. 插件在哪里下载、怎样启用？

- 打开[安装说明](https://www.structguide.com/download/)，进入对应浏览器的扩展商店。

- 添加 Struct Guide，在浏览器扩展管理页确认已启用。

- 如果图表在安装前已打开，刷新网页后等待 K 线加载。

支持桌面版 Chrome、Edge、360 浏览器及安卓手机上的 Edge。原生行情 App、桌面行情客户端及其他手机浏览器不在插件运行范围内。安卓手机也需要在 Edge 内打开网页。

## 2. TradingView 完整图表怎么打开？

在 TradingView 网页选择你要查看的品种，进入 Full Chart 完整图表，使用单品种图表布局并等待 K 线加载。列表中的预览图和多图表分屏不在稳定适配范围内。

![TradingView 预览图右上方的 Full chart 入口](https://www.structguide.com/assets/images/demos/tradingview-full-chart-entry.webp)
放大查看

TradingView 预览图右上方的 Full chart 入口首页动图截帧的页面局部。录制时可从预览图右上方的“Full chart”按钮进入完整图表；网页布局以实际界面为准。

TradingView 预览图右上方的 Full chart 入口原始尺寸×

插件处理的是这个网页已加载的数据。市场、周期和可见历史范围仍受 TradingView 数据来源及账户权限约束；安装扩展不会增加数据访问权限。兼容细节见[TradingView 兼容范围](https://www.structguide.com/sites/tradingview#supported-periods)。

## 3. 分型、笔、线段和中枢怎么设置？

在网页上的 Struct Guide 面板中找到“结构绘制”区域，按下图的位置开关图层。

![Struct Guide v2.1.2：选项与结构绘制](https://www.structguide.com/assets/images/demos/struct-guide-panel-options-20261105.avif)
放大查看

Struct Guide v2.1.2：选项与结构绘制实际控制面板截图。“选项”展开后可设置分型显示、笔模式和界面语言；“结构绘制”区域可分别开关分型、笔、线段和中枢。图中选择全部分型、宽松笔、简体，四个图层均开启。

Struct Guide v2.1.2：选项与结构绘制原始尺寸×

| 想完成的操作 | 面板中的操作 | 操作后的显示 |
| --- | --- | --- |
| 显示顶底分型标记 | 开启分型图层 | 显示工具已识别的顶底分型标记 |
| 显示笔或线段连接线 | 开启对应图层 | 显示工具已识别的对应连接线 |
| 更换笔模式 | 选择严格笔或宽松笔，等待重新计算 | 按所选模式重新计算，相关结构可能更新 |
| 只查看中枢区间 | 保留中枢图层，隐藏其他结构图层 | 显示已识别的中枢区间，原有 K 线仍保留 |
| 暂时隐藏画线 | 关闭对应图层，需要时再开启 | 隐藏对应图层；重新开启后显示已识别的对应对象 |

原始 K 线、均线和成交量保留。笔和线段用实线表示已确认、虚线表示待确认；中枢没有独立确认状态标签。开关控制显示，不表示每一段数据都会生成相应对象。参数细则统一见[Struct Guide 画线规则与参数总览](https://www.structguide.com/faq/drawing-rules)。

## 4. 切换品种、周期后如何更新？

保持扩展启用，等待新图表加载，插件按新的输入重新计算。品种、周期、复权方式、历史数据补载或笔模式变化都可能影响结果。切换输入后，新页面的结构以重新计算后的图层为准。

待确认端点可能随新 K 线延伸或调整；端点所在时间与工具取得确认依据的时间可能不同。详见[笔的确认与更新规则](https://www.structguide.com/concept/stroke#confirmation)。

## 5. 安装后不显示，怎么排查？

| 现象 | 核对项 | 处理步骤 |
| --- | --- | --- |
| 指标列表找不到 Struct Guide | 是否把浏览器扩展当作 Pine 指标 | 到浏览器扩展管理页核对安装，不向 Pine 编辑器粘贴扩展文件 |
| 列表预览或分屏没有结构 | 是否为单品种 Full Chart | 打开单图完整图表后重新核对 |
| 已在完整图表，但没有面板 | 扩展是否启用，K 线是否加载 | 启用扩展；刷新网页并等待加载 |
| 更换报价源后端点不同 | 报价源、周期、时段与历史范围 | 固定输入与参数，再比较显示 |
| 面板有显示，但缺少某类结构 | 对应图层与输入数据 | 开启相应图层；识别条件未满足时不会强制画出对象 |

仍有异常时，可暂时停用可能拦截页面脚本的其他扩展，刷新重试。反馈时记录浏览器与版本、插件版本、页面地址、品种、周期、复权方式、笔模式和重现步骤，通过 [structguide@outlook.com](mailto:structguide@outlook.com) 联系。如附截图，发送前请留意截图中是否包含个人账户信息。

## 常见操作问题

### 需要在 Pine 编辑器中运行什么代码？

不需要。Struct Guide 不提供 Pine 源码，设置入口在网页上的扩展控制面板。脚本安装方法与浏览器扩展不同，不能混用。

### 可以同时打开多个 TradingView 标签页吗？

可以分别打开受支持的单品种完整图表。多个浏览器标签页与同一页面内的多图表分屏是不同环境；后者不在稳定适配范围内。

### 桌面版 TradingView 软件能装扩展吗？

Struct Guide 的这条适配路径是受支持浏览器中的 tradingview.com 网页，不是 TradingView 桌面软件或手机 App。手机使用路径见上文[安卓 Edge 安装与使用说明](https://www.structguide.com/tutorial/tradingview#install)。

## 数据与使用范围

插件只处理当前网页已经加载并展示的 K 线，不提供额外行情数据；网站账户权限仍由网站管理。TradingView 仅为兼容性说明，与本产品无隶属或合作关系。

[TradingView 缠论自动画线支持说明](https://www.structguide.com/sites/tradingview) · [支持网站与周期](https://www.structguide.com/sites/) · [安装说明](https://www.structguide.com/download/)

Struct Guide 用于结构识别、学习与复盘，不提供投资建议，不预测行情，也不承诺任何投资收益。
