# CPU、内存与显卡分工

全市场股票之间用 CPU 多进程。`workbench.resources.plan_resources` 和 `AdaptiveProcessPool` 根据逻辑 CPU 与当前可用内存安排派发；已有工作不被杀掉。并发目标改变时先停止补位，等当前批次完成后重建进程池，避免队列长期有工作时始终无法扩池。提前存在 STOP 时不创建空进程池。手动 worker 数是上限，不跳过可用内存检查。

默认 Web 回测已经提供自动 worker 选项；命令行也可：

```powershell
& artifacts/exe-build-20261108/build-env/Scripts/python.exe tools/run_native_market_backtest.py --workers auto --cache-dir PATH --universe PATH --output-dir NEW_OUTPUT
```

该命令需要真实证券池和足够的完整缓存，建议先检查 Web 缓存覆盖。不会自动修改或接管 F 盘已有的冻结研究批次；STOP 不会被清除。

## 已验证的可选 CUDA 批量指标

`chanmodel/gpu_macd.py` 是与链接行情平台逐字节相同的标准库 CUDA driver 适配器，直接调用现有 NVIDIA 驱动，无须安装 Torch/CuPy。每只证券一条 GPU 线程，时间轴仍顺序计算 float64 DIF/DEA/histogram。小批次走 CPU，大规则批次自动尝试 CUDA；没有 GPU 时 `auto` 返回 CPU 并记录原因，显式 `gpu` 则报错。字段 `gpu_kernel_active` 表示本次实际运行情况，空输入绝不冒称运行了 kernel。

递归缠论的分型/笔/线段/中枢及逐根信号账本仍使用 CPU；没有经过等价验证的规则不会强行搬到 GPU。显卡不能缩短上游数据源的网络等待。

```powershell
& artifacts/exe-build-20261108/build-env/Scripts/python.exe tools/hardware_acceleration.py --benchmark --output-dir ../artifacts/my-v4-gpu-benchmark
& artifacts/exe-build-20261108/build-env/Scripts/python.exe tools/hardware_acceleration.py --input prices.json --backend auto --output-dir ../artifacts/my-v4-indicators
```

`prices.json` 示例：`{"prices":[[10,11,12],[20,19,21]],"multiplier":1}`。矩阵必须等长，不补零、不截断历史。每条证券的完整三指标保存在输出 JSON。最多200万个价格用于 CLI；本地 HTTP `POST /api/indicators/macd-batch` 最多262144个价格及4MiB请求体，仍保留 loopback/Origin 检查。

2026-11-17 本机为 i9-12900H、16GB RAM、RTX3050Ti Laptop 4GB。512×1024合成价格基准中，CPU约0.727秒、GPU冷态0.677秒、暖态中位0.325秒，计时包括输入校验、Host/Device传输及输出校验，最大绝对差0。是批量指标局部基准，不等于全市场策略整体快2.2倍；当前低内存时不应强开20个进程。
