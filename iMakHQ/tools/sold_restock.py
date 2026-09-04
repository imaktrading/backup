#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""売れた → 補充 (2026-08-28 新設)。**作り直さない**。既存の出品を戻すだけ。

ユーザー確定 (2026-08-28):
    「単純に在庫1にして、仕入れ値で価格とポリシーを変えるだけ」

    そのとおりで、中身 (タイトル / Item Specifics / 画像) は元の出品のままでよい。
    新規生成の経路 (タイトル生成・目視・カタログ照合・Claude API) を通す必要がない。
    実害 (2026-08-28): 窓口が Giratina を作り直したところ **値段が $100 で出た**
    (正しくは $120.98)。作り直しは遠回りな上に事故る。

やること:
    Completed (売れて終了) → RelistFixedPriceItem (中身そのまま・新ID)
    Active かつ qty=0      → ReviseFixedPriceItem (同ID)
    どちらも **qty=1 + 新しい仕入値から出した価格 + 送料ポリシー** を一緒に送る。

    eBay 呼出の本体は `ichibankuji_restock.ebay_restock` に既に在る (一番くじで実績)。
    こちらは **価格と送料ポリシーを一緒に送る** 版 (向こうは Quantity だけ)。

対象カテゴリ: PSA / G-Shock / 一番くじ (= 同じ物をもう一度仕入れられるもの)。
    アパレルは入れない (公式在庫が戻れば監視くんが復活させる。2026-08-28 ユーザー確定)。

使い方:
    python sold_restock.py                      # 何をやるかだけ出す (既定 = 送らない)
    python sold_restock.py --write              # 実行
    python sold_restock.py --cost 101051553=8000   # 仕入値を手で渡す (cert or SKU)
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

import sheet_io as S            # noqa: E402
import sold_restock_worklist as W  # noqa: E402


# ---------------------------------------------------------------- 純関数
def plan_action(status, qty):
    """eBay の状態 → やること (純関数, test 可)。

    判らない状態は **触らない** (fail-closed)。取り違えて出すより出さない方が安い。
    """
    if status == "Completed":
        return "relist"
    if status == "Active":
        return "noop" if (qty or 0) > 0 else "revise"
    return "skip"


def price_for(cost_jpy, category="TCG(PSA10)"):
    """仕入値 → (価格USD, 送料ポリシー名) (I/O 無し)。cost 不明なら (None, None)。

    ★価格も送料も **同じ1回の計算から出す**。片方だけ更新すると採算が狂う。
    """
    if not cost_jpy:
        return None, None
    from pricing_engine import compute_listing_price
    r = compute_listing_price(float(cost_jpy), None, category)
    return r.get("price"), r.get("shipping_profile_name")


def build_item_xml(item_id, price, profile, qty=1):
    """Relist/Revise に載せる <Item> (純関数, test 可)。

    価格/ポリシーが取れなかった時は **その要素を送らない** (元の値が残る)。
    0 や空で上書きすると赤字出品になるため。
    """
    parts = [f"<ItemID>{item_id}</ItemID>", f"<Quantity>{int(qty)}</Quantity>"]
    if price:
        parts.append(f"<StartPrice>{float(price):.2f}</StartPrice>")
    if profile:
        parts.append("<SellerProfiles><SellerShippingProfile>"
                     f"<ShippingProfileName>{profile}</ShippingProfileName>"
                     "</SellerShippingProfile></SellerProfiles>")
    return "<Item>" + "".join(parts) + "</Item>"


CATEGORY_FOR_PRICING = {
    "PSA": "TCG(PSA10)",
    "G-Shock": "G-shock",
    "一番くじ": "Ichibankuji",
}


def parse_cost_args(argv):
    """--cost KEY=VALUE を dict に (純関数, test 可)。"""
    out = {}
    for i, a in enumerate(argv):
        if a == "--cost" and i + 1 < len(argv) and "=" in argv[i + 1]:
            k, v = argv[i + 1].split("=", 1)
            try:
                out[k.strip()] = float(v)
            except ValueError:
                pass
    return out


def ebay_status(fx, U, item_id, tok):
    """GetItem → (ListingStatus, Quantity)。取れなければ ('?', -1) = 触らない。"""
    try:
        r = fx.post("GetItem", f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel>",
                    tok, U.SITE_US)
    except Exception:                                              # noqa: BLE001
        return "?", -1
    st = re.search(r"<ListingStatus>(.*?)</ListingStatus>", r or "")
    q = re.search(r"<QuantityAvailable>(\d+)</QuantityAvailable>", r or "") or         re.search(r"<Quantity>(\d+)</Quantity>", r or "")
    return (st.group(1) if st else "?"), (int(q.group(1)) if q else -1)


# ---------------------------------------------------------------- I/O
def fresh_cost_map(rows2d):
    """「PSA再仕入れ」タブ → {card番号: 最安¥} (純関数, test 可)。

    ★台帳(商品管理シート)の仕入値は **売れた時の値** で、今 買える値ではない。
      実測 (2026-08-28): Giratina は台帳¥15,380 に対し実勢¥8,000、Eevee は
      ¥26,500 に対し ¥8,400。古い方で戻すと **売れない値段** で並ぶ。
      🃏 PSA再仕入れ照合 が出した「最安¥」を正とする。
    """
    if not rows2d:
        return {}
    hdr = rows2d[0]

    def _i(name):
        for i, h in enumerate(hdr):
            if name in (h or ""):
                return i
        return None

    ci, pi = _i("set_no"), _i("最安")
    if ci is None or pi is None:
        return {}
    out = {}
    for r in rows2d[1:]:
        k = (r[ci] or "").strip() if len(r) > ci else ""
        v = re.sub(r"[^0-9]", "", (r[pi] or "")) if len(r) > pi else ""
        if k and v:
            out[k] = float(v)
    return out


def card_no_of(order):
    """「PSA再仕入れ」タブと突き合わせる card番号 (純関数, test 可)。

    タブの set_no は `016/054` `196/SV-P` の形。出品タイトルの `#016/054` から取る。
    """
    m = re.search(r"#([A-Za-z0-9-]+/[A-Za-z0-9-]+)", (order.get("Item Title") or "") if order else "")
    return m.group(1) if m else ""


def live_keys(sheets, live_ids, key_col=S.PRODUCT_COL_KEY,
              item_col=S.PRODUCT_COL_ITEMID):
    """**同じカードが既に live** な KEY の集合 (純関数, test 可)。

    ★2026-08-30: 補充は「その行の B列が空か」だけで未補充と判断していたため、
      **別の行に同じカードの生きた出品があっても もう1本出してしまった**。
      実害: Giratina (pokemon_tcg:SM10a-016) が 820057636763 と 820045155453 の2本 live。

      出品くん本体は同じカードの二重出品を3段で止めている
      (抽出時の「同KEYが出品済の2枚目を除外」/ 重複くん excluder / dup_guard)。
      補充は eBay を直接叩くのでそのどれも通らない。**ここで同じ判定をする**。
    """
    out = set()
    for _label, rows in sheets:
        for r in rows[1:]:
            b = (r[item_col] or "").strip() if len(r) > item_col else ""
            k = (r[key_col] or "").strip() if len(r) > key_col else ""
            if b and k and b in live_ids:
                out.add(k)
    return out


def _cost_from_row(row):
    """台帳の行 → 仕入値¥ (既存の pick_cost をそのまま借りる)。"""
    try:
        from listing_common import pick_cost_jpy
        return pick_cost_jpy(row)
    except Exception:                                              # noqa: BLE001
        for col in (S.PRODUCT_COL_COST, S.PRODUCT_COL_COST_M):
            v = (row[col] or "").strip() if len(row) > col else ""
            n = re.sub(r"[^\d.]", "", v)
            if n:
                return float(n)
    return None


def count_workload():
    """押したら何件・何が起きるか (2026-08-31・ラベル/ヒント用)。

    ★eBay の per-item 状態確認 (ebay_status) はしない。live キャッシュ
      (itemid_writeback_audit、2時間以内なら再取得しない) があればそれで判定し、
      無ければ「要確認」として **actionable には数えない** (cull_end / shelf_evict と
      同じ理由: 表示のために API 枠を使わない。2026-08-24 に表示目的の取得で
      取下げが5時間止まった実害がある)。

    戻り: {report: 注文レポートが在るか, actionable: 今すぐ送れる件数
           (live キャッシュで Active&qty=0 と確認できた分), unknown: キャッシュに無く
           判定できない件数 (Completed=要 relist の可能性。押せば分かる), done: 既に補充済,
           error: 読めなかった理由}"""
    out = {"report": False, "actionable": 0, "unknown": 0, "done": 0,
           "blocked": 0, "error": ""}
    try:
        src = W._find_desk_report()
        if not src:
            out["error"] = "注文レポートがありません (デスクトップの ebay-all-orders-report-*.csv)"
            return out
        out["report"] = True
        pairs = [(o, W.category_of(o.get("Item Title") or "")) for o in W.read_orders(src)]
        want = [(o, c) for o, c in pairs if c]
        if not want:
            return out
        sheets = W._sheets()
        cache_raw = {}
        try:
            import json as _json
            import itemid_writeback_audit as _A
            if _A.CACHE.exists():
                cache_raw = _json.loads(_A.CACHE.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            cache_raw = {}
        already = live_keys(sheets, set(cache_raw.keys())) if cache_raw else set()
        for o, cat in want:
            sku = (o.get("Custom Label") or "").strip()
            iid = (o.get("Item Number") or "").strip()
            label, n, row = W.find_row(sheets, sku, iid)
            if row is None:
                continue
            state, _aux = W.classify(row)
            if state == "補充済":
                out["done"] += 1
                continue
            _key = (row[S.PRODUCT_COL_KEY] or "").strip() if len(row) > S.PRODUCT_COL_KEY else ""
            if _key and _key in already:
                continue
            # ★2026-09-04: 仕入値が取れない行は **押しても止まる** (本体が
            #   「仕入値が取れないので止めます」で skip)。青にすると押しても減らない。
            #   本体と同じ _cost_from_row を通す (二重実装しない)。cost_override や
            #   当日の調査結果で埋まる可能性は残るので、0 にせず blocked として出す。
            _has_cost = bool(_cost_from_row(row))
            info = cache_raw.get(iid)
            if info is None:
                out["unknown"] += 1
            elif int(info.get("avail") or 0) == 0:
                if _has_cost:
                    out["actionable"] += 1
                else:
                    out["blocked"] = out.get("blocked", 0) + 1
            # avail > 0 = 既に在庫あり (noop)。候補にも数えない。
    except Exception as e:                                          # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:60]
    return out


def main():
    argv = sys.argv[1:]
    write = "--write" in argv
    allow_stale = "--allow-stale-cost" in argv
    cost_override = parse_cost_args(argv)
    paths = [a for a in argv if not a.startswith("--") and "=" not in a]
    src = paths[0] if paths else W._find_desk_report()
    if not src or not os.path.isfile(src):
        print("注文レポートが見つかりません (デスクトップの ebay-all-orders-report-*.csv)")
        return 2
    print(f"対象: {os.path.basename(src)} / {'本番' if write else 'まだ送りません (--write で実行)'}")

    pairs = [(o, W.category_of(o.get("Item Title") or "")) for o in W.read_orders(src)]
    want = [(o, c) for o, c in pairs if c]
    if not want:
        print("補充対象カテゴリ (PSA / G-Shock / 一番くじ) の売上はありません")
        return 0

    sheets = W._sheets()
    try:
        fresh = fresh_cost_map(S.read_tab("PSA再仕入れ"))
    except Exception:                                              # noqa: BLE001
        fresh = {}
    print(f"今の仕入値 (🃏 PSA再仕入れ照合 の最安¥): {len(fresh)}件")
    # ★同じカードが既に live なら補充しない (本体と同じ判定)
    try:
        import json as _json
        import itemid_writeback_audit as _A
        _live = set(_json.loads(_A.CACHE.read_text(encoding="utf-8")))
        already = live_keys(sheets, _live)
    except Exception:                                              # noqa: BLE001
        already = set()
        print("  ⚠ live 一覧を読めず、同じカードの二重出品チェックを飛ばします")
    print(f"  既に live なカード: {len(already)}種類")
    # ★eBay の口は **今日の出品で実績のある** fix_de_speedpak_shipping を使う
    #   (ichibankuji_restock._sell_token は別 worktree のトークン path を見ていて動かない)
    import ebay_upload_csv as U
    import fix_de_speedpak_shipping as fx
    fx.refresh()
    tok = fx.token()

    done = skipped = acted = 0
    for o, cat in want:
        sku = (o.get("Custom Label") or "").strip()
        iid = (o.get("Item Number") or "").strip()
        title = (o.get("Item Title") or "")[:56]
        label, n, row = W.find_row(sheets, sku, iid)
        if row is None:
            print(f"  ⏭ [{cat}] 台帳に行が無い: {title}")
            skipped += 1
            continue
        state, _aux = W.classify(row)
        if state == "補充済":
            done += 1
            continue
        _key = (row[S.PRODUCT_COL_KEY] or "").strip() if len(row) > S.PRODUCT_COL_KEY else ""
        if _key and _key in already:
            print(f"  ⏭ [{cat}] 同じカードが既に出品中 ({_key}) → 補充しない: {title}")
            skipped += 1
            continue

        cost = cost_override.get(sku) or cost_override.get(
            re.sub(r"\D", "", row[S.PRODUCT_COL_CERT] or "") if len(row) > S.PRODUCT_COL_CERT else "")
        stale = False
        if not cost:
            cost = fresh.get(card_no_of(o))
        if not cost:
            cost = _cost_from_row(row)
            stale = bool(cost)
        price, profile = price_for(cost, CATEGORY_FOR_PRICING.get(cat, "TCG(PSA10)"))
        # ★2026-09-04: 仕入値の上限 (global.yaml cost_sanity) はここにも効かせる。
        #   売れた物をもう一度出すのも「仕入れる」こと。新規と同じ基準にする。
        try:
            from pricing_engine import cost_sanity as _cs
            _ng = _cs(int(float(cost))) if cost else None
        except Exception:                                          # noqa: BLE001
            _ng = None

        status, qty = ebay_status(fx, U, iid, tok)
        act = plan_action(status, qty)
        head = f"  [{cat}] row{n} {title}"
        if act in ("noop", "skip"):
            print(f"{head}\n     → {act} (eBay状態={status} qty={qty}) 触らない")
            skipped += 1
            continue
        if _ng:
            print(head + chr(10) + "     → " + _ng + " → 補充しない")
            skipped += 1
            continue
        if not price:
            # ★仕入値が無いまま戻すと **元の値段のまま** 出てしまう。fail-closed で止める。
            print(f"{head}\n     → 仕入値が取れないので止めます (--cost で渡してください)")
            skipped += 1
            continue

        src_mark = " ⚠️売れた時の古い仕入値" if stale else ""
        print(f"{head}")
        print(f"     → {act} / qty=1 / ${price} / {profile} "
              f"(仕入¥{int(cost):,}{src_mark})")
        if stale and write and not allow_stale:
            # 古い仕入値のまま戻すと「売れない値段」で並ぶ。既定では送らない。
            print("     → 止めました。今の仕入値を --cost で渡すか、"
                  "🃏 PSA再仕入れ照合 を先に走らせてください (--allow-stale-cost で強行)")
            skipped += 1
            continue
        if not write:
            acted += 1
            continue
        call = "RelistFixedPriceItem" if act == "relist" else "ReviseFixedPriceItem"
        resp = fx.post(call, build_item_xml(iid, price, profile), tok, U.SITE_US)
        ack, new_id, err = U.parse_ack(resp)
        if ack not in ("Success", "Warning"):
            print(f"     ❌ 失敗: {err[:120]}")
            continue
        new_id = new_id or iid
        print(f"     ✅ {call} → ItemID {new_id}")
        acted += 1

    print(f"\n補充済で何もしない {done} / 対象 {acted} / 見送り {skipped}")
    if acted and not write:
        print("→ 実行するには --write")
    if write and acted:
        print("→ itemID をスプシに反映: python itemid_writeback_audit.py --apply --no-cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
