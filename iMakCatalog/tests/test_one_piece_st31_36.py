"""One Piece スターターデッキ ST-16/18/20/26/27/28/29/30/31-36 resolve 回帰.

2026-08-02 更新: 依頼 `2026-08-02_ebay_filter_map_st18_st26_collapse_response.md` を実装。
- ST-18/26/31 (Monkey D. Luffy 3種), ST-20/34 (Charlotte Katakuri 2種),
  ST-11/16 (Uta 2種), ST-09/28 (Yamato 2種) の silent collision を色 prefix で解消
- REVIEW eBay 値 note を検証根拠に置換 (set_code section 内)
- ST-27/32/33/35/36 は現時点 collision 無しだが将来防御のため色 prefix 付与
- ST-08 の Monkey D. Luffy と揃えて dot 表記 (Monkey D.) に統一

固定する状態: yaml 側の新 ebay_value + set_code 一意性 (意図的 alias を除く)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

import psa_to_csv as pc  # type: ignore  # noqa: E402
from iMakCatalog.ebay_filter_map import loader  # noqa: E402

# 依頼応答 (2026-08-02) で確定した set_code → ebay_value 表.
_EXPECT = {
    # A. 色 prefix + dot 統一で 3-way collision (ST-08/18/26/31) 解消
    "ST-08": "Monkey D. Luffy",
    "ST-18": "PURPLE Monkey D. Luffy",
    "ST-26": "PURPLE/BLACK Monkey D. Luffy",
    "ST-31": "RED Monkey D. Luffy",
    # A. Charlotte Katakuri collision 解消 (ST-20/34)
    "ST-20": "YELLOW Charlotte Katakuri",
    "ST-34": "PURPLE Charlotte Katakuri",
    # B. silent collision 解消
    "ST-11": "Uta",
    "ST-16": "GREEN Uta",
    "ST-09": "Yamato",
    "ST-28": "GREEN/YELLOW Yamato",
    # A. 将来防御の色 prefix (現時点 collision 無し)
    "ST-27": "BLACK Marshall D. Teach",
    "ST-32": "GREEN Roronoa Zoro",
    "ST-33": "BLUE Kuzan",
    "ST-35": "RED/BLACK Sabo",
    "ST-36": 'YELLOW Eustass "Captain" Kid',
    # A. 色 prefix 無し (公式に色 prefix 無し・collision 無し)
    "ST-29": "Egghead",
    "ST-30": "Luffy & Ace",
}


class TestST31to36Yaml(unittest.TestCase):
    def test_set_code_mappings(self):
        data = loader.load_yaml(loader.YAML_DIR / "one_piece.yaml")
        m = {e["source"]: e["ebay"] for e in data["set_code"]}
        for code, ebay in _EXPECT.items():
            self.assertEqual(m.get(code), ebay, code)


class TestST31to36Resolve(unittest.TestCase):
    def test_listable_name_rarity_set(self):
        """C:Rarity/C:Set が非空で listing 可能なこと (rarity 正規化まで通過)."""
        cases = [
            ("ONE PIECE JAPANESE ST31-STARTER DECK", "001", "SANJI", "RED Monkey D. Luffy"),
            ("ONE PIECE JAPANESE ST34-STARTER DECK", "001", "CHARLOTTE KATAKURI", "PURPLE Charlotte Katakuri"),
        ]
        for brand, num, subj, set_ebay in cases:
            r = pc.lookup_one_piece(brand, num, subj, verbose=False)
            self.assertIsNotNone(r, brand)
            self.assertTrue(r.get("name_en") or r.get("card_name"), brand)
            self.assertTrue(r.get("rarity"), f"{brand} rarity empty")
            self.assertEqual(r.get("set_name_ebay"), set_ebay, brand)


# 意図的 alias (hyphen variant / EN-JA bundled release) 許容リスト.
# ここに載る組は「複数 set_code が同じ ebay_value に写る」ことを許容する.
# audit test は本集合以外の重複を赤化する.
_INTENTIONAL_ALIASES: dict[str, frozenset[str]] = {
    "500 Years in the Future": frozenset({"OP-07", "OP07"}),
    "Premium Booster One Piece The Best": frozenset({"PRB-01", "PRB01"}),
    "The Azure Sea's Seven Heroes": frozenset({"OP-14", "OP14-EB04"}),
    "Adventure on Kami's Island": frozenset({"OP-15", "OP15-EB04"}),
}


class TestNoSilentCollision(unittest.TestCase):
    """set_code 内で同一 ebay_value に写る組が _INTENTIONAL_ALIASES 以外に無いこと.

    今回の依頼 (silent collision 3件発見) が再発しないための audit 回帰.
    """

    def test_no_unintentional_collision(self):
        data = loader.load_yaml(loader.YAML_DIR / "one_piece.yaml")
        by_ebay: dict[str, list[str]] = {}
        for e in data["set_code"]:
            by_ebay.setdefault(e["ebay"], []).append(e["source"])
        offenders: list[tuple[str, list[str]]] = []
        for ebay_value, sources in by_ebay.items():
            if len(sources) <= 1:
                continue
            allowed = _INTENTIONAL_ALIASES.get(ebay_value)
            if allowed is not None and set(sources) == allowed:
                continue
            offenders.append((ebay_value, sources))
        self.assertEqual(
            offenders,
            [],
            f"unintentional collision detected in set_code: {offenders}",
        )


class TestNoResidualReviewNote(unittest.TestCase):
    """set_code section の note に `REVIEW eBay 値` が残っていないこと (完了条件 #2)."""

    def test_no_review_ebay_value_in_set_code_notes(self):
        data = loader.load_yaml(loader.YAML_DIR / "one_piece.yaml")
        offenders = [
            e["source"] for e in data["set_code"]
            if e.get("note") and "REVIEW eBay 値" in e["note"]
        ]
        self.assertEqual(
            offenders,
            [],
            f"REVIEW eBay 値 note が set_code に残存: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
