# 缠论结构研究算法

**V4.4.0 本地研究版：** 修复更新运行中TDX服务的 `WinError 5`，新增增量日线底部/突破/顶部/下跌趋势研究、价量成本代理与可用时间受限的独立资金流证据。5,580只本地事件研究已完成，结果与限制见 [V4.4本地研究与验证](V4.4本地研究与验证.md)。本轮没有推送GitHub，代理数据不冒充真实资金或筹码。

**V2历史研究入口：递归与触发链。** 包含完成走势类型递归、中心谓词证书、趋势背驰结构门控、真实周期/证券/复权/OHLCV校验，以及下级反转确认后的细级笔触发器。使用[run_v2.py](run_v2.py)，详见[V2说明与运行命令](递归与触发V2说明.md)。采用原文38课对应的明确同级分解规范；分解完成与反转确认分别记录。早期V2回归为328项；V4.4当前测试数量及结果以本地验证器生成的JSON/命令日志为准。

**V4.3.3 安装锁修复版：** MSI 更新前检测已运行的工作台，给出关闭/重试/取消选项，并通过正常窗口关闭请求释放 EXE；超时仍被占用时提示 Windows 重启替换，不强制结束进程。全市场任务在旧版关闭时进入可恢复暂停流程，已保存结果保留。启动脚本沿用程序内已保存的数据目录。为匹配实测 V4.3.0 安装，MSI 保留同一文件组件 GUID、`Software\ChanlunWorkbenchV4\4.3.0` 键路径和 `LaunchV43.cmd` 文件成员；后续版本必须保留这些组件身份字段，除非显式迁移组件。V4.3.2 的大盘完整缠论图层、V4.3.1 的多级别信号、固定原生引擎和增量行情保持不变。更新说明见[发行说明](V4.3发行说明.md)、[UI改版说明](UI改版说明-v4.3.md)、[V4.2增量架构](V4.2增量行情与市场数据架构.md)和[数据源复核](DATA_SOURCES_REVIEW_20261113.md)。

以下`run.py`和历史批次说明对应原V1研究引擎。V2输出另存`runs/recursive-v2-20261107/`；以前的5578股批次不会被自动改写成V2结果。

2026-11-07历史任务已收尾：[统一结果与核验入口](历史任务完成报告.md)。原批次中的分钟超时和已明确隔离的零成交异常已在独立修复目录补齐；原始结果和来源版本均保留。

已接入指定的TDX接口，可运行沪深京A股全市场日线、日线/30分钟/5分钟联立，以及从每股最早可得日期开始的逐日历史回放。当前任务入口见[全市场三流水线说明](全市场三流水线说明.md)，API设置见[TDX使用说明](TDX全市场使用说明.md)，历史事件和评估口径见[逐日回放说明](逐日历史回放说明.md)。

这是与[缠论知识库](../缠论知识库/README.md)对应的可运行研究实现。它把公开规则分为三层：

1. `documented_base_structure`：方向性包含、严格高低比较分型、严格/宽松笔、特征序列两条线段确认路径、已确认线段的实际覆盖范围中枢。
2. `segment_recursion_proxy`：把已确认线段继续递归组织为更高层结构，用于研究自相似关系。它不冒充已经证明的“次级别走势类型递归”。
3. `signal_proxy` / `multi_timeframe_structure_proxy`：在命名结构上比较MACD力度、生成一二三类候选点、检查多周期区间嵌套。它们需要更低级别数据和人工审计，默认`execution_allowed=false`。

## 安装与运行

Windows MSI 允许选择程序安装目录。首次启动会弹出中文数据目录选择框；选择结果保存在 `%LOCALAPPDATA%\\ChanlunWorkbench\\desktop-settings.json`。选择已有文件的盘符/父目录时，程序会在其中创建专属 `ChanlunWorkbenchData` 子目录，不碰其他文件；若该子目录已存在且不是本程序数据目录，则拒绝覆盖。已有数据目录变更时，程序会在没有运行任务且目录未被旧实例占用的情况下复制数据，保留旧目录作为备份。也可通过 `ChanlunWorkbenchV4.exe --data-dir "E:\\ChanlunData"` 指定或切换数据目录。数据库、行情缓存、任务结果和日志统一写入所选数据目录。

本地CSV算法只需要Python 3.11+，无第三方依赖；构建TDX数据服务另需Go1.23+。工作目录设为本目录：

```powershell
python run.py demo --output-dir .\examples
python run.py analyze .\examples\synthetic_1m.csv --level 1m --output .\examples\analysis.json
python run.py replay .\examples\synthetic_1m.csv --level 1m --output .\examples\replay.json --events .\examples\events.jsonl
python run.py evaluate .\examples\synthetic_1m.csv --events .\examples\events.jsonl --output .\examples\evaluation.json
```

CSV要求`open,high,low,close`，建议提供带时区的`closed_at`列，并可提供`volume,is_closed`。没有`is_closed`时默认输入行已闭合；没有时区时默认`+08:00`并在来源元数据里标记假定。多周期运行必须有明确的收盘时间：

```powershell
python run.py multilevel `
  --input 30m=.\examples\synthetic_30m.csv `
  --input 5m=.\examples\synthetic_5m.csv `
  --input 1m=.\examples\synthetic_1m.csv `
  --trade-level 30m --confirm-level 5m --trigger-level 1m `
  --as-of 2026-01-01T04:00:00Z --output .\examples\multilevel.json
```

## 核心接口

- `chanmodel.model.Config`：固定笔模式、价格精度、递归深度、二买口径和三买边界口径。
- `chanmodel.model.load_csv`：验证OHLC范围、时间单调性、开放K线位置、输入哈希。
- `chanmodel.structure`：包含、来源追踪、分型、笔及拒绝原因。
- `chanmodel.segments`：前三笔正宽度、特征序列无缺口/有缺口第二序列、第一反向笔破坏路径、候选端点选择。
- `chanmodel.centers`：三条已确认线段的实际极值、ZG/ZD、成员、L0/L1返回、停止依据。
- `chanmodel.signals`：MACD辅助力度、同向比较、六类候选点、二买`original_101`与`conservative`。
- `chanmodel.engine.ReplayEngine`：逐根追加、开放K线替换、历史修订、出现/确认/撤回/修订事件。
- `chanmodel.engine.multilevel`：同一截止时间下的trade/confirm/trigger层嵌套审计。
- `chanmodel.evaluate`：只用未来数据给已经出现的事件贴固定窗口结果标签，不模拟真实组合收益。

## 可复核字段

每个快照和事件保留`trade_level`、`confirm_level`、`trigger_level`、`definition_mode`、`structure_completeness`、`approximation_loss`、`basis_at`、`available_at`、`confirmed_at`、`revision`、`source_range`。`basis_at`是结构取得依据的输入位置；`available_at`是该版本被观测到的位置；历史修订只新增事件，不删除旧记录。

分型必须等右侧标准K线到位；笔确认需要合法反向笔；线段确认在特征序列或笔破坏路径获得依据后才发生；中枢只接受已确认线段。最后一根开放K线可替换但不可成为历史中间K线。

## 规则口径

- 包含：完整高低价范围，等边界计入；向上取高高/低高，向下取低高/低低；顺序处理并追踪原始来源。
- 分型：中间高低同时严格高于/低于两侧；等号不通过。
- 笔：严格模式按标准K线间隔，宽松模式按极值来源原始K线间隔；两端分型组不共用标准K线；相邻两笔可共用端点。
- 线段：前三笔共同区间须有正宽度；无缺口等第一特征分型，有缺口等待反向第二特征分型；第一笔破坏不等于立即结束。
- 中枢：三条已确认线段实际覆盖范围计算`ZG=min(H)`、`ZD=max(L)`，要求`ZG>ZD`；触边按返回，未返回才停止旧框延伸。
- 二买：`original_101`保留101课描述的弱回试候选，可低于一买；`conservative`只保留边界未破坏候选。

## 质量门禁

在本目录运行：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q .
```

测试覆盖规则、时间因果、数据输入、递归代理、多周期审计和事后评估，实际执行数量见[核验记录](artifacts/VERIFICATION.txt)。合成演示只用明确标注的合成数据，不能当作市场历史事实。真实CSV运行后的JSON会带输入SHA-256和来源字段。

可复核的规则、模块与测试对应见[算法契约](算法契约.md)。

## 尚未实现为严格结论的部分

严格递归的次级别走势类型、所有原文版本差异、完整特征序列边界争议、图像逐像素复现、跨市场交易制度、成交成本和实时低级别触发仍需继续验证。算法会输出候选和`observe`，不会把代理结构升级为严格买卖确认。
