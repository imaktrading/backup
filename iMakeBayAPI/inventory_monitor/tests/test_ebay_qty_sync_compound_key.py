"""ebay_qty_sync の (listing_id, UUID) 複合キー照合 regression (2026-07-08).

bug: eBay の variation SKU (Custom label) UUID は listing 固有でなく size ごとの共通テンプレで、
同一 UUID が数百 listing で共有される (実測: XL の UUID が 330 listing で共有)。旧 build_uuid_to_qty
は {uuid: qty} の UUID 単独キーで、dict last-wins により report 末尾 listing の qty が全 listing の
同 size 行に書かれ K 列 (eBay 現Qty) が壊れる → 在庫あるのに restore されない (◎ × K=0 を満たさず)。
発覚: 358749467113 の XL が UNIQLO 在庫あり (qty11) なのに eBay qty=0 のまま復活しなかった。

修正: (listing_id, uuid) 複合キーで listing 別に qty を保持。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ebay_qty_sync import build_uuid_to_qty, match_qty_updates  # noqa: E402

# 同一 UUID が 2 listing で共有される状況を再現 (XL 相当)
SHARED_XL = "49ffc2ec-e991-489d-9cd1-780515dacdd6"
UNIQ_M = "d124b063-c10f-4fd3-813f-69b1fe85b95e"


def _ebay_data():
    # listingA: XL=0 (実際は売切/未補充), M=1
    # listingB: XL=1 (別 listing は在庫あり) ← report 末尾
    return {
        "111111111111": [
            {"sku": SHARED_XL, "qty": "0", "variation_details": "Sizes=US L(JP XL)"},
            {"sku": UNIQ_M, "qty": "1", "variation_details": "Sizes=US S(JP M)"},
        ],
        "222222222222": [
            {"sku": SHARED_XL, "qty": "1", "variation_details": "Sizes=US L(JP XL)"},
        ],
    }


def test_shared_uuid_keeps_per_listing_qty():
    kq = build_uuid_to_qty(_ebay_data())
    # 共有 UUID でも listing 別に正しい qty (旧実装は両方 last-wins で 1 になっていた)
    assert kq[("111111111111", SHARED_XL)] == 0, "listingA の XL=0 が last-wins で上書きされている (bug 再発)"
    assert kq[("222222222222", SHARED_XL)] == 1
    assert kq[("111111111111", UNIQ_M)] == 1


def test_match_updates_uses_listing_and_uuid():
    kq = build_uuid_to_qty(_ebay_data())
    # SKU シート行: [A対処要, B対処済, C対処日, D listingID, E title, F sku, G size, H在庫, I価格, J?, K現Qty]
    def row(lid, sku, cur_k):
        r = [""] * 11
        r[1] = "FALSE"; r[3] = lid; r[5] = sku; r[10] = str(cur_k)
        return r
    sheet = [
        row("111111111111", SHARED_XL, 1),  # シートK=1 だが実際は 0 → changed=True で 0 に是正すべき
        row("222222222222", SHARED_XL, 1),  # 実際 1 → 変更なし
    ]
    ups = {(u["listing_id"], u["sku_id"]): u for u in match_qty_updates(kq, sheet)}
    a = ups[("111111111111", SHARED_XL)]
    assert a["new_qty"] == 0 and a["changed"] is True, "listingA XL が 0 に是正されない (= restore が発火しない bug)"
    b = ups[("222222222222", SHARED_XL)]
    assert b["new_qty"] == 1 and b["changed"] is False


def test_done_rows_skipped():
    # B=TRUE (対処済) 行は auto_qty_zero 保護のため skip
    kq = build_uuid_to_qty(_ebay_data())
    r = [""] * 11
    r[1] = "TRUE"; r[3] = "111111111111"; r[5] = SHARED_XL; r[10] = "0"
    assert match_qty_updates(kq, [r]) == []
