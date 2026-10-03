"""コマンドで使う: python -m kocrwork <ファイル> [--engine paddleocr] [--llm none|text|vision] [--profile order] [--json]"""
import argparse
import json
import sys

from . import engines, pipeline


def main():
    ap = argparse.ArgumentParser(prog='kocrwork')
    ap.add_argument('file', nargs='?')
    ap.add_argument('--engine', default='paddleocr')
    ap.add_argument('--llm', default='none', choices=list(pipeline.LLM_MODES))
    ap.add_argument('--profile', default='order')
    ap.add_argument('--engines', action='store_true', help='使えるエンジンの一覧')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.engines or not a.file:
        for e in engines.list_engines():
            print(('○' if e['available'] else '×'), e['key'], '-', e['label'], '' if e['available'] else '（' + e['why'] + '）')
        return
    r = pipeline.run(a.file, a.engine, a.llm, a.profile, progress=lambda s: print('…', s, file=sys.stderr))
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1)); return
    print(f"== {r['engine']} {r['ocr']['seconds']}秒  生成AI={r['llm']} {r.get('llm_seconds') or ''}")
    if r['error']:
        print('エラー:', r['error'])
    print(r['ocr']['text'][:1500])
    if r['fields']:
        print('-- 項目'); print(json.dumps(r['fields'], ensure_ascii=False, indent=1)[:2000])
    if r['score']:
        print('-- 正解との一致', r['score']['rate'], {k: v for k, v in r['score']['fields'].items() if not v}, f"明細 {r['score']['items_ok']}/{r['score']['items_total']}")


main()
