#!/usr/bin/env python3
"""Transcribe a local Chinese lecture with a cached faster-whisper model."""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from faster_whisper import BatchedInferencePipeline, WhisperModel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--chunk-seconds", type=int, default=600)
    parser.add_argument("--start-seconds", type=int, default=0)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    if args.chunk_seconds < 60:
        parser.error("--chunk-seconds must be at least 60")
    ffmpeg = shutil.which(args.ffmpeg) or args.ffmpeg
    ffprobe = shutil.which(args.ffprobe) or args.ffprobe
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(args.video)],
        capture_output=True, text=True, check=True,
    )
    duration = float(probe.stdout.strip())
    dll_handles = []
    if args.device == "cuda" and os.name == "nt":
        spec = importlib.util.find_spec("nvidia")
        if spec and spec.submodule_search_locations:
            for root in spec.submodule_search_locations:
                for p in Path(root).glob("*/bin"):
                    dll_handles.append(os.add_dll_directory(str(p)))
                    os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")
            for name in ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll"):
                candidates = [p for root in spec.submodule_search_locations
                              for p in Path(root).glob(f"*/bin/{name}")]
                if candidates:
                    dll_handles.append(ctypes.WinDLL(str(candidates[0])))
    model = WhisperModel(args.model, device=args.device,
                         compute_type="int8_float16" if args.device == "cuda" else "int8")
    pipeline = BatchedInferencePipeline(model=model)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with args.output.open("a" if args.append else "w", encoding="utf-8", newline="\n") as stream:
        if not args.append:
            stream.write(f"# language=zh model={args.model} device={args.device}\n")
        with tempfile.TemporaryDirectory(prefix="chanlun-audio-") as temp_dir:
            for chunk_index, offset in enumerate(range(args.start_seconds, int(duration + args.chunk_seconds), args.chunk_seconds)):
                if offset >= duration:
                    break
                chunk_path = Path(temp_dir) / f"chunk_{chunk_index:04d}.wav"
                result = subprocess.run(
                    [ffmpeg, "-v", "error", "-y", "-ss", str(offset), "-t",
                     str(args.chunk_seconds), "-i", str(args.video), "-vn", "-ac", "1",
                     "-ar", "16000", "-c:a", "pcm_s16le", str(chunk_path)],
                    capture_output=True, text=True,
                )
                if result.returncode:
                    raise RuntimeError(f"ffmpeg failed at {offset}s: {result.stderr.strip()}")
                if not chunk_path.exists() or chunk_path.stat().st_size < 1000:
                    break
                segments, info = pipeline.transcribe(
                    str(chunk_path), language="zh", vad_filter=True,
                    batch_size=args.batch_size, beam_size=5,
                    repetition_penalty=1.1, no_repeat_ngram_size=6,
                    initial_prompt="简体中文，技术分析课程。缠论、分型、笔、线段、中枢、背驰。",
                    vad_parameters={"min_silence_duration_ms": 700},
                )
                chunk_count = 0
                for segment in segments:
                    start = int(offset + segment.start)
                    end = int(offset + segment.end)
                    stream.write(f"[{start // 3600:02d}:{start % 3600 // 60:02d}:{start % 60:02d} - "
                                 f"{end // 3600:02d}:{end % 3600 // 60:02d}:{end % 60:02d}] "
                                 f"{segment.text.strip()}\n")
                    count += 1
                    chunk_count += 1
                stream.flush()
                print(f"chunk={chunk_index + 1} offset={offset}s segments={chunk_count} "
                      f"total={count}", flush=True)
                if info.duration < args.chunk_seconds:
                    break
    print(f"done segments={count} output={args.output}")


if __name__ == "__main__":
    main()
