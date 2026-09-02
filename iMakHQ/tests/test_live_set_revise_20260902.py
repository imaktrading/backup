# -*- coding: utf-8 -*-
"""出品中の C:Set をカタログの現在値に揃える Revise の判定 (2026-09-02)。

## 実害
カタログが 8/23 に英語版セット名を捨て、9/2 に空欄 1,829行を埋めたが、**既に出した分**は
eBay 側が当時の値のまま。実測 (2026-09-02) で 出品中 Pokemon PSA 247件のうち **124件**が
カタログの現在値と違っていた。日本のカードに英語版の弾名 (`Sword & Shield—Crown Zenith`)
が付いたままの行が含まれ、買い手には別セットの収録品に見える = 誤記載。

## ここで守ること
1. **エンティティを戻してから比べる**。eBay は `&apos;` `&amp;` で返すので、戻さないと
   `Sv: Ex Starter Set Marnie's ...` が毎回「ずれている」ことになり、直す必要のない行を
   Revise してしまう (実際に 9/2 の新規出品9件の照合で1件が偽の不一致になった)。
2. **fail-closed**。カタログ値が空 / 取れない / US 以外 (eBaymag のミラー) / 残数0 は
   触らない。ミラーは親 (US) を直せば付いてくるので、直接 Revise してはいけない。
3. **pokemon は日本語 set_name に落ちない**。adapter (`_apply_ebay_fields`) と同じ規則。
"""
import os
import sys

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _HQ_TOOLS not in sys.path:
    sys.path.insert(0, _HQ_TOOLS)

import live_set_revise as M  # noqa: E402


def _live(set_value, site="US", qty=1, title="PSA 10 ..."):
    return {"set": set_value, "site": site, "qty": qty, "title": title, "error": None}


def _t(item_id="1", cat_set="Sv2p: Snow Hazard", category="pokemon_tcg"):
    return {"itemID": item_id, "row": 2, "cert": "123", "pid": "SV2P-075",
            "category": category, "title": "t", "cat_set": cat_set}


def test_entity_escaped_value_is_not_a_mismatch():
    """eBay の `&apos;` `&amp;` は同じ値。直す対象にしてはいけない。"""
    cat = "Sv: Ex Starter Set Marnie's Morpeko & Grimmsnarl Ex"
    live = {"1": _live("Sv: Ex Starter Set Marnie&apos;s Morpeko &amp; Grimmsnarl Ex")}
    fix, skip = M.diff_rows([_t(cat_set=cat)], live)
    assert fix == []
    assert skip["一致"] == 1


def test_real_mismatch_is_picked_up():
    """英語版の弾名が付いたままの行は直す。"""
    fix, _ = M.diff_rows([_t(cat_set="S12a: Vstar Universe")],
                         {"1": _live("Sword & Shield—Crown Zenith")})
    assert len(fix) == 1
    assert fix[0]["new_set"] == "S12a: Vstar Universe"
    assert fix[0]["live_set"] == "Sword & Shield—Crown Zenith"


def test_fail_closed_cases_are_not_revised():
    """カタログ空 / 取れない / ミラー / 残数0 は触らない。"""
    targets = [_t("a", cat_set=""), _t("b"), _t("c"), _t("d"), _t("e")]
    live = {
        "a": _live("なんでも"),                     # カタログ空 → 触らない
        "b": {"error": "Invalid item ID", "title": None},   # 取れない
        "c": _live("ちがう値", site="UK"),          # eBaymag のミラー
        "d": _live("ちがう値", qty=0),              # 残数0
        # "e" は live に無い = 取れない
    }
    fix, skip = M.diff_rows(targets, live)
    assert fix == []
    assert skip["catalog空"] == 1
    assert skip["US以外"] == 1
    assert skip["残数0"] == 1
    assert skip["取れない"] == 2


def test_catalog_set_value_pokemon_does_not_fall_back_to_japanese():
    """pokemon は specs だけ。日本語 set_name に落ちると eBay が認識できない。"""
    assert M.catalog_set_value("pokemon_tcg", {}, "拡張パック「黒炎の支配者」") == ""
    assert M.catalog_set_value("pokemon_tcg", {"set_name_ebay": "Sv3: Ruler"}, "x") == "Sv3: Ruler"


def test_catalog_set_value_other_categories_fall_back_to_set_name():
    assert M.catalog_set_value("one_piece_tcg", {}, "Promo Cards") == "Promo Cards"
    assert M.catalog_set_value("gundam_tcg", {"set_name_ebay": "A"}, "B") == "A"


def test_csv_rows_are_revise_with_itemid_and_set():
    rows = M.build_csv_rows([{"itemID": "820077373966", "new_set": "S12a: Vstar Universe"}])
    assert rows == [["Revise", "820077373966", "S12a: Vstar Universe"]]
    assert M.HEADER[1:] == ["ItemID", "C:Set"]


def test_response_is_read_as_utf8_not_latin1():
    """eBay は charset を返さない。latin-1 で読むと em-dash が化けて偽の不一致になる。"""
    raw = "<Title>PSA 10 Pokemon Sword &amp; Shield—Silver Tempest</Title>".encode("utf-8")
    assert "—" in M.decode_xml(raw)
    assert "â" not in M.decode_xml(raw)
    got = M._parse_item(M.decode_xml(raw))
    assert M.norm(got["title"]).endswith("Sword & Shield—Silver Tempest")


def test_disputed_catalog_value_is_held_back():
    """カタログに差し戻した値は出品に送らない (値の判断はカタログの持ち物)。"""
    disputed = sorted(M.DISPUTED_SET_VALUES)[0]
    fix, skip = M.diff_rows([_t(cat_set=disputed)],
                            {"1": _live("Scarlet & Violet—Obsidian Flames")})
    assert fix == []
    assert skip["カタログに差戻し中"] == 1
