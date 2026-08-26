# -*- coding: utf-8 -*-
"""正解の変種行が目視候補に出ること (2026-08-26).

実害 (cert149779654 BOA HANCOCK / PSA brand=
`ONE PIECE JAPANESE PREMIUM BOOSTER -ONE PIECE CARD THE BEST- STORAGE BOX SET`):
候補51件に `ST17-004` (通常版) しか出ず、catalog に在る
`ST17-004_L` / `_L_haku` / `_p1` / `_p2` の4行が1件も出なかった。原因は2つで、
どちらも引き方 (②) 側:

  1. `_extract_set_code` が商品名の `STORAGE` を set_code と誤読 →
     `LIKE '%STORAGE%'` が DON-STORAGE-001〜010 を返して枠を食っていた
  2. キャラ名の枝の番号一致が `%-004` の末尾完全一致だけで、`_L` が付くと外れる

判定 (1丁目1番地): ①カタログは正しい (5行とも画像つきで在る) → ②を直す。
候補に出すだけで自動採用はしない (人が絵とセット名で選ぶ)。

依頼書: hq/requests/2026-08-24_cert149779654_correct_rows_not_offered.md
回答書: hq/requests/2026-08-24_cert149779654_correct_rows_not_offered_response.md
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import post_psa_review as R  # noqa: E402

BRAND = ("ONE PIECE JAPANESE PREMIUM BOOSTER -ONE PIECE CARD THE BEST- "
         "STORAGE BOX SET")

# catalog の実データ (2026-08-26 実測) を模した最小セット。
_ROWS = [
    ("ST17-004", "Boa Hancock", "STARTER DECK -BLUE Donquixote Doflamingo- [ST-17]"),
    ("ST17-004_L", "Boa Hancock", "限定商品収録カード"),
    ("ST17-004_L_haku", "Boa Hancock", "限定商品収録カード"),
    ("ST17-004_p1", "Boa Hancock", "プレミアムブースター ONE PIECE CARD THE BEST ストレージボックスセット"),
    ("ST17-004_p2", "Boa Hancock", "プレミアムブースター ONE PIECE CARD THE BEST ストレージボックスセット"),
    # 番号違いの同キャラ (落としてはいけないが、004 の枠を奪ってもいけない)
    ("OP01-078", "Boa Hancock", "ROMANCE DAWN"),
]
# `%STORAGE%` で釣れてしまう別カード (誤読の実害そのもの)
_NOISE = [(f"DON-STORAGE-{i:03d}", "Don!! Card", "ストレージボックスセット") for i in range(1, 11)]


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    db = tmp_path / "products.sqlite"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE products (category TEXT, product_id TEXT, name_en TEXT,"
                " set_name_official TEXT, set_name TEXT, images TEXT)")
    for pid, name, setn in _ROWS + _NOISE:
        con.execute("INSERT INTO products VALUES ('one_piece_tcg',?,?,?,'','[]')",
                    (pid, name, setn))
    con.commit()
    con.close()
    monkeypatch.setattr(R, "CATALOG_DB", db)
    return db


def _pids(**kw):
    kw.setdefault("brand", BRAND)
    return [p for (p, _img, _set) in R._get_candidates(**kw)]


class Test商品名をセット記号と読まない:
    def test_STORAGEはset_codeにしない(self):
        assert R._extract_set_code(BRAND, "one_piece_tcg") is None

    def test_本物のセット記号は今までどおり読む(self):
        for b, want in [("ONE PIECE JAPANESE ST17 STARTER DECK", "ST17"),
                        ("ONE PIECE JAPANESE OP01 ROMANCE DAWN", "OP01"),
                        ("ONE PIECE JAPANESE PROMOS", "PROMOS")]:
            assert R._extract_set_code(b, "one_piece_tcg") == want, b


class Test候補に変種が出る:
    def test_正解4行が候補に入る(self, catalog):
        got = _pids(category="one_piece_tcg", set_code=None, card_number="004",
                    subject="BOA HANCOCK")
        for pid in ("ST17-004", "ST17-004_L", "ST17-004_L_haku",
                    "ST17-004_p1", "ST17-004_p2"):
            assert pid in got, f"{pid} が候補に出ていない: {got}"

    def test_DONで枠が埋まらない(self, catalog):
        got = _pids(category="one_piece_tcg", set_code=None, card_number="004",
                    subject="BOA HANCOCK")
        assert not [p for p in got if p.startswith("DON-STORAGE-")], got

    def test_番号違いの同キャラは候補から消えない(self, catalog):
        """救済枠は残す (取りこぼしを増やす変更ではない)。"""
        got = _pids(category="one_piece_tcg", set_code=None, card_number="004",
                    subject="BOA HANCOCK")
        assert "OP01-078" in got, got

    def test_余計な行は増えない(self, catalog):
        """候補は catalog に在る Boa Hancock 6行だけ (別カードを釣らない)。"""
        got = _pids(category="one_piece_tcg", set_code=None, card_number="004",
                    subject="BOA HANCOCK")
        assert set(got) == {p for p, _n, _s in _ROWS}, got

    def test_番号一致は変種suffixだけを足す(self, catalog):
        """足したのは `004_` の形だけ。`0041` のような別番号は釣らない。

        (キャラ名が違う行で見る。同じキャラなら番号違いでも救済枠で出るのが正)。
        """
        con = sqlite3.connect(str(catalog))
        con.execute("INSERT INTO products VALUES "
                    "('one_piece_tcg','ST17-0041','Nico Robin','x','','[]')")
        con.commit()
        con.close()
        got = _pids(category="one_piece_tcg", set_code=None, card_number="004",
                    subject="BOA HANCOCK")
        assert "ST17-0041" not in got, got
