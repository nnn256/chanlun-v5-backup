"""Connect contextual narration to the self-contained native study view."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
TEMPLATE=HERE/'tools/complete_study_view.html'


def replace_once(text, old, new):
    if text.count(old)!=1:
        raise ValueError(f'expected exactly one native-view anchor: {old[:90]!r}')
    return text.replace(old,new,1)


def hydrate(template, packed):
    files={'__CHART_EXPLAINER__':'chart_explainer.js','__CHART_NARRATION_WIDGET__':'chart_narration.js',
           '__CHART_NARRATION_CSS__':'chart_narration.css'}
    result=template.replace('__COMPLETE_DATA__',packed)
    for marker,name in files.items():
        value=(HERE/name).read_text(encoding='utf-8')
        if name.endswith('.js'):value=value.replace('</script','<\\/script')
        result=result.replace(marker,value)
    return result


def prepare():
    text=TEMPLATE.read_text(encoding='utf-8')
    if '__CHART_EXPLAINER__' not in text:
        text=replace_once(text,'</style></head>', '</style><style>__CHART_NARRATION_CSS__</style><script>__CHART_EXPLAINER__</script><script>__CHART_NARRATION_WIDGET__</script></head>')
        text=replace_once(text,'<div class="grid"><section class="panel"><h2>六类候选',
            '<section id="full-narration" aria-label="当前周期与层级的中文讲解"></section><div class="grid"><section class="panel"><h2>六类候选')
        text=replace_once(text,"const data=JSON.parse(unpacked),NS=", "let narrator=null;const data=JSON.parse(unpacked),NS=")
        text=replace_once(text,"function get(){return data.frames[index];}",
            "function narrationContext(){const p=$('period').value,r=report();return {period:p,rank:rank(),as_of:r.input_count-1,bars:data.bars[p].slice(0,r.input_count),report:r,synthetic:data.manifest.synthetic,source_group:'同一细级源经OHLCV对账的多周期示例'};}function highlightNarration(id){for(const n of svg.querySelectorAll('[data-object-id]'))n.classList.toggle('cn-highlight',!!id&&n.dataset.objectId===String(id));}function get(){return data.frames[index];}")
        text=replace_once(text,"function rank(){return Number($('rank').value)||1;}","function rank(){return Math.max(0,Number($('rank').value)||0);}")
        text=replace_once(text,"n.addEventListener('click',()=>{$('evidence').textContent=txt(o);});return n;}",
            "n.dataset.objectId=String(o.id||'');n.setAttribute('tabindex','0');n.setAttribute('role','button');const choose=()=>{$('evidence').textContent=txt(o);narrator?.selectObject(o.class?'买卖点候选':o.certificate?'递归中枢':o.confirmation?'特征序列线段':o.completion?'完成分解':o.kind||'结构',o);};n.addEventListener('click',choose);n.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}});return n;}")
        text=replace_once(text,"function optionRanks(){const old=$('rank').value;$('rank').replaceChildren();for(const l of report().hierarchy.levels){const o=document.createElement('option');o.value=String(l.rank);o.textContent='L'+l.rank;$('rank').appendChild(o);}if([...$('rank').options].some(x=>x.value===old))$('rank').value=old;}",
            "function optionRanks(){const old=$('rank').value||'1';$('rank').replaceChildren();const ranks=report().hierarchy.levels.map(l=>l.rank);for(let k=0;k<=Math.max(8,...ranks);k++){const o=document.createElement('option');o.value=String(k);o.textContent='L'+k+(k===0?' 基础':ranks.includes(k)?'':' · 尚未形成');$('rank').appendChild(o);}$('rank').value=old;}")
        text=replace_once(text,"r.hierarchy.levels.find(x=>x.rank===rank())||r.hierarchy.levels[0],bars=", "r.hierarchy.levels.find(x=>x.rank===rank())||{rank:rank(),centers:[],completed_types:[]},bars=")
        text=replace_once(text,"$('monitor').textContent=txt({monitors:r.center_monitors,construction:r.construction_phases});}",
            "$('monitor').textContent=txt({monitors:r.center_monitors,construction:r.construction_phases});narrator?.update(narrationContext());}")
        text=replace_once(text,"},300);};optionRanks();draw();", "},300);};optionRanks();narrator=window.ChanChartNarrator?.mount($('full-narration'),narrationContext,{highlight:highlightNarration});draw();window.CHAN_FULL_APP={data,go,getReport:report,getNarrator:()=>narrator,getState:()=>({index,period:$('period').value,rank:rank()})};")
        TEMPLATE.write_text(text,encoding='utf-8')
    exported=HERE/'full-study-final/完整算法复习.html'
    original=exported.read_text(encoding='utf-8')
    found=re.search(r'<script id="packed" type="application/octet-stream">(.*?)</script>',original,re.S)
    if not found:raise ValueError('native complete view contains no packed data')
    packed=found.group(1)
    updated=hydrate(text,packed)
    assert re.search(r'<script id="packed" type="application/octet-stream">(.*?)</script>',updated,re.S).group(1)==packed
    exported.write_text(updated,encoding='utf-8')
    print(f'native narration embedded; original packed data preserved; packed_sha256={hashlib.sha256(packed.encode()).hexdigest()}')


if __name__=='__main__':prepare()
