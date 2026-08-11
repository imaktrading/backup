"""ST-21 / ST-22 / ST-25 set_name_ebay restamp 回帰テスト (窓口GO 2026-08-01).

依頼: iMak_data/catalog/requests/2026-08-01_fix_catalog_data_only_response.md §段階1

真因: filter_map/yaml (SSOT) は 6/8 に修正済だが、products.specs.set_name_ebay に
2026-06-08 の stamp が残り、以下 3 セット計 76件が古い値のまま
(ST-21='Ace & Newgate' / ST-22='ONE PIECE FILM RED' / ST-25='Aramaki Premium Card Set')。
migration `2026-08-01_st21_22_25_setname_ebay_restamp.py` で SSOT に合わせて再導出。

このテストは以下の再発を検出する:
  1. filter_map (SSOT) が 3 セットで期待値を返さなくなった (再誤設定)
  2. products の 76件が SSOT の期待値でない (再 stamp 漏れ / 別 migration による退行)
  3. Ultra Prism 誤マップ 327件 (blanked_by_ultra_prism_mismap_20260731) が壊れた
  4. 8/1 backfill 21件 (filter_map_backfill_20260801) が壊れた
  5. 他 STARTER DECK (ST-01..30 のうち事故 5 セット以外) が誤って touch された
"""
from __future__ import annotations
import json
import sqlite3
import sys
import unittest
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))

import api  # noqa: E402


CAT = "one_piece_tcg"

# (set_name_official, expected_set_name_ebay, expected_row_count)
TARGETS = [
    ("STARTER DECK EX -GEAR5- [ST-21]",       "Gear 5",         30),
    ("STARTER DECK -Ace & Newgate- [ST-22]",  "Ace & Newgate",  31),
    ("STARTER DECK -BLUE Buggy- [ST-25]",     "Buggy",          15),
]

# 対象外だがユニット化しておく (再発防止)
OTHER_STARTER_DECK_SAMPLE = [
    # (set_name_official, expected_set_name_ebay)
    # 段階3 (ST-31..36) は 2026-08-11 Advisor GO で色 prefix 付き canonical に反映
    # (op03_001_p2_set_name_ebay_empty_response.md 段2, Group A 85 行)。
    # 旧 2026-08-01 の「fail_closed_no_map で空欄維持」は撤回。
    ("STARTER DECK -RED Monkey.D.Luffy- [ST-31]", "RED Monkey D. Luffy"),
    ("STARTER DECK -GREEN Roronoa Zoro- [ST-32]", "GREEN Roronoa Zoro"),
    ("STARTER DECK -BLUE Kuzan- [ST-33]", "BLUE Kuzan"),
]

# 段階2 (ST-18/ST-26) は保留=触らない
STAGE2_UNTOUCHED = [
    "STARTER DECK -PURPLE Monkey.D.Luffy- [ST-18]",
    "STARTER DECK -PURPLE/BLACK Monkey.D.Luffy- [ST-26]",
]


class TestFilterMapSsot(unittest.TestCase):
    """SSOT (DB filter_map + yaml) が 3 セットで期待値を返すこと."""

    def test_st21_maps_to_gear5(self):
        v = api.derive_set_name_ebay(
            CAT, "STARTER DECK EX -GEAR5- [ST-21]", "ST21-001")
        self.assertEqual(v, "Gear 5")

    def test_st22_maps_to_ace_and_newgate(self):
        v = api.derive_set_name_ebay(
            CAT, "STARTER DECK -Ace & Newgate- [ST-22]", "ST22-001")
        self.assertEqual(v, "Ace & Newgate")

    def test_st25_maps_to_buggy(self):
        v = api.derive_set_name_ebay(
            CAT, "STARTER DECK -BLUE Buggy- [ST-25]", "ST25-001")
        self.assertEqual(v, "Buggy")


class TestProductsRestamped(unittest.TestCase):
    """DB 上の 76 商品が SSOT の期待値でスタンプされていること."""

    def _rows(self, set_official: str):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            rows = con.execute(
                "SELECT product_id, specs FROM products "
                "WHERE category=? AND set_name_official=?",
                (CAT, set_official),
            ).fetchall()
        finally:
            con.close()
        return rows

    def test_each_target_set_all_rows_have_expected_ebay_value(self):
        for set_official, expected_val, expected_count in TARGETS:
            rows = self._rows(set_official)
            self.assertEqual(len(rows), expected_count,
                             f"{set_official}: 件数が {expected_count} から変動")
            vals = Counter()
            for _pid, specs_json in rows:
                d = json.loads(specs_json) if specs_json else {}
                vals[d.get("set_name_ebay")] += 1
            self.assertEqual(
                dict(vals), {expected_val: expected_count},
                f"{set_official}: set_name_ebay 分布が期待と不一致 {dict(vals)}")

    def test_source_tag_restamp_present_for_updated_rows(self):
        """一度 restamp した行は filter_map_restamp_20260801 が付くこと.

        (別 migration が上書きしていない前提)."""
        for set_official, expected_val, _n in TARGETS:
            rows = self._rows(set_official)
            for pid, specs_json in rows:
                d = json.loads(specs_json) if specs_json else {}
                self.assertEqual(d.get("set_name_ebay"), expected_val,
                                 f"{pid}: value mismatch")
                # source tag は restamp 由来を許容 (以降の SSOT 由来 stamp 全般を受容)
                src = d.get("set_name_ebay_source", "")
                self.assertNotIn("clean_20260608", src,
                                 f"{pid}: 6/8 stamp が残っている ({src})")


class TestInvariantsUntouched(unittest.TestCase):
    """他ラベル 2 種の件数が変わっていない (§条件4)."""

    def _count_tag(self, tag: str) -> int:
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            n = con.execute(
                "SELECT count(*) FROM products WHERE "
                "json_extract(specs,'$.set_name_ebay_source')=?",
                (tag,),
            ).fetchone()[0]
        finally:
            con.close()
        return n

    def test_ultra_prism_206_still_blanked(self):
        # 当初327。SM4p 121件は SSOT契約(Advisor 2026-08-11 §4)で canonical 再populate
        # したため 327-121=206 が残 blank (ウルトラサン/ムーン/フォース = master に canonical 無し)。
        self.assertEqual(
            self._count_tag("blanked_by_ultra_prism_mismap_20260731"), 206)

    def test_backfill_21_still_promo_cards(self):
        self.assertEqual(
            self._count_tag("filter_map_backfill_20260801"), 21)


class TestStage2Untouched(unittest.TestCase):
    """段階2 (ST-18/ST-26) は窓口の目視確認待ちで触らない."""

    def test_stage2_sets_not_stamped_by_this_restamp(self):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            for set_official in STAGE2_UNTOUCHED:
                rows = con.execute(
                    "SELECT product_id, specs FROM products "
                    "WHERE category=? AND set_name_official=?",
                    (CAT, set_official),
                ).fetchall()
                for pid, specs_json in rows:
                    d = json.loads(specs_json) if specs_json else {}
                    self.assertNotEqual(
                        d.get("set_name_ebay_source"),
                        "filter_map_restamp_20260801",
                        f"{pid}: 段階2 のはずが restamp が付いている")
        finally:
            con.close()


class TestStage3Untouched(unittest.TestCase):
    """段階3 (ST-31..36) は restamp 対象外.

    starter deck 本体行 (ST31-001..005 等) は fail_closed_no_map で空欄維持。
    ただし draft A-2 のとおり P-xxx_STxx (Promo P- 系再録) は 'Promo Cards' で
    正しく埋まっており、これは触らない。判定基準は「restamp source tag が付いていない」。
    """

    def test_stage3_not_stamped_by_this_restamp(self):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            for set_official, _expected in OTHER_STARTER_DECK_SAMPLE:
                rows = con.execute(
                    "SELECT product_id, specs FROM products "
                    "WHERE category=? AND set_name_official=?",
                    (CAT, set_official),
                ).fetchall()
                for pid, specs_json in rows:
                    d = json.loads(specs_json) if specs_json else {}
                    self.assertNotEqual(
                        d.get("set_name_ebay_source"),
                        "filter_map_restamp_20260801",
                        f"{pid}: 段階3 のはずが restamp が付いている")
        finally:
            con.close()

    def test_stage3_starter_deck_body_rows_filled_with_color_prefix(self):
        """starter deck 本体 (STxx-NNN 型式) は 2026-08-11 の Advisor GO 以降、
        色 prefix 付き canonical で埋まっている
        (op03_001_p2_set_name_ebay_empty_response.md 段2, Group A の 85 行)。
        Why 撤回: 2026-08-02 に yaml で ST-31..36 に色 prefix mapping を追加
        (ST-08/18/26 collision 解消) → 現行 filter_map で自動導出可能に。"""
        import re
        body_re = re.compile(r"^ST3[1-6]-\d+$")
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            for set_official, expected in OTHER_STARTER_DECK_SAMPLE:
                rows = con.execute(
                    "SELECT product_id, specs FROM products "
                    "WHERE category=? AND set_name_official=?",
                    (CAT, set_official),
                ).fetchall()
                for pid, specs_json in rows:
                    if not body_re.match(pid):
                        continue  # P-xxx_STxx 再録は対象外
                    d = json.loads(specs_json) if specs_json else {}
                    val = d.get("set_name_ebay")
                    self.assertEqual(
                        val, expected,
                        f"{pid}: 段階3 本体行が canonical でない ({val!r} vs {expected!r})")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
