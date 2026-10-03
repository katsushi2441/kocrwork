"""書類1枚を「読む → 項目を取り出す → 正解と比べる」の流れ。画面・API・MCP・コマンドはすべてここを通る。

llm の選び方（客先に合わせて切り替える）:
  none   … 生成AIを使わない。OCR の文字から規則で項目を拾う（明細は人が入れる）
  text   … OCR の文字を生成AIに渡して項目にする（速い。印刷の書類向き）
  vision … 画像を生成AIに直接見せて項目にする（手書き・崩れた FAX 向き。OCR の文字も参考に渡す）
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata

from PIL import Image

from . import config as C
from . import engines as E
from . import llm, rules

SAMPLES = os.path.join(C.ROOT, 'samples')
PROFILES = os.path.join(C.ROOT, 'profiles')
LLM_MODES = {
    'none': '使わない（規則で項目を拾う）',
    'text': 'OCRの文字から項目を取り出す',
    'vision': '画像を直接見て項目を取り出す',
}
SAMPLE_INFO = {
    'order_print.png': '印刷の注文書（きれいな原本）',
    'order_scan.pdf': 'スキャンした注文書（画像PDF・少し傾き）',
    'order_digital.pdf': 'Excel などから書き出したPDF（文字の層あり）',
    'order_fax_hand.png': '手書きで記入されたFAXの注文書（手書き風フォントで作った見本）',
}


def profiles() -> dict:
    out = {}
    for f in sorted(os.listdir(PROFILES)):
        if f.endswith('.json'):
            p = json.load(open(os.path.join(PROFILES, f), encoding='utf-8'))
            out[p['key']] = p
    for p in out.values():
        if p.get('extends') in out:
            base = dict(out[p['extends']])
            base.update({k: v for k, v in p.items() if k != 'extends'})
            p.clear(); p.update(base)
    return out


def load_pages(path: str) -> list[Image.Image]:
    if path.lower().endswith('.pdf'):
        import pymupdf
        doc = pymupdf.open(path)
        pages = []
        for i, pg in enumerate(doc):
            if i >= C.MAX_PAGES:
                break
            pix = pg.get_pixmap(dpi=C.DPI)
            pages.append(Image.frombytes('RGB', (pix.width, pix.height), pix.samples))
        return pages
    im = Image.open(path)
    im.load()
    return [im.convert('RGB') if im.mode not in ('L', 'RGB') else im]


def _num(v):
    if v is None or isinstance(v, (int, float)):
        return v
    s = unicodedata.normalize('NFKC', str(v)).replace(',', '').replace('円', '').strip()
    try:
        return int(float(s))
    except ValueError:
        return v


def clean(profile: dict, data: dict) -> dict:
    out = {}
    for f in profile.get('fields', []):
        v = data.get(f['key'])
        if f.get('type') == 'number':
            v = _num(v)
        elif isinstance(v, str):
            v = unicodedata.normalize('NFKC', v).strip() or None
        out[f['key']] = v
    items = []
    for it in data.get('items') or []:
        if not isinstance(it, dict):
            continue
        row = {}
        for c in profile.get('items', []):
            v = it.get(c['key'])
            row[c['key']] = _num(v) if c.get('type') == 'number' else (unicodedata.normalize('NFKC', str(v)).strip() if v not in (None, '') else None)
        if any(v not in (None, '') for v in row.values()):
            items.append(row)
    out['items'] = items
    return out


def _eq(a, b):
    if a is None or b is None:
        return False
    na = re.sub(r'[\s\-ー‐−/,，]', '', unicodedata.normalize('NFKC', str(a)))
    nb = re.sub(r'[\s\-ー‐−/,，]', '', unicodedata.normalize('NFKC', str(b)))
    return na == nb


def score(profile: dict, got: dict, truth: dict) -> dict:
    """見本の正解と比べる。項目ごとの一致と、明細のセルの一致数。"""
    det = {}
    for f in profile.get('fields', []):
        det[f['key']] = _eq(got.get(f['key']), truth.get(f['key']))
    cells = ok = 0
    gi = got.get('items') or []
    for i, t in enumerate(truth.get('items') or []):
        for c in profile.get('items', []):
            cells += 1
            if i < len(gi) and _eq(gi[i].get(c['key']), t.get(c['key'])):
                ok += 1
    n = len(det) + cells
    good = sum(det.values()) + ok
    return {'fields': det, 'items_ok': ok, 'items_total': cells, 'rate': round(good / n, 3) if n else None}


def truth_for(path: str):
    name = os.path.splitext(os.path.basename(path))[0]
    t = os.path.join(SAMPLES, 'truth.json')
    if os.path.dirname(os.path.abspath(path)) == SAMPLES and os.path.exists(t):
        return json.load(open(t, encoding='utf-8')).get(name)
    return None


def run(path: str, engine: str, llm_mode: str = 'none', profile_key: str = 'order', progress=None) -> dict:
    prof = profiles().get(profile_key) or profiles()['order']
    say = progress or (lambda s: None)
    t0 = time.time()
    say('書類を読み込んでいます')
    pages = load_pages(path)
    say(f'{E.ENGINES[engine].label if engine in E.ENGINES else engine} で読み取っています')
    ocr = E.run(engine, pages, path)
    res = {'engine': engine, 'llm': llm_mode, 'profile': prof['key'], 'ocr': ocr.to_dict(),
           'fields': None, 'score': None, 'llm_seconds': None, 'error': ocr.error}
    if ocr.error and engine != 'llm-vision':
        res['seconds'] = round(time.time() - t0, 2)
        return res
    if prof.get('fields'):
        t1 = time.time()
        try:
            if llm_mode == 'none':
                data = rules.extract(prof, ocr.text)
            elif llm_mode == 'text':
                say(f'生成AI（{C.LLM_LABEL}）が項目を取り出しています')
                data = llm.extract(prof, text=ocr.text)
            else:
                say(f'生成AI（{C.LLM_LABEL}）が画像を見て項目を取り出しています')
                data = llm.extract(prof, text=ocr.text if not ocr.error else None, image=pages[0])
            res['fields'] = clean(prof, data)
        except Exception as ex:
            res['error'] = f'項目の取り出しに失敗しました: {ex.__class__.__name__}: {str(ex)[:200]}'
        if llm_mode != 'none':
            res['llm_seconds'] = round(time.time() - t1, 2)
        tr = truth_for(path)
        if tr and res['fields'] is not None:
            res['score'] = score(prof, res['fields'], tr)
    res['seconds'] = round(time.time() - t0, 2)
    return res
