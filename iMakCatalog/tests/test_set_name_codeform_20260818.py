"""表記規約22セット = コード形 (HQ 裁定 2026-08-18) の回帰アンカー.

回答書: requests/2026-08-10_tcg_ssot_a4_result_and_one_decision_req_response.md [IMPLEMENT-GO]

判定 (1丁目1番地): ① カタログのデータは正しい (set_name_official は公式原文のまま /
候補はどちらも eBay master 実在) → ② 出品くん側 = C:Set に出す表記を HQ が裁定。

決定: master に「コード形」と「長形/素名」が併存する 15 set は **コード形**。
根拠は HQ の eBay 本番 API 実測 (長形相手に 7.5倍 / 素名相手は差 10% 以内)。

このテストが守る不変条件:
  A) 15 set の値が master 2,290値に verbatim で実在する (組み立て値を混ぜない)
  B) DB に長形/素名が 1 行も残っていない
  C) yaml (=SSOT) からの導出と焼き込み値が一致する (map と DB の乖離を作らない)
  D) 意図的に触らないと決めた 3 件を巻き込んでいない
  E) 裁定が pokemon.yaml に載っている (DB だけに書いて git に残さない事故の再発防止)
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
import api  # type: ignore  # noqa: E402

MASTER = _REPO / "data/ebay_filter_masters/tcg.json"
CATEGORY = "pokemon_tcg"

# 旧表記 → 決定したコード形 (master verbatim)
CODEFORM = {
    "Sword & Shield - Battle Styles":     "Swsh05: Battle Styles",
    "Sword & Shield - Chilling Reign":    "Swsh06: Sword & Shield - Chilling Reign",
    "Sword & Shield - Lost Origin":       "Swsh11: Lost Origin",
    "Sword & Shield - Silver Tempest":    "Swsh12: Sword & Shield - Silver Tempest",
    "Scarlet & Violet - Obsidian Flames": "SV03: Obsidian Flames",
    "Prismatic Evolutions":               "Sv: Prismatic Evolutions",
    "Journey Together":                   "Sv09: Journey Together",
    "Astral Radiance":                    "Swsh10: Astral Radiance",
    "Fusion Strike":                      "Swsh08: Fusion Strike",
    "Vivid Voltage":                      "Swsh04: Vivid Voltage",
    "Darkness Ablaze":                    "Swsh03: Darkness Ablaze",
    "Rebel Clash":                        "Swsh02: Rebel Clash",
    "Evolving Skies":                     "SWSH07: Evolving Skies",
    "Shining Legends":                    "Sm3+: Shining Legends",
    "Pokémon GO":                         "S10b: Pokémon GO",
}
EXPECTED_ROWS = 2051

# 「表記の選択」ではないので巻き込んではいけない値 (2026-08-11 回答 §2/§3 + 別名ケース)
UNTOUCHED = {
    "Start Deck 100":              "2026-08-11 §3 現状維持 (テスト在り=意図値)",
    "Premium Champion Pack":       "2026-08-11 §3 現状維持 (テスト在り=意図値)",
    "25th Anniversary Golden Box": "2026-08-11 §2 現状維持",
    "Double Crisis":               "master 対抗値は別名 (CP1: Magma Gang vs Aqua Gang: …) = 保留",
}


def _master_values() -> set:
    return set(json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]["Set"]["values"])


def _set_name_rows():
    con = sqlite3.connect(str(api._DB_PATH))
    try:
        return con.execute(
            "SELECT product_id, set_name_official, "
            "       json_extract(specs,'$.set_name_ebay') se "
            "FROM products WHERE category=?", (CATEGORY,)).fetchall()
    finally:
        con.close()


class TestCodeformValuesAreMasterVerbatim(unittest.TestCase):
    def test_all_targets_exist_in_master(self):
        """A) 書いた値が master に実在する.

        外れても eBay はエラーを返さずカテゴリ全件を返す (= 絞り込めていないのに
        正常応答に見える) ため、実在チェックはテストでしか担保できない。
        """
        master = _master_values()
        missing = sorted(v for v in CODEFORM.values() if v not in master)
        self.assertEqual(missing, [], f"master 非実在: {missing}")

    def test_case_sensitive_verbatim(self):
        """大文字小文字を勝手に整形していない (`SV02:` は master に無く `Sv02:` が正)."""
        master = _master_values()
        lower = {m.lower(): m for m in master}
        for v in CODEFORM.values():
            self.assertEqual(lower.get(v.lower()), v,
                             f"{v!r} は master の表記と大小が違う (正: {lower.get(v.lower())!r})")


class TestDbSwitchedToCodeform(unittest.TestCase):
    def test_no_longform_row_left(self):
        """B) 長形/素名が 1 行も残っていない."""
        left = Counter(r[2] for r in _set_name_rows() if r[2] in CODEFORM)
        self.assertEqual(dict(left), {}, f"長形が残っている: {dict(left)}")

    def test_codeform_row_count(self):
        """コード形 15 set の合計が実測 baseline と一致."""
        want = set(CODEFORM.values())
        n = sum(1 for r in _set_name_rows() if r[2] in want)
        self.assertEqual(n, EXPECTED_ROWS)

    def test_derive_matches_stored(self):
        """C) yaml からの導出 == 焼き込み値 (map と DB が乖離していない)."""
        want = set(CODEFORM.values())
        bad = []
        for pid, official, se in _set_name_rows():
            if se not in want:
                continue
            if api.derive_set_name_ebay(CATEGORY, official, pid) != se:
                bad.append((pid, official, se))
        self.assertEqual(bad[:5], [], f"map 導出と不一致 {len(bad)} 行")


class TestCarveOutsUntouched(unittest.TestCase):
    def test_intentional_values_still_present(self):
        """D) 触らないと決めた値が消えていない (一括適用の巻き込み検知)."""
        vals = Counter(r[2] for r in _set_name_rows())
        for v, why in UNTOUCHED.items():
            self.assertGreater(vals.get(v, 0), 0, f"{v!r} が消えた — {why}")


class TestYamlIsSsot(unittest.TestCase):
    """E) 裁定が pokemon.yaml に載っている (= git に残り、DB を作り直しても再現する).

    2026-08-18 の実害: 20 件の official→コード形 マップが **共有 DB の
    ebay_filter_map テーブルにだけ** 書かれ、yaml にも migration にも残っていなかった。
    api.register_filter_map の docstring どおり yaml が SSOT なので、この状態だと
    DB を yaml から作り直した瞬間に 20 件が消え、2,051 行の導出が
    None (= 空欄 = 出品されない) に落ちる。しかも **eBay はエラーを返さない**ので
    気付けない。yaml に載っていることをテストで固定する。
    """

    def _yaml_set_entries(self) -> dict:
        import yaml  # noqa: PLC0415
        path = _REPO / "ebay_filter_map/pokemon.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {e["source"]: e["ebay"] for e in (data.get("set") or [])}

    def test_every_codeform_value_is_declared_in_yaml(self):
        declared = set(self._yaml_set_entries().values())
        missing = sorted(v for v in CODEFORM.values() if v not in declared)
        self.assertEqual(missing, [], f"yaml に無いコード形 (DB だけの裁定): {missing}")

    def test_yaml_matches_db_filter_map(self):
        """yaml の宣言と DB の map が一致 (loader を回せば同じ状態に戻る)."""
        drift = []
        for source, ebay in self._yaml_set_entries().items():
            got = api.to_ebay_value(CATEGORY, "set", source)
            if got != ebay:
                drift.append((source, ebay, got))
        self.assertEqual(drift, [], f"yaml↔DB 乖離 {len(drift)} 件: {drift[:5]}")

    def test_yaml_covers_all_rows_that_carry_codeform(self):
        """yaml 宣言だけで 2,051 行を導出できる (焼き込みに依存していない)."""
        want = set(CODEFORM.values())
        declared = self._yaml_set_entries()
        uncovered = sorted({
            official for official, _, se in
            ((o, p, s) for p, o, s in _set_name_rows())
            if se in want and official not in declared
        })
        self.assertEqual(uncovered, [], f"yaml 未宣言の official: {uncovered}")


if __name__ == "__main__":
    unittest.main()
