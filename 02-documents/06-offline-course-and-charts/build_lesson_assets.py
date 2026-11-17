"""Derive player data and plain-language manuscript from one lesson source."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
lessons = json.loads((HERE / 'lessons.json').read_text(encoding='utf-8'))
(HERE / 'lessons.js').write_text('window.CHAN_LESSONS = ' + json.dumps(lessons, ensure_ascii=False, indent=2) + ';\n', encoding='utf-8')
(HERE / 'script.md').write_text('# 缠论，一遍串起来｜中文口播稿\n\n' + '\n\n---\n\n'.join(f"## {i+1}. {l['title']}\n\n{l['narration']}" for i,l in enumerate(lessons)), encoding='utf-8')
(HERE / 'outline.md').write_text('# 连贯讲解计划\n\n13章。沿用复习PDF的青绿主题；课程材料为已核对转写及总复习，全部配图为教学示意。\n\n'+'\n\n'.join(f"## {i+1}. {l['id']} / {l['title']}\n\n信息池：{l['summary']}\n\n- 一个连续节拍，口播估时约 {round(len(l['narration'])/4)} 秒。\n- 屏幕内容：{l['summary']}" for i,l in enumerate(lessons)), encoding='utf-8')
print(f'chapters={len(lessons)} narration_chars={sum(len(l["narration"]) for l in lessons)}')
