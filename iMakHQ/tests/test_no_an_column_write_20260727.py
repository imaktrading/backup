# -*- coding: utf-8 -*-
"""★AN列(仕入override)へ **プログラムが書き込まない** ことを構造的に固定する (2026-07-27)。

## 経緯 (同型事故 2 回)
1. 2026-07-24: `restock_reactivate_master` が **N列に直書き** → N の ARRAYFORMULA が壊れ
   N1=#REF! → 全1415行の N が空 → 古い F 由来で価格が過大に (DON!! $279.98)。
   根治として「N は数式のまま、override は AN 列に分離」した。
2. 2026-07-26〜27: 今度は RESTOCK が **毎回 AN に書く** ようになり、AN が入った行は
   N=(M or F)−K の動的追随を無視して **仕入値が凍結**。実測で Boa Hancock P-066 が
   仕入 ¥29,999 で凍結 → 実勢 ¥48,000 に対し $353.98 で出品 = 安売り(EUR265のオファーで発覚)。

## この test が守る不変条件
**AN 列は「人が意図的に固定したい時だけ」入れる入口であり、コードは絶対に書かない。**
書き込みが1つでもコードに入ると、その行は市場価格に追随しなくなり、誰も気づけないまま
安売り(または売れない高値)が続く。監視だけでは事後にしか気づけないので、source 段階で止める。

## 判定方法
リポジトリ内の .py から、スプレッドシートの **AN{行番号} レンジへの書込リテラル** を探す。
`f"AN{row}"` / `"AN%d" % row` / `'AN' + str(row)` 等。read(定数参照)は許可。
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {".git", "__pycache__", "_archive", "node_modules", ".pytest_cache", "venv", ".venv"}
# この test 自身と、AN を **読む** だけのモジュールは対象外
ALLOW_FILES = {"test_no_an_column_write_20260727.py"}

# AN{row} レンジを組み立てる書き方
PATTERNS = [
    re.compile(r'f["\']AN\{'),            # f"AN{row}"
    re.compile(r'["\']AN["\']\s*\+'),     # "AN" + str(row)
    re.compile(r'["\']AN%[ds]'),          # "AN%d" % row
    re.compile(r'["\']AN\{\}'),           # "AN{}".format(row)
]


def _py_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py") and f not in ALLOW_FILES:
                yield os.path.join(root, f)


def test_no_code_writes_to_an_column():
    """AN{row} レンジを作るコードが1つも無いこと。"""
    hits = []
    for path in _py_files():
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for n, line in enumerate(src.splitlines(), start=1):
            if any(p.search(line) for p in PATTERNS):
                hits.append(f"{os.path.relpath(path, REPO)}:{n}: {line.strip()[:100]}")
    assert not hits, (
        "AN列(仕入override)への書込がコードに入っています。AN は人が手で入れる入口であり、"
        "プログラムが書くと仕入値が凍結し市場価格に追随しなくなります。"
        "cost を反映したいなら M列(現在価格)を seed してください。\n  " + "\n  ".join(hits))


def test_restock_writeback_still_seeds_m():
    """RESTOCK writeback が M を seed する実装のままであること(退行検知)。"""
    import sys
    sys.path.insert(0, os.path.join(REPO, "iMakHQ", "tools"))
    import inspect
    import sheet_io
    src = inspect.getsource(sheet_io.restock_reactivate_master)
    # docstring(説明文で AN に言及している)を除いた **コード本体** だけを見る
    body = src.split('"""')[-1]
    assert 'f"M{row}"' in body, "cost は M列に seed する実装であること"
    assert not any(p.search(body) for p in PATTERNS), \
        "restock_reactivate_master が AN レンジに書いていないこと"
