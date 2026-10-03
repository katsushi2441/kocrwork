"""画面と API（FastAPI）。中身はすべて pipeline / store を呼ぶだけ。MCP（mcp_server.py）も同じ関数を通る。

  .venv/bin/python -m uvicorn kocrwork.app:app --host 0.0.0.0 --port 18348
"""
from __future__ import annotations

import html as H
import io
import json
import os
import queue
import re
import secrets
import threading
import time
import uuid

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config as C
from . import engines as E
from . import pipeline as P
from . import store

app = FastAPI(title='Kurage OCR Work')
app.mount('/static', StaticFiles(directory=os.path.join(C.ROOT, 'static')), name='static')
UP = os.path.join(C.ROOT, 'outputs', 'uploads')
OK_EXT = ('.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp', '.bmp')

JOBS: dict[str, dict] = {}
Q: 'queue.Queue[str]' = queue.Queue()
RATE: dict[str, list] = {}


def _sid(req: Request) -> str:
    s = req.cookies.get('kocr_sid', '')
    return s if re.fullmatch(r'[0-9a-f]{24}', s or '') else ''


def _ip(req: Request) -> str:
    return (req.headers.get('x-forwarded-for') or (req.client.host if req.client else '')).split(',')[0].strip()


def _src_path(src: str) -> str:
    if src.startswith('sample:'):
        name = os.path.basename(src[7:])
        if name not in P.SAMPLE_INFO:
            raise HTTPException(404, '見本がありません')
        return os.path.join(P.SAMPLES, name)
    if src.startswith('up:'):
        name = os.path.basename(src[3:])
        p = os.path.join(UP, name)
        if not re.fullmatch(r'[0-9a-f]{32}\.[a-z]+', name) or not os.path.exists(p):
            raise HTTPException(404, 'ファイルが見つかりません（24時間で消えます）')
        return p
    raise HTTPException(400, 'src は sample:… か up:… です')


def _worker():
    while True:
        jid = Q.get()
        job = JOBS.get(jid)
        if not job:
            continue
        job['state'] = 'running'
        try:
            path = _src_path(job['src'])
            for eng in job['engines']:
                job['current'] = eng
                job['progress'] = f'{E.ENGINES[eng].label} の順番です'
                r = P.run(path, eng, job['llm'], job['profile'], progress=lambda s: job.__setitem__('progress', s))
                job['results'].append(r)
            job['state'] = 'done'
        except Exception as ex:
            job['state'] = 'error'; job['error'] = f'{ex.__class__.__name__}: {str(ex)[:200]}'
        job['current'] = ''; job['progress'] = ''; job['finished'] = time.time()


threading.Thread(target=_worker, daemon=True).start()


def _cleanup():
    now = time.time()
    for f in os.listdir(UP):
        p = os.path.join(UP, f)
        if now - os.path.getmtime(p) > 86400:
            os.remove(p)
    for k in [k for k, j in JOBS.items() if now - j['created'] > 7200]:
        JOBS.pop(k, None)


@app.middleware('http')
async def sid_cookie(req: Request, call_next):
    resp = await call_next(req)
    if not _sid(req):
        resp.set_cookie('kocr_sid', secrets.token_hex(12), max_age=86400 * 30, httponly=True, samesite='lax')
    return resp


@app.get('/api/meta')
def meta():
    return {'brand': C.BRAND, 'llm_label': C.LLM_LABEL, 'engines': E.list_engines(),
            'llm_modes': P.LLM_MODES,
            'profiles': [{k: p.get(k) for k in ('key', 'label', 'note', 'default_engine', 'default_llm')} | {
                'fields': p.get('fields', []), 'items': p.get('items', [])} for p in P.profiles().values()],
            'samples': [{'name': k, 'label': v} for k, v in P.SAMPLE_INFO.items() if os.path.exists(os.path.join(P.SAMPLES, k))],
            'limits': {'mb': C.MAX_MB, 'pages': C.MAX_PAGES}}


@app.get('/api/preview')
def preview(src: str, w: int = 900):
    path = _src_path(src)
    im = P.load_pages(path)[0].convert('RGB')
    w = max(200, min(1400, w))
    if im.width > w:
        im = im.resize((w, int(im.height * w / im.width)))
    b = io.BytesIO(); im.save(b, 'PNG')
    return Response(b.getvalue(), media_type='image/png', headers={'Cache-Control': 'public, max-age=3600'})


@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    _cleanup()
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in OK_EXT:
        raise HTTPException(415, 'PDF か画像（PNG・JPEG・TIFF・WebP）を選んでください')
    data = await file.read()
    if len(data) > C.MAX_MB * 1024 * 1024:
        raise HTTPException(413, f'{C.MAX_MB}MB までのファイルにしてください')
    name = uuid.uuid4().hex + ext
    p = os.path.join(UP, name)
    open(p, 'wb').write(data)
    try:
        pages = P.load_pages(p)
        if not pages:
            raise ValueError
    except Exception:
        os.remove(p)
        raise HTTPException(422, 'ファイルを開けませんでした（壊れているか、対応していない形式です）')
    return {'src': 'up:' + name, 'name': file.filename, 'pages': len(pages)}


@app.post('/api/run')
async def run(req: Request):
    b = await req.json()
    src = str(b.get('src', ''))
    _src_path(src)
    engines = [e for e in (b.get('engines') or []) if e in E.ENGINES][:6]
    if not engines:
        raise HTTPException(400, 'エンジンを選んでください')
    llm = b.get('llm') if b.get('llm') in P.LLM_MODES else 'none'
    prof = b.get('profile') if b.get('profile') in P.profiles() else 'order'
    ip = _ip(req)
    hits = [t for t in RATE.get(ip, []) if time.time() - t < 3600]
    if len(hits) >= 30:
        raise HTTPException(429, '1時間に30回までです。しばらくしてからお試しください')
    RATE[ip] = hits + [time.time()]
    jid = uuid.uuid4().hex[:16]
    JOBS[jid] = {'id': jid, 'src': src, 'engines': engines, 'llm': llm, 'profile': prof, 'state': 'queued',
                 'results': [], 'progress': '順番を待っています', 'current': '', 'created': time.time(), 'error': ''}
    Q.put(jid)
    return {'job': jid, 'ahead': Q.qsize() - 1}


@app.get('/api/job/{jid}')
def job(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, '処理が見つかりません（2時間で消えます）')
    out = dict(j)
    out['results'] = [dict(r, ocr={k: v for k, v in r['ocr'].items() if k != 'files'} | {
        'files': {k: f'api/file/{jid}/{i}/{k}' for k in r['ocr'].get('files', {})}}) for i, r in enumerate(j['results'])]
    return out


@app.get('/api/file/{jid}/{idx}/{kind}')
def file(jid: str, idx: int, kind: str):
    j = JOBS.get(jid)
    try:
        p = j['results'][idx]['ocr']['files'][kind]
    except Exception:
        raise HTTPException(404, 'ファイルがありません')
    return FileResponse(p, filename='kocrwork-' + kind + ('.pdf' if p.endswith('.pdf') else ''))


@app.post('/api/orders')
async def add_order(req: Request):
    b = await req.json()
    data = b.get('data')
    if not isinstance(data, dict):
        raise HTTPException(400, 'data がありません')
    return store.register(data, source=str(b.get('source', ''))[:200], profile=str(b.get('profile', 'order')),
                          engine=str(b.get('engine', '')), llm=str(b.get('llm', '')), sid=_sid(req) or 'anon')


@app.get('/api/orders')
def orders(req: Request):
    return {'orders': store.list_orders(50, _sid(req) or 'anon'), 'webhook': bool(C.WEBHOOK)}


@app.delete('/api/orders/{oid}')
def del_order(oid: int, req: Request):
    store.delete(oid, _sid(req) or 'anon')
    return {'ok': True}


@app.get('/api/orders.csv')
def orders_csv(req: Request):
    return Response(store.to_csv(_sid(req) or 'anon'), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="kocrwork-orders.csv"'})


def _page():
    s = open(os.path.join(C.ROOT, 'templates', 'index.html'), encoding='utf-8').read()
    promo = ''
    if C.BUY_URL:
        promo = ('<nav class="hcta" aria-label="導入と相談">'
                 f'<a class="hot" href="{H.escape(C.BUY_URL)}">導入版</a>'
                 '<a href="https://exbridge.jp/contact.php?subject=Kurage%20OCR%20Work%E3%81%AE%E7%9B%B8%E8%AB%87&amp;ref=kocrwork-head-contact#form">相談する</a>'
                 '<a href="https://exbridge.jp/ai-it-komon.html?ref=kocrwork-head-komon">AI-IT顧問</a>'
                 '<a href="https://kurage.exbridge.jp/reseller.html?ref=kocrwork-head-reseller">販売代理店募集</a></nav>')
    for k, v in (('__PUBLIC__', H.escape(C.PUBLIC or './')), ('__BRAND__', H.escape(C.BRAND)),
                 ('__HEAD_CTA__', promo), ('__LLM_LABEL__', H.escape(C.LLM_LABEL)),
                 ('__TRACK__', os.environ.get('KOCR_TRACK_JS', ''))):
        s = s.replace(k, v)
    return s


@app.get('/', response_class=HTMLResponse)
def index():
    return _page()


@app.get('/robots.txt', response_class=PlainTextResponse)
def robots():
    return f'User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {C.PUBLIC}sitemap.xml\n'


@app.get('/sitemap.xml')
def sitemap():
    x = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{H.escape(C.PUBLIC)}</loc><lastmod>{time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(os.path.join(C.ROOT, "templates", "index.html"))))}</lastmod></url></urlset>\n'
    return Response(x, media_type='application/xml')


@app.get('/llms.txt', response_class=PlainTextResponse)
def llms():
    return open(os.path.join(C.ROOT, 'llms.txt'), encoding='utf-8').read()
