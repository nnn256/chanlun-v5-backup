# GitHub 私有仓库

目标仓库：`https://github.com/nnn256/chanlun-v5-backup`

当前 Git 树只包含源码、文档、课程学习材料、选定聊天窗口可见记录、用户附件和验证清单。
没有把数十 GB 行情、SQLite、回测结果、视频和构建发布包放进 Git。它们位于本机
`D:/ProjectBackups/chanlun-v5/20261117/local-data` 的内容寻址对象中，映射在
`file-manifest.jsonl`。GitHub 下载后若需要完整数据，按 `05-backup-manifests/00-RESTORE.md`
执行本机恢复。

仓库边界：当前 V5 版本与历史版本并列保存，版本 profile 不改写；当前工作台部署在 F 盘
仅作为核验目标，不把其运行数据库自动当作源码。聊天导出只包含所选窗口的可见内容，
不含系统、开发者消息或隐藏推理。认证配置、token、private key 不进入仓库。

推送前检查：

```powershell
git diff --cached --check
git ls-files | Select-String '(^|/)(\.env|auth\.json|credentials\.json|.*\.sqlite3?|.*\.db|.*\.pem|.*\.key)$'
```
