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
# test_*.py は対象外(検体や説明で AN{row} を書くため)。本番コードだけを見る。
# テストが誤って AN に書いても実行時ガード(_ANWriteGuard)が止めるので二重に守られている。
def _is_test_file(name):
    return name.startswith("test_")

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
            if f.endswith(".py") and not _is_test_file(f):
                yield os.path.join(root, f)


def test_patterns_actually_detect_violations():
    """★このガード自体が空振りでないことを検体で固定する (監査指摘 2026-07-27)。

    以前は手元で確認しただけで証跡がリポジトリに残っていなかった。
    なお **数値列指定 / chr() 生成は source 走査では検知できない**(下 2 検体)。
    そこは実行時ガードが受け持つ → `test_an_write_runtime_guard_20260727.py`。
    """
    must_detect = [
        'reqs.append({"range": f"AN{row}", "values": [[cost]]})',
        'rng = "AN" + str(row)',
        'rng = "AN%d" % row',
        'rng = "AN{}".format(row)',
    ]
    must_pass = [
        'reqs.append({"range": f"M{row}", "values": [[cost]]})',   # 正しい書き方
        "PRODUCT_COL_COST_OVERRIDE = 39",                          # 定義
        "an = row[PRODUCT_COL_COST_OVERRIDE]",                     # 読取
    ]
    for s in must_detect:
        assert any(p.search(s) for p in PATTERNS), f"検知できていない: {s}"
    for s in must_pass:
        assert not any(p.search(s) for p in PATTERNS), f"誤検知: {s}"
    # source 走査の限界(=実行時ガードが必要な理由)も明示しておく
    bypasses = ['ws.update_cell(row, 40, cost)', 'col = "A" + chr(65 + idx0 - 26)']
    for s in bypasses:
        assert not any(p.search(s) for p in PATTERNS), \
            "この検体は source 走査では検知できない前提。実行時ガード側で止める"


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
