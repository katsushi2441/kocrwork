#!/usr/bin/env python3
"""デモ用の見本の注文書を作る（架空の会社・架空の品目）。

  python3 samples/make_samples.py

出力（samples/ 直下）:
  order_print.png      … 印刷された注文書（きれいな原本）
  order_scan.pdf       … 同じ注文書をスキャンした風の画像PDF（文字の層なし・少し傾き・灰色）
  order_fax_hand.png   … 印刷の様式に手書きで記入して FAX で届いた風（2値化・ノイズ・傾き）
  truth.json           … 3枚それぞれの正解（読み取り精度の比較に使う）

手書きは本物の手書きではなく、手書き風フォント（Yomogi / Zen Kurenaido・SIL OFL）で書いている。
画面と README にもそう書く。客先では、その会社の本物の FAX を使って試す。
"""
import json
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(os.path.dirname(HERE), 'fonts')
NOTO = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
NOTO_B = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
HAND = [os.path.join(FONTS, 'Yomogi-Regular.ttf'), os.path.join(FONTS, 'ZenKurenaido-Regular.ttf')]

W, H = 1654, 2339   # A4 200dpi

ORDERS = {
    'order_print': {
        'order_no': 'PO-2026-1017',
        'order_date': '2026-10-01',
        'buyer': {'company': '株式会社みなと食品', 'person': '佐藤 花子', 'tel': '052-000-1234', 'fax': '052-000-1235'},
        'ship_to': '愛知県名古屋市港区港町1-2-3 みなと食品 第二倉庫',
        'due_date': '2026-10-10',
        'items': [
            {'code': 'A-101', 'name': '有機しょうゆ 1L', 'qty': 24, 'unit': '本', 'price': 680},
            {'code': 'A-205', 'name': '米みそ 750g', 'qty': 12, 'unit': '個', 'price': 540},
            {'code': 'B-310', 'name': '本みりん 500ml', 'qty': 18, 'unit': '本', 'price': 420},
            {'code': 'C-012', 'name': '昆布だし 10袋入', 'qty': 30, 'unit': '箱', 'price': 380},
        ],
        'note': '午前中の納品を希望します。',
    },
    'order_fax_hand': {
        'order_no': '1018',
        'order_date': '2026-10-02',
        'buyer': {'company': 'さくら食堂', 'person': '田中', 'tel': '052-000-5678', 'fax': '052-000-5679'},
        'ship_to': '名古屋市中区栄9-8-7 さくら食堂',
        'due_date': '2026-10-05',
        'items': [
            {'code': 'A-101', 'name': '有機しょうゆ 1L', 'qty': 6, 'unit': '本', 'price': 680},
            {'code': 'C-012', 'name': '昆布だし 10袋入', 'qty': 5, 'unit': '箱', 'price': 380},
            {'code': 'D-440', 'name': 'かつお節 500g', 'qty': 3, 'unit': '袋', 'price': 1850},
        ],
        'note': '裏口に置いてください',
    },
}
ORDERS['order_scan'] = ORDERS['order_print']
ORDERS['order_digital'] = ORDERS['order_print']
SELLER = '株式会社クラゲ食材（架空）'


def totals(o):
    sub = sum(i['qty'] * i['price'] for i in o['items'])
    tax = sub * 8 // 100   # 食品なので軽減税率8%
    return sub, tax, sub + tax


def font(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)


def form(d, o, hand=None):
    """様式（罫線と見出し）を印刷で描き、値は hand があれば手書き風フォントで、無ければ印刷で入れる。"""
    f_t = font(NOTO_B, 64)
    f_l = font(NOTO, 30)
    f_s = font(NOTO, 26)
    val = (lambda s: font(hand, s)) if hand else (lambda s: font(NOTO, s))
    jit = (lambda: random.randint(-4, 4)) if hand else (lambda: 0)
    d.text((W // 2, 140), '注　文　書', font=f_t, fill=0, anchor='mm')
    # 右上：注文番号・注文日
    d.text((1060, 230), '注文番号', font=f_l, fill=0, anchor='lm')
    d.text((1230 + jit(), 230 + jit()), o['order_no'], font=val(36), fill=0, anchor='lm')
    d.text((1060, 290), '注文日', font=f_l, fill=0, anchor='lm')
    d.text((1230 + jit(), 290 + jit()), o['order_date'].replace('-', '/'), font=val(36), fill=0, anchor='lm')
    # 宛先（受注側）
    d.text((120, 260), SELLER + '　御中', font=font(NOTO, 38), fill=0, anchor='lm')
    d.line((120, 290, 860, 290), fill=0, width=2)
    d.text((120, 340), '下記のとおり注文いたします。', font=f_s, fill=0, anchor='lm')
    # 発注者
    y = 420
    rows = [('発注者', o['buyer']['company']), ('ご担当', o['buyer']['person']),
            ('電話', o['buyer']['tel']), ('FAX', o['buyer']['fax']),
            ('納品先', o['ship_to']), ('希望納期', o['due_date'].replace('-', '/'))]
    for k, v in rows:
        d.rectangle((120, y, 360, y + 64), outline=0, width=2)
        d.rectangle((360, y, W - 120, y + 64), outline=0, width=2)
        d.text((140, y + 32), k, font=f_l, fill=0, anchor='lm')
        d.text((380 + jit(), y + 32 + jit()), v, font=val(34), fill=0, anchor='lm')
        y += 64
    # 明細
    y += 50
    cols = [(120, '品番'), (300, '品名'), (900, '数量'), (1050, '単位'), (1180, '単価'), (1360, '金額')]
    edges = [c[0] for c in cols] + [W - 120]
    d.rectangle((120, y, W - 120, y + 60), outline=0, width=2, fill=230 if not hand else 255)
    for i, (x, t) in enumerate(cols):
        d.line((x, y, x, y + 60 + 60 * 8), fill=0, width=2)
        d.text(((edges[i] + edges[i + 1]) // 2, y + 30), t, font=f_l, fill=0, anchor='mm')
    d.line((W - 120, y, W - 120, y + 60 + 60 * 8), fill=0, width=2)
    yy = y + 60
    for r in range(8):
        d.line((120, yy + 60, W - 120, yy + 60), fill=0, width=1)
        if r < len(o['items']):
            it = o['items'][r]
            amt = it['qty'] * it['price']
            cy = yy + 30
            d.text((140 + jit(), cy + jit()), it['code'], font=val(32), fill=0, anchor='lm')
            d.text((320 + jit(), cy + jit()), it['name'], font=val(32), fill=0, anchor='lm')
            d.text((1030 + jit(), cy + jit()), str(it['qty']), font=val(34), fill=0, anchor='rm')
            d.text((1115 + jit(), cy + jit()), it['unit'], font=val(32), fill=0, anchor='mm')
            d.text((1340 + jit(), cy + jit()), f"{it['price']:,}", font=val(34), fill=0, anchor='rm')
            d.text((W - 140 + jit(), cy + jit()), f"{amt:,}", font=val(34), fill=0, anchor='rm')
        yy += 60
    d.rectangle((120, y, W - 120, yy), outline=0, width=2)
    # 合計
    sub, tax, tot = totals(o)
    for k, v in (('小計', sub), ('消費税（8%）', tax), ('合計', tot)):
        d.rectangle((1050, yy, 1360, yy + 60), outline=0, width=2)
        d.rectangle((1360, yy, W - 120, yy + 60), outline=0, width=2)
        d.text((1070, yy + 30), k, font=f_l, fill=0, anchor='lm')
        d.text((W - 140 + jit(), yy + 30 + jit()), f'{v:,}', font=val(36), fill=0, anchor='rm')
        yy += 60
    # 備考
    yy += 40
    d.text((120, yy), '備考', font=f_l, fill=0, anchor='lm')
    d.rectangle((120, yy + 30, W - 120, yy + 180), outline=0, width=2)
    d.text((150 + jit(), yy + 90 + jit()), o['note'], font=val(34), fill=0, anchor='lm')
    d.text((W // 2, H - 90), 'この注文書は Kurage OCR Work のデモ用の見本です（会社名・品目は架空）。', font=f_s, fill=110, anchor='mm')


def truth(o):
    sub, tax, tot = totals(o)
    return {'order_no': o['order_no'], 'order_date': o['order_date'], 'buyer_company': o['buyer']['company'],
            'buyer_person': o['buyer']['person'], 'buyer_tel': o['buyer']['tel'], 'buyer_fax': o['buyer']['fax'],
            'ship_to': o['ship_to'], 'due_date': o['due_date'],
            'items': [dict(i, amount=i['qty'] * i['price']) for i in o['items']],
            'subtotal': sub, 'tax': tax, 'total': tot, 'note': o['note']}


def main():
    random.seed(7)
    # 1. 印刷
    img = Image.new('L', (W, H), 255)
    form(ImageDraw.Draw(img), ORDERS['order_print'])
    img.save(os.path.join(HERE, 'order_print.png'), dpi=(200, 200))
    # 2. スキャン風 PDF（文字の層なし）
    sc = img.rotate(0.8, resample=Image.BICUBIC, fillcolor=255, expand=False)
    sc = ImageOps.autocontrast(sc.point(lambda p: min(255, int(p * 0.92 + 14))))
    sc = sc.filter(ImageFilter.GaussianBlur(0.6))
    sc.convert('RGB').save(os.path.join(HERE, 'order_scan.pdf'), 'PDF', resolution=200)
    # 3. 手書き FAX（様式は印刷・値は手書き風フォント。FAX らしく解像度を落として2値化）
    img = Image.new('L', (W, H), 255)
    random.seed(11)
    form(ImageDraw.Draw(img), ORDERS['order_fax_hand'], hand=HAND[0])
    d = ImageDraw.Draw(img)
    d.text((120, 40), '2026/10/02 08:41  FROM: さくら食堂  052-000-5679        P.01', font=font(NOTO, 26), fill=0)
    fx = img.rotate(-1.2, resample=Image.BICUBIC, fillcolor=255)
    fx = fx.resize((W // 2, H // 2), Image.BILINEAR).resize((W, H), Image.NEAREST)   # FAX の粗さ（約100dpi）
    px = fx.load()
    for _ in range(9000):   # 点のノイズ
        x, y = random.randrange(W), random.randrange(H)
        px[x, y] = 0 if random.random() < 0.5 else 255
    fx = fx.point(lambda p: 0 if p < 150 else 255).convert('1')
    fx.save(os.path.join(HERE, 'order_fax_hand.png'), dpi=(200, 200))
    t = {k: truth(v) for k, v in ORDERS.items()}
    json.dump(t, open(os.path.join(HERE, 'truth.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('samples:', ', '.join(sorted(os.listdir(HERE))))


if __name__ == '__main__':
    main()


def digital_pdf():
    """Excel や販売管理から書き出した風の、文字の層がある PDF（Docling の得意な形）。"""
    import pymupdf
    o = ORDERS['order_print']
    sub, tax, tot = totals(o)
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_font(fontname='noto', fontfile='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    t = lambda x, y, s, size=10: pg.insert_text((x, y), s, fontname='noto', fontsize=size)
    t(250, 60, '注 文 書', 18)
    t(40, 95, SELLER + '　御中', 11)
    t(380, 95, '注文番号  ' + o['order_no']); t(380, 112, '注文日  ' + o['order_date'].replace('-', '/'))
    y = 140
    for k, v in (('発注者', o['buyer']['company']), ('ご担当', o['buyer']['person']), ('電話', o['buyer']['tel']),
                 ('FAX', o['buyer']['fax']), ('納品先', o['ship_to']), ('希望納期', o['due_date'].replace('-', '/'))):
        pg.draw_rect(pymupdf.Rect(40, y - 13, 555, y + 5)); t(46, y, k); t(130, y, v); y += 18
    y += 20
    xs = [40, 100, 300, 360, 400, 470, 555]
    heads = ['品番', '品名', '数量', '単位', '単価', '金額']
    rows = [heads] + [[i['code'], i['name'], str(i['qty']), i['unit'], f"{i['price']:,}", f"{i['qty'] * i['price']:,}"] for i in o['items']]
    for r in rows:
        for j, c in enumerate(r):
            pg.draw_rect(pymupdf.Rect(xs[j], y - 13, xs[j + 1], y + 5)); t(xs[j] + 4, y, c)
        y += 18
    for k, v in (('小計', sub), ('消費税（8%）', tax), ('合計', tot)):
        pg.draw_rect(pymupdf.Rect(400, y - 13, 555, y + 5)); t(404, y, k); t(475, y, f'{v:,}'); y += 18
    y += 20; t(40, y, '備考'); t(40, y + 18, o['note'])
    t(120, 810, 'この注文書は Kurage OCR Work のデモ用の見本です（会社名・品目は架空）。', 8)
    doc.save(os.path.join(HERE, 'order_digital.pdf'))


if __name__ == '__main__':
    digital_pdf()
