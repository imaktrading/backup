# -*- coding: utf-8 -*-
"""カタログの取得元を公式だけに保つ見張り (2026-08-08).

経緯:
  ユーザーが「Gundam の収集が exburst.dev を見ている / PSA でエラーが出ている」と気づいた。
  調べた結果:
    - 犯人は `iMakTCG/data/test_carddb.py` (2026-05-09 の使い捨て確認スクリプト、29行)。
      print するだけで DB 書込は無く、**products は 1件も汚染されていなかった**
    - しかし **誰からも参照されていない**のに repo に残っており、
      「これは DB に書くのか?」を調べる過程で **実際に実行された** (headless catalog が
      回答書にファイル全文を引用していた)
    - PSA 側のエラーは別件で `version_main=146` 固定 (Chrome は 151)。`3feeb31` で是正済

  = 非公式サイトを開くだけのスクリプトが SSOT の隣に置いてあると、調査のたびに実行される。

守りたいこと (memory `catalog_official` / `catalog_ssot_principle`):
  **catalog に入れてよいのは公式だけ。** 非公式サイトへの参照を repo に置かない。

Gundam の公式 (2026-08-08 実測。products の source_url はこの2つだけ):
  https://api.bandai-tcg-plus.com/api/user/card/...   1,808件 (Bandai 公式API)
  https://www.gundam-gcg.com/jp/cards/detail/...        816件 (公式カードゲームサイト)
"""
from __future__ import annotations

import os
import subprocess
import sys

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

#: 非公式の カードDB / まとめサイト。catalog の取得元にしてはいけない。
#: (ここに足す時は「なぜ非公式か」を1行書くこと)
NON_OFFICIAL_SOURCES = [
    "exburst.dev",      # 有志の Gundam カードリスト。公式表記と食い違う可能性がある
]

#: このテスト自身は語を持つので走査から除く
_SKIP_PREFIX = os.path.join("iMakHQ", "tests").replace("\\", "/")


def _tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=_ROOT,
                             capture_output=True, text=True, timeout=90)
    except Exception:                                          # noqa: BLE001
        return []
    return [p for p in out.stdout.splitlines() if p and not p.startswith(_SKIP_PREFIX)]


def test_git_ls_files_works():
    """走査できていること (空振りしてテストが無意味になる事故の防止)。"""
    assert _tracked_files(), "git ls-files が空 — 走査できていない"


def test_no_non_official_source_in_tracked_files():
    """git 管理下に非公式ソースへの参照が無いこと。

    ★「使わなければ害はない」ではない。**置いてあると調査のたびに実行される**
    (2026-08-07 に実際そうなった)。参照ごと消すのが唯一の防ぎ方。
    """
    offenders = []
    for rel in _tracked_files():
        path = os.path.join(_ROOT, rel)
        if not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > 2_000_000:              # 巨大 dump は読まない
                continue
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for bad in NON_OFFICIAL_SOURCES:
            if bad in src:
                offenders.append(f"{rel}: {bad}")
    assert not offenders, (
        "非公式ソースへの参照が git 管理下にある (catalog は公式のみ): " + "; ".join(offenders))


def test_denylist_is_documented():
    """足す時に理由を書かせる (このファイルのコメント運用を固定)。"""
    src = open(__file__, encoding="utf-8").read()
    for bad in NON_OFFICIAL_SOURCES:
        i = src.find(f'"{bad}"')
        assert i > 0 and "#" in src[i:i + 200], f"{bad} に『なぜ非公式か』の注記が無い"
