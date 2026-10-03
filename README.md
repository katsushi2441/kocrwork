# Kurage OCR Work（kocrwork）

客先で OCR（AI-OCR）のデモを即興で組むためのフレームワーク。
OCR エンジンと生成AIの使い方を切り替えて、同じ書類を読み比べ、項目を取り出して受注登録まで見せられる。
画面・HTTP API・MCP（AI エージェント）・コマンドが、すべて同じ処理（`kocrwork/pipeline.py`）を通る。

公開デモ: https://proto.exbridge.jp/kocrwork.php/

## 切り替えられるもの

| 何を | 選択肢 | どこで |
|---|---|---|
| OCR エンジン | `tesseract` / `ocrmypdf`（Tesseract＋OCRmyPDF） / `paddleocr` / `docling` / `llm-vision`（生成AIで直接読む） / `mineru`（追加の部品） | 画面・API の `engines` |
| 生成AIの使い方 | `none`（使わない・規則で拾う） / `text`（OCR の文字から項目に） / `vision`（画像を直接見て項目に） | 画面・API の `llm` |
| 生成AIの置き場所 | ローカルの Ollama（既定 gemma4） / OpenAI 互換 API | `.env` の `KOCR_LLM_KIND` ほか |
| 取り出す項目 | `profiles/*.json`（注文書・手書きFAX・全文だけ） | ファイルを1つ足す |
| 受注の送り先 | 台帳（SQLite）＋CSV／`KOCR_WEBHOOK` に JSON を POST | `.env` |

## 見本での実測（正解との一致率・2026-10-03）

| 書類 | 読み方 | 一致 |
|---|---|---:|
| 印刷の注文書 | PaddleOCR＋規則（AIなし） | 100% |
| 文字の層がある PDF | Docling＋規則 | 100% |
| スキャンした PDF | Tesseract＋OCRmyPDF＋規則 | 81〜86% |
| 手書きで記入した FAX | PaddleOCR＋規則 | 33% |
| 〃 | PaddleOCR＋生成AI（文字から） | 73% |
| 〃 | PaddleOCR＋生成AI（画像を見て） | 93〜97% |

見本は `samples/make_samples.py` で作る（会社名・品目は架空）。**手書きは手書き風フォント（Yomogi・SIL OFL）で作ったもので、本物の手書きではない。**
客先では、その会社の本物の FAX で試して数字を出し直す。速さは CPU 16コアで PaddleOCR 1ページ約20秒（初回はモデルの読み込みで+20秒）。

## 客先で組み替える手順

1. **書類の種類を足す**: `profiles/order.json` をコピーして `profiles/invoice.json` などにし、`fields`（見出しの語 `rule` つき）と `items`（明細の列）を書き換える。画面の入力欄・生成AIへの指示・規則での拾い方がすべて変わる。`extends` で既存の設定を引き継げる。
2. **合う読み方を探す**: 画面で「全部で読み比べる」を押し、生成AIの使い方を3通り試す。客先の書類の正解を `samples/truth.json` の形で用意すれば一致率も出る。
3. **既定を決める**: プロファイルの `default_engine` / `default_llm` に書く。
4. **受注の送り先をつなぐ**: `.env` に `KOCR_WEBHOOK=https://…` を書くと、登録のたびに `{"created","source","order"}` を POST する。基幹や kintone へは、この JSON を受ける中継を1本書く。

## エンジンを足す

`kocrwork/engines.py` に `Engine` を継承したクラスを書いて `ENGINES` に1行足す。`read()` は `OcrResult(text, lines, markdown, files)` を返す。画面・API・MCP に自動で出る。

## 起動

```bash
python3 -m venv --system-site-packages .venv      # PaddleOCR を共有するなら system-site-packages
.venv/bin/pip install docling ocrmypdf pymupdf mcp python-multipart httpx "fastapi>=0.120" uvicorn paddleocr paddlepaddle
.venv/bin/python samples/make_samples.py
.venv/bin/python -m uvicorn kocrwork.app:app --port 18348      # 画面 http://localhost:18348/
.venv/bin/python -m kocrwork samples/order_fax_hand.png --engine paddleocr --llm vision   # コマンド
```

- Tesseract の日本語（`jpn` `jpn_vert`）は `tessdata/` に置く（`KOCR_TESSDATA` で変更可）。
- 生成AIは既定で `http://localhost:11434`（Ollama）の `gemma4:12b-it-qat`（`KOCR_OLLAMA_URL` / `KOCR_TEXT_MODEL` / `KOCR_VISION_MODEL`）。gemma4 は思考型なので `think:false` を付けて呼んでいる。
- PaddleOCR は CPU で動かす（Paddle 3.3 の oneDNN は落ちるので切っている）。

## MCP（AI エージェントから使う）

```json
{"mcpServers":{"kocrwork":{"command":"/path/to/kocrwork/.venv/bin/python","args":["-m","kocrwork.mcp_server"]}}}
```

道具: `list_engines` / `read_document(path, engine, llm, profile)` / `register_order(data)` / `list_orders`

## HTTP API

- `GET api/meta` … エンジン・生成AIの使い方・書類の種類・見本
- `POST api/upload`（multipart `file`）→ `{src}`
- `POST api/run {src, engines[], llm, profile}` → `{job}` → `GET api/job/{job}`（読み取りは時間がかかるので非同期）
- `POST api/orders {data}` / `GET api/orders` / `GET api/orders.csv` / `DELETE api/orders/{id}`
- 受注の台帳は見る人（cookie）ごとに分かれる。公開デモで他人の登録は見えない。上げたファイルは24時間で消える。

## ライセンス

本体は MIT。同梱・利用している部品: PaddleOCR（Apache-2.0）・Tesseract（Apache-2.0）・OCRmyPDF（MPL-2.0）・Docling（MIT）・PyMuPDF（AGPL-3.0／商用ライセンスあり）・フォント Yomogi / Zen Kurenaido（SIL OFL）。
**MinerU は同梱しない**（一定規模以上の会社には別の商用ライセンスが要る）。使う場合は利用者が自分で入れる。
**PyMuPDF は AGPL** なので、製品として配る場合は pypdfium2 などへの置き換えか、商用ライセンスを検討する。

株式会社エクスブリッジ（名古屋市） https://exbridge.jp/
