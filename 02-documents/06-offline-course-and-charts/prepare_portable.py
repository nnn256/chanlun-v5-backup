"""Prepare the portable full-study CLI, PDF, and regression bundle."""
from pathlib import Path

HERE=Path(__file__).resolve().parent
template=HERE/'tools'/'complete_study_view.html'
contents=template.read_text(encoding='utf-8')
old="$('period').value=periods.includes('day')?'day':periods[0];"
new="$('period').value=periods.includes('5m')?'5m':periods[0];"
if contents.count(old)!=1:
    raise SystemExit('expected one timeframe default expression in standalone full-study template')
template.write_text(contents.replace(old,new),encoding='utf-8')
print('portable period selector defaults to 5m structural detail')
