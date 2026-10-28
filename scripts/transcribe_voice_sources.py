"""在本机转写已分离音轨；结果只写入 D 盘，不上传对白。"""
import argparse
import json
import os
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources",nargs="+",type=Path)
    p.add_argument("--root",type=Path,default=Path("D:/saber-voice"))
    p.add_argument("--model",choices=("base","small"),default="base")
    p.add_argument("--model-dir",type=Path,help="使用已下载并校验的本地 ASR 模型目录")
    args=p.parse_args();root=args.root.resolve()
    os.environ["HF_HOME"]=str(root/"cache/huggingface")
    from faster_whisper import WhisperModel
    model=WhisperModel(str(args.model_dir) if args.model_dir else args.model,device="cpu",compute_type="int8",cpu_threads=6,download_root=str(root/"cache/asr"))
    for source in args.sources:
        segments,info=model.transcribe(str(source),beam_size=5,vad_filter=True,condition_on_previous_text=False)
        result=[]
        for s in segments:
            result.append({"start":s.start,"end":s.end,"text":s.text.strip(),"avg_logprob":s.avg_logprob,"no_speech_prob":s.no_speech_prob})
        target=source.with_suffix(".transcript.json")
        target.write_text(json.dumps({"language":info.language,"language_probability":info.language_probability,"source":str(source),"segments":result},ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"转写完成：{source.name}；语言={info.language}；片段={len(result)}；结果={target}",flush=True)


if __name__=="__main__":
    main()
