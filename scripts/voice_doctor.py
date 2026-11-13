"""检查本地语音运行所需的公开依赖和文件，不读取用户配置或音频内容。"""
import argparse
import importlib.util
from pathlib import Path


def inspect(root):
    root = Path(root)
    files = {
        'GPT-SoVITS 源码': root / 'GPT-SoVITS/api_v2.py',
        'FFmpeg': root / 'tools/ffmpeg/bin/ffmpeg.exe',
        'FFprobe': root / 'tools/ffmpeg/bin/ffprobe.exe',
        'GPT 模型': root / 'GPT-SoVITS/GPT_SoVITS/pretrained_models/s1v3.ckpt',
        'SoVITS 模型': root / 'GPT-SoVITS/GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth',
        '中文 BERT 模型': root / 'GPT-SoVITS/GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large/pytorch_model.bin',
        'HuBERT 模型': root / 'GPT-SoVITS/GPT_SoVITS/pretrained_models/chinese-hubert-base/pytorch_model.bin',
        'Whisper base 模型': root / 'cache/asr-base/model.bin',
    }
    result = [(label, path.is_file()) for label, path in files.items()]
    for name in ('torch', 'torchaudio', 'fastapi', 'uvicorn', 'faster_whisper', 'jieba'):
        result.append((f'Python 包 {name}', importlib.util.find_spec(name) is not None))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('D:/saber-voice'))
    args = parser.parse_args()
    results = inspect(args.root)
    for label, present in results:
        print(f"{'通过' if present else '缺少'}：{label}")
    print('此检查不加载模型，也不保证显卡、声线或 QQ 电话可用。')
    return 0 if all(present for _, present in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
