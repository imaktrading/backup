"""Trading API による qty 改訂 / 取下げ (= sell_feed_uploader の Trading API 版).

HQ 2026-06-03 「監視くんを Trading API 化」 指示で新規実装。
sell_feed_uploader (= Selenium FileExchange UI) の脆さ (chromedriver DevTools 2GB
JSONDecodeError 等) を回避し、 ReviseInventoryStatus direct call で qty=0 化する。

CSV (= eBay FileExchange 形式、 既存 revise_csv_generator 出力) をそのまま受け、
各行 ItemID + Quantity を ReviseInventoryStatus に投げる。 fail-closed: 個別失敗は
記録 + 続行、 cycle 全体は通る。
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

from ebay_actions.trading_api_client import (
    revise_inventory_status,
    revise_inventory_status_variation,
    load_access_token,
    _call_trading,
)


def _parse_variation_specifics(details_str: str) -> dict:
    """RelationshipDetails 'Sizes=US M(JP L)|Color=BL' → {'Sizes': 'US M(JP L)', 'Color': 'BL'}."""
    out = {}
    for part in (details_str or "").split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _extract_variation_available(xml: str, specifics: dict):
    """GetItem 全文 XML から specifics 完全一致 variation の available qty を返す.

    available = Quantity - QuantitySold (= eBay の per-variation 実在庫)。
    多 variation listing で 1 SKU だけ取下げた verify に使う (= top-level Quantity =
    全 variation sum では他 SKU 在庫で永遠に >0 = false-NG になるため)。

    Returns: int (available) / None (一致 variation が XML に無い)。
    """
    import re as _re  # noqa: PLC0415
    for vb in _re.findall(r"<Variation>(.*?)</Variation>", xml, _re.DOTALL):
        vspecs = dict(_re.findall(
            r"<Name>(.*?)</Name>\s*<Value>(.*?)</Value>", vb))
        if all(vspecs.get(k, "").strip() == str(v).strip()
               for k, v in specifics.items()):
            q_m = _re.search(r"<Quantity>(\d+)</Quantity>", vb)
            sold_m = _re.search(r"<QuantitySold>(\d+)</QuantitySold>", vb)
            total_qty = int(q_m.group(1)) if q_m else 0
            sold = int(sold_m.group(1)) if sold_m else 0
            return max(0, total_qty - sold)
    return None


def _enumerate_variations(xml: str) -> list:
    """GetItem 全文 XML から全 variation の (specifics_dict, available) を列挙.

    available = Quantity - QuantitySold。 Multi-SKU listing の qty>0 variation を
    特定するのに使う (= 単行 Revise が 21916736 で弾かれた listing の救済用)。
    """
    import re as _re  # noqa: PLC0415
    out = []
    for vb in _re.findall(r"<Variation>(.*?)</Variation>", xml, _re.DOTALL):
        vspecs = dict(_re.findall(
            r"<Name>(.*?)</Name>\s*<Value>(.*?)</Value>", vb))
        q_m = _re.search(r"<Quantity>(\d+)</Quantity>", vb)
        sold_m = _re.search(r"<QuantitySold>(\d+)</QuantitySold>", vb)
        total_qty = int(q_m.group(1)) if q_m else 0
        sold = int(sold_m.group(1)) if sold_m else 0
        out.append((vspecs, max(0, total_qty - sold)))
    return out


def _revise_multisku_to_zero(item_id: str, token: str) -> dict:
    """単行 Revise が 21916736 (Multi-SKU) で弾かれた listing を救済して qty=0 化.

    背景: 通常 cycle の revise_csv_generator は単行 (3列) CSV のみ生成 = variation
    非対応。 Multi-SKU listing に投げると eBay が 21916736 "Cannot revise a Multi-SKU
    item when ItemID alone is supplied" で拒否 → pending 永久滞留 = fail-OPEN。
    これが無いと variation 商材 (UT/GU Tシャツ等) が売切れても取り下がらない。

    処置: GetItem (ReturnAll) で variation 列挙 → available>0 の variation を全て
    ReviseFixedPriceItem 経路 (revise_inventory_status_variation) で qty=0 化 →
    再 GetItem で全 variation available=0 を verify。

    1 listing = 1 仕入元 (= mercari URL 1 行) モデル前提 (= HIGH/LOW シートは item_id
    重複なし): 仕入元が売切なら その listing の在庫サイズ (= qty>0 variation) は全て
    履行不能 → 全て qty=0 にするのが正しい。 title→size の脆い解析は不要。

    Returns: {"success","ack","error_code","error_message",
              "verified","verify_qty","verify_msg","zeroed","attempted"}
    """
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f'<ItemID>{item_id}</ItemID>'
        '<DetailLevel>ReturnAll</DetailLevel>'
        '</GetItemRequest>'
    )
    try:
        g = _call_trading("GetItem", body, access_token=token, raw_xml_cap=None)
    except Exception as e:
        return {"success": False, "ack": None, "error_code": "multisku_getitem_exc",
                "error_message": f"{type(e).__name__}: {e}",
                "verified": False, "verify_qty": None,
                "verify_msg": "getitem_exception", "zeroed": 0, "attempted": 0}
    if g.get("error_code") == "17":
        # Item not found / ended = qty=0 同等扱い (safe)
        return {"success": True, "ack": "Success", "error_code": "17",
                "error_message": "Item not found (ended)",
                "verified": True, "verify_qty": 0, "verify_msg": "err_17_safe",
                "zeroed": 0, "attempted": 0}
    if not g.get("success"):
        return {"success": False, "ack": g.get("ack"),
                "error_code": g.get("error_code"),
                "error_message": g.get("error_message"),
                "verified": False, "verify_qty": None,
                "verify_msg": "getitem_failed", "zeroed": 0, "attempted": 0}

    active = [(sp, av) for sp, av in _enumerate_variations(g.get("raw_xml", "")) if av > 0]
    if not active:
        # 既に全 variation available=0 (= 取下げ済 or 別経路で 0 化済)
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None, "verified": True, "verify_qty": 0,
                "verify_msg": "already_all_zero", "zeroed": 0, "attempted": 0}

    last_err = None
    zeroed = 0
    for sp, _av in active:
        r = revise_inventory_status_variation(item_id, sp, 0, access_token=token)
        if r.get("success"):
            zeroed += 1
        else:
            last_err = r
        time.sleep(1.0)  # pacing (= eBay API 連投回避)

    # 再 GetItem で verify (= 全 variation available=0 を物理確認)
    remaining = None
    try:
        g2 = _call_trading("GetItem", body, access_token=token, raw_xml_cap=None)
        if g2.get("error_code") == "17":
            remaining = 0
        elif g2.get("success"):
            remaining = sum(av for _sp, av in _enumerate_variations(g2.get("raw_xml", "")))
    except Exception:
        remaining = None

    if remaining is None:
        verified, verify_qty, verify_msg = False, None, "reverify_failed"
    else:
        verified = (remaining == 0)
        verify_qty = remaining
        verify_msg = "all_var_zero" if verified else f"var_remaining_{remaining}"

    return {"success": verified,
            "ack": "Success" if verified else (last_err.get("ack") if last_err else "Warning"),
            "error_code": None if verified else (last_err.get("error_code") if last_err else None),
            "error_message": None if verified else (
                (last_err.get("error_message") if last_err else None) or verify_msg),
            "verified": verified, "verify_qty": verify_qty, "verify_msg": verify_msg,
            "zeroed": zeroed, "attempted": len(active)}


def _parse_csv_rows(csv_path: Path) -> list:
    """CSV 自動判定: 3 col (single) or 6 col (variation) 両対応.

    Returns: list of dict
      single: {"kind": "single", "item_id": str, "quantity": int}
      variation: {"kind": "variation", "item_id": str, "specifics": dict,
                  "quantity": int, "start_price": float|None}
    """
    rows = []
    parent_iid = None
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # 6 col CSV か判定 (= Relationship 列 存在)
        is_variation_csv = "Relationship" in (reader.fieldnames or [])
        for row in reader:
            iid = (row.get("ItemID") or "").strip().strip('"')
            qty_raw = (row.get("*Quantity") or "").strip().strip('"')
            relationship = (row.get("Relationship") or "").strip().strip('"') if is_variation_csv else ""

            if not is_variation_csv:
                # 3 col (single listing)
                if iid:
                    try:
                        qty = int(qty_raw or "0")
                    except (ValueError, TypeError):
                        qty = 0
                    rows.append({"kind": "single", "item_id": iid, "quantity": qty})
                continue

            # 6 col (variation)
            if iid and not relationship:
                # 親行: ItemID + variation structure 定義。 親 qty 指定があれば single 扱い
                parent_iid = iid
                if qty_raw:
                    try:
                        qty = int(qty_raw)
                    except (ValueError, TypeError):
                        qty = 0
                    rows.append({"kind": "single", "item_id": iid, "quantity": qty})
            elif relationship == "Variation" and parent_iid:
                # 子行: variation 単位 qty 改訂
                details = (row.get("RelationshipDetails") or "").strip().strip('"')
                specifics = _parse_variation_specifics(details)
                try:
                    qty = int(qty_raw or "0")
                except (ValueError, TypeError):
                    qty = 0
                price_raw = (row.get("*StartPrice") or "").strip().strip('"')
                try:
                    price = float(price_raw) if price_raw else None
                except (ValueError, TypeError):
                    price = None
                if specifics:
                    rows.append({
                        "kind": "variation", "item_id": parent_iid,
                        "specifics": specifics, "quantity": qty, "start_price": price,
                    })
    return rows


# HQ 2026-06-10 FINAL 指示 A: in-cycle short retry intervals (= revise + verify NG 時の再試行)
# 設計: 5s/15s/45s 計 3 回追加試行 = 65s 上限。 取下げ義務を「同 cycle 内で閉じる」 ため
# 数十秒〜分単位のスパンで qty=0 確認まで諦めない。 数 cycle 越し (= 旧設計) は禁止。
INCYCLE_RETRY_INTERVALS_SEC = [5.0, 15.0, 45.0]


def upload_csv_via_trading_api(csv_path: Path, dry_run: bool = False,
                                pacing_sec: float = 0.3) -> dict:
    """CSV (= eBay FileExchange format) を Trading API ReviseInventoryStatus で処理.

    CSV format (3 col、 既存 revise_csv_generator 出力):
      "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","*Quantity"
      "Revise","357008108111","0"

    Returns:
      {
        "success": bool (= 全件 OK か。 fail-closed: ng>0 でも cycle は通る、 success=False のみ),
        "total": int,
        "ok": int (= ack=Success/Warning、 既に取下げ済の safe failure も ok 扱い),
        "ng": int (= ack=Failure 系、 要 人手対処),
        "results": list,
        "decision_log": str (= jsonl path) | None,
      }
    """
    csv_path = Path(csv_path)
    rows = _parse_csv_rows(csv_path)

    if not rows:
        return {"success": True, "total": 0, "ok": 0, "ng": 0,
                "results": [], "decision_log": None}

    if dry_run:
        kinds = {}
        for r in rows:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        print(f"  [dry-run] Trading API revise {len(rows)} 件 / CSV: {csv_path.name} "
              f"({kinds})")
        return {"success": True, "total": len(rows), "ok": 0, "ng": 0,
                "results": rows, "decision_log": None, "dry_run": True}

    # token 1 回 load (= refresh は call 内自動 retry)
    token = load_access_token()
    results = []
    ok_count = ng_count = 0

    def _call_one(item):
        if item["kind"] == "variation":
            return revise_inventory_status_variation(
                item["item_id"], item["specifics"], item["quantity"],
                start_price=item.get("start_price"), access_token=token)
        return revise_inventory_status(item["item_id"], item["quantity"],
                                        access_token=token)

    def _is_transient_failure(res: dict) -> bool:
        """DNS / ConnectionError / Timeout 系は 偶発失敗 → 同 cycle 内 retry 対象."""
        if res["success"] or res.get("ack") is not None:
            return False
        msg = (res.get("error_message") or "")
        return any(kw in msg for kw in (
            "ConnectionError", "Timeout", "NameResolutionError",
            "getaddrinfo failed", "Max retries exceeded",
        ))

    def _verify_qty_zero(item) -> tuple:
        """HQ 2026-06-10 FINAL 指示 A: in-cycle verify (= 即 GetItem で qty=0 確認).

        Returns: (verified: bool, observed_qty: int|None, err_msg: str)
          - verified=True: available=0 確認 or err 17 (Item not found = ended、 同等扱い)
          - verified=False, observed_qty=N: available>0 のまま (= revise が反映されてない)
          - verified=False, observed_qty=None: API 失敗 / 確認不能 (= 保守的に失敗扱い)

        ★ 2026-06-10 修正 (variation false-NG 撲滅):
        旧 logic は variation listing でも top-level <Quantity> (= 全 variation の sum) を
        読んでいた。 多 variation listing で 1 SKU だけ取下げると、 他 SKU 在庫で sum>0 が
        残り 「取下げ失敗」 と永遠に false-NG → 無駄リトライ + 偽 ⚠️要対応 メール (実際は
        取下げ成功済)。 → variation は specifics 一致の <Variation> ブロックを GetItem
        全文 (DetailLevel=ReturnAll, raw_xml cap 解除) から取り、 per-SKU の
        available = Quantity - QuantitySold で判定する。
        """
        import re as _re  # noqa: PLC0415
        iid = item.get("item_id", "")
        if not iid:
            return False, None, "item_id_empty"
        specifics = item.get("specifics") or {}
        is_variation = (item.get("kind") == "variation") or bool(specifics)
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'<ItemID>{iid}</ItemID>'
            + ('<DetailLevel>ReturnAll</DetailLevel>' if is_variation else '')
            + '</GetItemRequest>'
        )
        try:
            # cap 解除で全文取得 (raw_xml_cap=None)。
            # - variation: Variations ブロックが 2000 字 cap の外 → 全文必要。
            # - single: <QuantitySold> も SellingStatus 内で 2000 字より後ろ (実測 pos≈3669)
            #   に来るため、 cap=2000 だと取りこぼし → sold=0 と誤算 → available=Quantity と
            #   過大評価 → sold-out 単品 (Quantity=1/QuantitySold=1, 実 available=0) を
            #   永久に qty_gt0 と誤判定 = 偽「滞留」spam (2026-06-22 iid=358251931733、
            #   5/13 売却済の Active listing が amazon 源切れ flag で ~18h 偽滞留)。
            #   → 単品も cap 解除して QuantitySold を確実に読む。
            res = _call_trading("GetItem", body, access_token=token,
                                raw_xml_cap=None)
        except Exception as e:
            return False, None, f"verify_exception: {type(e).__name__}: {e}"
        if res.get("error_code") == "17":
            # Item not found / already ended → qty=0 同等扱い
            return True, 0, "err_17_safe"
        if not res.get("success"):
            return False, None, f"verify_failed_ack={res.get('ack')} err={res.get('error_code')}"
        xml = res.get("raw_xml", "")

        if is_variation:
            # specifics 完全一致の <Variation> の per-SKU available を読む
            available = _extract_variation_available(xml, specifics)
            if available is None:
                # 一致 variation が無い = eBay が 0-qty variation を削除した可能性 (= 取下げ済)
                # だが specifics format 不一致の取りこぼしと区別不能 → 保守的に未確認扱い。
                return False, None, "var_not_found_in_getitem"
            return (available == 0), available, (
                "var_qty_zero" if available == 0 else f"var_available_{available}"
            )

        # single listing: top-level available = Quantity - QuantitySold
        # (eBay <Quantity> は累計出品数。 Quantity=1 sold=1 = 実 available 0 を正しく扱う)
        q_m = _re.search(r"<Quantity>(\d+)</Quantity>", xml)
        sold_m = _re.search(r"<QuantitySold>(\d+)</QuantitySold>", xml)
        if q_m:
            total_qty = int(q_m.group(1))
            sold = int(sold_m.group(1)) if sold_m else 0
            available = max(0, total_qty - sold)
            return (available == 0), available, (
                "qty_zero" if available == 0 else f"available_{available}_(total_{total_qty}_sold_{sold})"
            )
        return False, None, "qty_tag_missing"

    # in-cycle retry policy: module-level INCYCLE_RETRY_INTERVALS_SEC を使う

    # run_daily.py の _parse_qty_output で 「CSV 行数」 文言を regex match させるため
    # 件数を 明示出力 (= sell_feed_uploader stdout 互換)。
    # 「listing」 keyword で single CSV 認識、 含まれない場合は variation 集計に倒す
    has_variation = any(r["kind"] == "variation" for r in rows)
    kind_label = "variation" if has_variation else "single listing"
    print(f"  Trading API ReviseInventoryStatus ({kind_label}): CSV 行数 {len(rows)} 件 "
          f"(pacing {pacing_sec}s)...", flush=True)
    for i, item in enumerate(rows, 1):
        if item["kind"] == "variation":
            label = f"iid={item['item_id']} var={item['specifics']} qty={item['quantity']}"
        else:
            label = f"iid={item['item_id']} qty={item['quantity']}"
        # 1 回目 call
        res = _call_one(item)
        # DNS / ConnectionError 系は 1 回だけ retry (= 偶発失敗救済、 同 cycle 内)
        if _is_transient_failure(res):
            print(f"  [{i}/{len(rows)}] transient fail (DNS/Timeout) → 2s sleep + retry",
                  flush=True)
            time.sleep(2.0)
            res = _call_one(item)

        # Multi-SKU listing 救済 fallback (= 21916736 撲滅、 構造的 fail-OPEN 対策):
        # 単行 Revise が 21916736 で弾かれた = variation listing。 単行 generator は
        # variation 非対応なので、 GetItem で variation 列挙 → qty>0 variation を全て
        # qty=0 化 + 再 GetItem verify まで本 fallback で完結させる。
        multisku_handled = False
        ms_verified = (False, None, "not_attempted")
        if (item.get("kind") != "variation"
                and item.get("quantity") == 0
                and not res["success"]
                and res.get("error_code") == "21916736"):
            print(f"  [{i}/{len(rows)}] Multi-SKU 検出 (21916736) → "
                  f"GetItem で variation 全 qty=0 化 fallback", flush=True)
            ms = _revise_multisku_to_zero(item["item_id"], token)
            res = {"success": ms["success"], "ack": ms["ack"],
                   "error_code": ms["error_code"],
                   "error_message": ms["error_message"]}
            multisku_handled = True
            ms_verified = (ms["verified"], ms["verify_qty"], ms["verify_msg"])
            print(f"  [{i}/{len(rows)}] Multi-SKU fallback: zeroed "
                  f"{ms['zeroed']}/{ms['attempted']} verified={ms['verified']} "
                  f"({ms['verify_msg']})", flush=True)
        # eBay Trading API の 「既に取下げ済 / listing 不在 / ended」 系は safe failure
        # (= 既に 目的達成、 監視くんとしては 取下げ完了扱い)。 互換性のため
        # sell_feed_uploader 系の code 17 も同列で扱う。
        # - 231 "Item not found" (= ended/削除済 listing に Revise 投げた)
        # - 17 "listing has been deleted or you are not the seller" (= FileExchange 系の旧 code)
        # - 21916750 "FixedPrice item ended" (= sold/expired/manual end で既に inactive、
        #   取下げ無用、 dropshipping_model 前提だと売れた item は別経路で処理される、
        #   2026-06-04 追加: 3 cycle 連続 ng=1 で汎用エラー閾値超アラート対策)
        is_safe_failure = res["error_code"] in ("17", "231", "21916750")
        revise_success = res["success"] or is_safe_failure

        # HQ 2026-06-10 FINAL 指示 A: in-cycle verify (= revise 後すぐ GetItem で qty=0 確認)
        # + 失敗時 short retry。 verified=True が真の「取下げ完了」。
        # qty=0 と仕入元の整合性を物理担保し、 silent loss 構造を根絶。
        verified = False
        verify_qty = None
        verify_msg = "not_attempted"
        verify_attempts = 0
        if multisku_handled:
            # Multi-SKU fallback が GetItem 再確認まで実施済 → その verify 結果を採用
            # (単行 _call_one を再投すると 21916736 が再発するので retry loop は回さない)
            verified, verify_qty, verify_msg = ms_verified
            verify_attempts = 1
        elif is_safe_failure and item.get("quantity") == 0:
            # safe_failure (= ended/not-found/already-gone) は取下げ目的達成済。
            # ★ 2026-06-17 修正: 終了 listing (Completed) でも eBay は元の <Quantity> を
            # 残すため、 GetItem verify が available=Quantity-Sold>0 と誤読 → 永久 verify NG
            # → 偽「未取下げ/滞留」spam になっていた (357181571869: 2026-05-18 終了済 Qty1 が
            # 12.5h 滞留)。 revise が 21916750 "FixedPrice item ended" 等を返した時点で
            # 購入不可 = fail-OPEN ではないので、 verify を通過扱いにする。
            verified, verify_qty, verify_msg = True, 0, f"safe_failure_{res['error_code']}"
            verify_attempts = 1
        elif revise_success and item.get("quantity") == 0:
            # qty=0 化が目的の場合のみ verify (= revise の qty 変更が反映されたか chk)
            verified, verify_qty, verify_msg = _verify_qty_zero(item)
            verify_attempts = 1
            # in-cycle short retry: verify NG (qty>0 残存) なら再 Revise + 再 verify
            for attempt_idx, sleep_sec in enumerate(INCYCLE_RETRY_INTERVALS_SEC, start=2):
                if verified:
                    break
                if verify_qty is None:
                    # API 失敗 = 確認不能、 retry しても同じ可能性、 1 回だけ追加試行
                    if attempt_idx > 2:
                        break
                print(f"  [{i}/{len(rows)}] verify NG ({verify_msg}) → {sleep_sec}s sleep + 再 Revise + 再 verify",
                      flush=True)
                time.sleep(sleep_sec)
                res = _call_one(item)
                is_safe_failure = res["error_code"] in ("17", "231", "21916750")
                revise_success = res["success"] or is_safe_failure
                if revise_success:
                    verified, verify_qty, verify_msg = _verify_qty_zero(item)
                verify_attempts = attempt_idx

        # 最終判定: verify 通過 or 元から verify 対象外 (qty != 0 等) なら success
        # verify が必要だったのに通過しなかった → success=False (= action_required)
        if item.get("quantity") == 0 and not verified:
            # qty=0 化が目的だったが in-cycle verify 通過せず → 失敗確定 (= silent ではない)
            success = False
        else:
            success = revise_success
        entry = {
            **item,
            "success": success,
            "ack": res["ack"],
            "error_code": res["error_code"],
            "error_message": res["error_message"],
            "safe_failure": is_safe_failure,
            "verified": verified,
            "verify_qty": verify_qty,
            "verify_msg": verify_msg,
            "verify_attempts": verify_attempts,
        }
        results.append(entry)
        if success:
            ok_count += 1
        else:
            ng_count += 1
        flag = "OK" if success else "NG"
        suffix = ""
        if is_safe_failure:
            suffix = " (safe: 既取下げ済)"
        elif verified:
            suffix = f" (verified qty={verify_qty} attempts={verify_attempts})"
        elif item.get("quantity") == 0:
            suffix = f" (★verify 通過せず: {verify_msg} attempts={verify_attempts} → 要対応)"
        print(f"  [{i}/{len(rows)}] {flag} {label} ack={res['ack']} "
              f"err={res['error_code']}{suffix}", flush=True)
        if i < len(rows):
            time.sleep(pacing_sec)

    # decision_log
    log_dir = Path(__file__).resolve().parent.parent / "decision_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"trading_api_upload_{ts}.jsonl"
    with open(log_path, "w", encoding="utf-8") as f:
        for entry in results:
            f.write(json.dumps(
                {**entry, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "csv_path": str(csv_path)},
                ensure_ascii=False) + "\n")

    # sell_feed_uploader 互換 field (= 既存 cycle log / inventory_monitor から読まれる)
    success_count = sum(1 for r in results if r["ack"] == "Success")
    warning_count = sum(1 for r in results if r["ack"] == "Warning")
    safe_failure_count = sum(1 for r in results if r.get("safe_failure"))
    action_needed_failure = sum(
        1 for r in results
        if r["ack"] == "Failure" and not r.get("safe_failure")
    )
    transient_failure = sum(
        1 for r in results
        if r.get("ack") is None and not r.get("safe_failure") and not r["success"]
    )
    # 旧 sell_feed_uploader 互換: 「Warning N + safe Failure M + action-needed Failure J」
    # + Trading API 拡張: Success N (= 成功) + Transient K (= DNS/Timeout 系)
    result_text = (f"Success {success_count} + Warning {warning_count} "
                   f"+ safe Failure {safe_failure_count} "
                   f"+ action-needed Failure {action_needed_failure} "
                   f"+ Transient {transient_failure}")
    failure_details = [
        {"item_id": r["item_id"], "error_code": r["error_code"],
         "error_message": r["error_message"], "safe": r.get("safe_failure", False)}
        for r in results
        if r["ack"] == "Failure" or not r["success"]
    ]
    return {
        "success": ng_count == 0,
        "total": len(rows),
        "ok": ok_count,
        "ng": ng_count,
        "results": results,
        "decision_log": str(log_path),
        # sell_feed_uploader 互換
        "result_text": result_text,
        "warning": warning_count,
        "safe_failure": safe_failure_count,
        "action_needed_failure": action_needed_failure,
        "failure_details": failure_details,
        "csv_lines": len(rows),
        "log_path": str(log_path),
        # 旧 path で参照されてた field (= 既存 logic 互換)
        "popup_text": "",
        "page_url": "",
        "screenshot": None,
        "error": None if ng_count == 0 else f"Trading API: {ng_count}/{len(rows)} failures",
    }


def main():
    import argparse  # noqa: PLC0415
    parser = argparse.ArgumentParser(
        description="Trading API ReviseInventoryStatus 経由で qty 改訂")
    parser.add_argument("csv", type=Path, help="upload 対象 CSV パス")
    parser.add_argument("--dry-run", action="store_true",
                        help="dry-run mode (= API call せず件数のみ)")
    parser.add_argument("--pacing", type=float, default=0.3,
                        help="inter-call sleep sec (default 0.3)")
    args = parser.parse_args()
    result = upload_csv_via_trading_api(args.csv, dry_run=args.dry_run,
                                          pacing_sec=args.pacing)
    print(f"\n=== 結果 ===")
    print(f"  total={result['total']} ok={result['ok']} ng={result['ng']}")
    print(f"  decision_log: {result.get('decision_log')}")
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
