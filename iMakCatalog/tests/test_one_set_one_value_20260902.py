"""1つのセット名に Set の値は1つ (2026-09-02 制定).

## なぜ要るか

2026-09-01 に「Set が空の行を全部埋めた」と報告したが、**空欄ではない誤り**が残っていた:
同じセットの中に、そのカードが元々収録されていた**別の弾の名前**が混ざっていた。

    ハイクラスパック「VSTARユニバース」 254行 'S12a: Vstar Universe' / 8行 'Crown Zenith'
    アニバーサリーパック01               10行 'Blazing Aura' / 4行 'Raging Roar' …
    Deck Build Box Freedom Ascension    22行 'Newtype Rising' ほか8種

空欄チェックでは見えない (値は入っているので)。**「1セット1値」なら機械で見える**。
ユーザー指摘 (2026-09-02):「何を正と理解したらいいのか分からなくなる」。
= 完了の宣言を人の言葉ではなくテストにする。

## 例外は1つだけ

プロモの刷り (`*-P-*` の product_id) は、`set_name_official` に「元々どの弾のカードか」が
書いてあってもプロモ側の値を持つ。例: `SM-P-165` は 拡張パック「ウルトラサン」 収録の
カードのプロモ版で、値は `Sm-P: Sun & Moon Promos` が正しい。
**プロモID の行だけが違う値**なら合格。それ以外の食い違いは落とす。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api  # noqa: E402

CATEGORIES = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")
# プロモの刷りを表す product_id (SM-P-165 / S-P-042 / SV-P-196 / XYP-182 …)
_PROMO_ID = re.compile(r"(^|[-_])(P|[A-Z]{1,3}-?P)[-_]\d", re.IGNORECASE)


def _rows():
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    try:
        ph = ",".join("?" for _ in CATEGORIES)
        return db.execute(
            f"SELECT category, product_id, set_name_official, specs FROM products "
            f"WHERE category IN ({ph}) AND IFNULL(set_name_official,'') <> ''",
            CATEGORIES).fetchall()
    finally:
        db.close()


def _conflicts():
    """(category, set_name_official, {値: [product_id,…]}) の食い違いだけ返す."""
    by_set = defaultdict(lambda: defaultdict(list))
    for r in _rows():
        v = (json.loads(r["specs"] or "{}") or {}).get("set_name_ebay") or ""
        by_set[(r["category"], r["set_name_official"])][v].append(r["product_id"])

    bad = []
    for (cat, so), vals in by_set.items():
        if len(vals) <= 1:
            continue
        # 一番多い値を本命、それ以外を「違う値の行」とみなす
        main = max(vals, key=lambda v: len(vals[v]))
        deviating = [pid for v, pids in vals.items() if v != main for pid in pids]
        if all(_PROMO_ID.search(p) for p in deviating):
            continue          # プロモの刷りだけが違う = 許す
        bad.append((cat, so, {v: pids[:4] for v, pids in vals.items()}))
    return bad


class TestOneSetOneValue(unittest.TestCase):
    def test_no_set_carries_two_values(self):
        bad = _conflicts()
        msg = "\n".join(f"  {c} / {s} -> {v}" for c, s, v in bad[:10])
        self.assertEqual(bad, [], f"1セットに Set の値が2つ以上ある:\n{msg}")


class TestPromoExceptionIsNarrow(unittest.TestCase):
    """例外がザルになっていないこと (プロモID の判定が普通の弾番号を拾わない)."""

    def test_promo_pattern_matches_promo_ids_only(self):
        for pid in ("SM-P-165", "S-P-042", "SV-P-196", "XYP-182", "M-P-020"):
            self.assertTrue(_PROMO_ID.search(pid), pid)
        for pid in ("OP12-079", "ST21-001_p2", "S12a-197", "FB03-139", "GD01-001"):
            self.assertIsNone(_PROMO_ID.search(pid), pid)


if __name__ == "__main__":
    unittest.main()
