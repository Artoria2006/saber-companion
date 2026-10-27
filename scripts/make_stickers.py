"""绘制原创的简单金发骑士表情测试图；运行时不依赖此脚本。"""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "assets" / "stickers"
ROOT.mkdir(parents=True, exist_ok=True)
FONT = next((Path(p) for p in ("C:/Windows/Fonts/msyhbd.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if Path(p).exists()), None)


def heart(draw, x, y, size, color):
    draw.ellipse((x, y, x+size, y+size), fill=color)
    draw.ellipse((x+size*.75, y, x+size*1.75, y+size), fill=color)
    draw.polygon([(x, y+size*.55), (x+size*1.75, y+size*.55), (x+size*.875, y+size*1.9)], fill=color)


rows = []
for mood, label, english in [("hug", "抱抱", "A hug for you"), ("happy", "好开心", "So happy"),
                              ("miss", "想你啦", "Thinking of you"), ("goodnight", "晚安", "Good night")]:
    im = Image.new("RGBA", (480, 480), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((10,10,470,470), radius=90, fill="#fff8ec", outline="#e2cda6", width=5)
    # 原创的几何造型，不使用外部人物图片或素材。
    d.ellipse((105,65,375,330), fill="#e9c568", outline="#8c7145", width=5)
    d.rounded_rectangle((118,237,362,386), radius=58, fill="#405c91", outline="#314363", width=5)
    d.ellipse((126,99,354,310), fill="#fff0dc", outline="#8c7145", width=4)
    for points in [[(120,176),(135,99),(211,81),(195,163),(164,137)],[(189,93),(265,76),(285,170),(231,139)],[(264,85),(339,111),(357,190),(307,145)]]:
        d.polygon(points, fill="#e9c568", outline="#8c7145", width=3)
    d.arc((217,35,269,102), 185,355, fill="#8c7145", width=6)
    d.polygon([(346,134),(390,106),(391,172)],fill="#405c91",outline="#314363",width=4)
    d.polygon([(346,140),(307,110),(306,174)],fill="#405c91",outline="#314363",width=4)
    d.ellipse((334,127,356,151),fill="#6684b4")
    if mood in ("happy","goodnight"):
        d.arc((166,181,207,218),190,350,fill="#465c4b",width=6)
        d.arc((267,181,308,218),190,350,fill="#465c4b",width=6)
    else:
        d.ellipse((174,183,199,217),fill="#507d61")
        d.ellipse((278,183,303,217),fill="#507d61")
        d.ellipse((179,186,187,195),fill="white")
        d.ellipse((283,186,291,195),fill="white")
    d.ellipse((148,220,188,237), fill="#f1bdba")
    d.ellipse((293,220,333,237), fill="#f1bdba")
    d.arc((220,224,260,250),0,180,fill="#a97667",width=4)
    d.polygon([(221,302),(240,322),(260,302)],fill="#f2eddc")
    if mood=="hug":
        d.rounded_rectangle((91,309,224,350),20,fill="#fff0dc",outline="#8c7145",width=3)
        d.rounded_rectangle((256,309,389,350),20,fill="#fff0dc",outline="#8c7145",width=3)
        heart(d,219,329,24,"#d98189")
    elif mood=="goodnight":
        d.ellipse((47,64,108,125), fill="#e9c568")
        d.ellipse((65,51,115,109), fill="#fff8ec")
        d.text((355,45),"zZ",font=ImageFont.truetype(str(FONT),28) if FONT else None,fill="#7188ad")
    else:
        heart(d,55,126,22,"#d98189")
        heart(d,374,220,18,"#d98189")
    font = ImageFont.truetype(str(FONT),46) if FONT else ImageFont.load_default()
    text = label if FONT and str(FONT).lower().endswith(".ttc") else english
    d.text((240,412),text,anchor="mm",font=font,fill="#32496d")
    im.save(ROOT / (mood+".png"), optimize=True)
    rows.append({"id":mood,"label":label,"file":mood+".png"})
(ROOT / "index.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
print("Generated",len(rows),"original starter stickers.")
