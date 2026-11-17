# 验证记录

- `auto-resources-20261117/tests.stderr.log`：自动资源调度最终全量 436 项测试输出。
- `auto-resources-20261117/v5-equivalence.json`：本地真实浦发银行 800 根日线，
  直接计算与单进程调度的 V5 报告哈希一致；不是吞吐提速倍数基准。
- `auto-resources-20261117/runtime-verification.json`：运行路径、硬件资源、分钟批次冻结代码与 GPU 核验进度快照。
- `full-package-20261115/package-receipt.json`：原完整 ZIP 独立解压、文件哈希、API 和行情回执核验。

进度文件只代表抓取快照时刻。分钟数据完整性 GPU 核验完成不等于缠论结构回放已全量完成。
后续状态以原运行目录的 summary 和工作台为准。
