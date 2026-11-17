# 当前全历史测算运行记录

用户已授权“全部历史测算”和“继续工作”，两个系统都要运行。不要再次请求许可，不要重复启动既有批次。

## 正式日线批次

- 根目录：`D:/ChanlunFullHistory-20261117`
- 最新供应商股票池：5,580 只，已获取原始回执和哈希。相对本地工作台旧名单新增 sh688845，移除 sz002731。
- 固定截止：2026-11-17T19:49:45+08:00。TDX 本地来源 `http://127.0.0.1:65004` 已实测 sz300949 返回上市以来 1,388 根日线至 Nov17。
- 冻结入口：`code/v4/tools/full_history_pipeline.py run --root D:/ChanlunFullHistory-20261117`
- Python：工作区 `liangce-v3/.venv/Scripts/python.exe`。Windows venv会出现启动器与实际解释器两个进程，不能把它们误当重复运行。
- 流水线：全市场全部可得日线采集（2网络线程）→固定来源清单→V4全历史因果回放（CPU最多2进程/内存门控）→量测v3全历史递归回放（CPU串行/低于1GiB等待）。
- 母进程17540/实际22468，采集启动器46124/实际48548（以后以status.json及实时进程为准）。
- 实际数据/结果：`acquisition/summary.json`、`inputs/daily-sources.json`、`inputs/coverage.json`、`v4-daily/summary.json`、`v3-daily/summary.json`。
- 当前状态以文件实时读数为准。采集5,580/5,580已处理：5,579成功、1 unavailable、0 failed，17,104,233 bars，成功全部末日Nov17，最早1990-12-19；无历史为sh688845。
- 正式流水线已自动进入V4日线，latest已读297/5,548成功、0failed；31股因日线不足50根被单列排除，加无数据1股共32 excluded。量测v3还在后续队列中。
- 每阶段有durable checkpoint，根目录OS锁防重，已实测重复启动被拦且不破坏当前status。STOP只排空/暂停，不强杀；不会自动删除STOP。恢复须明确移除用户创建的根及阶段STOP，再运行同一冻结入口。
- 不要修改冻结code/inputs或原始缓存，否则身份校验会阻止续跑。来源清单绑定acquisition manifest/results SHA。

## 真实验证

- smoke两股：sh600000 6,429根、sz300949 1,388根，合计7,817根，两套算法都成功，实际最晚2026-11-17。证据`smoke/verification.json`。
- acquisition9tests、pipeline5tests、v3新runner及旧batch共17tests、viewer4tests通过。
- V4引擎仍原固定chan.py；v3仍原prefix_events+portfolio，未修改算法。V4少于50根排除，v3少于3根记历史不足，不把这些记成功。

## 已有分钟批次

- `F:/ChanlunAlgorithmTests/2026-11-15-all-market-intraday`
- 5,579股 × 1m/5m，共11,158项。采集早已全部完成256,654,260 bars，回放+独立核验仍在跑。
- 已有supervisor63856、adaptive runner40448、进度8798/8799，保持原算法/STOP/参数，不接管或重复启动。
- 最新已读756已核验、0失败；实时从analysis/summary.json读取。

## 用户入口

- 统一进度：`http://127.0.0.1:8801`，独立只读viewer。
- viewer源码：`缠论算法/tools/serve_full_history_progress.py`。目前已启动，端口拥有者以Get-NetTCPConnection为准。
- 当前V4源码工作台8793；原安装EXE8791保持；量测v3本机8830已更新启动。
- `全历史测算运行说明-20261117.md`、`打开全历史测算进度.url`已创建。
- 已明确：日线批次/分钟批次尚未全部完成；其他周期和历史竞价不能被默认为本次已跑完。
