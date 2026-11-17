"""Read scoped data locations without loading their contents into memory."""
import collections,json,os
from pathlib import Path

OUT=Path(__file__).resolve().parent.parent
ROOTS={
    'd_v5':Path('D:/缠论V5'),
    'f_v5':Path('F:/ChanlunV5-20261115'),
    'intraday':Path('F:/ChanlunAlgorithmTests/2026-11-15-all-market-intraday'),
    'full_daily':Path('D:/ChanlunFullHistory-20261117'),
    'workspace_output':Path('C:/Users/li/Documents/ChatGPT/缠学习/output'),
}
SKIP={'.git','__pycache__','node_modules','.venv','extracted-verification','pyinstaller-work','before','live-workbench-before'}

def main():
    counts={}
    for label,root in ROOTS.items():
        groups=collections.defaultdict(lambda:{'files':0,'bytes':0})
        for base,dirs,files in os.walk(root):
            dirs[:]=[name for name in dirs if name not in SKIP]
            for name in files:
                path=Path(base)/name;rel=path.relative_to(root)
                if path.name.endswith('.incomplete'):continue
                key='/'.join(rel.parts[:2]) if len(rel.parts)>2 else rel.parts[0] if len(rel.parts)>1 else '_root'
                try:groups[key]['files']+=1;groups[key]['bytes']+=path.stat().st_size
                except OSError:pass
        counts[label]={'root':str(root),'groups':dict(sorted(groups.items()))}
    (OUT/'storage-inventory.json').write_text(json.dumps(counts,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(counts,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
