"""補URL 充填の対象順を「新規出品を最優先」にした回帰テスト (2026-07-28).

なぜ必要か: 1日あたりの充填件数が限られる運用では、行順(=古い順)だと新規出品が backlog の
最後尾に並び、**一番死にやすい出品直後の数日が補URL 0本のまま**過ぎる。
実測 (2026-07-20〜27 出品49件): 仕入元売切れ10件のうち補URL 0本の8件が完全死、
補URLがあった2件は生存 = 補URLの有無が生死を分けていた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_hoju_fill as P  # noqa: E402


def _row(iid, listed, aux=0, cert="123", cat="TCG", key="pokemon_tcg:X-001"):
    r = [""] * 41
    r[P.B] = iid
    r[P.CERT] = cert
    r[P.CATEGORY] = cat
    r[P.KEY] = key
    r[P.LISTED_AT] = listed
    r[2] = f"title {iid}"
    for k in range(aux):
        r[P.AUX0 + k] = "https://example.com/u"
    return r


HDR = [""] * 41


def test_newest_listing_comes_first():
    rows = [HDR,
            _row("old", "2026-07-01 10:00"),
            _row("new", "2026-07-27 19:30"),
            _row("mid", "2026-07-20 09:00")]
    got = [t["itemID"] for t in P.select_backfill_targets(rows)]
    assert got == ["new", "mid", "old"]


def test_slash_and_hyphen_dates_compare_consistently():
    """出品日時は 'YYYY/MM/DD' と 'YYYY-MM-DD' が実データに混在する。"""
    rows = [HDR,
            _row("hyphen", "2026-07-27 19:30"),
            _row("slash", "2026/07/28 08:00")]
    got = [t["itemID"] for t in P.select_backfill_targets(rows)]
    assert got == ["slash", "hyphen"]


def test_missing_listed_at_goes_last():
    """日時が無い行を先頭に置くと、新規優先の意味が消える。"""
    rows = [HDR,
            _row("nodate", ""),
            _row("dated", "2026-07-10 00:00")]
    got = [t["itemID"] for t in P.select_backfill_targets(rows)]
    assert got == ["dated", "nodate"]


def test_ordering_does_not_change_filtering():
    """並べ替えを入れても除外条件 (未出品/売切れ/非TCG/cert無し/補URL充足) は不変。"""
    rows = [HDR,
            _row("ok", "2026-07-27 10:00"),
            _row("", "2026-07-27 11:00"),                      # itemID 空 = 未出品
            _row("hasaux", "2026-07-27 12:00", aux=1),         # 補URL 充足
            _row("notcg", "2026-07-27 13:00", cat="Tシャツ"),   # 非TCG
            _row("nocert", "2026-07-27 14:00", cert="abc")]    # cert が数値でない
    sold = _row("sold", "2026-07-27 15:00")
    sold[P.D] = "○"
    rows.append(sold)
    got = [t["itemID"] for t in P.select_backfill_targets(rows)]
    assert got == ["ok"]
