"""受注の台帳（SQLite）。登録したら、設定があれば基幹システムなどへ JSON を送る（webhook）。

客先のデモでは「読み取り → 人が確認・修正 → 受注登録 → 一覧・CSV・基幹へ送信」までを見せる。
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import time

import httpx

from . import config as C


def db():
    c = sqlite3.connect(C.DB)
    c.row_factory = sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, source TEXT, profile TEXT,
        engine TEXT, llm TEXT, data TEXT, webhook TEXT, sid TEXT DEFAULT 'local')''')
    return c


def register(data: dict, source='', profile='order', engine='', llm='', sid='local') -> dict:
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    hook = ''
    if C.WEBHOOK:
        try:
            r = httpx.post(C.WEBHOOK, json={'created': now, 'source': source, 'order': data}, timeout=15)
            hook = f'送信 {r.status_code}'
        except Exception as e:
            hook = f'送信失敗 {e.__class__.__name__}'
    with db() as c:
        cur = c.execute('INSERT INTO orders(created,source,profile,engine,llm,data,webhook,sid) VALUES(?,?,?,?,?,?,?,?)',
                        (now, source, profile, engine, llm, json.dumps(data, ensure_ascii=False), hook, sid))
        oid = cur.lastrowid
    return {'id': oid, 'created': now, 'webhook': hook or '外部への送信なし'}


def list_orders(limit=50, sid='local') -> list[dict]:
    """台帳は見る人（sid）ごとに分ける。公開デモで、ほかの人が登録した受注が見えないように。"""
    with db() as c:
        rows = c.execute('SELECT * FROM orders WHERE sid=? ORDER BY id DESC LIMIT ?', (sid, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r); d['data'] = json.loads(d['data']); out.append(d)
    return out


def delete(oid: int, sid='local'):
    with db() as c:
        c.execute('DELETE FROM orders WHERE id=? AND sid=?', (oid, sid))


def to_csv(sid='local') -> str:
    """明細1行を1行にした CSV（基幹への取り込み用）。"""
    b = io.StringIO()
    w = csv.writer(b)
    w.writerow(['受注ID', '登録日時', '注文番号', '注文日', '発注者', '担当', '納品先', '希望納期',
                '品番', '品名', '数量', '単位', '単価', '金額', '合計'])
    for o in reversed(list_orders(1000, sid)):
        d = o['data']
        items = d.get('items') or [{}]
        for it in items:
            w.writerow([o['id'], o['created'], d.get('order_no'), d.get('order_date'), d.get('buyer_company'),
                        d.get('buyer_person'), d.get('ship_to'), d.get('due_date'),
                        it.get('code'), it.get('name'), it.get('qty'), it.get('unit'), it.get('price'),
                        it.get('amount'), d.get('total')])
    return '﻿' + b.getvalue()   # Excel で文字化けしないよう BOM 付き
