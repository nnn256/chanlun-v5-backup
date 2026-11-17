# 缠论完整结构研究包

## 使用

- `缠论一遍串起来.mp4`：约 6 分钟中文讲解，13 章配音和字幕。
- 双击 `打开讲解与算法图.cmd`：进入离线学习页，含逐章讲解、逐根回放和完整递归多周期视图。
- `period-explained.html`：全周期中文讲解页。支持 1m、5m、15m、30m、60m、日、周、月、季、年；切换周期、层级、历史时点后，文字和浏览器中文朗读跟着当前图更新。
- `缠论大白话复习总结.pdf`：四页大白话复习卡，与当前算法规则同步。
- 交互页默认示例为合成教学数据，不是历史行情。

## 当前实现

算法已按固定规则配置实现一条完整结构研究流程：包含处理、分型、严格笔、线段特征序列无缺口/有缺口路径、笔破坏确认、已完成下级走势类型递归、中枢及同级分解、力度背驰、六类候选、真实周期 OHLCV 对账、区间套结构确认、确认后新细笔触发、小转大审计和逐时事件回放。

L0 为选定输入周期上已确认线段；更高层只接收完整、连续、同秩的下级组件。分解单元完成不等于反转，反转由独立的反向中枢破坏/不返回规范判断。每项结构带组成对象与可用时间；未发生的确认不伪造。

理论口径边界也明确保留：`strict_original_equivalence_proven=false` 表示没有证明原著各篇、各流派的全部争议点严格唯一等价；这不表示递归模块缺失。当前 profile 是一套有版本、可测试、可复核的声明算法。`execution_allowed=false`，不连接交易执行。

## 运行

单周期结构、递归层级、证书和候选：

```powershell
python run_analysis.py --csv .\demo_ohlc.csv --period 5m --symbol sz000001 --max-rank 3 --output .\analysis.json
```

完整多周期示例：

```powershell
python run_multiframe.py --demo --max-rank 3 --output .\multiframe.json
```

真实多周期输入：

```powershell
python run_multiframe.py --trade 30m=trade.csv --confirm 5m=confirm.csv --trigger 1m=trigger.csv --symbol sz000001 --cutoff 2026-11-13T15:00:00+08:00 --output .\multiframe.json
```

真实输入必须显式提供证券、周期、收盘时间、成交量和同一复权口径；行情窗口还须通过父子 OHLCV 聚合核对。未验证、缺失或尚未确认的结构会被隔离在触发分析之外。

运行完整回归与交付重建检查：

```powershell
python .\test_all.py
python .\verify_complete_bundle.py
```

## 输出解释

- `output/chanlun-complete/index.html`：中文视频、单周期特征序列及递归图、多周期全层结构。
- `full-study-final/完整算法复习.html`：独立自包含研究页面，包含 30m/5m/day 多周期逐时回放、递归秩、六类点、区间套、事件版本、中枢演化、特征序列和凭据审核。
- `full-study-final/report.json`、`events.jsonl`、`signals.csv`：同一运行的原始机器结果。
- `analysis-final.json`、`multiframe-final.json`：用包内 CSV 实际运行命令所得的示例报告。
- `AUDIT.json`：规则审计、输入哈希、等级数量及前缀因果时点摘要。
- `SOURCE_PROVENANCE.json`：逐文件核对随包引擎与工作区算法源码的哈希。
- `FINAL_VERIFICATION.json`：打包前证书、周期对账、回放、候选与视频摘要。
- `period_catalog_manifest.json`：十个周期、完整桶聚合、来源分组和历史不足说明。分钟源与长期日线源禁止拼成跨源区间套。

若信号数量为零，表示在这份样例、所选时间和 profile 下没有找到候选；程序不会为展示而添加信号。合成数据只用来检查结构链、回放和视觉，不代表市场事实或收益。
