# V4.3 工作台改版记录

Mode: redesign-preserve

Preserve: 浅色蓝灰配色、A股红涨绿跌、现有主导航、股票/周期/API字段、数据来源和失效/候选状态语义。

Improve: 桌面端使用股票列表、K线主图、信号台账三栏；紧凑指标栏；全部真实周期、全部实际结构级别及买/卖/全部筛选；指数卡片可打开原始指数K线。

Remove: 促销式大标题和占位的L3-L8选择项；未实现级别不显示为有效算法结果。

Protected contracts: HTTP route、任务/持久化字段、K线原始数据、结构确认时点、跨级别不得混同、行业源不可用时不造数、execution_allowed=false。

Design Read: 面向日常A股结构研究的桌面行情终端；现有浅蓝灰研究工作台作为品牌基线。Variance 4, motion 2, density 9, asset dependence 1, fidelity 9。

Layout: 约220px股票清单 + 自适应主K线 + 约270px信号台账；窄屏依次折叠为股票、图表、台账。指数页保留2x3/3x2可点卡片，并用图表对话框查看指数尾部K线。

Rollback: 回退本文件记录的 `workbench/web` 文件即可恢复4.2.2的浅色工作台；市场缓存、数据库和任务结果不迁移、不删除。
