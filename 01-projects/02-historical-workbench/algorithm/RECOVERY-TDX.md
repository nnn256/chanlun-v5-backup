# TDX全市场任务恢复点

## 最新状态：2026-11-07已完成历史流水线收尾

三项任务均已处理5579股票池，5578只有效成功，sh688827原始接口无历史单列不可用；无待处理或未解释失败。数据固定截止2026-11-06T02:03:45+08:00。日线17,062,480根；30m21,487,433根；5m128,924,257根；全history逐日17,062,480前缀、172,306事件、35,691次首次候选，warmup0。

最终分钟组合目录runs/tdx-intraday-completed-20261107（不是旧all-a失败汇总）。复用原5563成功结果/指纹，15目标修复独立输出并全部重算核验；7个13:00平价零活动行明确隔离，不改时间/价格；补取响应中744条截止后K线明确排除。全部源raw/质量/缓存可回溯。summary/manifest与verification完成，status pass_with_source_unavailable。

本次新增chanmodel/tdx_quality.py保持原严格normalizer不变，质量策略显式调用。tools/complete_historical_runs.py与verify_completed_history.py可复现本次补齐。120tests通过。最终读历史任务完成报告.md / 历史任务完成结果.json；进度入口tools/market_progress.py通过runs/latest_completed_runs.json指向最终目录。

算法严格缺口仍存在，尤其走势类型递归/真实trigger/multilevel数据周期身份验证；本次仅收尾数据与回放历史任务，不宣称严格算法完整。

以下为先前执行过程记录，所列进程/运行中状态均已过时，以以上最新状态与最终report为准。

用户要求：使用https://github.com/oficcejo/tdx-api获取实时与历史数据；后续明确“三个都需要”：全市场日线、30m+5m多级别联立、逐日历史回放与信号评估。

日期：2026-11-06 Asia/Shanghai。工作区C:/Users/li/Documents/ChatGPT/缠学习/缠论算法。

数据源：vendor/tdx-api commit ea07dccb67aeb92ebde851ac31503b4bf457a318；Go服务本地patch监听127.0.0.1:18080，PID16260，TZ=Asia/Shanghai，TDX_API_LITE=1；runtime/service.json。patch及源码审查见artifacts/tdx-integration。不能用health的硬编码时间代替真实数据测试。

实测：/api/codes fresh完整5579A股=sh2319/sz2906/bj354；5579行情快照已收齐。日线/api/kline-all/tdx为不复权、price/1000、volume手*100；Quote.Amount已元不/1000，ServerTime raw不假装完整成交时间。分钟仅上游约2年，sz000001 30m3944根/5m23664根（2024-10-25起）。

主日线：market_scan.py，runs/tdx-all-a-20261106固定as_of2026-11-06T02:03:45+08:00，cache market_data。已两轮完成，最终session96348最终5578成功+1有证据empty_history(sh688827)，17062480根。prod已修count0/listnull合法空状态，不造数据。最终verifier session67422正在全5578hash+20股抽查。当前JSON/CSV摘要不是历史回测。

用户最后明确全history逐日从最早开始，不可近一年替代。history_replay.py已完成精确增量包含/分型/笔和MACD，只base结构变化才重算，使用相同原函数，无滚动截断；8485日逐日14.27秒样例。真实BJ591全prefix等价、SZ1200每prefix/8485每1000比较均过。history全量session57197，runs/history-all-a-fullspan-20261106，workers12，全部当前股票池5579。此刻约931成功/400万prefix，原始未可取sh688827最终应由daily证据归unavailable。datafingerprint只hash实际依赖，生产禁止再改以免重启。

intraday_scan.py + chanmodel/tdx_intraday.py全量session99435，runs/tdx-intraday-all-a-20261106，8workers，共5579，asof同daily；此刻约1475成功，30m+5m实际约两年。原raw及CSV均gz，约9GB总，现场上游/CPU共用每股12-17s。tdx_data后来仅改null合法empty导致fullenginehash与running不一致，最终verifier会明示different_version，抽样当前计算相同另证，不伪造旧version一致。可接受samecontractdifferentarchiveversion，无需为无效指纹重跑全部。

测试当前114项全部通过，执行stdout/stderr在artifacts/tdx-integration/final-tests.*。主机14core20logical，CPU100，free memory约1.4GB（不要再多开巨大并发）。GoPID16260属于此任务，另有无关tdx服务别动。

新文件：chanmodel/tdx_data.py、market_scan.py、Start/Stop-TdxApi.ps1、Start-MarketScan.ps1、TDX全市场使用说明.md。existingsegments做等价提前停止优化，8000bar约.06s；测试原33+优化5+Adapter16=54passed；新增tests/test_market_scan.py已加恢复/stop测试。

并行agents：batch_review负责已完成market_scan恢复6缺陷/STOP bounded队列及tests，完成后冻结。intraday_pipeline负责新增chanmodel/tdx_intraday.py、intraday_scan.py及tests，先单股真实缓存/多周期，之后root调度全量。tdx_review负责新增history_replay.py及tests，精确prefix逐日+仅signal events，评估，先真实BJ591根并给性能；可做严格等价strokes-change gate加速，不滚动截断冒充全history。

下一步：持续监控分钟99435和history57197直到全部完成，不能把启动或样例称全部完成。用tools/market_progress.py紧凑快照；write_stdin输出会很大max_tokens限制，独立exec读summary更好。日线核验67422取最终；分钟跑完tools/verify_intraday_run.py --sample20 --workers4（逐条OHLC+grid很重），history跑完tools/verify_history_run.py --run-dir runs/history-all-a-fullspan-20261106 --cache-dir market_data --daily-run runs/tdx-all-a-20261106 --sample20，参数是--sample 20不是黏连（intraday另有--sample20 alias）。所有agent现在只读/核验工具职责。

文档已写全市场三流水线说明.md，TDX全市场使用说明.md，Start/Stop脚本。需要最后汇总MD+JSON、真实统计、有限候选评估（不是portfolio回测），修任何剩余失败；打轻量代码/报告ZIP，禁止运行旧finalize_delivery.py递归把vendor/.git、市场数据巨量全部塞压缩。别冒充所有历史图/原文strict证明。记录原文件backup+diff+verification+rollback。最终回答给三项完成数字、空行情例外、完整结果链接和研究边界。

结果语义：全历史仅接口可供，不保证上市首日；当前证券池不涵盖所有退市股，历史绩效有幸存者偏差；三市coverage与历史范围逐股记录。严格原文递归仍proxy，execution_allowed=false。
