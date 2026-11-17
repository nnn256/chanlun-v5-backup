#!/usr/bin/env python3
"""Render the authored Chanlun course to an animated, narrated H.264 video.

Narration uses the installed Windows SAPI Chinese voice. Only newly authored
lesson text is synthesized. Visual examples are educational synthetic drawings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
FFDIR = Path("C:/Users/li/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin")
FFMPEG = FFDIR / "ffmpeg.exe"
FFPROBE = FFDIR / "ffprobe.exe"
W, H = 1280, 720
FPS = 12
BG = "#102B2C"
SURFACE = "#163638"
WHITE = "#F6F4E9"
MUTED = "#A5BEBA"
TEAL = "#5ED3B8"
CORAL = "#F2937D"
GRID = "#28504F"
GOLD = "#EBD596"
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
BOLD_PATH = "C:/Windows/Fonts/msyhbd.ttc"
FONTS = {size: ImageFont.truetype(FONT_PATH, size) for size in (20, 22, 24, 26, 28, 30, 32, 34, 36, 40, 44, 48, 52)}
BOLD = {size: ImageFont.truetype(BOLD_PATH, size) for size in (22, 24, 26, 28, 30, 32, 34, 36, 40, 44, 48, 52)}


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def duration(path):
    output = subprocess.check_output([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(output)["format"]["duration"])


def wrap(text, font, max_width):
    result, line = [], ""
    for char in text:
        if char == "\n":
            result.append(line)
            line = ""
        elif font.getlength(line + char) > max_width and line:
            result.append(line)
            line = char
        else:
            line += char
    if line:
        result.append(line)
    return result


def text(draw, xy, value, size=28, fill=WHITE, bold=False, width=None, spacing=8):
    font = (BOLD if bold else FONTS)[size]
    lines = wrap(str(value), font, width or 1200)
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += size + spacing
    return y


def line(draw, points, progress=1.0, color=TEAL, width=5):
    if len(points) < 2:
        return
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    remaining = sum(lengths) * max(0.0, min(1.0, progress))
    for a, b, dist in zip(points, points[1:], lengths):
        if remaining <= 0:
            break
        portion = min(1.0, remaining / max(dist, 0.001))
        end = (a[0] + (b[0] - a[0]) * portion, a[1] + (b[1] - a[1]) * portion)
        draw.line([a, end], fill=color, width=width)
        if portion == 1:
            draw.ellipse((b[0]-4, b[1]-4, b[0]+4, b[1]+4), fill=color)
        remaining -= dist


def axes(draw, left=90, top=210, right=1190, bottom=535):
    for j in range(5):
        y = top + (bottom-top)*j/4
        draw.line((left,y,right,y),fill=GRID,width=1)
    draw.line((left,top,left,bottom),fill=MUTED,width=1)
    draw.line((left,bottom,right,bottom),fill=MUTED,width=1)


def normalized(values, left=110, top=220, right=1170, bottom=515):
    lo, hi = min(values), max(values)
    span = max(1, hi-lo)
    return [(left+(right-left)*i/(len(values)-1), bottom-(value-lo)/span*(bottom-top)) for i,value in enumerate(values)]


def candle(draw, x, high, low, open_, close_, yscale, width=30, alpha=False):
    color = CORAL if close_ >= open_ else TEAL
    yhigh, ylow, yo, yc = (yscale(v) for v in (high,low,open_,close_))
    draw.line((x,yhigh,x,ylow),fill=color,width=3)
    draw.rectangle((x-width/2,min(yo,yc),x+width/2,max(yo,yc)+2),fill=color)


def draw_diagram(image, lesson, progress):
    draw = ImageDraw.Draw(image)
    kind = str(lesson.get("kind", lesson.get("id", "overview"))).lower()
    phase = min(1, progress * 1.4)

    if any(x in kind for x in ("inclusion", "include", "merge", "contain")):
        scale = lambda v: 520-(v-3)*32
        axes(draw)
        candle(draw,250,10,5,6,9,scale,65)
        candle(draw,400,9,6,8,7,scale,65)
        text(draw,(195,530),"[5, 10]",24,MUTED)
        text(draw,(350,530),"[6, 9]",24,MUTED)
        draw.line((540,360,700,360),fill=TEAL,width=5)
        draw.polygon([(700,360),(681,350),(681,370)],fill=TEAL)
        if phase > .3:
            candle(draw,870,10,6,7,9,scale,80)
            text(draw,(760,530),"向上合并：[6, 10]",28,TEAL,True)
        text(draw,(645,252),"高点取高，低点也取高",26,WHITE,width=500)
        text(draw,(155,218),"已经知道向上时",26,GOLD)
    elif "fractal" in kind:
        axes(draw)
        scale=lambda v: 500-(v-3)*24
        candle(draw,350,8,5,6,7,scale,74)
        if phase>.25: candle(draw,630,12,8,9,11,scale,74)
        if phase>.55: candle(draw,910,9,6,8,7,scale,74)
        if phase>.65:
            draw.polygon([(630,237),(618,216),(642,216)],fill=GOLD)
            text(draw,(555,177),"顶分型",30,GOLD,True)
            text(draw,(785,530),"右侧完成后才能确认",26,TEAL)
        text(draw,(365,525),"左",24,MUTED)
        text(draw,(615,525),"中",24,MUTED)
        text(draw,(900,525),"右",24,MUTED)
    elif "macd" in kind:
        axes(draw,top=240,bottom=490)
        draw.line((110,410,1170,410),fill=MUTED,width=2)
        count=36
        upto=int(count*phase)
        for i in range(upto):
            value=math.sin(i*.25)*60+math.sin(i*.6)*13
            x=125+i*29
            draw.rectangle((x,min(410,410-value),x+14,max(410,410-value)),fill=CORAL if value>0 else TEAL)
        points=[(125+i*29,350-45*math.sin(i*.13)) for i in range(count)]
        line(draw,points,phase,WHITE,4)
        line(draw,[(x,y+22*math.sin(i*.19+.7)) for i,(x,y) in enumerate(points)],phase,GOLD,4)
        text(draw,(970,418),"零轴",24,MUTED)
        text(draw,(122,523),"DIF 快慢EMA差值",24,WHITE)
        text(draw,(470,523),"DEA DIF平滑",24,GOLD)
        text(draw,(820,523),"柱体 两线差值",24,TEAL)
    elif "diverg" in kind or "force" in kind:
        axes(draw,top=235,bottom=480)
        points=normalized([3,8,5,10,7,11],top=230,bottom=430)
        line(draw,points,phase,WHITE,5)
        if phase>.45:
            draw.rounded_rectangle((230,463,410,530),radius=4,fill=TEAL)
            draw.rounded_rectangle((820,493,1000,530),radius=4,fill=TEAL)
            text(draw,(250,430),"前段动力",22,MUTED)
            text(draw,(835,460),"后段动力更弱",22,MUTED)
            text(draw,(705,192),"价格仍创新高",28,GOLD,True)
    elif any(x in kind for x in ("multi", "level", "nest")):
        labels=["大级别：背景", "操作级：结构", "次级别：确认", "更小级：触发"]
        for i,label in enumerate(labels):
            if phase > i/5:
                x=110+i*278; y=245+i*35
                draw.rectangle((x,y,x+240,y+100),outline=TEAL if i%2==0 else GOLD,width=3)
                text(draw,(x+18,y+31),label,22,WHITE,True)
                if i:
                    draw.line((x-38,y+20,x-5,y+35),fill=MUTED,width=3)
        text(draw,(270,520),"低级别触发，不能凭空创造高级别买点",28,MUTED)
    elif "third" in kind or "3buy" in kind:
        axes(draw)
        draw.rectangle((110,340,710,455),fill=SURFACE,outline=TEAL,width=2)
        text(draw,(140,373),"中枢",28,MUTED)
        draw.line((710,340,1165,340),fill=GRID,width=2)
        points=[(120,420),(250,355),(360,430),(470,355),(595,440),(800,220),(950,316),(1140,215)]
        line(draw,points,phase,WHITE,5)
        if phase>.72:
            draw.ellipse((938,304,962,328),outline=GOLD,width=4)
            text(draw,(840,356),"回拉不回中枢",28,GOLD,True)
            text(draw,(950,270),"8",26,GOLD,True)
        text(draw,(780,177),"12",26,WHITE,True)
        text(draw,(1070,343),"ZG = 7",22,TEAL)
    elif "second" in kind or "2buy" in kind:
        axes(draw)
        points=[(130,245),(320,495),(570,300),(810,425),(1150,225)]
        line(draw,points,phase,WHITE,5)
        draw.line((300,495,1140,495),fill=GRID,width=2)
        text(draw,(250,505),"一买候选低点",24,MUTED)
        text(draw,(326,453),"10",26,GOLD,True)
        if phase>.4: text(draw,(550,250),"16",26,WHITE,True)
        if phase>.6:
            draw.ellipse((800,415,820,435),outline=GOLD,width=4)
            text(draw,(810,375),"11",26,GOLD,True)
            text(draw,(675,450),"第一次回调，守住结构低点",26,TEAL)
    elif "first" in kind or "1buy" in kind:
        axes(draw)
        points=normalized([18,9,14,6,10,4,9,6,14],top=240,bottom=505)
        line(draw,points,phase,WHITE,5)
        if phase>.6:
            p=points[5]; draw.ellipse((p[0]-10,p[1]-10,p[0]+10,p[1]+10),outline=GOLD,width=4)
            text(draw,(p[0]-110,p[1]+15),"一买候选",26,GOLD,True)
        text(draw,(760,230),"先有下跌趋势背景",26,MUTED)
    elif "center" in kind or "zhongshu" in kind:
        axes(draw)
        # Three continuous legs [1,8], [3,8], [3,7] share exactly [3,7].
        scale=lambda value: 500-(value-1)*37
        draw.rectangle((180,scale(7),1030,scale(3)),fill=SURFACE,outline=TEAL,width=2)
        pts=[(130,scale(1)),(440,scale(8)),(710,scale(3)),(1030,scale(7))]
        line(draw,pts,phase,WHITE,5)
        text(draw,(1050,scale(7)-15),"ZG = 7",26,TEAL,True)
        text(draw,(1050,scale(3)-15),"ZD = 3",26,TEAL,True)
        text(draw,(420,scale(8)-42),"GG = 8",22,WHITE)
        text(draw,(112,scale(1)+4),"DD = 1",22,WHITE)
        text(draw,(425,340),"共同重叠区 [3, 7]",30,TEAL,True)
        text(draw,(220,528),"核心边界 ZD / ZG       整体极值 DD / GG",24,MUTED)
    elif "trend" in kind or "type" in kind:
        axes(draw)
        for i,(x,y) in enumerate([(160,402),(520,330),(900,245)]):
            if phase>i/4:
                draw.rectangle((x,y,x+180,y+78),fill=SURFACE,outline=TEAL,width=2)
                text(draw,(x+24,y+23),f"中枢 {i+1}",24,TEAL)
        line(draw,[(120,505),(280,395),(360,440),(650,310),(730,365),(1050,220),(1150,270)],phase,WHITE,5)
        text(draw,(200,195),"同级别中枢依次抬高，才支持上行判断",28,GOLD)
    elif "segment" in kind:
        axes(draw)
        pts=[(140,500),(360,260),(540,420),(760,230),(970,350),(1140,200)]
        draw.rectangle((230,330,740,415),fill=SURFACE,outline=GRID,width=1)
        line(draw,pts,phase,WHITE,4)
        if phase>.6:
            line(draw,[(140,500),(760,230)],min(1,(phase-.6)*2.5),TEAL,9)
        text(draw,(220,195),"至少前三笔有重叠，还要等破坏确认",28,GOLD)
        text(draw,(820,485),"反向一笔 ≠ 已经反转",24,MUTED)
    elif "stroke" in kind or "bi" == kind:
        axes(draw)
        pts=[(140,500),(400,245),(680,435),(1100,200)]
        line(draw,pts,phase,WHITE,5)
        for i,(x,y) in enumerate(pts):
            if phase>i/4:
                draw.ellipse((x-9,y-9,x+9,y+9),fill=TEAL if i%2==0 else CORAL)
                text(draw,(x-25,y+18 if i%2==0 else y-44),"底" if i%2==0 else "顶",26,TEAL if i%2==0 else CORAL,True)
        text(draw,(230,195),"底接顶是上笔，顶接底是下笔",28,GOLD)
    elif any(x in kind for x in ("time", "causal", "algorithm", "replay")):
        axes(draw)
        pts=normalized([5,9,6,11,4,8,6,13],top=245,bottom=480)
        line(draw,pts,phase,WHITE,5)
        if phase>.65:
            draw.line((pts[4][0],470,pts[4][0],540),fill=CORAL,width=2)
            draw.line((pts[6][0],470,pts[6][0],540),fill=TEAL,width=2)
            text(draw,(pts[4][0]-100,540),"极值发生",24,CORAL)
            text(draw,(pts[6][0]-90,540),"证据可用",24,TEAL)
            draw.line((pts[4][0],520,pts[6][0],520),fill=GOLD,width=3)
    elif any(x in kind for x in ("small", "turn", "risk")):
        axes(draw)
        pts=normalized([3,7,5,8,6,9,7,17,22,16,8,4],top=235,bottom=510)
        line(draw,pts,phase,WHITE,5)
        text(draw,(220,195),"重要位置 + 小级别变化 → 风险预警",28,GOLD)
        if phase>.7:
            draw.rectangle((700,235,1000,515),outline=CORAL,width=3)
            text(draw,(780,525),"重新检查父级结构",24,CORAL)
    else:
        labels=["K线", "分型", "笔", "线段", "中枢", "走势", "背驰", "买卖点"]
        for i,label in enumerate(labels):
            if phase>i/10:
                x=100+i*145
                color=TEAL if i in (0,4,7) else WHITE
                draw.ellipse((x,320,x+18,338),fill=color)
                text(draw,(x-14,365),label,26,color,True)
                if i: draw.line((x-125,329,x-10,329),fill=GRID,width=3)
        text(draw,(230,463),"先定级别，再认结构，最后等确认",36,GOLD,True)


def caption_parts(narration):
    sentences = [x.strip() for x in re.split(r"(?<=[。！？；])", narration) if x.strip()]
    chunks=[]
    for sentence in sentences:
        while len(sentence)>42:
            cutoff = max(sentence.rfind("，",0,42),sentence.rfind("、",0,42))
            if cutoff<14: cutoff=36
            else: cutoff += 1
            chunks.append(sentence[:cutoff]);sentence=sentence[cutoff:]
        if sentence: chunks.append(sentence)
    return chunks or [narration]


def compose_frame(lesson, chapter, total, t, clip_duration, captions):
    image=Image.new("RGB",(W,H),BG)
    draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,7,H),fill=TEAL)
    text(draw,(62,34),f"缠论 · 一次串起来",22,TEAL,True)
    text(draw,(790,36),"教学示意 · 非真实行情",20,MUTED)
    text(draw,(1055,34),f"{chapter:02d} / {total:02d}",22,MUTED)
    title=str(lesson.get("title","缠论结构"))
    title_size=44 if len(title)>15 else 48
    text(draw,(62,83),title,title_size,WHITE,True,width=1150)
    summary=str(lesson.get("summary",lesson.get("kicker","")))
    if len(summary)>47: summary=summary[:47]+"…"
    text(draw,(65,149),summary,24,MUTED,width=1140)
    progress=t/max(clip_duration,.1)
    draw_diagram(image,lesson,progress)
    draw=ImageDraw.Draw(image)
    draw.rectangle((40,592,1240,688),fill="#0B2022")
    caption=captions[-1][2]
    for start,end,words in captions:
        if start<=t<end:
            caption=words;break
    lines=wrap(caption,FONTS[28],1120)
    start_y=620 if len(lines)==1 else 603
    for i,words in enumerate(lines[:2]):
        x=(W-FONTS[28].getlength(words))/2
        draw.text((x,start_y+i*36),words,font=FONTS[28],fill=WHITE)
    draw.rectangle((40,695,1240,699),fill=GRID)
    draw.rectangle((40,695,40+1200*progress,699),fill=TEAL)
    return image


def make_sapi_script():
    script = ROOT / "synthesize_sapi.ps1"
    script.write_text('''param([string]$LessonsPath,[string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$raw = Get-Content -LiteralPath $LessonsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($raw -is [Array]) { $lessons = $raw }
elseif ($raw.PSObject.Properties.Name -contains 'lessons') { $lessons = $raw.lessons }
else { throw 'Expected a lessons array.' }
$voice = New-Object -ComObject SAPI.SpVoice
$chosen = $voice.GetVoices() | Where-Object { $_.GetDescription() -like '*Huihui*' } | Select-Object -First 1
if (-not $chosen) { throw 'Installed Chinese SAPI voice not found.' }
$voice.Voice = $chosen
$voice.Rate = 1
$index = 0
foreach ($lesson in $lessons) {
  $index++
  $id = '{0:d2}' -f $index
  $target = Join-Path $OutputDirectory ($id + '.wav')
  if ((Test-Path -LiteralPath $target) -and (Get-Item -LiteralPath $target).Length -gt 1000) { continue }
  $stream = New-Object -ComObject SAPI.SpFileStream
  $stream.Format.Type = 22
  $stream.Open($target,3,$false)
  $voice.AudioOutputStream = $stream
  $words = [string]$lesson.narration
  if ($words.Length -lt 10) { throw ('Narration is missing at ' + $id) }
  [void]$voice.Speak($words)
  [void]$voice.WaitUntilDone(60000)
  $stream.Close()
  Write-Output ('speech=' + $id)
}
''',encoding="utf-8-sig")
    return script


def srt_stamp(seconds):
    ms=round(seconds*1000)
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"


def build(lessons_path, limit=None):
    lessons=json.loads(lessons_path.read_text(encoding="utf-8"))
    if isinstance(lessons,dict): lessons=lessons["lessons"]
    if limit: lessons=lessons[:limit]
    if not lessons: raise ValueError("No lessons to render")
    (ROOT/"audio").mkdir(exist_ok=True)
    (ROOT/"frames").mkdir(exist_ok=True)
    script=make_sapi_script()
    run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",script,
         "-LessonsPath",lessons_path.resolve(),"-OutputDirectory",(ROOT/"audio").resolve()])
    manifest=[];offset=0.;subtitles=[];subtitle_idx=1
    for index,lesson in enumerate(lessons,1):
        wav=ROOT/"audio"/f"{index:02d}.wav"
        mp3=ROOT/"audio"/f"{index:02d}.mp3"
        if not mp3.exists() or mp3.stat().st_size<1000 or mp3.stat().st_mtime<wav.stat().st_mtime:
            run([FFMPEG,"-v","error","-y","-i",wav,"-c:a","libmp3lame","-b:a","128k",mp3])
        spoken=duration(mp3);clip_duration=spoken+.8
        sentences=caption_parts(str(lesson["narration"]))
        total_chars=sum(len(s) for s in sentences)
        captions=[];start=0.
        for words in sentences:
            end=start+spoken*len(words)/total_chars
            captions.append((start,end,words))
            subtitles.append(f"{subtitle_idx}\n{srt_stamp(offset+start)} --> {srt_stamp(offset+end)}\n{words}\n")
            subtitle_idx+=1;start=end
        clip=ROOT/"frames"/f"chapter-{index:02d}.mp4"
        preview=compose_frame(lesson,index,len(lessons),clip_duration*.72,clip_duration,captions)
        preview.save(ROOT/"frames"/f"preview-{index:02d}.jpg",quality=86)
        count=math.ceil(clip_duration*FPS)
        command=[FFMPEG,"-v","error","-y","-f","rawvideo","-pixel_format","rgb24","-video_size",f"{W}x{H}",
                 "-framerate",str(FPS),"-i","pipe:0","-i",str(mp3),"-filter_complex","[1:a]apad=pad_dur=0.8[a]",
                 "-map","0:v","-map","[a]","-t",str(clip_duration),"-c:v","libx264","-preset","veryfast","-crf","23",
                 "-pix_fmt","yuv420p","-threads","4","-c:a","aac","-b:a","128k","-movflags","+faststart",str(clip)]
        process=subprocess.Popen([str(x) for x in command],stdin=subprocess.PIPE)
        try:
            for frame_idx in range(count):
                image=compose_frame(lesson,index,len(lessons),frame_idx/FPS,clip_duration,captions)
                process.stdin.write(image.tobytes())
            process.stdin.close()
            if process.wait(): raise RuntimeError(f"ffmpeg failed for chapter {index}")
        except BaseException:
            process.kill();raise
        actual=duration(clip)
        manifest.append({"id":lesson.get("id",str(index)),"title":lesson.get("title",""),
                         "audio":f"audio/{index:02d}.mp3","duration":spoken,"clip_duration":actual,
                         "start":offset,"end":offset+actual,"voice":"Microsoft Huihui Desktop - Chinese (Simplified)",
                         "subtitle_timing":"sentence timings estimated proportionally within synthesized speech"})
        offset+=actual
        print(f"chapter={index}/{len(lessons)} seconds={actual:.2f} total={offset:.2f}",flush=True)
    concat=ROOT/"frames"/"concat.txt"
    concat.write_text("\n".join(f"file 'chapter-{i:02d}.mp4'" for i in range(1,len(lessons)+1))+"\n",encoding="utf-8")
    output=ROOT/"缠论一遍串起来.mp4"
    run([FFMPEG,"-v","error","-y","-f","concat","-safe","0","-i",concat,"-c","copy","-movflags","+faststart",output])
    (ROOT/"缠论一次串起来-字幕.srt").write_text("\n".join(subtitles),encoding="utf-8-sig")
    summary={"voice_provider":"Windows SAPI offline","voice":"Microsoft Huihui Desktop - Chinese (Simplified)",
             "video":output.name,"video_seconds":duration(output),"width":W,"height":H,"fps":FPS,
             "synthetic_visual_examples":True,"chapters":manifest,
             "script_sha256":hashlib.sha256(lessons_path.read_bytes()).hexdigest()}
    (ROOT/"media_manifest.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (ROOT/"media.js").write_text("window.CHAN_MEDIA="+json.dumps(summary,ensure_ascii=False)+";\n",encoding="utf-8")
    contact=Image.new("RGB",(1280,math.ceil(len(lessons)/3)*240),"#ECF2EE")
    for i in range(len(lessons)):
        preview=Image.open(ROOT/"frames"/f"preview-{i+1:02d}.jpg")
        preview.thumbnail((426,240))
        contact.paste(preview,((i%3)*426,(i//3)*240))
    contact.save(ROOT/"frames"/"contact.jpg",quality=86)
    print(json.dumps({"video":str(output),"seconds":summary["video_seconds"],"bytes":output.stat().st_size},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lessons",type=Path,default=ROOT/"lessons.json")
    parser.add_argument("--limit",type=int)
    args=parser.parse_args()
    build(args.lessons,args.limit)
