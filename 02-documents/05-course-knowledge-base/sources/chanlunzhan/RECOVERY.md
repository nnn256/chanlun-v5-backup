# 缠论站资料补充恢复点

- 目标：https://chanlunzhan.com/ 的公开静态知识资料，接入既有本地缠论知识库。
- 当前证据：网站地图205页；26课、8阶段、52词条、113篇转载原文；robots排除 /practice/、/stocks/、/data/。
- 已完成：205/205页静态正文、43/43张PNG/JPEG静态原图；8阶段、26课、52词条、108课与5补充篇；6份新学习笔记、36道自测、30天计划、完整来源目录及离线检索接入。
- 当前检查点：tools/verify_chanlunzhan.py 已通过，205页及43图哈希、108编号连续性、631个内部链接、155份原有来源、5组命令行检索、独立副本三腿回退均通过。
- 下一动作：正常使用 README.md 与 data_structure.md 进入；问具体概念先查 notes/12—17，再用 tools/search_kb.py 查询并回到课号上下文。如更新资料，先备份再采集；当前无需继续抓取。
- 原始资料优先级：作者原文 > 有明确课号的解读 > 本站算法工程口径；本站转载不自动等同作者校勘版。
- 修改边界：新增 sources/chanlunzhan；修改README和检索工具前先保存基线；行情算法不在任务范围。
- 编码：Windows Python stdout默认GBK，输出中文前 reconfigure(encoding="utf-8")；文件显式UTF-8。
- 交付记录：delivery/chanlunzhan-20261108/{MODIFIED_FILES.json,DIFF_FILE.patch,VERIFICATION.txt,verification.json,VERIFICATION.md,ROLLBACK.py}。
- 完成状态：静态知识库补充已完成；23页动态画线、训练题库、个股实验室、浏览器进度、网站算法测试、严格多周期区间套未离线运行验证。
