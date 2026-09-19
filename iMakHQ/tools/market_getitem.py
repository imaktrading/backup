#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""売れた競合の出品を **丸ごと** 取って残す (GetItem)。

    python iMakHQ/tools/market_getitem.py fetch [--limit N]   # 台帳の itemID を引く
    python iMakHQ/tools/market_getitem.py report              # 取れた物の中身を見る

★2026-09-20 ユーザー確定「丸ごとなら、取り直し要らないね」。
  集計して保存すると、後から「これも見たい」となった時に全件取り直しになる。
  **XML をそのまま1件1ファイルで残す**。読み方は後からいくらでも変えられる。

★使うのは GetItem (Trading API)。Browse は **今出ている商品しか返さない**ので、
  売れて終わった出品 (= 台帳の中身) には使えない (2026-09-20 実機確認)。
  終わった出品でも Item Specifics が全部返る (実測: 24項目)。

用途は値段だけではない。売れている出品の **タイトルの組み立て / どの項目を埋めているか /
値の書き方 / カテゴリ / 写真の枚数 / 送料無料か / Best Offer を受けているか** まで見る。
★取った値を **そのまま うちの出品に写さないこと**。値を決めるのはカタログの仕事なので、
  「カタログに何が足りないか」を示す材料として使い、カタログに投げる。
"""

import gzip
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = r"C:/dev/iMak_data/hq/market_sold/getitem"
EP = "https://api.ebay.com/ws/api.dll"


def _tools():
    sys.path.insert(0, HERE)
    import live_set_revise as L
    return L


def path_of(item_id):
    return os.path.join(OUT_DIR, f"{item_id}.xml.gz")


def have(item_id):
    return os.path.exists(path_of(item_id))


def save_raw(item_id, xml):
    """XML をそのまま残す (gzip)。1件1ファイル = 途中で止まっても続きから。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    with gzip.open(path_of(item_id), "wt", encoding="utf-8") as f:
        f.write(xml)


def load_raw(item_id):
    with gzip.open(path_of(item_id), "rt", encoding="utf-8") as f:
        return f.read()


# ---- 読み方 (保存した XML から後で好きに取り出す。焼かない) ----

def specifics(xml):
    """Item Specifics → {項目: [値…]} (純関数)。"""
    out = {}
    for blk in re.findall(r"<NameValueList>(.*?)</NameValueList>", xml or "", re.S):
        n = re.search(r"<Name>(.*?)</Name>", blk, re.S)
        if not n:
            continue
        vals = re.findall(r"<Value>(.*?)</Value>", blk, re.S)
        out.setdefault(n.group(1).strip(), []).extend(v.strip() for v in vals)
    return out


def _one(xml, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml or "", re.S)
    return m.group(1).strip() if m else ""


def summary(xml):
    """1件の出品から「リスティングの作り」を取り出す (純関数)。"""
    pics = re.findall(r"<PictureURL>(.*?)</PictureURL>", xml or "", re.S)
    free = "<ShippingServiceCost currencyID=\"USD\">0.0</ShippingServiceCost>" in (xml or "")
    return {
        "itemID": _one(xml, "ItemID"),
        # ★2026-09-20 ユーザー「セラーidもとれる?」→ 取れる。誰が売っているか / 国内か海外か /
        #   評価が少なくても売れているか、を見るため残す。
        "セラー": _one(xml, "UserID"),
        "評価数": _one(xml, "FeedbackScore"),
        "評価率": _one(xml, "PositiveFeedbackPercent"),
        "国": _one(xml, "Country"),
        "所在地": _one(xml, "Location"),
        "タイトル": _one(xml, "Title"),
        "サブタイトル": _one(xml, "SubTitle"),
        "カテゴリ": _one(xml, "CategoryID"),
        "カテゴリ名": _one(xml, "CategoryName"),
        "写真枚数": len(pics),
        "送料無料": free,
        "BestOffer": _one(xml, "BestOfferEnabled") == "true",
        # ★2026-09-20 ユーザー「それが何個売れているかは?」「シッピングポリシーとか、
        #   リターンポリシーとか」→ 全部 取れる。ポリシーの **名前**は他人の出品なので
        #   出ないが、中身は出る。比べるのに要るのは中身の方。
        "売れた数": _one(xml, "QuantitySold"),
        "在庫数": _one(xml, "Quantity"),
        "発送方法": _one(xml, "ShippingService"),
        "送料の形": _one(xml, "ShippingType"),
        "発送までの日数": _one(xml, "DispatchTimeMax"),
        "送料負担": _one(xml, "ShippingCostPaidBy"),
        "返品": _one(xml, "ReturnsAcceptedOption") or _one(xml, "ReturnsAccepted"),
        "返品期限": _one(xml, "ReturnsWithin"),
        "返金方法": _one(xml, "RefundOption"),
        "状態": _one(xml, "ConditionDisplayName"),
        "出品形式": _one(xml, "ListingType"),
        "説明文の長さ": len(_one(xml, "Description")),
        "項目数": len(specifics(xml)),
    }


# ---- 取得 ----

def ledger_item_ids():
    sys.path.insert(0, HERE)
    import market_ledger as M
    seen, out = set(), []
    for r in M.load_ledger():
        iid = (r.get("itemId") or "").strip()
        if iid and iid not in seen:
            seen.add(iid)
            out.append(iid)
    return out


def cmd_fetch(argv):
    import requests
    L = _tools()
    limit = None
    for a in argv:
        if a.startswith("--limit"):
            limit = int(a.split("=", 1)[1] if "=" in a else argv[argv.index(a) + 1])
    ids = [i for i in ledger_item_ids() if not have(i)]
    total = len(ids)
    if limit:
        ids = ids[:limit]
    print(f"未取得 {total}件 / 今回 {len(ids)}件 を取ります")
    ok = err = 0
    for n, iid in enumerate(ids, 1):
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                f"<ItemID>{iid}</ItemID>"
                "<DetailLevel>ReturnAll</DetailLevel>"
                "<IncludeItemSpecifics>true</IncludeItemSpecifics>"
                "</GetItemRequest>")
        xml = None
        for attempt in range(3):
            try:
                r = requests.post(EP, data=body.encode("utf-8"),
                                  headers=L._oauth_headers("GetItem"), timeout=40)
                xml = L.decode_xml(r.content)
                L._check_auth(xml)          # 認証で落ちたら例外 (空を残して黙らない)
                break
            except Exception as e:          # noqa: BLE001
                if attempt == 2:
                    xml = None
                    print(f"  ⚠ {iid}: {type(e).__name__}: {e}")
                else:
                    time.sleep(3)
        if xml is None:
            err += 1
            continue
        # ★取れなかった物も「取れなかった」と分かる形で残す (空ファイルにしない)
        save_raw(iid, xml)
        ok += 1 if "<Ack>Success</Ack>" in xml or "<Ack>Warning</Ack>" in xml else 0
        if n % 50 == 0 or n == len(ids):
            print(f"  {n}/{len(ids)} 件", flush=True)
        time.sleep(0.2)
    print(f"取得 {ok}件 / 失敗 {err}件 → {OUT_DIR}")
    return 0


def cmd_report(_argv):
    import collections
    files = [f for f in os.listdir(OUT_DIR)] if os.path.isdir(OUT_DIR) else []
    if not files:
        print("まだ1件も取っていません。先に fetch してください")
        return 1
    rows, fields = [], collections.Counter()
    for f in files:
        xml = load_raw(f.split(".")[0])
        if "<Ack>Failure</Ack>" in xml:
            continue
        rows.append(summary(xml))
        for k in specifics(xml):
            fields[k] += 1
    sellers = collections.Counter(r["セラー"] for r in rows if r["セラー"])
    print(f"取れた出品 {len(rows)}件 / セラー {len(sellers)}人")
    print("よく売れているセラー:")
    for who, n in sellers.most_common(8):
        one = next(r for r in rows if r["セラー"] == who)
        print(f"  {n:>3}件  {who:<24} 評価{one['評価数']:>6} ({one['評価率']}%) {one['国']}")
    print(f"写真 中央値 {sorted(r['写真枚数'] for r in rows)[len(rows) // 2]}枚 / "
          f"送料無料 {sum(1 for r in rows if r['送料無料'])}件 / "
          f"BestOffer {sum(1 for r in rows if r['BestOffer'])}件 / "
          f"サブタイトル {sum(1 for r in rows if r['サブタイトル'])}件")
    ship = collections.Counter(r["発送方法"] for r in rows if r["発送方法"])
    days = [int(r["発送までの日数"]) for r in rows if (r["発送までの日数"] or "").isdigit()]
    ret = collections.Counter(r["返品期限"] for r in rows if r["返品期限"])
    print(f"発送までの日数 中央値 {sorted(days)[len(days) // 2] if days else '-'}日 / "
          f"返品 {sum(1 for r in rows if '返品' in r and r['返品'] and 'Not' not in r['返品'])}件")
    print("発送方法:", dict(ship.most_common(5)))
    print("返品期限:", dict(ret.most_common(5)))
    print("よく埋めている項目:")
    for k, v in fields.most_common(25):
        print(f"  {v:>4}件 ({v / len(rows):>3.0%})  {k}")
    return 0


def main(argv):
    cmds = {"fetch": cmd_fetch, "report": cmd_report}
    if len(argv) < 2 or argv[1] not in cmds:
        print(__doc__)
        return 1
    return cmds[argv[1]](argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
