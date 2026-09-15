"""日本語版の旧セットに英語版の別セット名を当てていないこと (2026-09-15).

8/23 ユーザー確定「③ 英語版の別セット名を使う → 禁止。例外は作らない」の後も、
拡張パック「赤い閃光」= Breakthrough 等が 1,580行 残っていた (週次監査 §5 で発見)。
英訳は Bulbapedia の日本語版セット一覧で確認した名前。
"""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
Y = yaml.safe_load((ROOT / "ebay_filter_map" / "pokemon.yaml").read_text(encoding="utf-8"))
SET = {e["source"]: e["ebay"] for e in Y["set"]}
CODE = {e["source"]: e["ebay"] for e in Y["set_code"]}
DBS = yaml.safe_load((ROOT / "ebay_filter_map" / "dragonball.yaml").read_text(encoding="utf-8"))

EN_VERSION_NAMES = {"Breakthrough", "XY - Steam Siege", "Fates Collide", "Legends Awakened",
                    "Diamond & Pearl", "Heartgold & Soulsilver", "Secret Wonders",
                    "Mysterious Treasures", "Stormfront", "XY - Furious Fists", "XY - Phantom Forces",
                    "XY - Ancient Origins", "Roaring Skies", "Majestic Dawn", "Great Encounters",
                    "Dragon Vault", "Breakpoint", "Triumphant"}


class TestJpOldSetsOwnValue(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(SET["拡張パック「赤い閃光」"], "Red Flash")
        self.assertEqual(SET["ポケモンカードゲームXY BREAK 拡張パック「青い衝撃」"], "Blue Shock")
        self.assertEqual(SET["ポケモンカードゲームDP 拡張パック「湖の秘密」"], "Secret of the Lakes")
        self.assertEqual(SET["拡張パック「頂上大激突」"], "L3: Clash at the Summit")          # eBay master の値
        self.assertEqual(SET["ポケモンカードゲームDPtギフトボックス（ナエトルデッキ）"], "DPt Gift Box (Turtwig)")

    def test_no_jp_set_maps_to_english_version_name(self):
        bad = {s: v for s, v in SET.items() if v in EN_VERSION_NAMES and ("「" in s or "DPt" in s)}
        self.assertEqual(bad, {})

    def test_set_code_values_are_master_values(self):
        self.assertEqual(CODE["SV6"], "Sv6: Transformation Mask")
        self.assertEqual(CODE["SV8a"], "Sv8a: Terastal Fest Ex")
        self.assertEqual(CODE["SV10"], "Sv10: The Glory of Team Rocket")

    def test_dbs_typo_sources_removed(self):
        srcs = {e["source"] for e in DBS["set"]}
        self.assertNotIn("ブースターパック 迫り高き戦闘力 [FB08]", srcs)
        self.assertNotIn("ブースターパック 迫り来る強敵[FB06]", srcs)


if __name__ == "__main__":
    unittest.main()
