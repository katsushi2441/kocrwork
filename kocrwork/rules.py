"""生成AIを使わない項目の取り出し（客先が「AIは使えない」と言うとき用）。

見出しの語（profile の rule）の右か下にある値を拾うだけの単純な規則。
定型の帳票ならこれで足りることも多い。足りない分は画面で人が直す。
"""
from __future__ import annotations

import re
import unicodedata

DATE = re.compile(r'(20\d{2})\s*[/年.\-]\s*(\d{1,2})\s*[/月.\-]\s*(\d{1,2})')
NUM = re.compile(r'[\d,，]+')
TEL = re.compile(r'0\d{1,4}[-ー‐−(（]?\d{1,4}[-ー‐−)）]?\d{3,4}')


ALT = str.maketrans({'稅': '税', '：': ':'})   # OCR がよく出す異体字・全角記号


def norm(s: str) -> str:
    return unicodedata.normalize('NFKC', s or '').translate(ALT)


def _value(kind, s):
    s = s.strip(' :：　|')
    if kind == 'date':
        m = DATE.search(s)
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else None
    if kind == 'number':
        m = NUM.search(s.replace(' ', ''))
        if not m:
            return None
        v = re.sub(r'[,，]', '', m.group(0))
        return int(v) if v.isdigit() else None
    if kind == 'tel':
        m = TEL.search(s.replace(' ', ''))
        return re.sub(r'[ー‐−]', '-', m.group(0)) if m else None
    return s or None


def extract(profile: dict, text: str) -> dict:
    lines = [norm(l) for l in text.splitlines() if l.strip()]
    out = {}
    for f in profile.get('fields', []):
        kind = f.get('type', 'text')
        val = None
        for word in f.get('rule', []):
            w = norm(word)
            # 見出しは行の頭にあるものを先に見る（本文中の「会社名」などを拾わないため）
            cand = [i for i, l in enumerate(lines) if l.lstrip(' |:：').startswith(w)] or \
                   [i for i, l in enumerate(lines) if w in l and len(l.split(w, 1)[0]) <= 30]
            for i in cand:
                l = lines[i]
                rest = l.split(w, 1)[1]
                # 「消費税（8%）」のような括弧書きを飛ばす
                rest = re.sub(r'^[（(][^）)]*[）)]', '', rest.strip())
                # 同じ行に別の見出しが続くとき（「注文番号 PO-1 注文日 2026/10/01」）は、そこで切る
                for g in profile.get('fields', []):
                    for w2 in g.get('rule', []):
                        w2 = norm(w2)
                        if w2 != w and len(w2) >= 2 and w2 in rest:
                            rest = rest.split(w2, 1)[0]
                val = _value(kind, rest)
                # 値が見出しの下の行にある様式（備考など）。次の行が別の見出しなら拾わない
                if val in (None, '') and i + 1 < len(lines) and not any(
                        lines[i + 1].startswith(norm(w2)) for g in profile.get('fields', []) for w2 in g.get('rule', [])):
                    val = _value(kind, lines[i + 1])
                if val not in (None, ''):
                    break
            if val not in (None, ''):
                break
        # 「FAX」の見出しは「電話」の行の中にも出るので、電話には FAX と同じ番号を入れない
        out[f['key']] = val
    if out.get('buyer_tel') and out.get('buyer_tel') == out.get('buyer_fax'):
        out['buyer_tel'] = None
    out['items'] = items(profile, lines)
    return out


def items(profile: dict, lines: list[str]) -> list[dict]:
    """明細の表。見出し行（品番・品名・数量…が3つ以上並ぶ行）を探し、その下の行を列の区切り（2つ以上の空白）で分ける。
    列の数が見出しとそろう行だけを拾う。そろわない行は拾わない（人が画面で足す）。"""
    cols = profile.get('items', [])
    if not cols:
        return []
    labels = [norm(c['label']) for c in cols]
    for i, l in enumerate(lines):
        toks = [t for t in re.split(r'\s{2,}|\t|\|', l) if t.strip()]
        hit = [t for t in toks if norm(t).strip() in labels]
        if len(hit) < 3:
            continue
        order = [labels.index(norm(t).strip()) if norm(t).strip() in labels else None for t in toks]
        out = []
        for row in lines[i + 1:]:
            if re.match(r'\s*(小計|合計|消費税|備考)', row):
                break
            if re.fullmatch(r'[\s|:\-]+', row):   # Markdown の区切り行
                continue
            cells = [t for t in re.split(r'\s{2,}|\t|\|', row) if t.strip()]
            if len(cells) != len(order):
                continue
            rec = {}
            for k, v in zip(order, cells):
                if k is None:
                    continue
                c = cols[k]
                rec[c['key']] = _value('number', v) if c.get('type') == 'number' else v.strip()
            out.append(rec)
        return out
    return []
