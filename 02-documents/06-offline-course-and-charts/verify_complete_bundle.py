"""One-command release gate for the complete Chanlun course bundle."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify():
    manifest = load_json(HERE/'full-study-final/manifest.json')
    report = load_json(HERE/'full-study-final/report.json')
    multiframe = load_json(HERE/'multiframe-final.json')
    profile = load_json(HERE/'RULE_PROFILE.json')
    period_manifest = load_json(HERE/'period_catalog_manifest.json')
    single = load_json(HERE/'full_report.json')
    provenance_path = HERE/'SOURCE_PROVENANCE.json'
    provenance = load_json(provenance_path) if provenance_path.exists() else None
    assert manifest['execution_allowed'] is False
    assert report['reports']
    report_by_period = report['reports']
    assert all(item['certificate_audit']['state'] == 'passed' for item in report_by_period.values())
    assert all(item['strict_original_equivalence_proven'] is False for item in report_by_period.values())
    assert all(item['config']['second_policy'] == profile['second_policy'] for item in report_by_period.values())
    assert multiframe['data_contract']['state'] == 'verified'
    assert multiframe['execution_allowed'] is False
    assert all(point.get('state') != 'structurally_triggered_under_profile' for point in multiframe['signals'])
    assert profile['strict_original_equivalence_proven'] is False
    assert profile['execution_allowed'] is False
    assert period_manifest['meta']['period_order'] == ['1m','5m','15m','30m','60m','day','week','month','quarter','year']
    assert period_manifest['meta']['rank_is_not_period'] is True
    assert period_manifest['meta']['cross_group_evidence'].startswith('forbidden')
    if provenance is not None:
        assert provenance['identical_files'] >= 18
        assert all(row['source_sha256'] == row['bundled_sha256'] for row in provenance['files'])
    five = report_by_period.get('5m', next(iter(report_by_period.values())))
    assert len(single['hierarchy']['levels']) >= 3
    assert single['certificate_audit']['state'] == 'passed'
    assert len(five['hierarchy']['levels']) >= 2
    assert len(five['feature_sequences']) >= 10
    assert len(five['center_evolution']) >= 10
    assert len(five['decompositions']) >= 1
    assert len(five['signals']) >= 1
    assert len(multiframe['study_links']['small_to_large_audit']) >= 1
    final_manifest = load_json(HERE/'full-study-final/manifest.json')
    assert set(final_manifest['input_audits']) >= {'day','30m','5m'}
    for period, meta in report['input_audits'].items():
        assert 'synthetic_teaching' in meta.get('source','')
    assert (HERE/'缠论一遍串起来.mp4').stat().st_size > 1_000_000
    assert (HERE/'缠论大白话复习总结.pdf').stat().st_size > 100_000
    assert (HERE/'period-explained.html').is_file()
    assert (HERE/'period_catalog.js').stat().st_size > 1_000_000
    assert (HERE/'chart_explainer.js').is_file() and (HERE/'chart_narration.js').is_file()
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory(prefix='chanlun-data-rebuild-') as temp:
        rebuilt=Path(temp)/'data.js'
        command=[sys.executable,str(HERE/'build_full_data.py'),'--output',str(rebuilt)]
        result=subprocess.run(command,cwd=HERE,capture_output=True,text=True,encoding='utf-8')
        if result.returncode:raise AssertionError(result.stderr or result.stdout)
        compare=("const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');"
                 "const read=p=>{const w={};vm.runInNewContext(fs.readFileSync(p,'utf8'),{window:w});return w.CHAN_DATA};"
                 "const stable=x=>JSON.stringify(x,(k,v)=>v&&typeof v==='object'&&!Array.isArray(v)?"
                 "Object.keys(v).sort().reduce((o,key)=>(o[key]=v[key],o),{}):v);"
                 "assert.equal(stable(read(process.argv[1])),stable(read(process.argv[2])));")
        result=subprocess.run(['node','-e',compare,str(HERE/'data.js'),str(rebuilt)],
                              cwd=HERE,capture_output=True,text=True,encoding='utf-8')
        if result.returncode:raise AssertionError(result.stderr or result.stdout)
    return {
        'verified': True,
        'certificate_state': {period:item['certificate_audit']['state'] for period,item in report_by_period.items()},
        'single_series_levels': len(single['hierarchy']['levels']),
        'full_multiframe_levels': len(five['hierarchy']['levels']),
        'feature_sequences': len(five['feature_sequences']),
        'center_evolution': len(five['center_evolution']),
        'decompositions': len(five['decompositions']),
        'signals': len(five['signals']),
        'replay_observations': final_manifest['replay_schedule']['observations'],
        'multiframe_contract': multiframe['data_contract']['state'],
        'period_count': len(period_manifest['meta']['period_order']),
        'multiframe_links': {k:len(multiframe['study_links'].get(k,[])) for k in ('interval_nesting','small_to_large','small_to_large_audit')},
        'video_sha256': hashlib.sha256((HERE/'缠论一遍串起来.mp4').read_bytes()).hexdigest(),
        'snapshot_rebuild':'deep-structure-identical',
    }


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
