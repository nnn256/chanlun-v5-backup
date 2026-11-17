"""Build an offline, read-only intraday research view from verified artifacts."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study_root',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--symbol',default='sz300949')
    parser.add_argument('--study-prefix',default='final-study',help='validated artifact directory prefix')
    args=parser.parse_args()
    root=args.study_root.resolve()
    target=args.output or root/'display/report-view.html'
    panels=[]
    cn=timezone(timedelta(hours=8))
    for period in ('1m','5m'):
        artifact=root/f'{args.study_prefix}-{period}'/args.symbol/period/'intraday-research.json.gz'
        raw=artifact.read_bytes()
        study=json.loads(gzip.decompress(raw))
        source=Path(study['source_receipt']['file'])
        source_raw=source.read_bytes()
        if hashlib.sha256(source_raw).hexdigest()!=study['source_receipt']['file_sha256']:
            raise ValueError('source file hash mismatch: '+str(source))
        decoded=gzip.decompress(source_raw) if source.suffix=='.gz' else source_raw
        if hashlib.sha256(decoded).hexdigest()!=study['source_receipt']['csv_sha256']:
            raise ValueError('source CSV hash mismatch: '+str(source))
        bars=[]
        for i,row in enumerate(csv.DictReader(decoded.decode('utf-8-sig').splitlines())):
            stamp=datetime.fromisoformat(row['closed_at']).astimezone(cn).isoformat()
            bars.append({'index':i,'time':stamp,**{k:float(row[k]) for k in ('open','high','low','close','volume')}})
        if len(bars)!=study['input_bars']:
            raise ValueError('bar count mismatch: '+period)
        panels.append({'period':period,'symbol':args.symbol,'bars':bars,'rows':study['evaluation']['rows'],
                       'summary':study['evaluation']['summary'],'config':study['config'],
                       'input_audit':study['input_audit'],'study_sha256':hashlib.sha256(raw).hexdigest(),
                       'csv_sha256':study['source_receipt']['csv_sha256'],
                       'source_file':str(source),'as_of':study['as_of'],'profile':study['profile'],
                       'limitations':study['limitations']})
    payload={'schema':'intraday.offline.display.v1','panels':panels,'execution_allowed':False,
             'display_semantics':'frozen local study; slider gates marker visibility by availability, not a fresh strategy rerun'}
    template=Path(__file__).with_name('intraday_report_view.html').read_text(encoding='utf-8')
    data=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(template.replace('/*__RESEARCH_DATA__*/',data),encoding='utf-8')
    receipt={'output':str(target.resolve()),'bytes':target.stat().st_size,
             'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
             'panels':[{'period':p['period'],'bars':len(p['bars']),'alerts':len(p['rows']),
                        'csv_sha256':p['csv_sha256'],'study_sha256':p['study_sha256']} for p in panels]}
    target.with_suffix('.receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
