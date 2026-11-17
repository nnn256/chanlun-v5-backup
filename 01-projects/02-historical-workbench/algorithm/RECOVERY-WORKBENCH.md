# 全市场工作台恢复点

用户目标：把既有V2、TDX全市场任务及TradingView三周期PNG整合成可操作的本地工作台。

实现：workbench/{store,compute,jobs,server}.py；workbench/web/{index.html,style.css,app.js}。入口 Start-Workbench.ps1 / 打开工作台.cmd，http://127.0.0.1:8791。SQLite/结果/任务日志在runtime/workbench，计算核心未修改。

完成：股票池搜索筛选、全市场/指定股票、日线/真实三周期/从最早日期逐日回放、刷新TDX、任务队列、暂停/恢复/失败重试、任务隔离、个股图层/周期切换、PNG与完整JSON。PNG iTXt中保存definition_mode/approximation_loss/as_of/input_sha256/execution_allowed。旧行情结果不能覆盖更新行情日期。数据库连接commit后显式close，Windows下避免锁定与句柄泄漏。

实测：159 tests passed（artifacts/workbench/tests.stderr.log）；最终新增文件变更针对性7tests通过。浏览器搜索、周期切换、PNG、1680/1280/390宽度无横向溢出。导出PNG真实文件artifacts/workbench/均胜电子_工作台导出.png，1800x1658，元数据已验证。全量日线5579只完成，5578成功，sh688827无日线数据；原列表至2026-11-05，不假称实时。已刷新真实供应商股票池5580只，多1只京股；原任务仍5579只。

任务：20261107-203943-e2b6e1为全市场三周期，已两次暂停/恢复检查，第二断点689，现已恢复；独立进程关闭网页和重启web服务仍继续，检查/api/overview。日线20261107-203943-4cd5f9已完成并验证仅失败项重试，仍1条真实空数据。刷新均胜电子20261107-205308-9f9e4a完成，行情至2026-11-06。3短历史股票回放20261107-205218-a9d2ec通过；2有结构股票bj920028/sh603284回放20261107-205541-7f0e3e通过，154/176bars和6/8events，final_matches_snapshot。

最后步骤：重启web服务载入完整导入证据导出分支（不停止独立worker），核验原单股import全JSON；保存最终截图、验证摘要、代码包，返回工作台URL/启动入口/实际运行进度。不要声称全市场三周期或全市场V2回放已完成。不要改动核心算法或复用V1结果冒称V2。

最终交付：本地工作台已启动并核验。全套159测试通过，核心未修改；最终完整import JSON核验通过；PNG元数据与文件有效性通过。artifacts/workbench/verification.json、VERIFICATION.txt、workbench-additions.patch、全市场工作台代码.zip及最终截图已生成。后台全市场三周期任务在交付检查时为819/5579，仍运行；只关闭了用于检查的agent-browser会话，服务和worker保留。下一步按用户后续指令使用工作台或跟踪任务，不需要重建。

2026-11-08更新2.1已完成：用户300949全历史与全周期请求，新增workbench/history.py/full_compute.py与tools/capture_full_stock.py/analyze_full_stock.py。先交付runs/aoya-full-history-20261108下完整日线2021至2026、2021放大和11周期PNG；day1381bars、replay106events；historical time-share1381days/331440points，daily-close全部一致。Native1m从2026-06-22，5/15/30/60m从2024-10-31，auction接口不提供。旧workbench.make_chart裁切已修复；旧结果按哈希回执展开，calendar形成中排除结构，minBarSpacing=.001确保全历史全可见；11周期选择、日期定位、15s报价、full任务及interactive独立队列。实际full任务20261108-020707-a65429已完成1/1，核心算法未改动，168tests passed。Artifacts/rollback/升级包在artifacts/workbench-v2.1-20261108。原用户全市场replay20261107-215400-d28a20仍运行，未重置。工作台url http://127.0.0.1:8791/?symbol=sz300949 。

2026-11-08 Windows EXE交付完成：用户10061是源工作台8791正常但TDX18080没监听。已新增desktop_app.py+workbench/services.py自动管理TDX、TK桌面状态、15s监控自动重连、用户目录持久化、单实例；adapter TdxClient环境端点/root配置、server frozen worker dispatch与自动ensure。PyInstaller6.22.3真实单文件Windowsx64GUI，35,606,825bytes，sha256224d947c8d6c0b49b1a48626c41ae124fce4f2a26531a16fc6c5ad7ae50b282d。EXE在Documents/ChatGPT/缠学习/缠论工作台Windows版-2.1.1-20261108.exe与桌面缠论研究工作台.exe，另有同名zip含文档与证据。源码构建环境/回滚/验证artifacts/exe-build-20261108。隔离无PythonPATH运行、native窗口、frozen2股刷新多周期job20261108-190328-573fcb成功2/2、自动杀TDX恢复51.45s、重复启动复用、历史持久性均pass。源测试206pass。交付的桌面EXE已打开，真实用户数据%LOCALAPPDATA%/ChanlunWorkbench，desktop-status记录url与端点；最终url63350、TDX63351，mainpid19368。新用户端口可动态选择不固定。关闭只检查的EXE已计时退出，正式用户app保持运行。下次可从appdata状态文件与logs继续诊断，勿重做构建或误停正式APP。

2026-11-08 任务无结果根因已实证并修复：旧EXE系统代理把本地18080 API转发到未监听7890，py-spy thread-locals记录network address127.0.0.1:7890与requestURL18080。TdxClient本地端点强制ProxyHandler({})直连，远端仍按代理设置；新增request_retry三次上限与实证回执。全周期采集/结构计算增加workbench/progress.py实时文件，overview暴露每股阶段/交易日完成数/结果股票，UI自动跟随提交任务完成后打开该股并清空旧搜索，查看结果按钮选真实result_symbol。源全213tests pass，EXE在显式HTTP_PROXY=127.0.0.1:7890且NO_PROXY空环境下从浏览器新建002149 full任务20261108-225515-195c58实跑成功1/1，进度1413→2357/4484已录，完成自动导航西部材料37.74，day4484，time-share4483received+1failed(20111121源ListNone)。主数据路径更改为C:/Users/li/Documents/ChanlunWorkbenchData避免Codex打包AppData虚拟映射。旧3jobs及3股结果已备份并迁移，新DB与API均4jobs一致。桌面EXE已更新2.1.2，sha2563569d7fc5466deab1b0af47288dc5f4233a90a040f4da0d12d5078194d043406。最终EXE在上级缠论工作台Windows版-2.1.2-任务进度修复.exe/zip。当前mainpid44036(parent46172)、TDX18080、web8791运行，status在Documents根。Artifacts/task-progress-fix-20261108含旧数据/原始根因/截图/213tests/最终验证/rollback/修复源码。已打开用户浏览器002149，检查浏览器会话会单独关闭。
