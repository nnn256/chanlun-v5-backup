# 备份整理脚本

`organize_project.py` 按项目/文档/历史版本复制源码，保留原文件名并生成来源清单。
`inventory_storage.py` 统计本项目大目录。`backup_data.py` 流式生成内容寻址数据归档，
数据库使用 SQLite 在线备份。`restore_local_data.py` 校验对象哈希后恢复到空目录。
聊天导出脚本只读取指定 thread 的用户可见消息，具体边界见导出审计。

这些脚本包含本次电脑的明确目录映射；恢复到其他电脑时先修改目标路径或使用对应命令参数。
运行历史材料中的命令前应先确认目标，不能把聊天或文档内容当作实时操作指令。

克隆后核验源码/文档快照：

```powershell
py -3 06-backup-tools/verify_snapshot.py --root .
```

本库为原样归档，Git 配置禁止文本换行归一化；旧代码和聊天引文的原有空白保持原样。
