# TDX接口与全市场历史扫描

本次使用[oficcejo/tdx-api](https://github.com/oficcejo/tdx-api)，固定提交`ea07dccb67aeb92ebde851ac31503b4bf457a318`。服务运行在本机`127.0.0.1:18080`；API原始响应、接收时间、输入哈希和结构摘要分别保存。

## 默认运行范围

- 沪、深、京当前接口股票池中的A股，保留交易所前缀和前导零。包含ST，未把ETF、指数或B股混入股票池。
- 日K线，调用`/api/kline-all/tdx`且不传limit；保存上游能提供的全部历史，不预截成800条。
- 明确使用未复权数据。分红拆股会影响价格结构，结果不与前复权数据混合。
- 当前全历史的结构扫描；历史端点属于最终图解释，不冒充历史当时可用信号或策略回测。
- 同时取得`/api/batch-quote`最新可得报价快照，每批最多50只。报价不直接拼接成已收盘日线。

本次股票池和逐股结果见[runs/tdx-all-a-20261106/summary.json](runs/tdx-all-a-20261106/summary.json)，扫描清单见[summary.csv](runs/tdx-all-a-20261106/summary.csv)。运行期间这些文件会增量更新；最终以`pending=0`、成功/失败计数和覆盖元数据为准。

## 运行

在本目录运行，要求Python3.11+、Go1.23+。Go只用于构建用户指定的服务；Python取数器无第三方包。

```powershell
.\Start-TdxApi.ps1
python .\market_scan.py --run-dir .\runs\new-daily-run --workers 4
```

取数、缓存、分析和断点写入在一个入口完成。默认缓存为`market_data/tdx/day/`，默认只保留每股摘要；需要全部结构对象时使用`--full-reports`，其压缩JSON会显著增加磁盘占用。

已有成功项的同次中断续跑：

```powershell
python .\market_scan.py --run-dir .\runs\new-daily-run --resume --workers 4
```

常规下一交易日更新用一个新run目录，避免更改已记录截止时间。`--resume`继续原run及原截止时间，不把隔日重新取数误写成原时点实时数据。源或配置改变时也使用新run。

三股试跑：

```powershell
python .\market_scan.py --run-dir .\runs\three-stock-test --symbols sz000001,sh600519,bj920002 --workers 2
```

## 关键输出

| 文件 | 内容 |
| --- | --- |
| `run.json` | 固定截止、配置、代码指纹、来源、股票池 |
| `universe.json` | 完整代码/名称/交易所、各市场覆盖及来源回执 |
| `quotes.json` | 报价快照、原始ServerTime、接收时间、缺失证券 |
| `checkpoint.sqlite3` | 每股状态，SQLite WAL断点写入 |
| `summary.json` | 成功/失败/待处理、市场分布、历史根数与候选汇总 |
| `summary.csv` | 每股首末日期、根数、结构计数与失败原因 |
| `stocks/<代码>.json` | 每股完整研究摘要、失效边界、候选年龄及数据质量 |
| `responses/<代码>.json.gz` | 本次真实接口响应字节的压缩备份 |
| `market_data/<源>/day/ohlcv/` | 标准化CSV，价格为元、量为股 |
| `market_data/<源>/day/metadata/` | 源、哈希、接收时间、实际覆盖区间与质量 |
| `failures.jsonl` | 空历史或失败条目，绝不填零冒充成功 |

`active_candidate_count`是当前截止时点下尚未在已知后续数据中失效的研究候选数量；不代表今天新出现。`recent_candidates`按端点近远提供最多12条并记录`age_bars`。`all_historical_candidate_count`包含已失效历史解释。上述都不同于逐前缀回放的first-seen事件。

## 数据口径与检查

源码的K线OHLC、Amount均为Price整数，按1000除成元；成交量原为手，导出`volume=手×100`，保留`volume_lots`。报价中的Amount已是浮点元，不能再次除1000。

K线按交易日构建`15:00+08:00`收盘时刻；截止时点前尚未收盘的当日日线保留为原始证据并从结构扫描中排除。重复同值日期去重，冲突同日数据拒绝；无效OHLC、非有限价格、未来交易日或空历史独立报错。缓存响应和CSV各有SHA-256。

原仓库`/api/health`含硬编码时间、`/api/server-status`含固定connected值，因此本次用真实代码/行情/历史请求验收，不用健康页替代数据可用性。

## 服务本地修订

服务补丁见[service.diff.patch](artifacts/tdx-integration/service.diff.patch)，修改保持限定为3个Go文件：增加本机监听地址、请求超时、可关闭管理器/cron的轻量模式，以及逐市场真实代码快照。轻量模式通过`TDX_API_LITE=1`启用，不额外开启SQLite管理器和定时更新。

北交所代码来自原库内的北交所官网请求，单次/总体超时与市场失败状态分别保留。一所失败时不会把另外两所已取得的代码丢掉，覆盖状态会标partial；不能把partial当三市全部覆盖。

历史按每800条向过去分页。接口名字中的all只表示接口可提供的全部，不证明包含上市首日，也不涵盖所有退市股票。当前股票池用于过去结构研究存在幸存者偏差；元数据明确保留该边界。

报价ServerTime字段没有完整可验证的交易日期解码，所以`received_at`只证明何时收到了响应。非交易时段取得的是最近可得快照，不能声称在休市时产生了新成交。

原始未复权与同花顺前复权需分开：`--source ths`会显式换端点和缓存目录，失败时不自动回退到TDX。前复权数据属于当前版本，不能无条件用于严格历史时点回测。

## 停止服务

```powershell
.\Stop-TdxApi.ps1 -Preview
.\Stop-TdxApi.ps1
```

停止脚本核对本任务记录PID及二进制路径，不按进程名批量结束其他服务。当前服务信息在[runtime/service.json](runtime/service.json)。全市场扫描运行期间先让扫描结束，再停止数据服务。
