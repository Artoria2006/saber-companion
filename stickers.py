"""本地表情图片库；模型只能选择已存在的 ID，不能提供网络地址或文件路径。"""

import base64
import io
import json
import re
import uuid
import warnings
from pathlib import Path
from PIL import Image


class StickerLibrary:
    def __init__(self, root, config):
        self.root = Path(root)
        self.config = config
        self.builtin = (self.root / config["builtin_dir"]).resolve()
        self.uploads = (self.root / config["upload_dir"]).resolve()
        self.uploads.mkdir(parents=True, exist_ok=True)

    def list(self):
        result = []
        for folder, custom in ((self.builtin, False), (self.uploads, True)):
            manifest = folder / "index.json"
            if not manifest.is_file():
                continue
            try:
                rows = json.loads(manifest.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if not isinstance(rows, list):
                continue
            for row in rows[:60]:
                if not isinstance(row, dict) or not re.fullmatch(r"[a-z0-9_-]{1,40}", str(row.get("id", ""))):
                    continue
                path = (folder / str(row.get("file", ""))).resolve()
                if path.parent != folder or path.suffix.lower() not in (".png", ".gif", ".jpg", ".jpeg", ".webp"):
                    continue
                if path.is_file() and path.stat().st_size <= self.config["max_bytes"]:
                    result.append({"id": row["id"], "label": str(row.get("label", row["id"]))[:40],
                                   "custom": custom, "path": path})
        return result

    def get(self, sticker_id):
        return next((item for item in self.list() if item["id"] == sticker_id), None)

    def options(self):
        return [{"id": row["id"], "label": row["label"]} for row in self.list()]

    def upload(self, label, encoded):
        if len(self.list()) >= 60:
            raise ValueError("表情库最多保存 60 张图片")
        if len(encoded) > self.config["max_bytes"] * 4 // 3 + 256:
            raise ValueError("图片过大")
        if encoded.startswith("data:"):
            encoded = encoded.split(",", 1)[-1]
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError("图片编码无效") from None
        if not data or len(data) > self.config["max_bytes"]:
            raise ValueError("图片为空或超过大小限制")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    kind = image.format
                    if image.width * image.height > 16000000 or getattr(image, "n_frames", 1) > 200:
                        raise ValueError("图片尺寸或动画帧数过大")
                    image.verify()
        except Exception:
            raise ValueError("图片无法识别，或尺寸超过限制") from None
        extension = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}.get(kind)
        if not extension:
            raise ValueError("仅支持 PNG、JPEG、GIF 和 WebP")
        sticker_id = "custom_" + uuid.uuid4().hex[:12]
        (self.uploads / (sticker_id + extension)).write_bytes(data)
        manifest = self.uploads / "index.json"
        rows = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else []
        rows.append({"id": sticker_id, "label": label.strip()[:40] or "自定义表情", "file": sticker_id + extension})
        temporary = manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest)
        return sticker_id
