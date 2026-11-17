"""Check the staged private-repository snapshot for credential material."""
import json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent/'staging'
PATTERNS={
    'github_token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,})\b'),
    'openai_style_key':re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}\b'),
    'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'jwt':re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b'),
    'url_credentials':re.compile(r'https?://[^\s/:@"\x27<>\\]{1,100}:[^\s/@"\x27<>\\]{4,100}@'),
}
BAD_NAMES={'.env','auth.json','credentials.json','.git-credentials','id_rsa','id_ed25519'}
TEXT={'.md','.txt','.py','.ps1','.cmd','.json','.jsonl','.js','.ts','.tsx','.cjs','.html','.yaml','.yml','.toml','.go','.sh','.sql','.log'}

def main():
    hits=[];bad=[];checked=0;large=[]
    for path in ROOT.rglob('*'):
        if not path.is_file() or '.git' in path.relative_to(ROOT).parts:continue
        if path.name in BAD_NAMES:bad.append(path.relative_to(ROOT).as_posix())
        if path.stat().st_size>80*1024*1024:large.append(path.relative_to(ROOT).as_posix())
        if path.suffix.lower() not in TEXT:continue
        try:body=path.read_text(encoding='utf-8')
        except UnicodeError:continue
        checked+=1
        for name,pattern in PATTERNS.items():
            for match in pattern.finditer(body):
                line=body.count('\n',0,match.start())+1
                hits.append({'path':path.relative_to(ROOT).as_posix(),'line':line,'kind':name})
    out={'text_files_checked':checked,'credential_pattern_hits':hits,'blocked_filenames':bad,
         'over_80MiB':large,'status':'pass' if not(hits or bad or large) else 'needs_review'}
    target=ROOT/'05-backup-manifests/upload-scan.json'
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
