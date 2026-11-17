"""Attach run-specific provenance and verify the existing single-stock charts."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root):
    data = load(root / 'chart-data.json')
    default = load(root / 'multiframe-default.json')
    comparison = load(root / 'multiframe-explicit-volume-tolerance.json')
    analysis = load(root / 'analysis/day.json')
    tolerance = comparison['data_contract']['pairs'][0]['volume_tolerance']
    provenance = {
        'symbol': analysis['symbol'], 'name': data['name'],
        'as_of': data['as_of_bar'] + ' +08:00', 'source': data['source'],
        'adjustment': analysis['adjustment'],
        'definition_mode': analysis['definition_mode'],
        'approximation_loss': analysis['remaining_scope'],
        'strict_original_equivalence_proven': analysis['strict_original_equivalence_proven'],
        'execution_allowed': False,
        'input_sha256': {k: v['input_sha256'] for k, v in default['data_contract']['series'].items()},
        'default_data_contract_state': default['state'],
        'comparison_data_contract_state': comparison['state'],
        'comparison_volume_tolerance_shares': tolerance,
        'comparison_triggered_count': data['triggered'],
        'snapshot_semantics': data['chart_snapshot_semantics'],
    }
    save(root / 'export-provenance.json', provenance)
    files = ('index.html', 'chart-data.json', 'chart-data.js')
    for name in files:
        backup = root / (name + '.original')
        if not backup.exists():
            shutil.copy2(root / name, backup)
    data['export_provenance'] = provenance
    for key in ('definition_mode', 'approximation_loss', 'execution_allowed', 'input_sha256', 'strict_original_equivalence_proven'):
        data[key] = provenance[key]
    save(root / 'chart-data.json', data)
    (root / 'chart-data.js').write_text('window.CHAN_CHART_DATA=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    default_text = '通过' if default['state'] == 'calculated' else '未通过'
    comparison_text = (f"{data['triggered']}个研究触发" if comparison['state'] == 'calculated' else '校验未通过')
    footer = f'量校验：默认1股容差{default_text}；{tolerance:g}股容差对照：{comparison_text}。V2尚未证明严格原文等价。<br>标记位置可能早于确认时间；候选不等于当前新买卖点，旧端点不代表最新行情。'
    html = (root / 'index.html.original').read_text(encoding='utf-8')
    original = '图形按截止时点计算；标记位置可能早于确认时间。候选不等于确认买点，旧端点不代表最新高点。'
    assert original in html
    html = html.replace(original, footer)
    html = html.replace("priceLineColor:'#da454b'", "priceLineColor:D.change>=0?'#da454b':'#16947f'")
    (root / 'index.html').write_text(html, encoding='utf-8')
    patch, changes = [], {}
    for name in files:
        original_path, modified = root / (name + '.original'), root / name
        patch.extend(difflib.unified_diff(original_path.read_text(encoding='utf-8').splitlines(True), modified.read_text(encoding='utf-8').splitlines(True), fromfile=name + '.original', tofile=name))
        changes[name] = {'original_sha256': sha(original_path), 'modified_sha256': sha(modified)}
    (root / 'export.patch').write_text(''.join(patch), encoding='utf-8')
    save(root / 'export-changes.json', changes)
    (root / 'ROLLBACK.ps1').write_text("$ErrorActionPreference = 'Stop'\nforeach ($name in @('index.html','chart-data.json','chart-data.js')) {\n  Copy-Item -LiteralPath (Join-Path $PSScriptRoot ($name + '.original')) -Destination (Join-Path $PSScriptRoot $name) -Force\n}\n", encoding='utf-8')
    print(json.dumps({'prepared': True, 'name': data['name'], 'comparison': comparison['state']}, ensure_ascii=False))


def verify(root):
    from PIL import Image, PngImagePlugin
    summary = load(root / 'summary.json')
    provenance = load(root / 'export-provenance.json')
    algorithm = load(root / 'algorithm-verification.json')
    assert algorithm['status'] == 'pass' and algorithm['day_replay_final_matches_snapshot']
    browser = {period: load(root / f'browser-{period}.json') for period in ('all', 'day')}
    assert all(p['ready'] and not p['errors'] for p in browser.values())
    assert len(browser['all']['proof']) == 3 and len(browser['day']['proof']) == 1
    images = []
    for kind, minimum in (('三周期', (1800, 1600)), ('日线', (1800, 1000))):
        path = root / f"{summary['name']}_V2_{kind}.png"
        with Image.open(path) as im:
            assert im.format == 'PNG'
            im.load()
            assert im.width >= minimum[0] and im.height >= minimum[1]
            metadata = PngImagePlugin.PngInfo()
            metadata.add_itxt('Description', json.dumps(provenance, ensure_ascii=False))
            im.save(path, pnginfo=metadata)
            dimensions = list(im.size)
            if kind == '三周期':
                preview = im.copy()
                preview.thumbnail((1280, 1280))
                preview.save(root / 'preview.png', optimize=True)
        with Image.open(path) as im:
            im.verify()
        images.append({'file': path.name, 'dimensions': dimensions, 'bytes': path.stat().st_size, 'sha256': sha(path)})
    with tempfile.TemporaryDirectory(prefix='chanlun-chart-rollback-') as directory:
        temporary = Path(directory)
        files = ('index.html', 'chart-data.json', 'chart-data.js')
        for name in files:
            for suffix in ('', '.original'):
                shutil.copy2(root / (name + suffix), temporary / (name + suffix))
        shutil.copy2(root / 'ROLLBACK.ps1', temporary / 'ROLLBACK.ps1')
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(temporary / 'ROLLBACK.ps1')], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        restored = {name: sha(temporary / name) == sha(root / (name + '.original')) for name in files}
        assert all(restored.values())
    verification = {'status': 'pass', 'algorithm': algorithm, 'browser': browser, 'images': images, 'provenance': provenance,
                    'rollback_on_separate_copy': {'exit_code': result.returncode, 'restored_hashes_match': restored}}
    save(root / 'verification.json', verification)
    save(root / 'VERIFICATION.txt', verification)
    lines = [f"# {summary['name']}（{summary['symbol'][2:]}）V2独立运行", '',
             f"行情截止：{summary['last_close_time']}，北京时间。TDX不复权收盘{summary['price']:.2f}元，较前收{summary['change_pct']:+.2f}%。图表使用TradingView Lightweight Charts本地渲染。", '',
             '| 周期 | 全量范围 | K线数 | 最近L1中枢核心 | 尾部线段 |', '|---|---|---:|---|---|']
    for period, p in summary['periods'].items():
        center, segment = p['latest_center'], p['last_segment']
        core = f"{center['zd']:.2f}—{center['zg']:.2f}" if center else '暂无'
        tail = f"{segment['direction']} / {segment['state']} / {segment['start_price']:.2f}→{segment['end_price']:.2f}" if segment else '暂无'
        lines.append(f"| {period} | {p['first_close']}—{p['last_close']} | {p['bars']:,} | {core} | {tail} |")
    replay = summary['daily_replay']
    lines += ['', f"日线从最早可得记录逐日回放，共{replay['bars']:,}根K线、{replay['events']}条结构事件，最终状态与全量快照一致。三个周期内部结构证书均通过。", '',
              f"默认1股容差：{summary['multiframe_default_state']}；显式{summary['volume_tolerance_shares']:g}股容差对照：{summary['multiframe_explicit_tolerance_state']}，触发数{summary['triggered_count']}。", '',
              '对照在实际分钟历史覆盖的重叠范围进行，默认结果保留。更早的日线终结段若缺少分钟历史，不能获得多周期确认。', '',
              '下列为历史锚点仍有效的研究候选，不自动代表最新交易信号：', '']
    for period, p in summary['periods'].items():
        for signal in p['active_candidates'][:3]:
            lines.append(f"- {period} L{signal['rank']} {signal['class']}：锚点{signal['anchor_time']}、价格{signal['price']:.2f}；{signal['available_time']}可见；状态{signal['state']}，失效边界{signal['invalidation']:.2f}。")
    lines += ['', '图中显示最近180根日线、280根30分钟及420根5分钟；计算使用全部可取历史。L1/L2是结构递归秩，不能直接等同于日线/30分钟理论级别。V2采用声明的同级别分解规则，尚未证明严格原文等价；execution_allowed=false。']
    (root / f"{summary['name']}_运行说明.md").write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'pass', 'images': images}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'verify'))
    parser.add_argument('--run-dir', required=True, type=Path)
    args = parser.parse_args()
    (prepare if args.action == 'prepare' else verify)(args.run_dir.resolve())
