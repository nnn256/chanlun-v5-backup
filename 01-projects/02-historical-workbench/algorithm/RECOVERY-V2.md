# V2实现恢复点

最新：全152tests（原120+新增32）已通过，runtime8.614s，artifacts/recursive-v2-20261107/tests.stderr.log。README/审计/契约已加V2入口与版本区别。最终真实6股回归已通过（40.828s）；代码/报告ZIP、四件套、独立回退演练已完成。最终结果按明确profile完成，不把本scope称原著所有分解等价。README的新151数字实测。

用户明确要求：走势类型递归 → 严格中枢与背驰 → 真实多周期校验和触发器。已实现独立chanmodel/v2/{series,recursive,divergence,engine,io}.py及run_v2.py。

完成状态：L0已确认原线段边界，L1以上采用原38课同级别分解生成完成盘整类型并递归；不可用仅3任意笔替代，中心入参严格同rank、连续、完成类型。独立保守反向中枢破坏视图可形成trend/consolidation完成证书供trigger；分解完成不等于反转完成。中心/类型审计从成员对象重算，不信任布尔标志。MACD辅助、零轴数值阈值仍研究约定，全原文等价false。原53课无同级一买的某些小转大二类形式未全面复现，文档已说明，不可硬称全严格。

多周期：强制Series(symbol/period/adjustment/timezone/source)，native分钟间隔、OHLCV聚合/缺口/父子缺观察检查；同日线换三个标签被v2及legacy engine.multilevelguard拒绝。volume默认1股真实TDX取整差会blocked；显式1000股容差可对平安银行及6股sample通过（每窗口差和阈值全部保存）。同真实5m derive得到day/30m零量差完全通过。

trigger要求下级同价且位于父末端bar的结构拐点、已完成下级反向中枢break/nonreturn，然后更细级别新confirmedstroke在confirmation与parentavailable之后；细级别持续检查失效，不同sidecandidate包含不能代替触发。

已过29项新增测试（tests/test_recursive_v2.py），原全120测试应合149（最后完整run只到145，因后来多加4测试，需最后重跑）。tools/verify_recursive_v2.py真实6股、500/600prefixledger、150/300/500/600direct-vs-replay、实际5m聚合493day/3944 30m、5个日末指定timeframecheckpoints验证pass，42.984s；保存artifacts/recursive-v2-20261107/real-validation.json和runs/recursive-v2-20261107/*.json（约190MB，最终ZIP只取轻量摘要或gzip，不要打巨大raw或所有marketdata）。

真实当前样本没有被假称triggered：6股多为invalidated/blocked_terminal_history/waiting_lower_confirmation。正向触发有规则构造fixture测试通过，不得称真实市场已测到确认买点。

旧文件修改：chanmodel/engine.py仅legacy重复时间序列拦截+input_contract说明；README/审计/契约待加新入口（基线已存artifacts/recursive-v2-20261107/baseline）。新文档递归与触发V2说明.md已写。

下一步：补source receipt和batchCLI相关测试如必要（不要扩大无关范围）；最终跑全测试和编译，检查近期改动的真人样本回归；更新README/ALGORITHM_AUDIT/算法契约为V2状态但保留旧run日期；打四件套+rollback独立副本验证+轻量代码/报告ZIP，最终用明确能力与剩余理论口径范围交付。不要再创建新subagent（当前developer禁主动）。
