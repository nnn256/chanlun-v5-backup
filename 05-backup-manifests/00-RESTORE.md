# 本地备份与恢复

本次本地备份根目录：`D:/ProjectBackups/chanlun-v5/20261117`。

- `staging/`：与私有 GitHub 仓库对应的整理副本。
- `local-data/objects/`：以 SHA-256 命名的大文件对象，相同内容只保存一次。
- `local-data/file-manifest.jsonl`：逻辑路径到对象的映射；同一路径多条时最后一条为最新快照。
- `local-data/status.json`：文件数、逻辑大小、实际新增对象大小、失败和边读边变化计数。
- `local-data/errors.jsonl`：未能复制的文件及原因，空文件表示没有记录错误。
- `tools/restore_local_data.py`：带哈希核验的恢复器。

恢复示例（输出目录必须为空）：

```powershell
py -3 tools/restore_local_data.py --backup D:/ProjectBackups/chanlun-v5/20261117/local-data --output D:/RestoredChanlun --prefix active-f-workbench/
```

该命令从本地对象目录恢复，不需要 GitHub 令牌；不要直接覆盖正在运行的数据库。
SQLite 使用在线备份 API 保存一致的单库快照；仍运行的批次各文件复制时间不同，
所以本地归档是“带时间记录的逐文件备份”，不声称所有文件在同一毫秒静止。

GitHub 仅含源码、课程、聊天、附件和清单。十几GB行情、数据库、原视频、发布包保存在本地。
`storage-inventory.json` 是源目录统计，不等于这些大文件已上传 GitHub。

本次数据归档已完成：327,959 个逻辑文件、64,464,288,340 字节；去重后 277,196 个对象、
55,268,570,907 字节。复制失败为 0。`daily-batch/logs/v4-daily.stdout.log` 在复制时继续写入，
按正在运行的日志快照保存，未把它声称为静止文件。9个用户原始课程视频均存在并已归档。
全部对象已检查存在性和大小；样本重新计算哈希与数据库完整性、TDX程序恢复冒烟通过。
没有对55GB对象做第二次全量重读哈希，具体证据见 `local-backup-status.json`。

聊天备份仅含本窗口可读取的用户可见记录；不包括系统内部指令、隐藏推理或其他无关聊天。
无法取得的附件会在聊天缺失清单列出，不补造内容。
