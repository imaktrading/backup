"""同時発売2種の弾を公式セット名で割った結果を固定する (§0c ステップ3).

2026-08-23: eBay 値が2つ在る6弾 (677行) を、公式セット名で行ごとに割り当てた。
1つの値へ機械的に寄せると片方が誤りになるため、**弾ではなく公式セット名をキー**にする。

★取り違え注意 (1文字違い):
    リューズブラスト = Dragon Blast   /  リューノブレード = Dragon Blade
    ラセンフォース   = Spiral Force   /  ライデンナックル = Thunder Knuckle

先例: BW6 (フリーズボルト / コールドフレア) が既に同じ形で入っていた。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools"))

import api  # type: ignore  # noqa: E402
import set_name_integrity_audit as A  # type: ignore  # noqa: E402

# 公式セット名 -> eBay 値 (master verbatim)
PAIRS = {
    "拡張パック「変幻の仮面」":                        "Sv6: Transformation Mask",
    "拡張パック「ロケット団の栄光」":                   "Sv10: The Glory of Team Rocket",
    "ポケモンカードゲームBW 拡張パック「ブラックコレクション」":  "Bw1: Black Collection",
    "ポケモンカードゲームBW 拡張パック「ホワイトコレクション」":  "Bw1: White Collection",
    "ポケモンカードゲームBW 拡張パック「サイコドライブ」":      "Bw3: Psycho Drive",
    "ポケモンカードゲームBW 拡張パック「ヘイルブリザード」":     "Bw3: Hail Blizzard",
    "ポケモンカードゲームBW 拡張パック「ラセンフォース」":      "Bw8: Spiral Force",
    "ポケモンカードゲームBW 拡張パック「ライデンナックル」":     "Bw8: Thunder Knuckle",
    "ポケモンカードゲームBW 拡張パック「リューズブラスト」":     "Bw5: Dragon Blast",
    "ポケモンカードゲームBW 拡張パック「リューノブレード」":     "Bw5: Dragon Blade",
}
# 使ってはいけない対抗値 (英語版の別セット)
FORBIDDEN = {"Sv06: Twilight Masquerade", "Sv10: Destined Rivals"}


def _rows():
    db = sqlite3.connect(str(api._DB_PATH))
    try:
        return db.execute(
            "SELECT set_name_official, json_extract(specs,'$.set_name_ebay') "
            "FROM products WHERE category='pokemon_tcg' "
            "AND set_name_official IS NOT NULL").fetchall()
    finally:
        db.close()


class TestTwinSets(unittest.TestCase):
    def test_values_exist_in_ebay_master(self):
        master = A._load_allowed()[0].get("pokemon_tcg", set())
        missing = sorted(v for v in PAIRS.values() if v not in master)
        self.assertEqual(missing, [], f"master 非実在 (大小含む verbatim 違い): {missing}")

    def test_each_official_maps_to_its_own_value(self):
        got = {}
        for off, se in _rows():
            if off in PAIRS and se:
                got.setdefault(off, set()).add(se)
        for off, want in PAIRS.items():
            self.assertIn(off, got, f"{off} の行が無い")
            self.assertEqual(got[off], {want},
                             f"{off}: 期待 {want!r} 単独。実測 {sorted(got[off])}")

    def test_english_counterpart_not_used(self):
        used = {se for _, se in _rows() if se}
        self.assertEqual(used & FORBIDDEN, set(),
                         "英語版の別セット名が使われている")

    def test_blast_and_blade_not_swapped(self):
        """★1文字違いの取り違えを名指しで止める."""
        m = {off: se for off, se in _rows() if off in PAIRS}
        self.assertEqual(m["ポケモンカードゲームBW 拡張パック「リューズブラスト」"], "Bw5: Dragon Blast")
        self.assertEqual(m["ポケモンカードゲームBW 拡張パック「リューノブレード」"], "Bw5: Dragon Blade")


class TestSectionZeroCIsClean(unittest.TestCase):
    def test_zero(self):
        """§0c が 0 行 (= 別セットの名前が残っていない). 0 のまま維持する."""
        res = A.audit(["pokemon_tcg"])
        self.assertEqual(res.code_value_mismatch, [],
                         f"別セットの名前 {len(res.code_value_mismatch)} 行")


if __name__ == "__main__":
    unittest.main()
