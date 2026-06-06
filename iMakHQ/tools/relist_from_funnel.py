#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取下再出品 ①取下げ: ファネルの RELIST候補(NO_SEARCH+NO_CLICK)を上位10件 End CSV 化。

旧 dump_us_qty1_sku(snapshot方式・Selenium 10分)を置換。snapshot 不要 —
最新 funnel_*.csv の flags に RELIST が立つ行を価格降順で読み、上位 CAP 件を取下げ対象に。

取下再出品の半自動化フロー (2026-06-05 確定・3コマンド):
  ① 取下げ(ここ): RELIST上位10 → End CSV + 保留リスト保存
  ② 再出品:        保留リスト → スプシB列空欄化 → 出品くん即live → Add CSV
  ③ 書戻し:        ACTIVEレポート → SKU照合 → スプシB列に新ItemID上書き

出力:
  1. End CSV (eBay FileExchange Action=EndItem) → c:/dev/iMak_data/revise/。eBay にアップ=取下げ
  2. 保留リスト relist_pending_<stamp>.csv → c:/dev/iMak_data/revise/。
     「取下げた10」を②③が参照する行固定キー (sku/old_item_id/category/supply_url/price/title)。
     supply_url(=スプシA列・仕入元URL) が ②再出品・③書戻しの不変アンカー。
  3. 候補一覧CSV → デスクトップ (確認用)

安全策: supply_url(行固定キー) が欠落した RELIST 行は ②③ で追えない (writeback不能) ため
取下げ対象から除外し、除外件数をログ明示する (silent cap 禁止)。
watcher有は RELIST に含まれない(タイトル編集等 in-place 対応)。
"""
import csv
import datetime
import glob
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FUNNEL_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
END_DIR = r"C:\dev\iMak_data\revise"
END_HEADER = ["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)", "ItemID", "EndCode"]
END_CODE = "OtherListingError"  # Cassini reset 目的の汎用 code (seller_hub_relist と統一)
CAP = 10  # 1バッチ=10件 (ユーザー指示 2026-06-05)。少量ずつ取下→再出品→書戻しを回す


def sku_from_url(url: str) -> str:
    """仕入元URL → listing が付与する Custom Label(SKU) を best-effort 再現。

    listing script (gshock_to_csv.py:1515-1527 / montbell・tshirt・ichibankuji・psa) と
    同じパターン規約:
      - Amazon ASIN:   /dp/XXXXXXXXXX (10文字)  → ASIN
      - Mercari itemID: /item/m+数字            → m<id>
      - それ以外:       末尾12文字 fallback
    casio.com は型番(build_row の model_official)で URL から導けない → 末尾12にフォール
    バック(正確には ②再出品で出品くんが生成する Add CSV の CustomLabel が権威。①は best-effort)。

    ③書戻しで ACTIVEレポート Custom Label と照合する不変キー。
    """
    if not url:
        return ""
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    if m:
        return m.group(1)
    m = re.search(r"/item/(m\d+)", url)
    if m:
        return m.group(1)
    cleaned = url.split("?")[0].split("#")[0].rstrip("/")
    return cleaned[-12:].lstrip("/")


def relist_candidates(rows):
    """funnel CSV rows から RELIST フラグ行 (NO_SEARCH+NO_CLICK) を抽出。"""
    return [r for r in rows if "RELIST" in (r.get("flags") or "").split("|")]


def load_relisted_history():
    """過去に**実際に再出品が完了した** supply_url の集合 = relist_history.csv。

    履歴は③書戻し(relist_writeback)成功時に追記される(=実際にlive化し新itemID書込が
    確定したものだけ)。skumapは②(Add生成)時点で書かれ「やった」止まりなので履歴源に
    しない(②だけ回して未アップ=未relistを誤って2回目扱いする事故を防ぐ)。
    """
    history = set()
    path = os.path.join(END_DIR, "relist_history.csv")
    if not os.path.exists(path):
        return history
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fp:
            for r in csv.DictReader(fp):
                u = (r.get("supply_url") or "").strip()
                if u:
                    history.add(u)
    except Exception:
        pass
    return history


def split_by_history(picked, history):
    """取下げ候補を「初回(relist)」と「2回目以降(END停止)」に分ける。

    一度 relist しても再び RELIST に出る = 露出やり直しが効かなかった実証 → 出品停止。
    (仕入過高で打ち手なしのケースを、当てにならない市場中央値でなく実績で切る)
    戻り: (relist_picks 初回, end_only_picks 2回目)
    """
    relist_picks, end_only_picks = [], []
    for r in picked:
        u = (r.get("supply_url") or "").strip()
        (end_only_picks if u in history else relist_picks).append(r)
    return relist_picks, end_only_picks


def load_current_b_map():
    """両管理スプシの {supply_url(A列): 現在のB列(itemID)} を返す (再出品済み除外用)。

    DNS flakiness 対策で retry。失敗時は例外を送出 (呼出側で「不明なら走らせない」=
    二重再出品事故を防ぐため、空dictで握り潰さない)。
    """
    import time
    from relist_writeback import SHEETS, CREDS_PATH
    import gspread
    from google.oauth2.service_account import Credentials
    last_err = None
    for attempt in range(4):
        try:
            creds = Credentials.from_service_account_file(
                CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
            gc = gspread.authorize(creds)
            bmap = {}
            for cfg in SHEETS:
                ws = gc.open_by_key(cfg["id"]).get_worksheet_by_id(cfg["gid"])
                for row in ws.get_all_values():
                    url = (row[0].strip() if row and row[0] else "")
                    if url and url not in bmap:
                        bmap[url] = (row[1].strip() if len(row) > 1 else "")
            return bmap
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(3)
    raise RuntimeError(f"スプシB列読込に失敗 (retry 4回): {type(last_err).__name__}: {last_err}")


def select(rows, sheet_b_map=None, cap=CAP):
    """RELIST 候補を価格降順で上位 cap 件。再出品済み(B列変化)を自動除外。

    sheet_b_map={supply_url: 現B列} を渡すと、funnel の item_id と現B列を照合し
    **B列がfunnel itemIDのまま(=未着手)の行だけ**を対象にする。B列が変わってる
    (=③で新itemIDに書換済=再出品済) / B空 / 不一致 は除外。これで funnel を
    回し直さずに「次の10件」を出せる (バッチ進行とファネル再分析を分離)。

    戻り: (picked, total_relist, skipped_no_supply, skipped_already)。
    """
    cands = relist_candidates(rows)
    with_supply = [r for r in cands if (r.get("supply_url") or "").strip()]
    skipped_no_supply = len(cands) - len(with_supply)
    skipped_already = 0
    if sheet_b_map is None:
        eligible = with_supply
    else:
        eligible = []
        for r in with_supply:
            url = (r.get("supply_url") or "").strip()
            cur_b = (sheet_b_map.get(url) or "").strip()
            funnel_id = (r.get("item_id") or "").strip()
            if cur_b and funnel_id and cur_b == funnel_id:
                eligible.append(r)          # B列が funnel itemID のまま = 未着手
            else:
                skipped_already += 1        # B変化(再出品済)/B空/不一致 = 除外
    ordered = sorted(eligible, key=lambda x: -float(x.get("price") or 0))
    return ordered[:cap], len(cands), skipped_no_supply, skipped_already


def write_pending(picked, path):
    """保留リスト出力。②再出品・③書戻しが参照する行固定キー。

    列: sku / old_item_id / category / supply_url / price / title。
    sku = supply_url末尾12 (③書戻しで ACTIVEレポート Custom Label と照合)。
    """
    fields = ["sku", "old_item_id", "category", "supply_url", "price", "title"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        for r in picked:
            supply_url = (r.get("supply_url") or "").strip()
            w.writerow({
                "sku": sku_from_url(supply_url),
                "old_item_id": r.get("item_id", ""),
                "category": r.get("category", ""),
                "supply_url": supply_url,
                "price": r.get("price", ""),
                "title": r.get("title", ""),
            })


def main():
    files = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not files:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    src = max(files, key=os.path.getmtime)
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    print(f"対象 funnel: {os.path.basename(src)}")
    # 再出品済み除外用に現スプシB列を読む (funnel再分析せず「次の10件」を出すため)
    print("📊 スプシB列読込中 (再出品済みを自動除外)...")
    try:
        b_map = load_current_b_map()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"⚠ {e}\n  → 再出品済みの判定ができないため中断 (二重再出品事故防止)。再実行してください。")
    picked, total_relist, skipped_no_supply, skipped_already = select(rows, sheet_b_map=b_map)
    print(f"RELIST候補(NO_SEARCH+NO_CLICK) = {total_relist}件 → 取下げ {len(picked)}件 (価格高い順・上限{CAP})")
    if skipped_already:
        print(f"  ✓ 再出品済み(B列更新済)を除外 = {skipped_already}件 → 同じfunnelで次の10件を出力")
    if skipped_no_supply:
        print(f"  ⚠ supply_url(仕入元URL)欠落で除外 = {skipped_no_supply}件 (②再出品/③書戻しで追えないため対象外)")
    if not picked:
        print("候補なし(未着手の supply_url 有 RELIST が0件)。全消化済 or ファネル再分析が必要。")
        return

    # 初回(relist) と 2回目以降(END停止) に振り分け。
    # 一度relistしても再びRELISTに出る = 露出やり直しが効かなかった = 仕入過高等で打ち手なし → END。
    history = load_relisted_history()
    relist_picks, end_only_picks = split_by_history(picked, history)
    print(f"  内訳: 初回(relist) {len(relist_picks)}件 / 2回目以降(END停止) {len(end_only_picks)}件")
    if end_only_picks:
        print("  ⛔ 2回目以降 (relist済だが再度RELIST → 効果なし → 出品停止):")
        for r in end_only_picks:
            print(f"     - {r.get('item_id','')}  {(r.get('title','') or '')[:45]}")

    stamp = datetime.date.today().strftime("%Y%m%d")
    os.makedirs(END_DIR, exist_ok=True)

    # 1) End CSV (eBay FileExchange) = 初回+2回目 すべて取下げ
    end_path = os.path.join(END_DIR, f"relist_end_{stamp}.csv")
    with open(end_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(END_HEADER)
        for r in picked:
            w.writerow(["End", r["item_id"], END_CODE])

    # 2) 保留リスト (②③の参照元) = 初回のみ (2回目は再出品しない=停止)
    pending_path = os.path.join(END_DIR, f"relist_pending_{stamp}.csv")
    write_pending(relist_picks, pending_path)

    # 2b) 停止リスト (2回目以降=relist打ち切り。記録用)
    if end_only_picks:
        stop_path = os.path.join(END_DIR, f"relist_stopped_{stamp}.csv")
        write_pending(end_only_picks, stop_path)
        print(f"停止リスト (2回目以降・記録): {stop_path}")

    # 3) 候補一覧 (デスクトップ・確認用) — ロック中(Excel/OneDrive)でも End/pending は死守
    cand_path = os.path.join(DESK, f"取下再出品候補_{stamp}.csv")
    fields = ["item_id", "title", "site", "category", "price", "watch", "flags", "supply_url", "ebay_url"]
    try:
        with open(cand_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in picked:
                w.writerow(r)
    except PermissionError:
        cand_path = "(スキップ: デスクトップの同名ファイルがロック中。End/保留リストは出力済)"

    print(f"\nEnd CSV (eBayアップで取下げ・{len(picked)}件): {end_path}")
    print(f"保留リスト (②再出品・初回{len(relist_picks)}件): {pending_path}")
    print(f"候補一覧(確認用): {cand_path}")
    print(f"\n▶ ① 取下げ: End CSV を eBay FileExchange にアップ → {len(picked)}件 終了")
    if relist_picks:
        print(f"▶ ② 再出品: ②ボタンで 初回 {len(relist_picks)}件 を即live再出品 (2回目以降{len(end_only_picks)}件は再出品しない=停止)")
    else:
        print(f"▶ ② 再出品: 今回は初回0件 → 再出品なし (全{len(end_only_picks)}件が2回目以降=停止のみ)")
    print("▶ ③ 書戻し: ③ボタンで Add結果→スプシB列に新ItemID")
    print("※ watcher有は候補外 / 2回目以降は relist打ち切り(効果なし実証)")

    # 進捗ダッシュボード更新 (全体像可視化・非致命)。読込済の rows/b_map を再利用
    try:
        import relist_dashboard as rd
        drows, dsummary = rd.build_rows(rows, b_map)
        rd.write_dashboard(drows, dsummary, os.path.basename(src))
        print(f"\n📋 進捗スプシ更新: タブ「{rd.DASH_TAB}」"
              f"(総数{dsummary['total']}/✅済{dsummary['done']}/⏳未{dsummary['todo']}・あと{-(-dsummary['todo']//CAP)}バッチ)")
    except Exception as _e:  # noqa: BLE001
        print(f"\n⚠ 進捗スプシ更新スキップ: {type(_e).__name__}: {_e}")


if __name__ == "__main__":
    main()
