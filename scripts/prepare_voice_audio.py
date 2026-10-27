"""从本地视频提取音轨；只写入新建的 D 盘工作目录，不删除或覆盖原文件。"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path


def run(command, env=None):
    return subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def candidates(log, duration, minimum=3.0, maximum=9.0):
    # 静音边界仅用于找候选片段，不能据此认定说话人就是 Saber。
    silence = []
    start = None
    for kind, value in re.findall(r"silence_(start|end):\s*([0-9.]+)", log):
        if kind == "start":
            start = float(value)
        else:
            silence.append((start if start is not None else 0, float(value)))
            start = None
    if start is not None:
        silence.append((start, duration))
    result, previous = [], 0.0
    for left, right in silence + [(duration, duration)]:
        # 保留不足 0.8 秒的句内停顿，避免短句全部被切成不到三秒的碎片。
        if right - left < 0.8 and right < duration:
            continue
        while left - previous >= minimum:
            end = min(left, previous + maximum)
            result.append((round(previous, 3), round(end - previous, 3)))
            previous = end
        previous = max(previous, right)
    return result


def prepare(source, root, ffmpeg, ffprobe, start=0.0, duration=600.0, separate=False):
    source, root = Path(source).resolve(strict=True), Path(root).resolve()
    if not source.is_file():
        raise ValueError("输入必须是本地音频或视频文件")
    if start < 0 or not 3 <= duration <= 1800:
        raise ValueError("开始时间不能为负，单次处理时长必须为 3—1800 秒")
    stem = re.sub(r"[^\w-]", "_", source.stem)[:60] or "audio"
    output = root / "processed" / f"{stem}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    output.mkdir(parents=True, exist_ok=False)
    audio = output / "original_audio.wav"
    run([ffmpeg,"-hide_banner","-nostdin","-v","error","-n","-ss",str(start),"-i",str(source),
         "-t",str(duration),"-map","0:a:0","-vn","-ac","2","-ar","44100","-c:a","pcm_s16le",str(audio)])
    vocals = audio
    if separate:
        environment = os.environ.copy()
        environment["HF_HOME"] = str(root / "cache" / "huggingface")
        environment["TORCH_HOME"] = str(root / "cache" / "torch")
        run([sys.executable,"-m","demucs.separate","--two-stems","vocals","-n","htdemucs",
             "--segment","6","-d","cuda","-o",str(output/"separated"),str(audio)], env=environment)
        vocals = output / "separated" / "htdemucs" / "original_audio" / "vocals.wav"
        if not vocals.is_file():
            raise ValueError("人声分离没有生成 vocals.wav，请检查独立环境的 Demucs")
    metadata = json.loads(run([ffprobe,"-v","error","-show_entries","format=duration","-of","json",str(vocals)]).stdout)
    seconds = float(metadata["format"]["duration"])
    detected = run([ffmpeg,"-hide_banner","-nostdin","-i",str(vocals),"-af","silencedetect=noise=-35dB:d=0.35","-f","null","-"]).stderr
    clips = []
    for index,(offset,length) in enumerate(candidates(detected,seconds)[:20],1):
        clip = output / f"candidate-{index:02d}.wav"
        run([ffmpeg,"-hide_banner","-nostdin","-v","error","-n","-ss",str(offset),"-i",str(vocals),
             "-t",str(length),"-ac","1","-ar","32000","-c:a","pcm_s16le",str(clip)])
        clips.append({"file":str(clip),"offset_seconds":offset,"duration_seconds":length,
                      "speaker_confirmed":False,"reference_text":"","emotion":"unreviewed"})
    result = {"source":str(source),"source_start_seconds":start,"audio":str(audio),"vocals":str(vocals),
              "separated":separate,"candidates":clips,
              "note":"候选音频尚未确认说话人、转写或情绪，不能直接宣布声线部署完成。"}
    (output/"manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("--root",type=Path,default=Path("D:/saber-voice"))
    parser.add_argument("--start",type=float,default=0)
    parser.add_argument("--duration",type=float,default=600)
    parser.add_argument("--separate",action="store_true")
    args=parser.parse_args()
    ffmpeg=shutil.which("ffmpeg");ffprobe=shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        parser.error("需要 FFmpeg 和 FFprobe；将其 bin 目录加入当前终端 PATH 后重试")
    try:
        result=prepare(args.source,args.root,ffmpeg,ffprobe,args.start,args.duration,args.separate)
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        print(f"音频准备失败：{exc}",file=sys.stderr)
        if isinstance(exc,subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr[-2500:],file=sys.stderr)
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
