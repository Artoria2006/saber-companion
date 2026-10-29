"""使用 D 盘已有 faster-whisper 模型提供本机语音识别，不保存请求音频。"""
import argparse
import asyncio
import io
import logging
import sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recognition import validate_wav, RecognitionError


def create_app(model, config, model_name='base'):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
    lock = asyncio.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/health')
    async def health():
        return {"ok":True,"provider":"faster_whisper","model":model_name,"device":"cpu"}

    def recognize(data):
        duration = validate_wav(data, config["max_bytes"], config["max_seconds"])
        from faster_whisper.audio import decode_audio
        audio = decode_audio(io.BytesIO(data), sampling_rate=16000)
        segments, _ = model.transcribe(audio, language="zh", task="transcribe", beam_size=5,
                                      vad_filter=True, condition_on_previous_text=False,
                                      no_speech_threshold=0.6)
        parts, scores = [], []
        for segment in segments:
            text = segment.text.strip()
            if text and segment.no_speech_prob <= 0.6:
                parts.append(text); scores.append(segment.avg_logprob)
        text = ''.join(parts).strip()
        uncertain = not text or len(text) > 3000 or not scores or min(scores) < config["min_avg_logprob"]
        return {"text":"" if uncertain else text,"uncertain":uncertain,"duration_seconds":round(duration,2)}

    @app.post('/transcribe')
    async def transcribe(request: Request):
        if lock.locked():
            return JSONResponse({"error":"识别服务忙，请稍后再试"},status_code=429)
        async with lock:
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > config["max_bytes"]:
                    return JSONResponse({"error":"音频超过大小上限"},status_code=413)
            try:
                result = await run_in_threadpool(recognize, bytes(data))
                logging.info('[asr] done duration=%.2f uncertain=%s',result['duration_seconds'],result['uncertain'])
                return JSONResponse(result,status_code=422 if result['uncertain'] else 200)
            except RecognitionError as exc:
                return JSONResponse({"error":str(exc)},status_code=400)
            except Exception as exc:
                logging.error('[asr] failed type=%s',type(exc).__name__)
                return JSONResponse({"error":"本机语音识别失败"},status_code=503)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('D:/saber-voice'))
    parser.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[1]/'config.toml')
    parser.add_argument('--port',type=int,default=9881)
    parser.add_argument('--model-name', choices=('base', 'small'), default='base')
    args = parser.parse_args()
    with args.config.open('rb') as f:
        config = tomllib.load(f)['asr']
    model_dir = args.root.resolve()/'cache'/('asr-'+args.model_name)
    if not (model_dir/'model.bin').is_file():
        parser.error('找不到本机 Whisper 模型：'+str(model_dir))
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    from faster_whisper import WhisperModel
    model = WhisperModel(str(model_dir),device='cpu',compute_type='int8',cpu_threads=6,local_files_only=True)
    import uvicorn
    uvicorn.run(create_app(model, config, args.model_name),host='127.0.0.1',port=args.port,workers=1)


if __name__ == '__main__':
    main()
