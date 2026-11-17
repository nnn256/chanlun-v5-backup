# 多周期输入示例

这三份 CSV 的价格和成交量全部由程序合成，不是 sz000001 的真实历史行情。证券标记只用于演示跨周期身份契约。

源为 8 个工作日共 1920 根 1 分钟 K 线，使用明确的中国 A 股上午/下午收盘时刻；5 分钟和30分钟数据由完整子窗口精确聚合。程序不把缺失子 K 线补零。

该样本验证数据契约和结构模块，不保证每一类买卖点都会发生。当前操作级没有买卖候选，报告会如实输出空列表；不会为了画图添加交易信号。六类点及真实结构触发路径另由命名的结构单元测试验证。

重建：在上级目录执行 `python run_multiframe.py --demo`。

真实 CSV：必须有带时区的 `closed_at,open,high,low,close,volume`，可带 `symbol,period,is_closed`。确认同证券、同复权、周期真实且 OHLCV 能聚合匹配后，才进行下级结构确认和触发核对。

```powershell
python run_multiframe.py --trade 30m=multiframe_examples/synthetic_30m.csv --confirm 5m=multiframe_examples/synthetic_5m.csv --trigger 1m=multiframe_examples/synthetic_1m.csv --symbol sz000001 --cutoff 2026-01-14T15:00:00+08:00 --output user-multiframe.json
```

直接用此命令输入合成 CSV 时，输入身份属于调用者声明。若要生成具有合成标记的正式示例报告，应使用 `--demo`，它会写出 `synthetic=true`。
