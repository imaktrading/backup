#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""売れた競合の出品を **丸ごと** 取って残す (GetItem)。

    python iMakHQ/tools/market_getitem.py fetch [--limit N]   # 台帳の itemID を引く
    python iMakHQ/tools/market_getitem.py report              # 取れた物の中身を見る
    python iMakHQ/tools/market_getitem.py missing            # まだ取れていない物を数える

■ 何のために取るのか (2026-09-20 ユーザー確定。**取り違えないこと**)

  ① **利益を取りこぼさない**
     出品価格は仕入値からの積み上げ (cost-plus) で決めているが、そこに縛られない。
     **市場が実際にその値段で買っているなら、そこまで取る**。
     今は実売より安く出している分を、そのまま取り逃している。
  ② **ライバルの出品を多面的に分析して、出品内容を強くする**
     タイトルの組み立て / Item Specifics の埋め方 / 発送・返品の条件 / 写真の枚数 /
     説明文 / 誰が売っているか。**うちに足りないものを見つけて直す**。

  どちらも「売上を増やす」ための話。突き合わせの精度を上げるのは ①の手段であって、
  目的ではない。

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


# ★2026-09-20: **2つ目の鍵 (imaktrading) で走る**。ユーザー指示「あたらしいKEYでやってね」。
#   市場調査で今 動いている方 (imax-64) の枠を減らさないため。鍵は用途ごとに分ける。
KEYS = r"C:/dev/iMak_data/credentials/imaktrading.txt"
TOKEN = r"C:/dev/iMak_data/credentials/ebay_oauth_token_imaktrading.json"


def _keys():
    d = {}
    with open(KEYS, encoding="utf-8-sig") as f:
        for ln in f:
            if "=" in ln:
                k, v = ln.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def access_token():
    """imaktrading 側の access_token を返す。切れていれば refresh_token で更新して保存する。"""
    import base64
    import datetime
    import requests
    tok = json.load(open(TOKEN, encoding="utf-8"))
    got = tok.get("_obtained_at")
    fresh = False
    if got:
        age = (datetime.datetime.now() - datetime.datetime.fromisoformat(got)).total_seconds()
        fresh = age < int(tok.get("expires_in", 7200)) - 300      # 5分の余裕を見る
    if fresh:
        return tok["access_token"]
    d = _keys()
    auth = base64.b64encode(f"{d['AppID']}:{d['AppSecret']}".encode()).decode()
    r = requests.post("https://api.ebay.com/identity/v1/oauth2/token",
                      headers={"Content-Type": "application/x-www-form-urlencoded",
                               "Authorization": "Basic " + auth},
                      data={"grant_type": "refresh_token",
                            "refresh_token": tok["refresh_token"]}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"トークン更新に失敗: {r.status_code} {r.text[:120]}")
    new = r.json()
    tok["access_token"] = new["access_token"]
    tok["expires_in"] = new.get("expires_in", 7200)
    tok["_obtained_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(TOKEN, "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False, indent=1)
    return tok["access_token"]


def headers(call="GetItem"):
    return {"X-EBAY-API-IAF-TOKEN": access_token(), "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
            "X-EBAY-API-CALL-NAME": call, "Content-Type": "text/xml"}


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


# ★2026-09-20 ユーザー「APIの無駄使いは出来ない」「いつも、それで失敗する」。
#   残りがこれを下回ったら **取りに行かない**。今日の他の処理 (監視くんの取下げ /
#   補URL目視の現物画像 / 夜の出品) が GetItem と同じ 5,000回 の枠を使うため。
QUOTA_FLOOR = 1500


def remaining_getitem():
    """GetItem の残り回数 (I/O)。取れなければ None = 分からない。"""
    import base64
    import requests
    try:
        d = _keys()
        auth = base64.b64encode(f"{d['AppID']}:{d['AppSecret']}".encode()).decode()
        t = requests.post("https://api.ebay.com/identity/v1/oauth2/token",
                          headers={"Content-Type": "application/x-www-form-urlencoded",
                                   "Authorization": "Basic " + auth},
                          data={"grant_type": "client_credentials",
                                "scope": "https://api.ebay.com/oauth/api_scope"},
                          timeout=30).json()["access_token"]
        g = requests.get("https://api.ebay.com/developer/analytics/v1_beta/rate_limit/",
                         headers={"Authorization": "Bearer " + t}, timeout=30).json()
        for grp in g.get("rateLimits", []):
            for res in grp.get("resources", []):
                if res.get("name") == "GetItem":
                    for rk in res.get("rates", []):
                        return int(rk.get("remaining"))
    except Exception:                                          # noqa: BLE001
        return None
    return None


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
    left = remaining_getitem()
    if left is None:
        print("⚠ 残り回数が分からないので取りに行きません (分からない時は動かさない)")
        return 1
    if left - len(ids) < QUOTA_FLOOR:
        can = max(0, left - QUOTA_FLOOR)
        print(f"⚠ 残り {left}回。{QUOTA_FLOOR}回は他の処理に残すので、今回は {can}件までです")
        ids = ids[:can]
        if not ids:
            print("  → 今日はここまで。16:00 のリセット後にもう一度どうぞ")
            return 0
    print(f"未取得 {total}件 / 今回 {len(ids)}件 を取ります (GetItem 残り {left}回)")
    failed = []
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
                                  headers=headers("GetItem"), timeout=40)
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
            # ★通信で落ちた分は **保存しない** = 次の走行でもう一度取りに行く (取りこぼさない)
            err += 1
            failed.append((iid, "通信"))
            continue
        # ★eBay が「取れない」と答えた物も残す (空ファイルにしない)。
        #   残さないと毎回 同じ物を取りに行って、枠だけ減る。
        save_raw(iid, xml)
        if "<Ack>Success</Ack>" in xml or "<Ack>Warning</Ack>" in xml:
            ok += 1
        else:
            m = re.search(r"<ShortMessage>(.*?)</ShortMessage>", xml, re.S)
            failed.append((iid, (m.group(1) if m else "不明")[:40]))
        if n % 50 == 0 or n == len(ids):
            print(f"  {n}/{len(ids)} 件", flush=True)
        time.sleep(0.2)
    left = [i for i in ledger_item_ids() if not have(i)]
    print(f"取得 {ok}件 / 取れなかった {len(failed)}件 / **まだ残り {len(left)}件**")
    if failed:
        print("  取れなかった物 (理由):")
        for iid, why in failed[:10]:
            print(f"    {iid}  {why}")
        if len(failed) > 10:
            print(f"    … 他 {len(failed) - 10}件")
    if left:
        print("  ★残りはもう一度 fetch すれば続きから取ります (取れた分は取り直しません)")
    print(f"→ {OUT_DIR}")
    return 0


def cmd_missing(_argv):
    """まだ取れていない物を数える。取りこぼしを黙って見逃さないため。"""
    ids = ledger_item_ids()
    left = [i for i in ids if not have(i)]
    bad = []
    for i in ids:
        if have(i) and "<Ack>Failure</Ack>" in load_raw(i):
            bad.append(i)
    print(f"台帳 {len(ids)}件 / 取れた {len(ids) - len(left)}件 / まだ {len(left)}件")
    print(f"eBay が「取れない」と答えた物: {len(bad)}件 (これは何度やっても取れない)")
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
    cmds = {"fetch": cmd_fetch, "report": cmd_report, "missing": cmd_missing}
    if len(argv) < 2 or argv[1] not in cmds:
        print(__doc__)
        return 1
    return cmds[argv[1]](argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
