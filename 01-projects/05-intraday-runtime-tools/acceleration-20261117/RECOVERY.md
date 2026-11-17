# 自适应回放恢复记录 · 2026-11-17

当前进度 627 / 11158，失败 0。本记录只代表写入时刻，后续查看 summary/runtime 心跳。

实际入口：operations-20261117/supervise_replay.py。PID 63856，runner 40448。执行 acceleration-20261117/run_adaptive_intraday.py，显式 frozen-code engine-root；最多4个CPU worker，guard/reserve各512MiB，GC default。

算法SHA256 67dc64e53f7eac7a9285e9a89f979b20c8e8c4f1069e9a43b88db3c744b9892f；81个冻结源码、manifest、数据与结果继续原批次。恢复拒绝NULL/未知PID；STOP停止新提交并排空活动任务。已通过19+9项隔离测试。

进度与资源：http://127.0.0.1:8799/；只读服务 serve_adaptive_intraday_progress.py，PID18860。8798旧进度页仍在。不要同时启动两个runner。先查进程、心跳与锁，再决定恢复。

停止标记：analysis/STOP 或 operations-20261117/STOP。不得自动清除用户STOP；这次由更新流程创建的STOP已在确认worker落库、进程退出和锁释放后归档为 STOP-drained-20261117.json。

D盘源码与测试：D:/LiangCe-Acceleration-20261117/research/intraday-replay。私有GitHub分支 codex/adaptive-intraday-20261117，commit78dfde2。GPU OpenCL小核可用但缠论递推未启用GPU；默认GC继续开启以控制峰值内存。
