#!/usr/bin/env python3
"""配布ZIP（kappstore 同梱物）を作る。git で管理しているファイルだけを入れる（.env・outputs・.venv は入らない）。

  /usr/bin/python3 scripts/make_zip.py
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'outputs' / 'kurage-ocr-work.zip'
OUT.parent.mkdir(exist_ok=True)
subprocess.run(['git', 'archive', '--format=zip', '--prefix=kurage-ocr-work/', '-o', str(OUT), 'HEAD'], cwd=ROOT, check=True)
names = subprocess.run(['unzip', '-Z1', str(OUT)], capture_output=True, text=True).stdout.split()
bad = [n for n in names if n.endswith('.env') or '/outputs/' in n or '/store/' in n]
assert not bad, bad
print(OUT, f'{OUT.stat().st_size:,}B', len(names), 'files')
for n in names:
    if n.count('/') <= 2 and not n.startswith('kurage-ocr-work/tessdata/configs/') and not n.startswith('kurage-ocr-work/tessdata/tessconfigs/'):
        print('  ', n)
