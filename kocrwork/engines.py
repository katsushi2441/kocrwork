"""OCR エンジンの切り替え口。どのエンジンも同じ形（OcrResult）で返す。

エンジンを足すときは Engine を継承して ENGINES に1行足すだけにしてある。
客先で「このエンジンも試したい」と言われたら、ここに1クラス書けば画面・API・MCP の全部に出る。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict

from PIL import Image

from .config import ROOT, TESSDATA, OLLAMA_URL, VISION_MODEL
from . import llm


@dataclass
class OcrResult:
    engine: str
    text: str = ''
    lines: list = field(default_factory=list)      # [{text, box:[x0,y0,x1,y1], score}]
    markdown: str = ''                              # 表を Markdown で返せるエンジンだけ
    seconds: float = 0.0
    files: dict = field(default_factory=dict)       # 出力ファイル（例: 文字の層つき PDF）
    error: str = ''

    def to_dict(self):
        return asdict(self)


class Engine:
    key = ''
    label = ''
    note = ''           # 画面に出す一行の説明（向き・不向き）
    gpu = False
    needs_llm = False

    def available(self) -> tuple[bool, str]:
        return True, ''

    def read(self, pages: list[Image.Image], src_path: str, workdir: str) -> OcrResult:
        raise NotImplementedError


def _env():
    e = dict(os.environ)
    e['TESSDATA_PREFIX'] = TESSDATA
    e['OMP_THREAD_LIMIT'] = e.get('OMP_THREAD_LIMIT', '4')
    return e


class Tesseract(Engine):
    key = 'tesseract'
    label = 'Tesseract'
    note = '昔からの定番。軽く CPU だけで動く。印刷のきれいな書類向き。手書き・表は苦手'

    def available(self):
        return (shutil.which('tesseract') is not None, 'tesseract が入っていません')

    def read(self, pages, src_path, workdir):
        texts, lines = [], []
        for i, im in enumerate(pages):
            p = os.path.join(workdir, f'tess-{i}.png')
            im.save(p)
            out = subprocess.run(['tesseract', p, 'stdout', '-l', 'jpn+eng', '--psm', '4', 'tsv'],
                                 capture_output=True, text=True, env=_env(), timeout=300)
            if out.returncode:
                raise RuntimeError(out.stderr.strip()[-300:])
            rows = [r.split('\t') for r in out.stdout.splitlines()[1:]]
            cur, key = [], None
            for r in rows:
                if len(r) < 12 or not r[11].strip():
                    continue
                k = (r[2], r[3], r[4])        # block, par, line
                if key is not None and k != key and cur:
                    lines.append(_join(cur, i)); cur = []
                key = k
                cur.append(r)
            if cur:
                lines.append(_join(cur, i))
            texts.append('\n'.join(l['text'] for l in lines if l['page'] == i))
        return OcrResult(self.key, text='\n\n'.join(texts), lines=lines)


def _join(cur, page):
    xs = [int(r[6]) for r in cur]; ys = [int(r[7]) for r in cur]
    x1 = [int(r[6]) + int(r[8]) for r in cur]; y1 = [int(r[7]) + int(r[9]) for r in cur]
    conf = [float(r[10]) for r in cur if float(r[10]) >= 0]
    # 日本語は単語の間に空白を入れない（tesseract は1文字ずつ区切って返す）。
    # ただし文字の高さの1.2倍より広い隙間は列の区切りとみなして2つの空白を入れる（表の列を残すため）
    hgt = sorted(int(r[9]) for r in cur)[len(cur) // 2] or 20
    text = cur[0][11]
    for a, b in zip(cur, cur[1:]):
        gap = int(b[6]) - (int(a[6]) + int(a[8]))
        text += ('  ' if gap > hgt * 1.2 else '') + b[11]
    return {'text': text, 'box': [min(xs), min(ys), max(x1), max(y1)],
            'score': round(sum(conf) / len(conf) / 100, 3) if conf else None, 'page': page}


class OcrMyPdf(Engine):
    key = 'ocrmypdf'
    label = 'Tesseract＋OCRmyPDF'
    note = 'スキャン PDF に文字の層を足して「検索できる PDF」にする。中身の読み取りは Tesseract'

    def available(self):
        try:
            import ocrmypdf  # noqa: F401
        except Exception:
            return False, 'ocrmypdf が入っていません'
        return (shutil.which('gs') is not None and shutil.which('tesseract') is not None,
                'ghostscript か tesseract が入っていません')

    def read(self, pages, src_path, workdir):
        src = os.path.join(workdir, 'in.pdf')
        if src_path.lower().endswith('.pdf'):
            shutil.copy(src_path, src)
        else:
            pages[0].convert('RGB').save(src, 'PDF', resolution=200, save_all=True,
                                         append_images=[p.convert('RGB') for p in pages[1:]])
        out_pdf = os.path.join(workdir, 'searchable.pdf')
        side = os.path.join(workdir, 'sidecar.txt')
        r = subprocess.run([os.path.join(os.path.dirname(os.sys.executable), 'ocrmypdf'),
                            '-l', 'jpn+eng', '--force-ocr', '--deskew', '--sidecar', side,
                            '--output-type', 'pdf', '--optimize', '0', '-q', src, out_pdf],
                           capture_output=True, text=True, env=_env(), timeout=600)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip()[-400:])
        text = open(side, encoding='utf-8', errors='ignore').read()
        # tesseract の日本語は文字の間に空白が入るので詰める（英数字の間の空白は残す）
        import re
        text = re.sub(r'(?<=[^\x00-\x7f]) (?=[^\x00-\x7f])', '', text)
        return OcrResult(self.key, text=text.strip(), files={'searchable_pdf': out_pdf})


class Paddle(Engine):
    key = 'paddleocr'
    label = 'PaddleOCR'
    note = '文字の読み取りの定番（Baidu・Apache-2.0）。日本語・傾き・FAX の粗さにも比較的強い'
    _ocr = None
    _lock = threading.Lock()

    def available(self):
        try:
            import paddleocr  # noqa: F401
            return True, ''
        except Exception as e:
            return False, f'paddleocr が入っていません（{e.__class__.__name__}）'

    def _get(self):
        if Paddle._ocr is None:
            from paddleocr import PaddleOCR
            # 速さの既定（2026-10-03 実測・CPU16コア・A4 200dpi）: 既定の検出モデル 40秒 → 軽い検出（mobile_det）＋12スレッドで 17秒。
            # 読み取り（rec）の精度はほぼ同じ。KOCR_PADDLE_DET で検出モデルを戻せる。oneDNN は Paddle 3.3 で落ちるので切る
            Paddle._ocr = PaddleOCR(lang='japan', device='cpu', enable_mkldnn=False,
                                    text_detection_model_name=os.environ.get('KOCR_PADDLE_DET', 'PP-OCRv5_mobile_det'),
                                    cpu_threads=int(os.environ.get('KOCR_PADDLE_THREADS', '12')),
                                    use_doc_orientation_classify=False, use_doc_unwarping=False,
                                    use_textline_orientation=False)
        return Paddle._ocr

    def read(self, pages, src_path, workdir):
        lines, texts = [], []
        with Paddle._lock:
            ocr = self._get()
            for i, im in enumerate(pages):
                p = os.path.join(workdir, f'paddle-{i}.png')
                im.convert('RGB').save(p)
                for res in ocr.predict(p):
                    j = res.json.get('res', res.json) if hasattr(res, 'json') else res
                    for t, b, s in zip(j.get('rec_texts', []), j.get('rec_boxes', []), j.get('rec_scores', [])):
                        lines.append({'text': t, 'box': [int(v) for v in list(b)[:4]], 'score': round(float(s), 3), 'page': i})
                texts.append('\n'.join(_reading_order([l for l in lines if l['page'] == i])))
        return OcrResult(self.key, text='\n\n'.join(texts), lines=lines)


def _reading_order(lines):
    """行の高さでまとめて、上から下・左から右に並べる（表の1行が1行の文字列になる）。"""
    rows = []
    for l in sorted(lines, key=lambda l: (l['box'][1] + l['box'][3]) / 2):
        cy = (l['box'][1] + l['box'][3]) / 2
        h = max(8, l['box'][3] - l['box'][1])
        if rows and abs(rows[-1]['cy'] - cy) < h * 0.6:
            rows[-1]['items'].append(l)
        else:
            rows.append({'cy': cy, 'items': [l]})
    return ['  '.join(x['text'] for x in sorted(r['items'], key=lambda l: l['box'][0])) for r in rows]


class Docling(Engine):
    key = 'docling'
    label = 'Docling'
    note = 'IBM 製（MIT）。Excel などから書き出した文字の入った PDF を、表の構造ごと読んで Markdown で返す。スキャン画像の日本語は苦手'
    _conv = None
    _lock = threading.Lock()

    def available(self):
        try:
            import docling  # noqa: F401
            return True, ''
        except Exception:
            return False, 'docling が入っていません'

    def _get(self):
        if Docling._conv is None:
            os.environ['TESSDATA_PREFIX'] = TESSDATA
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (PdfPipelineOptions, TesseractCliOcrOptions)
            from docling.datamodel.accelerator_options import AcceleratorOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption
            po = PdfPipelineOptions()
            po.do_ocr = True
            po.do_table_structure = True
            po.ocr_options = TesseractCliOcrOptions(lang=['jpn', 'eng'], force_full_page_ocr=False)
            po.accelerator_options = AcceleratorOptions(device='cpu', num_threads=4)
            Docling._conv = DocumentConverter(format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=po),
                InputFormat.IMAGE: ImageFormatOption(pipeline_options=po)})
        return Docling._conv

    def read(self, pages, src_path, workdir):
        with Docling._lock:
            conv = self._get()
            src = src_path
            if not src_path.lower().endswith('.pdf'):
                src = os.path.join(workdir, 'docling.png')
                pages[0].convert('RGB').save(src)
            doc = conv.convert(src).document
        md = doc.export_to_markdown()
        import re
        md = re.sub(r'(?<=[^\x00-\x7f]) (?=[^\x00-\x7f])', '', md)
        return OcrResult(self.key, text=md, markdown=md)


class MinerU(Engine):
    key = 'mineru'
    label = 'MinerU（追加の部品）'
    note = 'PDF を Markdown に変換。表に強い。一定規模以上の会社は別の商用ライセンスが要るため同梱しない'

    def available(self):
        return (shutil.which('mineru') is not None,
                '同梱していません。使う場合は利用者が自分で入れてください（ライセンスの条件があるため）')

    def read(self, pages, src_path, workdir):
        src = src_path
        if not src_path.lower().endswith('.pdf'):
            src = os.path.join(workdir, 'mineru.png'); pages[0].convert('RGB').save(src)
        out = os.path.join(workdir, 'mineru')
        r = subprocess.run(['mineru', '-p', src, '-o', out, '-l', 'japan'], capture_output=True, text=True, timeout=900)
        if r.returncode:
            raise RuntimeError(r.stderr.strip()[-400:])
        md = ''
        for dp, _, fs in os.walk(out):
            for f in fs:
                if f.endswith('.md'):
                    md += open(os.path.join(dp, f), encoding='utf-8').read()
        return OcrResult(self.key, text=md, markdown=md)


class LlmVision(Engine):
    key = 'llm-vision'
    label = '生成AIで直接読む'
    note = '画像を生成AI（既定はローカルの gemma4）にそのまま読ませる。手書き・崩れた FAX に強いが遅く、まれに読み違いを補ってしまう'
    needs_llm = True

    def available(self):
        return llm.ping()

    def read(self, pages, src_path, workdir):
        out = []
        for im in pages:
            out.append(llm.vision_transcribe(im))
        return OcrResult(self.key, text='\n\n'.join(out))


ENGINES = {e.key: e for e in (Tesseract(), OcrMyPdf(), Paddle(), Docling(), LlmVision(), MinerU())}


def list_engines():
    out = []
    for e in ENGINES.values():
        ok, why = e.available()
        out.append({'key': e.key, 'label': e.label, 'note': e.note, 'available': ok, 'why': '' if ok else why})
    return out


def run(engine: str, pages, src_path) -> OcrResult:
    e = ENGINES.get(engine)
    if not e:
        return OcrResult(engine, error=f'エンジン {engine} はありません')
    ok, why = e.available()
    if not ok:
        return OcrResult(engine, error=why)
    work = tempfile.mkdtemp(prefix=f'kocr-{engine}-', dir=os.path.join(ROOT, 'outputs', 'work'))
    t = time.time()
    try:
        r = e.read(pages, src_path, work)
    except Exception as ex:  # エンジンが落ちても画面は止めない
        r = OcrResult(engine, error=f'{ex.__class__.__name__}: {str(ex)[:300]}')
    r.seconds = round(time.time() - t, 2)
    return r
