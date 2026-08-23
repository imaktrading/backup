#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B: CULL(在庫切れ&需要皆無) 段階的 出品停止 End CSV 生成。

CULL = qty=0 ∩ 一度も売れず watcher も付かず。掲載しても無害(qty=0=購入不可)だが、
整理 + 誤って qty を戻して売れる事故の予防として段階的に End する。

安全策 (2026-06-05 ユーザー合意):
  1. age>=21日 の行のみ (NEW_WAIT補正: 出品から時間不足の良品を巻き込まない)。
     age 不明(0)は fail-closed で対象外 (判定不能を破壊側に倒さない)。
  2. $100未満は対象外 (枠は金額で詰まっており、安い出品を落としても効かない)
  3. CAP=200件/回 (burst禁止: 1755件一括 END はしない。2026-08-23 に 50→200)。
  3. 自動アップ無し (End CSV を生成するのみ。eBay FileExchange へは人が手動アップ)。
  並び: age 降順 (最も長く需要0=最も確実に dead を先に) → 同 age は価格昇順 (損失小を先に)。

入力 : ../funnel_output/funnel_*.csv (CULL flag, age_days)
出力 : End CSV → C:/dev/iMak_data/revise/cull_end_YYYYMMDD.csv
       確認用一覧 → デスクトップ CULL出品停止候補_YYYYMMDD.csv
"""
import csv
import datetime
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
END_DIR = r"C:\dev\iMak_data\revise"

# 1回あたりの上限 (burst禁止)。
# ★2026-08-23 ユーザー指示で 50 → 200。理由: eBay 公式のとおり **月末時点で生きている出品は
#   翌月の枠にも計上される** ので、8/31 までに CULL を落とすかどうかで9月の出発点が変わる。
#   残り約1,800件を8日で処理するには 50/回 では間に合わない (36回)。
#   誤取下げの守りは件数と独立: 毎回 eBay の実在庫を見て、復活していた行を除外する
#   (2026-08-23 の1回目は 50件中 11件が復活で除外された)。
CAP = 200
# ★2026-08-24 ユーザー指示で 21 → 14。理由: 取り下げで **当月の枠が戻るのは
#   「その月に出品したもの」だけ**なので、21日待つと月の前半に出した分しか間に合わない。
#   14日なら月の中旬に出した分まで当月中に判断できる。
MIN_AGE = 14      # これ未満(日)は新規=時間不足の可能性 → 対象外 (NEW_WAIT補正)

# ★2026-08-24 ユーザー指示: **金額が小さいものは対象にしない**。
#   枠は金額で詰まっており (点数は半分以上 余っている)、安い出品を落としても効かない。
#   実測: $100 で切ると 件数は 1,449→1,203 に減るのに、金額は $356,660→$339,453 と
#   ほぼ落ちない (T-Shirts は1件あたり $64 等)。カテゴリ名で列挙しないのは、
#   ガチャ等の新商材が増えるたびに書き足す運用にしないため。
MIN_PRICE = 100.0

# relist_from_funnel / seller_hub_relist と統一
END_HEADER = ["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)", "ItemID", "EndCode"]
END_CODE = "OtherListingError"


def _i(v):
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return 0


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


def listed_this_month(row, today=None):
    """その出品を **今月** 出したか (純関数, test可)。

    当月の枠が戻るのは今月出品した分だけなので、そこを先に処理したい。
    age_days が無い/読めない行は False (先頭に持ってこない)。
    """
    today = today or datetime.date.today()
    age = _i(row.get("age_days"))
    if age <= 0:
        return False
    d = today - datetime.timedelta(days=age)
    return (d.year, d.month) == (today.year, today.month)


def select(rows, cap=CAP, min_age=MIN_AGE, min_price=MIN_PRICE, today=None):
    """CULL ∩ age>=min_age を age降順・価格昇順で並べ、先頭 cap 件。

    age 不明(0)は対象外 (fail-closed)。テスト可能なよう純関数化。
    """
    cull = [r for r in rows if "CULL" in (r.get("flags") or "").split("|")]
    eligible = [r for r in cull
                if _i(r.get("age_days")) >= min_age and _f(r.get("price")) >= min_price]
    # ★2026-08-24: **今月出品した分を先に**。当月の枠が戻るのはそこだけ
    #   (実測: 古い順だけで 361件 落として当月に戻ったのは 1.5%)。
    #   今月分は金額の大きい順 = 戻る額を最大化。それ以前は従来どおり age 降順
    #   (最も長く需要0 = 最も確実に dead) → 価格昇順。
    def _key(r):
        cur = listed_this_month(r, today)
        if cur:
            return (0, -_f(r.get("price")), 0.0)
        return (1, -_i(r.get("age_days")), _f(r.get("price")))
    eligible.sort(key=_key)
    return cull, eligible, eligible[:cap]


def verify_oos(picked, fetch_fn, status_fn=None):
    """各 picked の現eBay 状態を実機確認し、**まだ生きていて qty==0** のものだけ残す。

    古い funnel を小分け処理する間に補充された listing を誤って取り下げる事故を防ぐ
    (2026-06-28)。fail-closed = qty>0(在庫復活) も qty取得不能(None/例外) も End しない。

    ★2026-08-23: **既に終了済みの listing を除外していなかった**。
      funnel CSV は静的なので、qty だけ見ると終了済みも「qty=0」で通ってしまい、
      毎回 同じ上位N件が選ばれて **2回目以降ずっと進まない**。
      実害: 1回目に End した33件が、2回目の CSV にそのまま載っていた。
      `status_fn` (item_id → ListingStatus) を渡して Active 以外を落とす。

    戻り: (kept, revived, ended, failed)。fetch_fn / status_fn は test 用に注入可能。
    """
    kept, revived, ended, failed = [], [], [], []
    for r in picked:
        if status_fn is not None:
            try:
                st = status_fn(r["item_id"])
            except Exception:                                      # noqa: BLE001
                st = None
            if st is None:
                failed.append(r)                     # 分からない = 触らない
                continue
            if st != "Active":
                ended.append(r)                      # 既に終わっている = もう対象でない
                continue
        try:
            q = fetch_fn(r["item_id"])
        except Exception:                                          # noqa: BLE001
            q = None
        if q is None:
            failed.append(r)
        elif q > 0:
            revived.append(r)
        else:
            kept.append(r)
    return kept, revived, ended, failed


def rows_from_live(fetch_active_fn):
    """出品中の一覧から CULL 行を作る (funnel CSV を使わない)。

    ★2026-08-23: funnel は Seller Hub のレポートを手で落とさないと更新できず、
      7/23 のまま古かった。CULL の材料 (在庫0 / 販売0 / watcher 0 / 出品日) は
      **ActiveList から全部取れる**ので、レポート無しで最新の対象を出せるようにする。
      eBay は 0 の要素を省くので、**QuantitySold / WatchCount が無い = 0** と読む。

    fetch_active_fn: () -> [{item_id, avail, sold, watch, age_days, price, title}]
    戻り: funnel CSV と同じ形の dict list (flags に CULL を立てる)。純関数寄り (test 可)。
    """
    out = []
    for it in fetch_active_fn():
        if it["avail"] > 0 or it["sold"] > 0 or it["watch"] > 0:
            continue                      # 買える / 売れた / 見られている → CULL ではない
        out.append({"item_id": it["item_id"], "title": it.get("title", ""),
                    "price": str(it.get("price", 0)), "age_days": str(it["age_days"]),
                    "flags": "CULL"})
    return out


def _fetch_active_live():
    """ActiveList を全ページ取って CULL 判定に要る項目だけ返す。"""
    import re as _re
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "iMakeBayAPI")))
    import fix_de_speedpak_shipping as fx
    fx.refresh()
    tok = fx.token()
    today = datetime.datetime.utcnow()
    seen, out = set(), []
    for page in range(1, 60):
        inner = ("<ActiveList><Include>true</Include><Pagination>"
                 "<EntriesPerPage>200</EntriesPerPage>"
                 f"<PageNumber>{page}</PageNumber></Pagination></ActiveList>"
                 "<DetailLevel>ReturnAll</DetailLevel>")
        xml = fx.post("GetMyeBaySelling", inner, tok, site="0")
        if "<Ack>Failure</Ack>" in (xml or ""):
            sys.exit(f"出品一覧の取得に失敗 ({page}ページ目)。途中結果では判断しない (fail-closed)")
        blocks = _re.findall(r"<Item>(.*?)</Item>", xml or "", _re.S)
        if not blocks:
            break
        for b in blocks:
            def g(tag, d=""):
                m = _re.search(rf"<{tag}>(.*?)</{tag}>", b)
                return m.group(1) if m else d
            iid = g("ItemID")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            st = g("StartTime")
            try:
                age = (today - datetime.datetime.strptime(st[:19], "%Y-%m-%dT%H:%M:%S")).days
            except ValueError:
                age = 0                    # 分からない = 対象外 (select が落とす)
            price = _re.search(r'<CurrentPrice currencyID="\w+">([\d.]+)</CurrentPrice>', b)
            out.append({"item_id": iid,
                        "avail": _i(g("Quantity")) - _i(g("QuantitySold")),
                        "sold": _i(g("QuantitySold")),
                        "watch": _i(g("WatchCount")),
                        "age_days": age,
                        "price": float(price.group(1)) if price else 0.0,
                        "title": g("Title")})
    return out


def main():
    live = "--live" in sys.argv
    if live:
        print("出品中の一覧を eBay から直接取得します (funnel CSV は使いません)...", flush=True)
        rows = rows_from_live(_fetch_active_live)
        src = "eBay ActiveList (live)"
    else:
        fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
        if not fs:
            sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
        src = max(fs, key=os.path.getmtime)
        rows = list(csv.DictReader(open(src, encoding="utf-8")))
        src = os.path.basename(src)
    cull, eligible, picked = select(rows)

    print(f"対象 funnel: {src}")
    print(f"CULL(在庫切れ&需要皆無) = {len(cull)}件")
    print(f"  うち age>={MIN_AGE}日 かつ ${MIN_PRICE:.0f}以上 = {len(eligible)}件")
    print(f"  今回 End 対象 (CAP {CAP}/回, age降順) = {len(picked)}件")
    skipped_young = len(cull) - len(eligible)
    if skipped_young:
        print(f"  ※ age<{MIN_AGE}日 / age不明 / ${MIN_PRICE:.0f}未満 で対象外 = {skipped_young}件")
    if not picked:
        print("対象なし。処理終了。")
        return

    # ★2026-08-23: --live は **数えるだけ**。End CSV は作らない。
    #   実測: live 判定 1,601件のうち **457件 (29%) は funnel では CULL でなかった**
    #   (うち 73件は RESTOCK/NO_CONVERT = 需要が実証されている)。
    #   ActiveList は「今の出品が売れたか」しか見えず、**一度売れて出し直した実績が見えない**。
    #   母数を知るには使えるが、取り下げる対象を選ぶ材料にはならない。
    if live:
        print()
        print("※ --live は件数の把握のみです。End CSV は作りません。")
        print("   取り下げる対象は Seller Hub のレポート → ファネル更新 から選んでください")
        print("   (live 判定は過去の販売実績が見えず、需要のある出品を CULL と誤判定します)")
        return

    # 古い funnel を小分け処理する間に補充された listing を誤取下げしないよう、
    # End 直前に現eBay qty を実機確認 (fail-closed: qty>0/不明は除外)。
    # CULL_NO_VERIFY=1 で明示スキップ可 (緊急時/オフライン)。
    if os.environ.get("CULL_NO_VERIFY") == "1":
        print("  ※ CULL_NO_VERIFY=1: 現eBay在庫の実機確認をスキップ")
    else:
        sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "iMakeBayAPI")))
        try:
            from ebay_getitem_images import fetch_listing_qty, fetch_listing_status
        except Exception as e:
            sys.exit(f"在庫検証モジュール読込失敗のため中止 (fail-closed): {e}\n"
                     "  → どうしても検証なしで進めるなら CULL_NO_VERIFY=1")
        print(f"  現eBay状態を実機確認中 ({len(picked)}件, 終了済/qty>0/不明は除外)...",
              flush=True)
        picked, revived, ended, failed = verify_oos(picked, fetch_listing_qty,
                                                    fetch_listing_status)
        if ended:
            print(f"  ⏭ 既に終了済みで除外 = {len(ended)}件 (前回までに End 済)")
        if revived:
            print(f"  ⚠ 在庫復活で除外 = {len(revived)}件 (補充された listing の誤取下げ防止)")
            for r in revived:
                print(f"     復活: {r['item_id']} {(r.get('title') or '')[:45]}")
        if failed:
            print(f"  ⚠ qty取得失敗で除外 (fail-closed) = {len(failed)}件")
        print(f"  → End 確定 (qty=0 実機確認済) = {len(picked)}件")
        if not picked:
            print("実機確認後の End 対象なし。処理終了。")
            return

    stamp = datetime.date.today().strftime("%Y%m%d")
    os.makedirs(END_DIR, exist_ok=True)
    end_path = os.path.join(END_DIR, f"cull_end_{stamp}.csv")
    with open(end_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(END_HEADER)
        for r in picked:
            w.writerow(["End", r["item_id"], END_CODE])

    cand_path = os.path.join(DESK, f"CULL出品停止候補_{stamp}.csv")
    fields = ["item_id", "title", "site", "category", "price", "age_days", "watch", "ebay_url"]
    with open(cand_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in picked:
            w.writerow(r)

    print(f"\nEnd CSV (eBayアップで取下げ): {end_path}")
    print(f"確認用一覧: {cand_path}")
    print(f"\n▶ End CSV を eBay FileExchange に手動アップ → {len(picked)}件 終了")
    print(f"▶ 残りは レポート再DL → ファネル再実行 → 本ツール再走 で段階的に (1回{CAP}件まで)")
    print("※ 在庫切れ(qty=0)=購入不可なので急がなくてよい。誤判定混入を避け少量ずつ。")


if __name__ == "__main__":
    main()
