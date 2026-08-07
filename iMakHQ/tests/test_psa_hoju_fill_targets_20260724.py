"""PSA 補URL 能動充填 Phase1 slice1: 対象抽出の純関数テスト (2026-07-24)。

設計: discussion/2026-07-24_psa_hoju_url_replenishment_design.md。
select_backfill_targets が「出品中(B有) / live(D空) / PSA(R='TCG'かつcert数値) / 補<閾値」だけを
拾い、他カテゴリ(montbell 等)・未出品・売切・満杯を除外することを固定。
純関数のみ (DB/network 非依存)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from psa_hoju_fill import select_backfill_targets, AUX0

# HIGH schema: A0 url, B1 itemID, C2 title, D3 sold, I8 cert, R17 category, AC28.. 補URL, AI34 KEY
_H = ["URL", "itemID", "タイトル", "売り切れ"] + [""] * 4 + ["Title"] + [""] * 8 + ["カテゴリ"] + [""] * 40


def _row(itemid="", cert="", cat="TCG", sold="", key="K1", title="t", backups=0):
    r = [""] * 41
    r[1] = itemid
    r[3] = sold
    r[8] = cert
    r[17] = cat
    r[34] = key
    r[2] = title
    for k in range(backups):
        r[AUX0 + k] = f"https://sup/{k}"
    return r


def test_live_psa_zero_backup_included():
    rows = [_H, _row(itemid="358x", cert="12345", backups=0)]
    tg = select_backfill_targets(rows, max_backups=1)
    assert len(tg) == 1 and tg[0]["itemID"] == "358x" and tg[0]["n_backups"] == 0


def test_unlisted_excluded():
    # B(itemID) 空 = 未出品 → 補は live 出品の延命策なので対象外
    rows = [_H, _row(itemid="", cert="12345")]
    assert select_backfill_targets(rows, max_backups=1) == []


def test_sold_excluded():
    rows = [_H, _row(itemid="358x", cert="12345", sold="○")]
    assert select_backfill_targets(rows, max_backups=1) == []


def test_non_tcg_category_excluded():
    # montbell 等: cert 欄が数値でも R!='TCG' なら除外
    rows = [_H, _row(itemid="358x", cert="1103219", cat="Tシャツ")]
    assert select_backfill_targets(rows, max_backups=1) == []


def test_non_numeric_cert_excluded():
    rows = [_H, _row(itemid="358x", cert="", cat="TCG", key="K1")]
    assert select_backfill_targets(rows, max_backups=1) == []


def test_threshold_backups():
    # 補1本: max_backups=1 では除外(>=閾値), =2 では対象(top-up)
    rows = [_H, _row(itemid="358x", cert="12345", backups=1)]
    assert select_backfill_targets(rows, max_backups=1) == []
    assert len(select_backfill_targets(rows, max_backups=2)) == 1


def test_full_backups_excluded_even_at_max5():
    rows = [_H, _row(itemid="358x", cert="12345", backups=5)]
    assert select_backfill_targets(rows, max_backups=5) == []


def test_empty_slots_reported():
    rows = [_H, _row(itemid="358x", cert="12345", backups=2)]
    tg = select_backfill_targets(rows, max_backups=5)
    assert tg[0]["n_backups"] == 2 and tg[0]["empty_slots"] == 3
