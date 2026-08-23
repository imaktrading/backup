"""進化段階を公式の欄 (`<span class="type">`) から取ることを固定する.

経緯 (2026-08-23): 取り込みが **ページ全文** から進化段階の語を探していたため、
進化段階の欄を持たないトレーナーズ/エネルギーで効果テキストやセット名に当たっていた。

    M4-074 変化の書      「自分のトラッシュから たね ポケモンを1枚選び」   -> 'たね'
    MC-650 ハイパーアロマ  「自分の山札から 1進化 ポケモンを3枚まで選び」  -> '1進化'
    M2a-148 改造ハンマー   「ハイクラスパック 『MEGAドリームex』」        -> 'MEGA'

依頼書の指摘は Trainer 479行だったが、実測は **2,366行** (Trainer 1,047 /
Energy 788 / Pokémon 503 / 種別なし 28) だった。同日のタイプ取り違え
(ピカチュウ 6,138枚が Fighting) と同じ形。
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
from tcg_ebay_normalized_fields_20260615 import norm_stage  # type: ignore  # noqa: E402

# 公式が実際に使う進化段階の語 (2026-08-23 に 21,982枚を走査)
OFFICIAL_VOCAB = {"たね", "1進化", "2進化", "V進化", "レベルアップ",
                  "BREAK進化", "復元", "M進化", "伝説", "V-UNION"}


class TestScraperAnchors(unittest.TestCase):
    def test_scraper_uses_span_anchor_not_free_text(self):
        src = (_REPO / "scrapers" / "pokemon_tcg.py").read_text(encoding="utf-8")
        self.assertIn('<span class="type">', src,
                      "進化段階が欄にアンカーされていない")
        self.assertNotIn(r'r"(2\s*進化|1\s*進化|たね|基本|MEGA', src,
                         "ページ全文から探す旧実装が残っている")


class TestStageMapping(unittest.TestCase):
    def test_keys_are_official_vocabulary(self):
        import tcg_ebay_normalized_fields_20260615 as T
        stray = sorted(k for k in T._STAGE if k not in OFFICIAL_VOCAB)
        self.assertEqual(stray, [], f"公式に存在しない鍵: {stray} (旧 'MEGA' 等)")

    def test_unknown_stage_is_blank_not_guessed(self):
        # eBay の Stage は FREE_TEXT で正解表が無い。分からないものは空欄 (fail-closed)
        for v in ("V進化", "レベルアップ", "BREAK進化", "復元", "伝説", "V-UNION", "なにか"):
            self.assertEqual(norm_stage(v), "", f"{v!r} に推測値を入れている")

    def test_known_stage_maps(self):
        self.assertEqual(norm_stage("たね"), "Basic")
        self.assertEqual(norm_stage("1進化"), "Stage 1")
        self.assertEqual(norm_stage("2進化"), "Stage 2")
        self.assertEqual(norm_stage("M進化"), "Mega")


class TestLiveData(unittest.TestCase):
    def _rows(self):
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            return db.execute(
                "SELECT product_id, specs FROM products WHERE category='pokemon_tcg'"
            ).fetchall()
        finally:
            db.close()

    def test_no_stage_on_trainer_or_energy(self):
        bad = []
        for pid, sp in self._rows():
            s = json.loads(sp or "{}")
            if s.get("card_type_ebay") in ("Trainer", "Energy") \
                    and (s.get("stage") or s.get("stage_ebay")):
                bad.append((pid, s.get("card_type_ebay"), s.get("stage")))
        self.assertEqual(bad[:5], [], f"進化段階を持たない種別に stage {len(bad)} 行")

    def test_stage_values_are_official_vocabulary(self):
        stray = {}
        for pid, sp in self._rows():
            v = (json.loads(sp or "{}").get("stage") or "").strip()
            if v and v not in OFFICIAL_VOCAB:
                stray.setdefault(v, []).append(pid)
        self.assertEqual(sorted(stray), [], f"公式に無い進化段階の値: {sorted(stray)}")

    def test_audit_section_is_zero(self):
        res = A.audit(["pokemon_tcg"])
        self.assertEqual(res.stage_on_non_pokemon, [],
                         f"監査 §9 が {len(res.stage_on_non_pokemon)} 行")


if __name__ == "__main__":
    unittest.main()
