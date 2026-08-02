"""Regression: 2026-06-21 — タイトルの重複語除去(Japanese Japanese / Japan…Japan).

set名+言語/condition マーカーの重複で 'Japanese Japanese Promo' / 'Japan Brand New Japan' が発生。
重複語の2回目以降を削除。ただしカード用語(VMAX/EX/V…)は set名+カード名で正当に再出現するため残す。
"""
import importlib.util
from pathlib import Path
import sys

_P = Path(__file__).resolve().parent.parent / "iMakTCG" / "tools" / "post_title_fix.py"
sys.path.insert(0, str(_P.parent))
_spec = importlib.util.spec_from_file_location("post_title_fix_t", _P)
ptf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ptf)


def test_dedup_consecutive_japanese():
    out, ch = ptf.remove_duplicate_words("PSA 10 Pokemon Japanese Japanese Promo #020/M-P Pikachu 2025")
    assert ch and out == "PSA 10 Pokemon Japanese Promo #020/M-P Pikachu 2025"


def test_dedup_nonconsecutive_japan():
    out, ch = ptf.remove_duplicate_words("UNIQLO UT KAWS T-Shirt Black L (JP XL) NWT Japan Brand New Japan")
    assert ch and out.count("Japan") == 1 and "Brand New" in out


def test_whitelist_vmax_kept():
    # set 'VMAX Climax' + card 'Orbeetle VMAX' = VMAX 2回だが両方意味あり → 残す
    t = "PSA 10 Pokemon Japanese VMAX Climax #215/184 Orbeetle VMAX Character Super Rare"
    out, ch = ptf.remove_duplicate_words(t)
    assert not ch and out == t


def test_whitelist_vstar_ex_kept():
    t = "PSA 10 Pokemon VSTAR Universe #210/172 Leafeon VSTAR Card"
    assert ptf.remove_duplicate_words(t)[0] == t   # VSTAR 2回 維持


def test_numbers_symbols_never_dropped():
    # 番号/記号は語でない → 重複扱いしない
    t = "PSA 10 Pokemon Set 100 #100/100 Card"
    out, _ = ptf.remove_duplicate_words(t)
    assert "#100/100" in out and "100" in out


# ---- listing_common.dedup_title_words (Tシャツ/mercari 系) ----
def _load_lc():
    p = Path(__file__).resolve().parent.parent / "iMakeBayAPI" / "listing_common.py"
    sys.path.insert(0, str(p.parent))
    spec = importlib.util.spec_from_file_location("listing_common_t", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_lc_dedup_japan():
    lc = _load_lc()
    out = lc.dedup_title_words("UNIQLO UT KAWS Tokyo First T-Shirt Black L (JP XL) NWT Japan Brand New Japan")
    assert out.count("Japan") == 1 and "Brand New" in out


def test_lc_dedup_keeps_whitelist():
    lc = _load_lc()
    t = "PSA 10 Pokemon VMAX Climax #215/184 Orbeetle VMAX Character Super Rare"
    assert lc.dedup_title_words(t) == t   # VMAX 2回 維持


# ---- 連続した繰り返しは作品名 (2026-08-03) ----
# 実害: 一番くじ 幽☆遊☆白書 の 'Yu Yu Hakusho' → 'Yu Hakusho' が2件。検索キーワード
# そのものが消えるので露出が落ちる。文字数制限による切り詰めではない(75字/72字で余裕あり)。
# この関数が本来直したいのは 'Japanese … Japanese' のような **離れた** 再出現。

def test_adjacent_repeat_is_kept_series_name():
    lc = _load_lc()
    t = "Ichiban Kuji Yu Yu Hakusho C Prize Hiei Masterlise Figure New"
    assert lc.dedup_title_words(t) == t, "作品名の連続した繰り返しを消している"


def test_adjacent_repeat_kept_but_distant_repeat_still_removed():
    lc = _load_lc()
    # 同じ語が「隣接」と「離れて」両方出る場合: 隣接は残し、離れた再出現だけ落とす
    got = lc.dedup_title_words("Yu Yu Hakusho Figure Yu Special")
    assert got == "Yu Yu Hakusho Figure Special"


def test_distant_repeat_removal_unchanged():
    lc = _load_lc()
    # 回帰: 本来の用途は従来どおり
    assert lc.dedup_title_words("PSA 10 Japanese Card Japanese Set") == "PSA 10 Japanese Card Set"
    assert (lc.dedup_title_words("PSA 10 One Piece Booster One Piece The Best")
            == "PSA 10 One Piece Booster The Best")
