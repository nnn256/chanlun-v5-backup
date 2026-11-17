# 全市场分时回放恢复记录 · 2026-11-17

批次：F:\ChanlunAlgorithmTests\2026-11-15-all-market-intraday

原冻结代码81文件哈希核验通过：67dc64e53f7eac7a9285e9a89f979b20c8e8c4f1069e9a43b88db3c744b9892f。
上轮在394项已验证后出现BrokenProcessPool，退出证据在 analysis-resume-20261116.stderr.log；无足够证据确定为OOM。
现用同manifest和原数据截止时间恢复，单worker；当前数据库：{"pending": 1, "running": 1, "verified": 394, "waiting_source": 10762}。
采集全部11158项成功；3项超时已补采并独立核验，详见 source-repair-20261117/POST_VERIFICATION.json。

运行入口：operations-20261117/supervise_replay.py。监督程序当前监视原runner锁，避免重复启动；原runner结束且任务未完成时按完整性、资源和STOP检查决定是否续跑，连续3次无增长或总8次重启停止。
运行状态、心跳及退出事件：operations-20261117/status.json、events.jsonl；现有runner输出：analysis-resume-20261117.stdout.log、analysis-resume-20261117.stderr.log。
停止标记：analysis/STOP 或 operations-20261117/STOP。勿自动清除用户STOP。
本地进度地址：http://127.0.0.1:8798/。
下次先检查真实进程、监督心跳、数据库计数及锁；不要启动第二个runner，不混用其他源码。

记录时间：2026-11-17T03:46:01.428043+08:00。
