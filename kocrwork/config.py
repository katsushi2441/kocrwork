"""設定はすべて環境変数（.env）で切り替える。客先ではここだけ変えれば済むようにしてある。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env():
    p = os.path.join(ROOT, '.env')
    if os.path.exists(p):
        for ln in open(p, encoding='utf-8'):
            ln = ln.strip()
            if ln and not ln.startswith('#') and '=' in ln:
                k, v = ln.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


_load_env()
E = os.environ.get

TESSDATA = E('KOCR_TESSDATA', os.path.join(ROOT, 'tessdata'))
PORT = int(E('KOCR_PORT', '18348'))
# 生成AI。既定はローカルの Ollama（社内の書類を外に出さない）。OpenAI 互換の API にも切り替えられる
LLM_KIND = E('KOCR_LLM_KIND', 'ollama')                        # ollama | openai
OLLAMA_URL = E('KOCR_OLLAMA_URL', 'http://localhost:11434')
OPENAI_URL = E('KOCR_OPENAI_URL', 'https://api.openai.com/v1')
OPENAI_KEY = E('KOCR_OPENAI_KEY', '')
TEXT_MODEL = E('KOCR_TEXT_MODEL', 'gemma4:12b-it-qat')
VISION_MODEL = E('KOCR_VISION_MODEL', 'gemma4:12b-it-qat')
LLM_LABEL = E('KOCR_LLM_LABEL', 'gemma4（ローカル）')
WEBHOOK = E('KOCR_WEBHOOK', '')                                  # 受注登録したら JSON を POST する先（基幹・kintone 中継など）
MAX_MB = int(E('KOCR_MAX_MB', '10'))
MAX_PAGES = int(E('KOCR_MAX_PAGES', '3'))
DPI = int(E('KOCR_DPI', '200'))
BRAND = E('KOCR_BRAND', 'Kurage OCR Work')
PUBLIC = E('KOCR_PUBLIC', '')                                     # 公開URL（canonical・OGP）
BUY_URL = E('KOCR_BUY_URL', '')                                   # 当社の公開先だけ。配布先では空
DB = E('KOCR_DB', os.path.join(ROOT, 'outputs', 'orders.sqlite'))

os.makedirs(os.path.join(ROOT, 'outputs', 'work'), exist_ok=True)
os.makedirs(os.path.join(ROOT, 'outputs', 'uploads'), exist_ok=True)
