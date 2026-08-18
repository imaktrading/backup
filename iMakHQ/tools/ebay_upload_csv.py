#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ebay_upload_csv.py — 入稿CSV を eBay API で出品する (2026-08-18)。

なぜ API か (ユーザー決定 2026-08-18):
    最後まで手作業だった「CSVを FileExchange に上げる」を無くす。API なら
    **出品と同時に ItemID が返る**ので、itemID の書き戻し待ちも消える。
    ブラウザ操作より壊れにくい (画面改変の影響を受けない)。

守っていること:
    - **CSV が正**。CSV を作り直さず、既にある行をそのまま API の形に写すだけ。
      値の決定 (価格/送料ポリシー/Item Specifics) は従来どおり生成側の責任
    - 既定は **検証のみ** (`VerifyAddFixedPriceItem` = eBay 側で検証するが出品しない)。
      `--write` を付けた時だけ本当に出す
    - 出したら **その場で ItemID をシート B列に書く** (書き忘れる隙を作らない。
      itemID が無い行は監視くんが取り下げられない = 売り切れても売れる状態で残る)
    - 1件でも失敗したら止める (`--keep-going` で続行)。半端に出して数が合わない状態にしない

使い方:
    python ebay_upload_csv.py <csv>                 # 検証のみ (出さない)
    python ebay_upload_csv.py <csv> --limit 1       # 1件だけ検証
    python ebay_upload_csv.py <csv> --write         # 実際に出品する
"""
import argparse
import csv as _csv
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

SITE_US = "0"
VERIFY_CALL = "VerifyAddFixedPriceItem"
ADD_CALL = "AddFixedPriceItem"


# ── CSV → API の写し替え (純関数・test 可) ──────────────────────────
def _esc(v):
    return html.escape(str(v or ""), quote=False)


def pic_urls(row):
    """CSV の PicURL 列 (1本 or | 区切り) → URL list (純関数)。"""
    raw = (row.get("PicURL") or row.get("*PicURL") or "").strip()
    return [u.strip() for u in raw.split("|") if u.strip()]


def item_specifics(row):
    """`C:` 始まりの列 → [(名前, 値)] (純関数)。空欄は出さない。"""
    out = []
    for k, v in row.items():
        if not k or not k.startswith("C:"):
            continue
        v = (v or "").strip()
        if v:
            out.append((k[2:], v))
    return out


_CD_COL = re.compile(r"^(CDA?):(.+?)\s*-\s*\(ID:\s*(\d+)\)$")


def condition_descriptors(row):
    """`CD:`/`CDA:` 列 → [(ID, 値)] (純関数)。

    PSA の 等級/鑑定会社/証明番号 は普通の Item Specifics ではなく eBay の
    **状態の詳細 (Condition Descriptors)** という別枠。ここに入れないと
    「Grade (27502) is a required field」で出品を拒否される (2026-08-18 実測)。
    CSV は FileExchange 形式で `CD:Grade - (ID: 27502)` = 選択肢ID、
    `CDA:Certification Number - (ID: 27503)` = 自由入力 を既に持っている。
    """
    out = []
    for k, v in row.items():
        m = _CD_COL.match(k or "")
        v = (v or "").strip()
        if m and v:
            # CD: = 選択肢 (Value に ID) / CDA: = 自由入力 (AdditionalInfo)。
            # 証明番号を Value で送ると「not valid for 27503」で弾かれる (2026-08-18 実測)
            out.append((m.group(3), v, m.group(1) == "CDA"))
    return out


def build_item_xml(row, schedule_time=""):
    """CSV 1行 → AddFixedPriceItem の <Item> XML (純関数)。

    値は **一切作らない**。CSV に入っているものだけを写す。
    足りない必須項目は呼び出し側が missing_fields() で先に弾く。
    """
    specs = "".join(
        f"<NameValueList><Name>{_esc(n)}</Name><Value>{_esc(v)}</Value></NameValueList>"
        for n, v in item_specifics(row))
    pics = "".join(f"<PictureURL>{_esc(u)}</PictureURL>" for u in pic_urls(row))
    store_cat = (row.get("StoreCategoryID") or "").strip()
    cds = "".join(
        f"<ConditionDescriptor><Name>{_esc(n)}</Name>"
        + (f"<AdditionalInfo>{_esc(v)}</AdditionalInfo>" if free
           else f"<Value>{_esc(v)}</Value>")
        + "</ConditionDescriptor>"
        for n, v, free in condition_descriptors(row))
    cds = f"<ConditionDescriptors>{cds}</ConditionDescriptors>" if cds else ""
    sched = f"<ScheduleTime>{_esc(schedule_time)}</ScheduleTime>" if schedule_time else ""
    return (
        "<Item>"
        f"<Title>{_esc(row.get('*Title'))}</Title>"
        f"<Description><![CDATA[{row.get('*Description') or ''}]]></Description>"
        f"<PrimaryCategory><CategoryID>{_esc(row.get('*Category'))}</CategoryID></PrimaryCategory>"
        f"<StartPrice currencyID=\"USD\">{_esc(row.get('*StartPrice'))}</StartPrice>"
        f"<Quantity>{_esc(row.get('*Quantity') or '1')}</Quantity>"
        f"<ConditionID>{_esc(row.get('ConditionID') or row.get('*ConditionID'))}</ConditionID>"
        f"<SKU>{_esc(row.get('CustomLabel'))}</SKU>"
        "<ListingType>FixedPriceItem</ListingType>"
        f"<ListingDuration>{_esc(row.get('*Duration') or 'GTC')}</ListingDuration>"
        "<Country>JP</Country><Currency>USD</Currency><Site>US</Site>"
        f"<Location>{_esc(row.get('*Location') or '')}</Location>"
        + (f"<Storefront><StoreCategoryID>{_esc(store_cat)}</StoreCategoryID></Storefront>"
           if store_cat else "")
        + "<SellerProfiles>"
        f"<SellerShippingProfile><ShippingProfileName>{_esc(row.get('ShippingProfileName'))}"
        "</ShippingProfileName></SellerShippingProfile>"
        f"<SellerPaymentProfile><PaymentProfileName>{_esc(row.get('PaymentProfileName'))}"
        "</PaymentProfileName></SellerPaymentProfile>"
        f"<SellerReturnProfile><ReturnProfileName>{_esc(row.get('ReturnProfileName'))}"
        "</ReturnProfileName></SellerReturnProfile>"
        "</SellerProfiles>"
        f"<PictureDetails>{pics}</PictureDetails>"
        f"<ItemSpecifics>{specs}</ItemSpecifics>"
        f"{cds}"
        f"{sched}"
        "</Item>"
    )


REQUIRED = ["*Title", "*Category", "*StartPrice", "CustomLabel",
            "ShippingProfileName", "PaymentProfileName", "ReturnProfileName"]


def missing_fields(row):
    """出品に必要な値が欠けている列名 (純関数)。推測で埋めない = 欠けたら出さない。"""
    out = [k for k in REQUIRED if not (row.get(k) or "").strip()]
    # ConditionID は CSV では `ConditionID` (アスタリスク無し)。両方の名前を許す
    if not ((row.get("ConditionID") or row.get("*ConditionID") or "").strip()):
        out.append("ConditionID")
    if not pic_urls(row):
        out.append("PicURL")
    if not (row.get("*Description") or "").strip():
        out.append("*Description")
    return out


def parse_ack(resp):
    """Trading API の応答 → (ack, itemID, エラー文) (純関数)。"""
    ack = re.search(r"<Ack>(\w+)</Ack>", resp or "")
    iid = re.search(r"<ItemID>(\d+)</ItemID>", resp or "")
    msgs = re.findall(r"<LongMessage>(.*?)</LongMessage>", resp or "", re.S)
    return (ack.group(1) if ack else "NoAck",
            iid.group(1) if iid else "",
            " / ".join(m.strip()[:160] for m in msgs[:3]))


# ── 実行 ────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--write", action="store_true", help="実際に出品する (既定は検証のみ)")
    ap.add_argument("--limit", type=int, default=0, help="先頭N件だけ")
    ap.add_argument("--keep-going", action="store_true", help="失敗しても続ける")
    ap.add_argument("--result-json", default="", help="出品結果 (label/itemID) の書き出し先")
    a = ap.parse_args()

    with open(a.csv, newline="", encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    if a.limit:
        rows = rows[:a.limit]

    import fix_de_speedpak_shipping as fx
    fx.refresh()
    tok = fx.token()
    call = ADD_CALL if a.write else VERIFY_CALL

    print(f"=== eBay 出品 [{'本番' if a.write else '検証のみ(出品しない)'}] {os.path.basename(a.csv)} "
          f"/ {len(rows)}件 ===")
    ok = ng = 0
    listed = []
    for i, row in enumerate(rows, 1):
        label = (row.get("CustomLabel") or "").strip()
        miss = missing_fields(row)
        if miss:
            print(f"  ❌ [{i}] {label} 値が足りない: {', '.join(miss)} → 出さない")
            ng += 1
            if not a.keep_going:
                break
            continue
        inner = ("<ErrorLanguage>en_US</ErrorLanguage><WarningLevel>High</WarningLevel>"
                 + build_item_xml(row))
        resp = fx.post(call, inner, tok, site=SITE_US)
        ack, iid, err = parse_ack(resp)
        if ack in ("Success", "Warning"):
            ok += 1
            mark = f" → ItemID {iid}" if iid and a.write else ""
            print(f"  ✅ [{i}] {label} {ack}{mark}")
            if err:
                print(f"      ⚠️ {err}")
            if a.write and iid:
                listed.append((label, iid))
        else:
            ng += 1
            print(f"  ❌ [{i}] {label} {ack}: {err}")
            if not a.keep_going:
                print("     → 1件目の失敗で停止 (半端に出さない。--keep-going で続行)")
                break

    print(f"\n  結果: OK {ok} / NG {ng}")
    if a.write and listed:
        print("  ✏️ ItemID をシートに書き戻します")
        import subprocess
        subprocess.run([sys.executable, "itemid_writeback_audit.py", "--apply"],
                       cwd=os.path.dirname(os.path.abspath(__file__)))
    return 0 if ng == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
