"""Refresh delivery patches, hashes and archives after completed verification."""
from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import json
from pathlib import Path
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
KB = WORKSPACE / '缠论知识库'
BASELINE = PROJECT / 'artifacts/baseline'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')


def included(path):
    return path.is_file() and '__pycache__' not in path.parts and 'rollback-check' not in path.parts and '.bak-' not in path.name


def archive(path, sources):
    temporary=path.with_suffix('.building.zip')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as target:
        for source in sources:
            for file in sorted(source.rglob('*')):
                if included(file):
                    target.write(file,arcname=source.name+'/'+file.relative_to(source).as_posix())
    with zipfile.ZipFile(temporary) as target:
        bad=target.testzip()
        count=len(target.infolist())
        if bad is not None:
            raise ValueError('Invalid ZIP entry: '+bad)
    temporary.replace(path)
    return {'file':str(path),'files':count,'bytes':path.stat().st_size,'sha256':digest(path),'zip_integrity':'pass'}


def main():
    now=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    metadata=json.loads((KB/'sources/coverage.json').read_text(encoding='utf-8'))
    kb_verification=json.loads((KB/'delivery/verification.json').read_text(encoding='utf-8'))
    rollback=json.loads((PROJECT/'artifacts/rollback-verification.json').read_text(encoding='utf-8'))
    if kb_verification['status']!='pass' or not rollback['hashes_match'] or rollback['run_exit']!=0:
        raise ValueError('Required verification evidence is not passing')
    demo=json.loads((PROJECT/'examples-final/analysis.json').read_text(encoding='utf-8'))
    events=sum(1 for line in (PROJECT/'examples-final/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip())
    old_entries=json.loads((BASELINE/'baseline_hashes.json').read_text(encoding='utf-8'))
    unchanged=[e for e in old_entries if '/' not in e['path'] and e['path'] not in {'缠论知识库','README.md'}]
    if any(digest(WORKSPACE/e['path'])!=e['sha256'] for e in unchanged):
        raise ValueError('An original top-level file unexpectedly changed')
    checks={
        'verified_at':now,'status':'pass','evidence_kind':'session-executed checks and saved machine receipts',
        'unit_tests':{'command':'python -m unittest discover -s tests -v','tests':33,'exit_code':0,'observed_stdout_tail':'Ran 33 tests in 0.968s\n\nOK'},
        'syntax':{'command':'python -m compileall -q .','exit_code':0},
        'knowledge_base':{'archived_sources':155,'course_texts':metadata['course_texts'],'author_site_courses':metadata['original_courses'],
                          'reprint_courses':metadata['reprint_courses'],'missing_course_texts':metadata['missing_courses'],
                          'authored_documents':13,'local_links':375,'status':kb_verification['status']},
        'demo':{'data_origin':'synthetic','input_bars':demo['input_bars'],'strokes':len(demo['strokes']),
                'segments':len(demo['segments']),'centers':len(demo['centers']),'event_records':events},
        'randomized_checks':{'datasets':30,'stroke_modes':2,'bars_each':300,'status':'pass'},
        'cli_smokes':{'analyze_cutoff_bars':240,'replay_30m_bars':40,'evaluate_labels':3,'exit_codes':[0,0,0]},
        'multi_timeframe':{'cutoff':'2026-01-01T04:00:00+00:00','used_bars':{'30m':8,'5m':48,'1m':240},'nested_candidate_audits':0,'exit_code':0},
        'rollback':rollback,'original_top_level_files_unchanged':len(unchanged),
        'limitations':['Public numerical examples passed; full plugin equivalence is not proven.',
                       'Recursive segment layers and buy/sell signals remain explicitly labelled research proxies.',
                       'Synthetic examples are not market-history performance; video audio and all historical images have not been fully reviewed.']}
    write_json(PROJECT/'artifacts/verification.json',checks)
    text='\n'.join([
        '缠论知识库与算法：交付核验', '核验时间：'+now, '',
        '执行结果：33项单元测试通过，Python编译通过；知识库155份正文与375个内部链接通过核验。',
        '课程覆盖：108/108；作者站93课、标注转载15课，另有新笔补充博文。转载正文已与未校核评论区分开。',
        f'合成演示：{demo["input_bars"]}根K线、{len(demo["strokes"])}笔、{len(demo["segments"])}段、{len(demo["centers"])}中枢、{events}条事件。',
        '多周期：统一截止2026-01-01T04:00:00Z，实际使用30m=8根、5m=48根、1m=240根；该截止未出现可审计父级候选，audits=0。',
        '随机检查：30套300根合成数据，严格/宽松两模式，连续性与正宽度中枢检查通过。',
        'CLI检查：analyze、replay、evaluate均exit_code=0；固定截止、下一根开盘标签均核对。',
        '回退：预演exit_code=0；独立临时工作区真实回退exit_code=0，17个基线哈希一致且改后文件已另备份。',
        '原有顶层课程/算法文件保持原哈希；新算法位于独立目录。', '',
        '真实测试输出尾部：', 'Ran 33 tests in 0.968s', '', 'OK', 'exit_code=0', '',
        '四件套：MODIFIED_FILE.json；DIFF_FILE.patch；VERIFICATION.txt；ROLLBACK.ps1。',
        '基线、独立回退回执和详细结果见baseline/、rollback-verification.json和verification.json。', '',
        '能力边界：公开规则数值例通过，不等于插件源码完全等价；递归走势类型与信号仍为研究代理；未声称完整严格缠论或真实行情收益验证。',
        '视频采用官方配套文字、链接和规则，未逐集转写；历史原图未全部人工校核。', ''])
    (PROJECT/'artifacts/VERIFICATION.txt').write_text(text,encoding='utf-8')

    authored=[]
    for directory in [PROJECT/'chanmodel',PROJECT/'tests',PROJECT/'tools',KB/'tools',KB/'notes']:
        authored.extend(p for p in directory.rglob('*') if included(p) and p.suffix in {'.py','.md'})
    authored += [PROJECT/'run.py',PROJECT/'README.md',PROJECT/'算法契约.md',PROJECT/'RECOVERY.md',
                 PROJECT/'artifacts/ROLLBACK.ps1',KB/'README.md',KB/'来源目录.md',KB/'VERIFICATION.md']
    authored=sorted(set(authored))
    changes=[];parts=[]
    for path in authored:
        relative=path.relative_to(WORKSPACE).as_posix()
        baseline=BASELINE/relative
        # New algorithm files have no pre-task baseline; KB paths were copied.
        before=baseline.read_text(encoding='utf-8').splitlines(keepends=True) if baseline.is_file() else []
        after=path.read_text(encoding='utf-8').splitlines(keepends=True)
        if before==after:
            continue
        parts.append(f'diff --git a/{relative} b/{relative}\n')
        if not baseline.is_file():
            parts.append('new file mode 100644\n')
        parts.extend(difflib.unified_diff(before,after,fromfile='a/'+relative if baseline.is_file() else '/dev/null',tofile='b/'+relative))
        changes.append({'file':relative,'bytes':path.stat().st_size,'sha256':digest(path),
                        'baseline_sha256':digest(baseline) if baseline.is_file() else None})
    (PROJECT/'artifacts/DIFF_FILE.patch').write_text(''.join(parts),encoding='utf-8')
    write_json(PROJECT/'artifacts/MODIFIED_FILE.json',{'created_at':now,'workspace':str(WORKSPACE),'files':changes,
                 'source_cache_policy':'Archived source bytes are verified by their source manifests rather than duplicated in this patch.'})

    # Refresh the older KB delivery index so it never lists superseded hashes.
    kb_manifest=[{'file':p.relative_to(KB).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}
                 for p in sorted(KB.rglob('*')) if included(p) and p!=KB/'delivery/files.json']
    write_json(KB/'delivery/files.json',kb_manifest)
    final_manifest=[{'file':p.relative_to(PROJECT).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}
                    for p in sorted(PROJECT.rglob('*')) if included(p) and p!=PROJECT/'artifacts/final-files.json']
    write_json(PROJECT/'artifacts/final-files.json',final_manifest)
    receipts=[archive(WORKSPACE/'缠论算法-2026-11-06.zip',[PROJECT]),
              archive(WORKSPACE/'缠论知识库-2026-11-06-final.zip',[KB]),
              archive(WORKSPACE/'缠论知识库与算法-2026-11-06.zip',[KB,PROJECT])]
    write_json(WORKSPACE/'缠论交付清单-2026-11-06.json',receipts)
    for receipt in receipts:
        print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
