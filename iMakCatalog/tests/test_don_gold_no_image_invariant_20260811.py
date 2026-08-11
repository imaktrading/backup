"""DON-*-GOLD 構造的画像なし規約の回帰テスト (2026-08-11 Advisor GO).

依頼: iMak_data/catalog/requests/2026-08-10_missing_images_blocking_listing_response.md
  §「DON-PRB02-BUGGY-GOLD / SHANKS-GOLD (2件): 構造的に画像なしで正しい。docs 明文化 GO」

守る不変条件:
  A) 対象 2 record が DB に存在し、`source` が `HQ_vision_character_poc`
  B) `images` が空 (`[]`) — 画像を持たないことが「正しい」状態
  C) `specs.catalog_internal_key_note` に「公式 card_number 不明」相当が入っている
  D) 将来 image_backfill が誤って上書きしないこと (source pattern が保持されている)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402


TARGETS = ("DON-PRB02-BUGGY-GOLD", "DON-PRB02-SHANKS-GOLD")


class TestDonGoldStructurallyNoImage(unittest.TestCase):

    def test_records_exist(self):
        for pid in TARGETS:
            rec = api.lookup(category="one_piece_tcg", product_id=pid)
            self.assertIsNotNone(rec, f"{pid}: DB に無い")

    def test_source_is_hq_vision(self):
        for pid in TARGETS:
            rec = api.lookup(category="one_piece_tcg", product_id=pid)
            src = (rec or {}).get("source", "")
            self.assertTrue(
                src.startswith("HQ_vision_"),
                f"{pid}: source={src!r} (期待 HQ_vision_*)")

    def test_images_empty(self):
        """画像が空であることが「正しい」状態。将来 backfill 誤動作の検知."""
        for pid in TARGETS:
            rec = api.lookup(category="one_piece_tcg", product_id=pid)
            imgs = (rec or {}).get("images") or []
            self.assertEqual(
                len(imgs), 0,
                f"{pid}: images={imgs!r} (期待 空)。"
                "backfill が誤って第三者画像を書いた可能性あり")

    def test_internal_key_note_present(self):
        """catalog_internal_key_note の記述が消えていない (指示解体防止)."""
        for pid in TARGETS:
            rec = api.lookup(category="one_piece_tcg", product_id=pid)
            note = (rec or {}).get("specs", {}).get("catalog_internal_key_note", "")
            # note が完全一致でなくてよい (歴史的に文言変化あり) が、
            # 「公式 card_number」相当のキーワードは含む想定。
            self.assertTrue(
                "公式" in note or "card_number" in note.lower() or "dedup" in note.lower(),
                f"{pid}: catalog_internal_key_note={note!r} "
                "(『公式 card_number 不明; ... dedup ...』相当が期待)")


if __name__ == "__main__":
    unittest.main()
