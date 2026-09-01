# -*- coding: utf-8 -*-
"""生成の無駄と、シート行の重複 (2026-09-01)。

③ 2026-09-01 の走行は 18件生成して 6件が live 重複で除外された。
   枠を選ぶ前の LIVE-DUP は「まだ一度も scrape していない cert」を判定できない
   (PSA の per-cert json が無い) ため、目視にも生成にも回ってから最後に落ちていた。
   → **scrape が済んだ直後**に同じ基準で見る。落とすものは後段と同じなので出品は減らない。

④ 商品管理シートに同じ cert の行が2つある (実測 36 cert / 72行)。
   dup_guard の「同一カード多重」が 1つの出品を2件と数え、
   `[358833464164, 358833464164]` と同じ番号を2回並べていた。
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import dup_guard as dg  # noqa: E402

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _gen_src():
    return io.open(os.path.join(_ROOT, "iMakTCG", "psa_to_csv.py"), encoding="utf-8").read()


# ---- ③ scrape 直後の重複除外 ------------------------------------------------
def test_live_dup_is_checked_right_after_scrape():
    s = _gen_src()
    assert "scrape後に除外 [LIVE-DUP" in s, "scrape 直後の重複チェックが無い"
    i = s.index("scrape後に除外 [LIVE-DUP")
    j = s.index("run_pre_build_verify")
    assert i < j, "目視 (run_pre_build_verify) より前に落とすこと"


def test_the_early_drop_uses_the_same_criterion_as_the_late_one():
    """基準がズレると『後段では残るのにここで落ちる』= 出品が減る。"""
    s = _gen_src()
    blk = s[s.index("scrape が済んだ直後"):s.index("run_pre_build_verify")]
    for token in ("ensure_fresh_live_cache", "live_card_index", "group_key", "classify"):
        assert token in blk, "後段と同じ判定材料 %s を使っていない" % token


def test_key_is_written_before_dropping():
    """落とす前に KEY をシートへ (補URL に回すため。枠前の LIVE-DUP と同じ理由)。"""
    s = _gen_src()
    blk = s[s.index("scrape が済んだ直後"):s.index("run_pre_build_verify")]
    assert "_keys_for_dropped_dupes" in blk and "write_keys" in blk
    assert blk.index("write_keys") < blk.index("cert_numbers = ["), "KEY を書く前に落としている"


def test_early_drop_never_stops_the_run():
    """重複チェックが転んでも生成は続ける (出品を止めない)。"""
    s = _gen_src()
    blk = s[s.index("scrape が済んだ直後"):s.index("run_pre_build_verify")]
    assert "scrape後の重複チェック skip" in blk, "例外を握って続行していない"


# ---- ④ シート行の重複 --------------------------------------------------------
def _rows(*specs):
    """(itemID, KEY) の並び → シート2d (KEY は AI=34列目)。"""
    out = [["h"] * 40]
    for iid, key in specs:
        r = [""] * 40
        r[1] = iid
        r[34] = key
        out.append(r)
    return out


def test_same_itemid_is_counted_once():
    """シートに同じ出品の行が2つ在っても『多重』にしない。"""
    rows = _rows(("111", "pokemon_tcg:A-1"), ("111", "pokemon_tcg:A-1"))
    idx, _ = dg.live_card_index(rows, {}, {"111"})
    assert idx["pokemon_tcg:A-1"] == ["111"], "同じ itemID を2回数えている"
    assert not {k: v for k, v in idx.items() if len(v) > 1}, "1出品を多重と誤検出している"


def test_two_different_listings_are_still_detected():
    """本物の多重は今までどおり出す (見逃しを作らない)。"""
    rows = _rows(("111", "pokemon_tcg:A-1"), ("222", "pokemon_tcg:A-1"))
    idx, _ = dg.live_card_index(rows, {}, {"111", "222"})
    assert idx["pokemon_tcg:A-1"] == ["111", "222"]


def test_duplicate_sheet_rows_are_listed_with_row_numbers():
    rows = [["h"] * 10]
    for cert in ("12345678", "12345678", "99999999"):
        r = [""] * 10
        r[8] = cert
        rows.append(r)
    assert dg.duplicate_sheet_rows(rows) == {"12345678": [2, 3]}


def test_duplicate_rows_are_not_deleted_automatically():
    """消すのは人の判断 (どちらの仕入元URLを残すかが行ごとに違う)。"""
    src = io.open(os.path.join(_ROOT, "iMakHQ", "tools", "dup_guard.py"), encoding="utf-8").read()
    i = src.index("def duplicate_sheet_rows")
    body = src[i:src.index(chr(10) + "def ", i + 10)]
    for bad in ("delete_row", "delete_rows", "batch_update", "update("):
        assert bad not in body, "検出だけにすること (自動で消さない)"
    assert "⑥ 同じ cert が複数行にある" in src, "audit に出していない"
