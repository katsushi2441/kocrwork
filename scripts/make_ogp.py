#!/usr/bin/env python3
"""OGP 画像（1200×630）を作る。数字は焼き込まない（変わるので）。  /usr/bin/python3 scripts/make_ogp.py"""
import os
from PIL import Image, ImageDraw, ImageFont

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
N = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
im = Image.new('RGB', (1200, 630), (244, 247, 249))
d = ImageDraw.Draw(im)
d.rectangle((0, 0, 1200, 12), fill=(10, 143, 133))
# 見本2枚（印刷と手書きFAX）を右に重ねる
for i, (f, x, y, rot) in enumerate((('order_print.png', 760, 90, 4), ('order_fax_hand.png', 860, 150, -5))):
    s = Image.open(os.path.join(R, 'samples', f)).convert('RGB')
    s = s.resize((300, int(300 * s.height / s.width)))
    s = s.crop((0, 0, 300, 420))
    fr = Image.new('RGB', (310, 430), (200, 210, 218)); fr.paste(s, (5, 5))
    fr = fr.rotate(rot, expand=True, fillcolor=(244, 247, 249))
    im.paste(fr, (x, y))
m = Image.open(os.path.join(R, 'static', 'mascot.png')).convert('RGBA')
m = m.resize((150, int(150 * m.height / m.width)))
im.paste(m, (60, 420), m)
d.text((60, 70), 'Kurage OCR Work', font=ImageFont.truetype(B, 34), fill=(10, 117, 109))
d.text((60, 130), 'AI-OCRで注文書を', font=ImageFont.truetype(B, 60), fill=(20, 34, 47))
d.text((60, 210), '受注登録まで', font=ImageFont.truetype(B, 60), fill=(20, 34, 47))
f = ImageFont.truetype(N, 26)
for k, t in enumerate(('OCRエンジンと生成AIを切り替えて', '印刷・スキャン・手書きFAXを読み比べ', '画面・API・MCPで同じ処理')):
    d.text((60, 310 + k * 38), '・' + t, font=f, fill=(60, 75, 90))
d.text((240, 560), '株式会社エクスブリッジ', font=ImageFont.truetype(N, 22), fill=(93, 107, 122))
im.save(os.path.join(R, 'static', 'ogp.png'), optimize=True)
print('static/ogp.png')
