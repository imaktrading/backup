# -*- coding: utf-8 -*-
"""dup_guard — 出品重複ガードの回帰テスト (2026-07-26)。

背景(実測):
- ガンダム RP-028 が cert 154708661 / 154708662 で 7/06・7/07 に2枠 live になった。
  真因 = 商品管理シート KEY(AI列)が空 → 重複くんが「判定不能」で素通り(fail-OPEN)。
- ただし実害の本体は同一カードではなく **同じ仕入元URLを2出品が指す** こと
  (両方売れる→片方履行不能→キャンセル→Defect)。実測では6組とも仕入元は別で健全だった。
→ よって ①URL共有=致命 として必ず検出 ②同一カード=注意(出品は止めない) を固定する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import dup_guard as dg  # noqa: E402

# 商品管理シート相当の 2次元配列 (A=0 主URL / B=1 itemID / C=2 title / D=3 売切 / I=8 cert /
#                                  AC=28.. 補URL / AI=34 KEY)
NCOL = 40


def _row(url="", iid="", title="", sold="", cert="", key="", aux=(), an="", m=""):
    r = [""] * NCOL
    r[dg.A], r[dg.B], r[dg.C], r[dg.D] = url, iid, title, sold
    r[dg.CERT], r[dg.KEY] = cert, key
    r[dg.COST_OVERRIDE], r[dg.COST_NOW] = an, m
    for k, u in enumerate(aux):
        r[dg.AUX0 + k] = u
    return r


HEADER = [f"c{i}" for i in range(NCOL)]


# ---------------------------------------------------------------- token 抽出
def test_card_token_from_title():
    assert dg.card_token_from_title("PSA 10 Gundam Japanese #RP-028 Resource 2026 Card") == "RP-028"
    # DON!! は catalog id が DON-PRB02-018。'#' 直後を丸ごと取る(PRB02-018=別カードとの衝突回避)
    assert dg.card_token_from_title(
        "PSA 10 One Piece Japanese Premium Booster Vol.2 #DON-PRB02-018 DON!! Card 2025"
    ) == "DON-PRB02-018"
    assert dg.card_token_from_title("PSA 10 Pokemon Japanese Crimson Haze #073/066 Heliolisk") == "073/066"
    assert dg.card_token_from_title("PSA 10 no number here") is None
    assert dg.card_token_from_title("") is None


# --------------- KEY のカテゴリ対応 (2026-07-27 Catalog 合意・案B の読む側)
def test_parse_key_new_and_legacy():
    assert dg.parse_key("gundam_tcg:ST02-010") == ("gundam_tcg", "ST02-010")
    assert dg.parse_key("ST02-010") == (None, "ST02-010")          # 旧形式
    assert dg.parse_key("OP09-062_p") == (None, "OP09-062_p")      # variant suffix はそのまま
    assert dg.parse_key("item:12345") == (None, "item:12345")      # url-key はカテゴリ扱いしない
    assert dg.parse_key("") == (None, "")


def test_different_games_same_number_are_separated():
    """★本命: One Piece と Gundam の ST02-010 を別商品として扱う(283件の重複対策)。"""
    rows = [HEADER,
            _row(iid="111", key="gundam_tcg:ST02-010"),
            _row(iid="222", key="one_piece_tcg:ST02-010")]
    index, _ = dg.live_card_index(rows, {})
    assert index == {"gundam_tcg:ST02-010": ["111"], "one_piece_tcg:ST02-010": ["222"]}


def test_same_game_same_number_still_groups():
    rows = [HEADER,
            _row(iid="111", key="gundam_tcg:ST02-010"),
            _row(iid="222", key="gundam_tcg:ST02-010")]
    index, _ = dg.live_card_index(rows, {})
    assert index["gundam_tcg:ST02-010"] == ["111", "222"]


def test_legacy_and_new_key_do_not_merge_during_migration():
    """移行期: 旧(カテゴリ無)と新は同一視しない = 誤って重複判定して出品を落とさない。"""
    rows = [HEADER,
            _row(iid="111", key="ST02-010"),
            _row(iid="222", key="gundam_tcg:ST02-010")]
    index, _ = dg.live_card_index(rows, {})
    assert sorted(index) == ["ST02-010", "gundam_tcg:ST02-010"]


def test_norm_url():
    assert dg.norm_url("https://jp.mercari.com/item/m123?utm=1") == "https://jp.mercari.com/item/m123"
    assert dg.norm_url("https://jp.mercari.com/item/m123/") == "https://jp.mercari.com/item/m123"
    assert dg.norm_url("") == ""


# ------------------------------------------------- ① URL共有 = 致命(必ず検出)
def test_shared_supply_url_is_detected():
    """2出品が同じ仕入元URLを指す = 両方売れたら履行不能 → 必ず拾う。"""
    rows = [HEADER,
            _row(url="https://jp.mercari.com/item/m1", iid="111"),
            _row(url="https://jp.mercari.com/item/m1?ref=x", iid="222")]
    shared = dg.shared_supply_urls(rows)
    assert list(shared) == ["https://jp.mercari.com/item/m1"]
    assert shared["https://jp.mercari.com/item/m1"] == ["111", "222"]


def test_shared_supply_detects_aux_url_overlap():
    """主URL と 他出品の補URL が同じでも拾う(補URL充填が作りうる事故)。"""
    rows = [HEADER,
            _row(url="https://jp.mercari.com/item/m1", iid="111"),
            _row(url="https://jp.mercari.com/item/m9", iid="222",
                 aux=("https://jp.mercari.com/item/m1",))]
    assert dg.shared_supply_urls(rows)["https://jp.mercari.com/item/m1"] == ["111", "222"]


def test_shared_supply_ignores_sold_and_unlisted():
    """取下げ済(D=○)や未出品(itemID空)は在庫を食い合わない → 誤警告しない。"""
    rows = [HEADER,
            _row(url="https://jp.mercari.com/item/m1", iid="111"),
            _row(url="https://jp.mercari.com/item/m1", iid="222", sold="○"),
            _row(url="https://jp.mercari.com/item/m1", iid="")]
    assert dg.shared_supply_urls(rows) == {}


def test_no_shared_supply_when_sources_differ():
    """同一カードでも仕入元が別なら健全 = 警告ゼロ(実測6組がこの形)。"""
    rows = [HEADER,
            _row(url="https://jp.mercari.com/item/m1", iid="111", key="RP-028"),
            _row(url="https://jp.mercari.com/item/m2", iid="222", key="RP-028")]
    assert dg.shared_supply_urls(rows) == {}


# ------------------------------------------- ② 同一カード = 注意(KEY空も拾う)
def test_live_card_index_uses_title_token_when_key_empty():
    """★本命: KEY空でも eBayタイトルの #ID で同一カードを検出する(ガンダム事故の再発防止)。"""
    rows = [HEADER,
            _row(url="u1", iid="358761687922", cert="154708662"),
            _row(url="u2", iid="358766462261", cert="154708661")]
    titles = {"358761687922": "PSA 10 Gundam Japanese #RP-028 Resource 2026 Card",
              "358766462261": "PSA 10 Gundam Japanese #RP-028 Resource 2026 Card"}
    index, unkeyed = dg.live_card_index(rows, titles)
    assert index["t:RP-028"] == ["358761687922", "358766462261"]
    assert unkeyed == []


def test_live_card_index_prefers_key_and_reports_unkeyed():
    rows = [HEADER,
            _row(iid="111", key="RP-028", title="日本語タイトル"),
            _row(iid="222"),                       # KEY無 + title無 = 判定不能
            _row(iid="333", key="item:12345")]     # url-key は catalog-backed でない
    index, unkeyed = dg.live_card_index(rows, {})
    assert index == {"RP-028": ["111"]}
    assert sorted(unkeyed) == ["222", "333"]


def test_dup_candidates_flags_existing_live_card():
    header = [dg.CSV_LABEL, dg.CSV_TITLE, dg.CSV_CERT]
    rows = [["m35515110073", "PSA 10 Gundam Japanese #RP-028 Resource 2026 Card", "154708661"]]
    index = {"t:RP-028": ["358761687922"]}
    out = dg.dup_candidates(rows, header, index)
    assert len(out) == 1 and out[0]["existing"] == ["358761687922"]
    assert out[0]["card_key"] == "t:RP-028"


def test_dup_candidates_uses_sheet_key_over_title():
    header = [dg.CSV_LABEL, dg.CSV_TITLE, dg.CSV_CERT]
    rows = [["x", "PSA 10 ... #073/066 Delibird", "999"]]
    # タイトル番号は set 違いで衝突しうる → シート KEY があればそちらが正
    out = dg.dup_candidates(rows, header, {"SV8a-073": ["111"]}, cert_to_key={"999": "SV8a-073"})
    assert out[0]["card_key"] == "SV8a-073" and out[0]["existing"] == ["111"]


def test_dup_candidates_empty_when_no_live_match():
    header = [dg.CSV_LABEL, dg.CSV_TITLE, dg.CSV_CERT]
    rows = [["x", "PSA 10 Gundam Japanese #RP-099 Resource", "1"]]
    assert dg.dup_candidates(rows, header, {"t:RP-028": ["111"]}) == []


# ------------------------------- ③ 補URL書込ガード(他出品のURLを奪わない)
def test_filter_urls_owned_by_others():
    owner = {"https://jp.mercari.com/item/m1": ["111"],
             "https://jp.mercari.com/item/m2": ["222"]}
    keep, dropped = dg.filter_urls_owned_by_others(
        ["https://jp.mercari.com/item/m1", "https://jp.mercari.com/item/m3"], owner, "222")
    assert keep == ["https://jp.mercari.com/item/m3"]
    assert dropped == [("https://jp.mercari.com/item/m1", ["111"])]


# ------------- ④ RESTOCK復活で2枠になる予備軍(取下げ中との衝突・Dedupe回答の推奨形)
def test_restock_collision_flags_live_vs_suspended():
    """★EB03-053型: live に1枚、取下げ中に同じカード → 復活すると2枠。疑いとして出す。"""
    rows = [HEADER,
            _row(iid="358600821593", key="EB03-053"),                 # live
            _row(iid="358810782374", key="EB03-053", sold="○")]       # 取下げ中
    out = dg.restock_collision(rows)
    assert len(out) == 1
    assert out[0]["live"] == ["358600821593"] and out[0]["suspended"] == ["358810782374"]


def test_restock_collision_ignores_when_no_suspended_twin():
    rows = [HEADER,
            _row(iid="111", key="EB03-053"),
            _row(iid="222", key="P-110", sold="○")]
    assert dg.restock_collision(rows) == []


def test_restock_collision_uses_title_token_when_key_empty():
    """KEY空でも eBayタイトルの #ID で拾う(母集団の穴を塞ぐのが目的なので)。"""
    rows = [HEADER, _row(iid="111"), _row(iid="222", sold="○")]
    titles = {"111": "PSA 10 Gundam Japanese #RP-028 Resource",
              "222": "PSA 10 Gundam Japanese #RP-028 Resource"}
    out = dg.restock_collision(rows, titles)
    assert out and out[0]["card_key"] == "t:RP-028"


# ------------- ⑤ 廃止した AN列に値が入っていないかの tripwire (2026-07-27 廃止)
def test_any_value_in_abolished_an_column_is_reported():
    """★AN列は廃止済(N は参照しない)。値があること自体が異常なので全件出す。"""
    rows = [HEADER, _row(iid="358357723957", an="29999", m="48000", title="Boa Hancock P-066")]
    out = dg.frozen_cost_rows(rows)
    assert len(out) == 1 and out[0]["an"] == 29999 and out[0]["m"] == 48000


def test_small_gap_is_still_reported_after_abolition():
    """乖離が小さくても「AN に値がある」時点で異常(旧: 3000円未満は無視していた)。"""
    rows = [HEADER, _row(iid="222", an="15180", m="14430")]
    assert len(dg.frozen_cost_rows(rows)) == 1


def test_no_override_is_clean():
    rows = [HEADER, _row(iid="111", m="48000")]
    assert dg.frozen_cost_rows(rows) == []


def test_yen_parser_handles_fullwidth_sign():
    """★実データは '￥7,500'(全角) が混在する。半角¥しか剥がさないと 0 と誤読する。"""
    rows = [HEADER, _row(iid="333", an="￥29,999", m="￥48,000")]
    out = dg.frozen_cost_rows(rows)
    assert out[0]["an"] == 29999 and out[0]["m"] == 48000


def test_frozen_cost_ignores_sold_rows():
    """取下げ済(D=○)は価格追随の対象外なので警告しない。"""
    rows = [HEADER, _row(iid="333", an="29999", m="48000", sold="○")]
    assert dg.frozen_cost_rows(rows) == []


def test_filter_urls_keeps_self_owned_url_idempotent():
    """自分が既に持っている URL は落とさない(冪等書込を壊さない)。"""
    owner = {"https://jp.mercari.com/item/m1": ["222"]}
    keep, dropped = dg.filter_urls_owned_by_others(["https://jp.mercari.com/item/m1"], owner, "222")
    assert keep == ["https://jp.mercari.com/item/m1"] and dropped == []
