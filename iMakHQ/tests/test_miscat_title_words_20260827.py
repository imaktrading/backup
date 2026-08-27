"""タイトルの Pack/Box は落とす・C:Set には残す (2026-08-27)。

2026-08-27 の走行 (cert158394314 サーナイトex 25th) が eBay で
`ErrorCode 240 / LP_SBM_Miscat_Trading_Cards_in_single_cat` で Failure。
VerifyAddFixedPriceItem で切り分け済み: **タイトルの `Pack` 1語だけ**が原因で、
Item Specifics の `C:Set = S8a-P: Promo Card Pack 25th Anniversary Edition` は
そのままでも通った。9件目で走行が止まり残り3件が未出品になった。

判定 (1丁目1番地): ①カタログは正しい (公式のセット名に本当に `Card Pack` がある) /
②引き方が誤り → ②を直す。カタログ依頼は出していない。

依頼書: hq/requests/2026-08-27_title_pack_word_miscat_240.md
"""
import csv
import os
import sys

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(WORKSPACE, "iMakeBayAPI"),
           os.path.join(WORKSPACE, "iMakTCG", "tools"),
           os.path.join(WORKSPACE, "iMakHQ", "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import csv_auditor as A                     # noqa: E402
import post_title_fix as P                  # noqa: E402
from listing_common import (                # noqa: E402
    SINGLES_CATEGORY,
    miscat_title_words_in,
    strip_miscat_title_words,
)

# 2026-08-27 の実物 (窓口が eBay で A=Failure / B=通る を実測した A の方)
GARDEVOIR_TITLE = ("PSA 10 Pokemon Japanese Card Pack 25th Anniversary Edition "
                   "#015/025 Gardevoir ex")
GARDEVOIR_SET = "S8a-P: Promo Card Pack 25th Anniversary Edition"


# ---------------------------------------------------------------- SSOT (語と照合)
def test_miscat_words_are_matched_on_word_boundary():
    """単語境界で照合する。'Boxer'/'Packrat' に反応しない (2026-08-09 'nr' 事故の同型防止)。"""
    assert miscat_title_words_in(GARDEVOIR_TITLE) == ["Pack"]
    assert miscat_title_words_in("PSA 10 One Piece Boxer Packrat #OP01-001 Luffy") == []


def test_miscat_words_cover_plural_and_phrase():
    """カタログの実値に 'Boxes' がある (SF: … Premium Trainer Boxes)。'Set of' も句で拾う。"""
    assert miscat_title_words_in("Premium Trainer Boxes") == ["Boxes"]
    assert miscat_title_words_in("Set of 3 Promo") == ["Set of"]
    assert miscat_title_words_in("Limited Box Beta Ver.") == ["Box"]
    assert miscat_title_words_in("Energy Marker Pack 01") == ["Pack"]


def test_strip_keeps_the_rest_of_the_set_name():
    """語だけ落として残りは活かす (セット名ごと消さない)。"""
    new, changed = strip_miscat_title_words(GARDEVOIR_TITLE)
    assert changed is True
    assert "Pack" not in new
    assert new == ("PSA 10 Pokemon Japanese Card 25th Anniversary Edition "
                   "#015/025 Gardevoir ex")


# --------------------------------------------- カード名の中の Bundle は落とさない
# `Iron Bundle` (Pokemon SV4M #071/066) は 2026-08-25 に出品済で **240 は出ていない**。
# ここを落とすと `Iron Art Rare` = 別のカード名で出る (2026-08-24 Tony Tony Chopper と同型)。
IRON_BUNDLE_TITLE = ("PSA 10 Pokemon Japanese Sv4m: Future Flash #071/066 "
                     "Iron Bundle Art Rare 2023")


def test_card_name_span_is_never_stripped():
    assert miscat_title_words_in(IRON_BUNDLE_TITLE, card_name="Iron Bundle") == []
    assert strip_miscat_title_words(IRON_BUNDLE_TITLE, card_name="Iron Bundle") == (
        IRON_BUNDLE_TITLE, False)


def test_set_name_word_still_stripped_when_card_name_is_elsewhere():
    """カード名を守っても、セット名側の語はちゃんと落ちる (守りすぎない)。"""
    t = "PSA 10 One Piece Japanese 8 Packs Battle-Winner #OP04-083 Sabo Super Rare Promo"
    assert miscat_title_words_in(t, card_name="Sabo") == ["Packs"]
    new, changed = strip_miscat_title_words(t, card_name="Sabo")
    assert changed is True and "Packs" not in new and "Sabo" in new


def test_fix_title_protects_card_name():
    new, log = P.fix_title(IRON_BUNDLE_TITLE, "Japanese", "", [],
                           card_name="Iron Bundle", category=SINGLES_CATEGORY, year="2023")
    assert new == IRON_BUNDLE_TITLE
    assert log["miscat_strip"] == []


def test_auditor_does_not_flag_card_name_bundle():
    """実在カード名を『禁止ワード』で除外しない (2026-08-09 'nr'×Shenron の同型防止)。"""
    findings = A.native_findings(
        ["*Title", "*Category", "C:Card Name"],
        [IRON_BUNDLE_TITLE, SINGLES_CATEGORY, "Iron Bundle"])
    assert findings == []


def test_strip_is_noop_for_clean_title():
    t = "PSA 10 Pokemon Sv9: Battle Partners #105/100 Lillie's Ribombee Art Rare"
    assert strip_miscat_title_words(t) == (t, False)


# ---------------------------------------------------------------- 生成側 (post_title_fix)
def test_fix_title_strips_pack_in_singles_category():
    new, log = P.fix_title(GARDEVOIR_TITLE, "Japanese", "", [],
                           category=SINGLES_CATEGORY, year="2021")
    assert "Pack" not in new
    assert log["miscat_strip"]          # 何を落としたか記録が残る
    assert log["banned_strip"] is True  # 既存の banned の口に合流 (分岐を増やさない)


def test_fix_title_leaves_other_categories_alone():
    """シングル (183454) 以外は触らない。Pack/Box が正当な出品を壊さない。"""
    new, log = P.fix_title(GARDEVOIR_TITLE, "Japanese", "", [], category="183050")
    assert new == GARDEVOIR_TITLE
    assert log["miscat_strip"] == []


def test_short_title_is_padded_with_year_after_strip():
    """落として短くなったら年号で補う (年号は C:Year Manufactured = カタログの値)。"""
    new, log = P.fix_title("PSA 10 Pokemon Japanese Golden Box #001 Pikachu",
                           "Japanese", "", [], category=SINGLES_CATEGORY, year="2021")
    assert "Box" not in new
    assert "2021" in new and "2021" in log["pad"]


def test_year_is_not_padded_when_nothing_was_stripped():
    """miscat と無関係な短タイトルに年号を足し始めない (影響範囲を広げない)。"""
    new, log = P.fix_title("PSA 10 Pokemon Japanese #001 Pikachu",
                           "Japanese", "", [], category=SINGLES_CATEGORY, year="2021")
    assert "2021" not in new


def test_process_csv_keeps_pack_in_c_set(tmp_path):
    """★CSV を通した時、タイトルからは消えて **C:Set には残る** (実測で C:Set は通る)。"""
    header = ["*Category", "*Title", "C:Rarity", "C:Language", "C:Card Name",
              "C:Set", "C:Year Manufactured"]
    row = [SINGLES_CATEGORY, GARDEVOIR_TITLE, "Promo", "Japanese", "Gardevoir ex",
           GARDEVOIR_SET, "2021"]
    p = tmp_path / "tcg_upload_test.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        csv.writer(f, quoting=csv.QUOTE_NONNUMERIC).writerows([header, row])

    stats = P.process_csv(str(p), rescues=[], log_func=lambda m: None)
    assert stats["banned_stripped"] == 1

    out = list(csv.reader(open(p, encoding="utf-8")))[1]
    got = dict(zip(header, out))
    assert "Pack" not in got["*Title"]
    assert got["C:Set"] == GARDEVOIR_SET      # ← 契約どおりカタログ値を写したまま


# ---------------------------------------------------------------- 入稿前の監査 (csv_auditor)
def test_auditor_flags_miscat_word_before_upload():
    """eBay に投げる前に止める。行は除外 + プログラム修正依頼に載る。"""
    findings = A.native_findings(["*Title", "*Category"],
                                 [GARDEVOIR_TITLE, SINGLES_CATEGORY])
    assert len(findings) == 1
    sev, msg = findings[0]
    assert sev == "ERROR" and "Pack" in msg
    assert A.classify_finding(sev, msg) == A.REPORT_PROGRAM
    assert A.should_exclude([A.classify_finding(sev, msg)]) is True


def test_auditor_ignores_non_singles_category():
    assert A.native_findings(["*Title", "*Category"], [GARDEVOIR_TITLE, "183050"]) == []
