"""MCP サーバー（stdio）。AI エージェントから、画面と同じ処理（pipeline / store）を呼べる。

  Claude Desktop などの設定:
  {"mcpServers":{"kocrwork":{"command":"/path/to/kocrwork/.venv/bin/python","args":["-m","kocrwork.mcp_server"]}}}
"""
from __future__ import annotations

import json
import os

from mcp.server.mcpserver import MCPServer

from . import engines as E
from . import pipeline as P
from . import store

mcp = MCPServer('kocrwork')


@mcp.tool()
def list_engines() -> list[dict]:
    """使える OCR エンジンと、生成AIの使い方（none/text/vision）、書類の種類（profile）の一覧。"""
    return [{'engines': E.list_engines(), 'llm_modes': P.LLM_MODES,
             'profiles': [{'key': p['key'], 'label': p['label']} for p in P.profiles().values()],
             'samples': [os.path.join(P.SAMPLES, k) for k in P.SAMPLE_INFO]}]


@mcp.tool()
def read_document(path: str, engine: str = 'paddleocr', llm: str = 'text', profile: str = 'order') -> dict:
    """書類（PDF か画像）を読み取り、profile の項目（注文書なら注文番号・発注者・明細など）を取り出す。

    engine: tesseract / ocrmypdf / paddleocr / docling / llm-vision / mineru
    llm: none（規則で拾う）/ text（OCRの文字から生成AIで）/ vision（画像を生成AIに直接見せる。手書きFAX向き）
    見本（samples/）を渡すと、正解との一致率（score）も返す。
    """
    if not os.path.exists(path):
        return {'error': f'{path} がありません'}
    r = P.run(path, engine, llm, profile)
    r['ocr'].pop('lines', None)
    return r


@mcp.tool()
def register_order(data: dict, source: str = '', engine: str = '', llm: str = '') -> dict:
    """取り出した注文の内容（read_document の fields）を受注台帳に登録する。設定があれば基幹へ JSON を送る。"""
    return store.register(data, source=source, engine=engine, llm=llm, sid='mcp')


@mcp.tool()
def list_orders(limit: int = 20) -> list[dict]:
    """MCP から登録した受注の一覧（新しい順）。"""
    return store.list_orders(limit, 'mcp')


if __name__ == '__main__':
    mcp.run()
