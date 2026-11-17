# 缠论V5

这是独立的 D 盘研究目录，不覆盖原有 D 盘软件和数据。

## 目录

- `algorithm/`：算法、工作台和本地 TDX 服务
- `data/market_data/`：V5 独立行情缓存
- `runs/`：全市场扫描和递归分析运行目录
- `workbench-data-8895/`：V5 工作台 SQLite、任务和结果
- `logs/`：V5 启动和运行日志

## 运行全市场

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\algorithm\Run-V5-MarketScan.ps1 -Workers 8
```

全市场使用当前 TDX provider 列表。若 provider 返回的覆盖不含北交所，运行报告会保留该缺口并标记为 `partial_provider_universe`，不会冒充沪深京全覆盖。

已完成运行示例：

- 采集/日线候选：`D:\缠论V5\runs\full-market-20261114-tdx-partial`
- V5 递归后处理：`D:\缠论V5\runs\v5-recursive-l8-20261115`
- 合并状态：`D:\缠论V5\V5-RUN-STATUS.json`

当前结果为 5225 个沪深 provider 代码，5224 个成功；北交所 provider DNS 失败，因此覆盖是 partial。V5 递归层级上限为 L8；实际层数由数据结构决定，不会补造不存在的层级。递归报告与旧日线扫描分开保存。

运行可恢复：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\algorithm\Run-V5-MarketScan.ps1 -RunDirectory .\runs\v5-all-a-YYYYMMDD-HHMMSS -Resume
```

暂停时在对应运行目录创建 `STOP` 文件；当前 worker 完成后停止提交新股票，删除 `STOP` 后用 `-Resume` 继续。

## 运行工作台

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\algorithm\Start-V5-Workbench-8895.ps1 -OpenBrowser
```

推荐工作台绑定 `127.0.0.1:8895`，数据库写入 `D:\缠论V5\workbench-data-8895`。8879 保留为旧 V5 实例；8791 是其他旧工作台端口。

## 语义边界

V5完整递归算法与V4兼容的全市场采集分开保存。全市场扫描先完成数据获取和日线候选；递归层、中枢凭据和多周期触发需用V5完整报告入口生成。所有结果继续 `execution_allowed=false`。
