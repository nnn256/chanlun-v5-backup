# 项目版本索引

| 顺序 | 目录 | 来源与用途 |
|---|---|---|
| 01 | `01-chanlun-v5/algorithm` | D 盘 V5 当前源码；独立 8895 工作台；CPU/内存自动调度 |
| 02 | `02-historical-workbench/algorithm` | 工作区旧 `缠论算法` 的源码快照，按实际文件保留历史版本 |
| 03 | `03-early-learning-engine` | 课程学习初期的小型引擎与转写脚本，不能当最新 V5 |
| 04 | `04-intraday-frozen-engine` | F 盘分钟批次冻结源码，实际 profile 和冻结哈希见运行清单 |
| 05 | `05-intraday-runtime-tools` | 分钟批次自适应调度、GPU数据核验与独立验证脚本 |
| 06 | `06-full-history-frozen-code` | 2026-11-17 日线全历史批次固定的 V4/V3 源码快照 |

当前源码版本是原样备份，不因为目录名而升级算法口径。分钟批次、日线 V4、量测 V3 和 V5
各保留自己的 profile；不同批次的结果不能拼成同一套回测结论。

源目录中的 `runtime`、`.venv`、`node_modules`、运行结果和大数据库不进 Git；
启动所需的 TDX 程序留在本地备份对象中，GitHub 可恢复源码但不是免安装的可执行发行版。
