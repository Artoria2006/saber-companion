"""下载固定版本的官方 GPT-SoVITS 基础模型，并校验大小和 SHA256。"""
import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen, Request
import shutil

REVISION = "8f8857563c040d542de108a2c18b0425abd6c9c5"
REPO = "lj1995/GPT-SoVITS"
FILES = (
    "chinese-hubert-base/config.json", "chinese-hubert-base/preprocessor_config.json",
    "chinese-hubert-base/pytorch_model.bin", "chinese-roberta-wwm-ext-large/config.json",
    "chinese-roberta-wwm-ext-large/tokenizer.json", "chinese-roberta-wwm-ext-large/pytorch_model.bin",
    "s1v3.ckpt", "v2Pro/s2Gv2ProPlus.pth", "sv/pretrained_eres2netv2w24s4ep4.ckpt",
)


def digest(path):
    value=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            value.update(chunk)
    return value.hexdigest()


def download(root, item, repo=REPO, revision=REVISION, allowed=FILES):
    name=item["rfilename"]
    if name not in allowed:
        raise ValueError("不在固定下载清单中")
    target=root/name
    size=item["size"]
    checksum=item.get("lfs",{}).get("sha256")
    def valid(path):
        return path.is_file() and path.stat().st_size==size and (not checksum or digest(path)==checksum)
    if target.exists():
        if not valid(target):
            raise ValueError(f"已有文件校验失败，保留原文件，请检查：{target}")
        print("已验证："+name,flush=True)
        return
    target.parent.mkdir(parents=True,exist_ok=True)
    partial=target.with_name(target.name+".download")
    url=f"https://huggingface.co/{repo}/resolve/{revision}/{quote(name)}"
    print("下载："+name,flush=True)
    if size>50*1024*1024:
        # 续用已取得的前缀；分段下载写入独立文件，最终合并并校验后才发布目标文件。
        offset=partial.stat().st_size if partial.is_file() else 0
        if offset>size:
            raise ValueError("已有临时文件过大，保留文件以便检查："+str(partial))
        ranges=[(begin,min(size-1,begin+16*1024*1024-1)) for begin in range(offset,size,16*1024*1024)]
        def fetch(bounds):
            begin,end=bounds
            part=partial.with_name(partial.name+f".{begin}-{end}")
            if part.is_file() and part.stat().st_size==end-begin+1:
                return part
            request=Request(url,headers={"Range":f"bytes={begin}-{end}"})
            with urlopen(request,timeout=60) as response:
                if response.status!=206 or not response.headers.get("Content-Range","").startswith(f"bytes {begin}-"):
                    raise ValueError("下载站未正确响应分段范围")
                with part.open("wb") as output:
                    while chunk:=response.read(1024*1024):output.write(chunk)
            if part.stat().st_size!=end-begin+1:raise ValueError("分段长度校验失败")
            return part
        with ThreadPoolExecutor(max_workers=6) as parts_pool:
            parts=list(parts_pool.map(fetch,ranges))
        completed=partial.with_name(partial.name+".joined")
        with completed.open("wb") as output:
            if offset:
                with partial.open("rb") as prefix:shutil.copyfileobj(prefix,output)
            for part in parts:
                with part.open("rb") as chunk:shutil.copyfileobj(chunk,output)
    else:
        completed=partial
        with urlopen(url,timeout=60) as response, completed.open("wb") as output:
            while chunk:=response.read(1024*1024):output.write(chunk)
    if not valid(completed):
        raise ValueError("下载文件校验失败："+name)
    completed.replace(target)
    print("完成："+name,flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path("D:/saber-voice/GPT-SoVITS/GPT_SoVITS/pretrained_models"))
    p.add_argument("--g2pw",action="store_true",help="同时准备中文多音字模型")
    p.add_argument("--asr",action="store_true",help="同时准备本地转写模型")
    args=p.parse_args()
    with urlopen(f"https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true",timeout=30) as response:
        info=json.load(response)
    listing={item["rfilename"]:item for item in info["siblings"]}
    root=args.root.resolve()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda name:download(root,listing[name]),FILES))
    print("固定版本基础模型已下载并校验。")
    if args.asr:
        repo="Systran/faster-whisper-base";revision="ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"
        names=("model.bin","config.json","tokenizer.json","vocabulary.txt")
        with urlopen(f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true",timeout=30) as response:
            info=json.load(response)
        items={x["rfilename"]:x for x in info["siblings"]}
        target=root.parents[2]/"cache/asr-base"
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda n:download(target,items[n],repo,revision,names),names))
        print("本地转写模型已准备完成。")
    if args.g2pw:
        import zipfile
        repo="XXXXRT/GPT-SoVITS-Pretrained";revision="0c47645e02a7bc3688d7b263b0042c81e3cd82cd"
        with urlopen(f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true",timeout=30) as response:
            info=json.load(response)
        item=next(x for x in info["siblings"] if x["rfilename"]=="G2PWModel.zip")
        work=root.parents[2]
        cache=work/"cache/models"
        download(cache,item,repo,revision,("G2PWModel.zip",))
        destination=(root.parent/"text/G2PWModel").resolve()
        with zipfile.ZipFile(cache/"G2PWModel.zip") as archive:
            if sum(x.file_size for x in archive.infolist())>2*1024**3:
                raise ValueError("中文模型解压大小超出上限")
            for member in archive.infolist():
                parts=Path(member.filename.replace('\\','/')).parts
                if "G2PWModel" in parts:parts=parts[parts.index("G2PWModel")+1:]
                if not parts:continue
                target=(destination/Path(*parts)).resolve()
                if not target.is_relative_to(destination):raise ValueError("压缩包路径越界")
                if member.is_dir():target.mkdir(parents=True,exist_ok=True);continue
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    if target.stat().st_size==member.file_size:continue
                    raise ValueError("保留已有不同文件，请检查："+str(target))
                with archive.open(member) as source,target.open('xb') as output:shutil.copyfileobj(source,output)
        print("中文多音字模型已准备完成。")


if __name__=="__main__":
    main()
