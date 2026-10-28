"""在 D 盘独立环境启动固定版本 GPT-SoVITS；仅监听本机回环地址。"""
import argparse
import importlib
import json
import os
import sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path("D:/saber-voice"))
    p.add_argument("--port",type=int,default=9880)
    args=p.parse_args()
    root=args.root.resolve();repo=root/"GPT-SoVITS"
    if not (repo/"api_v2.py").is_file():
        p.error("找不到 GPT-SoVITS 官方源码")
    for key,relative in (("HF_HOME","cache/huggingface"),("TORCH_HOME","cache/torch"),("NLTK_DATA","GPT-SoVITS/runtime/nltk_data")):
        os.environ[key]=str(root/relative)
    os.environ["TOKENIZERS_PARALLELISM"]="false"
    os.environ["PATH"]=str(root/"tools/ffmpeg/bin")+os.pathsep+os.environ.get("PATH","")
    os.chdir(repo)
    sys.path[:0]=[str(repo),str(repo/"GPT_SoVITS")]
    # 纯 Python 结巴提供兼容分词接口，避免给现有系统安装 C++ 编译工具。
    import jieba
    import jieba.posseg
    import jieba.finalseg
    sys.modules["jieba_fast"]=jieba
    sys.modules["jieba_fast.posseg"]=jieba.posseg
    sys.modules["jieba_fast.finalseg"]=jieba.finalseg
    runtime=importlib.import_module("tools.portable_runtime")
    runtime.FFMPEG_EXE=root/"tools/ffmpeg/bin/ffmpeg.exe"
    runtime.FFPROBE_EXE=root/"tools/ffmpeg/bin/ffprobe.exe"
    config=root/"gsv-inference.yaml"
    if not config.exists():
        import yaml
        base="GPT_SoVITS/pretrained_models/"
        value={"custom":{"device":"cuda","is_half":True,"version":"v2ProPlus",
                         "bert_base_path":base+"chinese-roberta-wwm-ext-large",
                         "cnhuhbert_base_path":base+"chinese-hubert-base",
                         "t2s_weights_path":base+"s1v3.ckpt","vits_weights_path":base+"v2Pro/s2Gv2ProPlus.pth"}}
        config.write_text(yaml.safe_dump(value),encoding="utf-8")
    sys.argv=["api_v2.py","-a","127.0.0.1","-p",str(args.port),"-c",str(config)]
    backend=importlib.import_module("api_v2")
    app=backend.APP
    # 日常服务只保留合成接口；模型切换和进程控制通过本机启动脚本完成。
    app.router.routes=[route for route in app.router.routes if getattr(route,"path","")=="/tts" and "POST" in getattr(route,"methods",set())]
    references=(root/"references").resolve()
    @app.middleware("http")
    async def bounded_reference(request,call_next):
        from starlette.responses import JSONResponse
        if request.url.path=="/tts":
            try:
                raw=await request.body()
                if len(raw)>12000:
                    raise ValueError()
                body=json.loads(raw)
                auxiliary=body.get("aux_ref_audio_paths",[])
                if not isinstance(auxiliary,list) or len(auxiliary)>5:
                    raise ValueError()
                for path in [body.get("ref_audio_path","")]+auxiliary:
                    reference=Path(path).resolve(strict=True)
                    if not reference.is_relative_to(references) or not reference.is_file():
                        raise ValueError()
                if not isinstance(body.get("text"),str) or not 1<=len(body["text"])<=300:
                    raise ValueError()
            except (ValueError,OSError,TypeError,AttributeError):
                return JSONResponse({"error":"正文或参考音频路径无效；仅接受本机 references 目录"},status_code=400)
        return await call_next(request)
    @app.get("/health")
    async def health():
        return {"ok":True,"provider":"gpt_sovits","version":"v2ProPlus","device":"cuda","pid":os.getpid()}
    import uvicorn
    uvicorn.run(app,host="127.0.0.1",port=args.port,workers=1)


if __name__=="__main__":
    main()
