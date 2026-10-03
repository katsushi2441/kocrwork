"""生成AIの呼び出し。Ollama（ローカル）と OpenAI 互換 API を同じ関数で切り替える。

- gemma4 は思考型なので Ollama には必ず think:false を付ける（付けないと応答が空になる）。
- 項目の取り出しは「JSON だけを返す」形にして、壊れた JSON は1回だけ直させる。
"""
from __future__ import annotations

import base64
import io
import json
import re

import httpx
from PIL import Image

from . import config as C


def _img_b64(im: Image.Image, max_side=1600) -> str:
    im = im.convert('RGB')
    if max(im.size) > max_side:
        r = max_side / max(im.size)
        im = im.resize((int(im.width * r), int(im.height * r)))
    b = io.BytesIO(); im.save(b, 'PNG')
    return base64.b64encode(b.getvalue()).decode()


def ping() -> tuple[bool, str]:
    try:
        if C.LLM_KIND == 'ollama':
            r = httpx.get(C.OLLAMA_URL + '/api/tags', timeout=4)
            names = [m['name'] for m in r.json().get('models', [])]
            if C.VISION_MODEL not in names:
                return False, f'{C.VISION_MODEL} が {C.OLLAMA_URL} にありません'
            return True, ''
        return (bool(C.OPENAI_KEY), 'KOCR_OPENAI_KEY が未設定です')
    except Exception as e:
        return False, f'生成AIにつながりません（{e.__class__.__name__}）'


def chat(prompt: str, image: Image.Image | None = None, model: str | None = None, json_mode=False, timeout=300) -> str:
    model = model or (C.VISION_MODEL if image is not None else C.TEXT_MODEL)
    if C.LLM_KIND == 'ollama':
        msg = {'role': 'user', 'content': prompt}
        if image is not None:
            msg['images'] = [_img_b64(image)]
        body = {'model': model, 'messages': [msg], 'stream': False, 'think': False,
                'options': {'temperature': 0, 'num_predict': 4096, 'num_ctx': 8192}}
        if json_mode:
            body['format'] = 'json'
        r = httpx.post(C.OLLAMA_URL + '/api/chat', json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()['message']['content']
    content = [{'type': 'text', 'text': prompt}]
    if image is not None:
        content.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + _img_b64(image)}})
    body = {'model': model, 'messages': [{'role': 'user', 'content': content}], 'temperature': 0}
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    r = httpx.post(C.OPENAI_URL + '/chat/completions', json=body, timeout=timeout,
                   headers={'Authorization': 'Bearer ' + C.OPENAI_KEY})
    r.raise_for_status()
    return r.json()['choices'][0]['message']['content']


def vision_transcribe(im: Image.Image) -> str:
    return chat('この書類の画像に書かれている文字を、上から順にそのまま書き出してください。'
                '表は1行ずつ、列の間を2つの空白で区切ってください。読めない文字は〓にしてください。'
                '書かれていない内容を補ったり、説明を付けたりしないでください。', image=im)


def schema_prompt(profile: dict) -> str:
    f = '\n'.join(f'- {x["key"]}: {x["label"]}（{x.get("hint", x.get("type", "文字"))}）' for x in profile['fields'])
    it = ''
    if profile.get('items'):
        cols = ', '.join(f'{x["key"]}={x["label"]}' for x in profile['items'])
        it = f'\n- items: 明細の配列。各行は {{{cols}}}。数値は数字だけ（カンマ・円なし）'
    return f'''次の項目を取り出して、JSON だけを返してください。
{f}{it}

決まり:
- 書類に書かれていない項目は null にする。推測で埋めない
- 日付は YYYY-MM-DD にそろえる（和暦や「10/2」は年を補ってよいが、年が分からなければ書かれたまま）
- 金額・数量は数字だけにする
- 余計な説明は書かない'''


def _parse(s: str):
    s = s.strip()
    m = re.search(r'\{.*\}', s, re.S)
    return json.loads(m.group(0) if m else s)


def extract(profile: dict, text: str | None = None, image: Image.Image | None = None) -> dict:
    p = schema_prompt(profile)
    if text is not None and image is None:
        p = p + '\n\n--- OCR で読み取った文字（読み違いを含むことがあります）---\n' + text[:12000]
    elif text:
        p = p + '\n\n--- 参考：OCR で読み取った文字（画像と食い違うときは画像を優先）---\n' + text[:8000]
    raw = chat(p, image=image, json_mode=True)
    try:
        return _parse(raw)
    except Exception:
        raw2 = chat('次の文字列を正しい JSON に直して、JSON だけを返してください。\n' + raw[:6000], json_mode=True)
        return _parse(raw2)
