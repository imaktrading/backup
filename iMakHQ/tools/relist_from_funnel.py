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
import shutil
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

# 在庫ゲート (2026-06-23): 管理スプシの監視くん列を読んで「仕入不可(3RD/OOS)」を再出品しない。
# funnel の露出シグナル(NO_CLICK)だけでは在庫を見ておらず、古い funnel で 3RD 化済の商品を
# 再出品 → キャンセル → BAN リスク だった (B0B78CZ3W3 事故 2026-06-23)。真実源は監視くんが
# スプシに書く「売り切れ」列。relist はこれに従う (fail-closed: ○/古い/行無し → 出さない)。
SOLD_OUT_COL = 3      # D列「売り切れ」: ○/〇 = 監視くんが OOS 判定済
CHECK_TIME_COL = 14   # O列「売り切れチェック時間」: 監視くんの最終在庫確認日時
CATEGORY_COL = 17     # R列「カテゴリ」: 商品の正本カテゴリ (G-shock/リール/一番くじ/バッグ/tomica/Tシャツ/フィギュア…)。② 振り分けの正本
SOLD_OUT_MARKS = ("○", "〇")  # ○=U+25CB / 〇=U+3007 両方 OOS 扱い
STOCK_FRESH_HOURS = 48  # 在庫確認の鮮度しきい値。これより古い=監視くんが最近見てない=不明→出さない
MIOKURI_B = "9999"  # 見送りマーカー: B列=9999 は「出品しない」確定(女性物等)。①再出品も通常出品も対象外。
                    # eBay未出品なのにスプシB列が死IDだと スプシ≠eBay になるのを、実IDでない 9999 で表現(2026-06-28)


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


# 取下げ再出品フローに乗せないカテゴリ (独立パイプラインが専任管轄)。
# CCG=PSA TCG は psa_to_csv(新規)/psa_resource_gate→psa_restock_*(再仕入れ) が専任。
# relist 候補から完全除外 = ダッシュボードにも出さない・取下げもしない (2026-06-23 ユーザー指示)。
EXCLUDED_CATEGORIES = {"CCG Individual Cards"}


def relist_candidates(rows):
    """funnel CSV rows から RELIST フラグ行 (NO_SEARCH+NO_CLICK) を抽出。

    EXCLUDED_CATEGORIES (PSA TCG 等の独立パイプライン管轄) は候補から完全除外する。
    """
    return [r for r in rows
            if "RELIST" in (r.get("flags") or "").split("|")
            and (r.get("category") or "").strip() not in EXCLUDED_CATEGORIES]


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


def load_relist_times():
    """relist_history.csv → {ASIN/SKU: 最新の処理日時(文字列)} (ダッシュボードのアイテム毎 処理日時用)。

    history は append-only なので同 ASIN は後勝ち(=最新の再出品時刻)。date列は date-only/
    datetime 混在可 (2026-06-23 datetime化)。空/読込失敗は空dict。
    """
    times = {}
    path = os.path.join(END_DIR, "relist_history.csv")
    if not os.path.exists(path):
        return times
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fp:
            for r in csv.DictReader(fp):
                u = (r.get("supply_url") or "").strip()
                d = (r.get("date") or "").strip()
                if u and d:
                    times[sku_from_url(u)] = d   # 後勝ち=最新
    except Exception:
        pass
    return times


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


def parse_check_time(s):
    """監視くんの「売り切れチェック時間」(YYYY/M/D H:MM:SS, 桁数まちまち) → datetime or None。"""
    s = (s or "").strip()
    if not s:
        return None
    try:
        date_part, _, time_part = s.partition(" ")
        y, mo, d = (int(x) for x in date_part.split("/"))
        hh = mm = ss = 0
        if time_part:
            parts = time_part.split(":")
            hh = int(parts[0]); mm = int(parts[1]) if len(parts) > 1 else 0
            ss = int(parts[2]) if len(parts) > 2 else 0
        return datetime.datetime(y, mo, d, hh, mm, ss)
    except (ValueError, IndexError):
        return None


def stock_verdict(entry, now, fresh_hours=STOCK_FRESH_HOURS):
    """在庫ゲート判定 (純粋)。戻り: 'OK' | 'SOLD_OUT' | 'NO_ROW'。

    2026-06-28 ユーザー判断: 監視くんの在庫鮮度(>48h)で除外しない。スプシの売り切れ列を見て
    判断する。現世代の取下再出品を完了させる(次世代へ進む)ことを優先。鮮度ゲートが STALE で
    大半を止め、世代が永久に終わらないのを解消。
      - NO_ROW : スプシに行が無い → 在庫不明(売り切れ列すら見れない)→ 出さない
      - SOLD_OUT: スプシ「売り切れ」○ → OOS → 出さない(これは維持=売り切れ再出品でBAN防止)
      - OK     : 行あり & 売り切れでない → last-known 在庫で出す(鮮度は問わない)
    ※rsk: 監視くんが未確認で実は売切の場合 last-known で出る。売り切れ列が真実源(ユーザー合意)。
    """
    if not entry:
        return "NO_ROW"
    if entry.get("sold_out"):
        return "SOLD_OUT"
    return "OK"   # 鮮度(check_time)では除外しない(2026-06-28 設計変更)


def load_sheet_index():
    """両管理スプシ → {ASIN/SKU(sku_from_url(A列)): {b, sold_out, check_time, category}} 。

    監視くんが書く 売り切れ[D] / 売り切れチェック時間[O] + カテゴリ列[R=col17] を取り込む。
    category(col17) は ② の振り分け+カテゴリゲートの正本 (funnel の eBay カテゴリは混在して
    信頼できないため。2026-06-23)。照合キーは ASIN (coliid 揺れ吸収)。DNS flakiness 対策 retry。
    失敗時は例外送出 (二重再出品/在庫不明での誤再出品を防ぐため空dictで握り潰さない)。
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
            index = {}
            for cfg in SHEETS:
                ws = gc.open_by_key(cfg["id"]).get_worksheet_by_id(cfg["gid"])
                for row in ws.get_all_values():
                    url = (row[0].strip() if row and row[0] else "")
                    if not url:
                        continue
                    key = sku_from_url(url)               # ASIN/SKU = 不変キー
                    if not key or key in index:           # 先勝ち (同ASIN重複は最初の行)
                        continue
                    sold = (row[SOLD_OUT_COL].strip() if len(row) > SOLD_OUT_COL else "")
                    chk = (row[CHECK_TIME_COL].strip() if len(row) > CHECK_TIME_COL else "")
                    cat = (row[CATEGORY_COL].strip() if len(row) > CATEGORY_COL else "")
                    index[key] = {
                        "b": (row[1].strip() if len(row) > 1 else ""),
                        "sold_out": sold in SOLD_OUT_MARKS,
                        "check_time": parse_check_time(chk),
                        "category": cat,
                    }
            return index
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(3)
    raise RuntimeError(f"スプシ読込に失敗 (retry 4回): {type(last_err).__name__}: {last_err}")


def load_current_b_map():
    """{ASIN/SKU: 現在のB列(itemID)} を返す (再出品済み除外用)。load_sheet_index の射影。

    ASINキー化 (2026-06-23): A列フルURLでなく sku_from_url(A列) をキーに (coliid 揺れ吸収)。
    select/build_rows も sku_from_url(supply_url) で引くので両端でキーが揃う。
    """
    return {k: v["b"] for k, v in load_sheet_index().items()}


def select(rows, sheet_b_map=None, cap=CAP, stock_index=None, now=None,
           fresh_hours=STOCK_FRESH_HOURS, supported_categories=None):
    """RELIST 候補を価格降順で上位 cap 件。再出品済み(B列変化)+仕入不可(在庫切れ)+②未対応カテゴリを自動除外。

    sheet_b_map={ASIN/SKU: 現B列} (load_current_b_map の戻り) を渡すと、funnel の
    item_id と現B列を照合し **B列がfunnel itemIDのまま(=未着手)の行だけ**を対象にする。
    B列が変わってる (=③で新itemIDに書換済=再出品済) / B空 / 不一致 は除外。これで funnel を
    回し直さずに「次の10件」を出せる (バッチ進行とファネル再分析を分離)。

    stock_index={ASIN/SKU: {sold_out, check_time}} (load_sheet_index の戻り) を渡すと、
    **在庫ゲート**を適用 (2026-06-23)。監視くんが「売り切れ」○ / チェックが古い(>fresh_hours) /
    スプシ行無し は仕入不可とみなし再出品しない (fail-closed)。古い funnel が 3RD 化済商品を
    拾う事故 (B0B78CZ3W3) を構造的に防ぐ。now 省略時は実行時刻。

    supported_categories (集合) を渡すと **カテゴリゲート** (2026-06-23)。②再出品が対応する
    **商品管理シートのカテゴリ列(col17)** 以外は取り下げない。①でEndしても②が再出品できない
    カテゴリを取り下げる=「取下げたのに再出品されない」silent gap を防ぐ (PSAカード事故)。
    判定は funnel の eBay カテゴリでなく stock_index 由来の col17 (funnel カテゴリは混在して
    信頼できない。例 "Other Animation Merchandise"=グッズ+一番くじ)。stock_index 必須。

    各 picked 行に "_master_category"(col17) を付与 → write_pending が ② の振り分けキーに使う。

    照合キーは sku_from_url(supply_url) = ASIN/SKU。coliid 揺れで行を取りこぼさない。

    戻り: (picked, total_relist, skipped_no_supply, skipped_already, skipped_oos, skipped_unsupported)。
    """
    if now is None:
        now = datetime.datetime.now()
    cands = relist_candidates(rows)
    with_supply = [r for r in cands if (r.get("supply_url") or "").strip()]
    skipped_no_supply = len(cands) - len(with_supply)
    skipped_already = skipped_oos = skipped_unsupported = 0
    eligible = []
    for r in with_supply:
        key = sku_from_url((r.get("supply_url") or "").strip())
        entry = stock_index.get(key) if stock_index else None
        # 未着手判定 (sheet_b_map 指定時のみ): B列が funnel itemID のまま = 未着手
        if sheet_b_map is not None:
            cur_b = (sheet_b_map.get(key) or "").strip()
            funnel_id = (r.get("item_id") or "").strip()
            if cur_b == MIOKURI_B:
                skipped_already += 1        # 見送り(9999)=恒久対象外。再ピックしない
                continue
            if not (cur_b and funnel_id and cur_b == funnel_id):
                skipped_already += 1        # B変化(再出品済)/B空/不一致 = 除外
                continue
        # カテゴリゲート: 商品管理 col17 が②対応カテゴリでなければ取り下げない
        master_cat = (entry or {}).get("category", "")
        if supported_categories is not None and master_cat not in supported_categories:
            skipped_unsupported += 1
            continue
        # 在庫ゲート (仕入可否=監視くんの真実)
        if stock_index is not None and stock_verdict(entry, now, fresh_hours) != "OK":
            skipped_oos += 1                # 売り切れ/古い/行無し = 仕入不可 → 出さない
            continue
        rr = dict(r)
        rr["_master_category"] = master_cat  # ② 振り分けキー (col17)
        eligible.append(rr)                  # 未着手 かつ 対応カテゴリ かつ 仕入可能
    ordered = sorted(eligible, key=lambda x: -float(x.get("price") or 0))
    return (ordered[:cap], len(cands), skipped_no_supply, skipped_already,
            skipped_oos, skipped_unsupported)


def write_pending(picked, path):
    """保留リスト出力。②再出品・③書戻しが参照する行固定キー。

    列: sku / old_item_id / category / supply_url / price / title。
    sku = supply_url末尾12 (③書戻しで ACTIVEレポート Custom Label と照合)。
    category は **商品管理 col17 (_master_category)** を採用 (②の振り分け正本)。select 経由でない
    呼出 (テスト等) は funnel category にフォールバック。
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
                "category": r.get("_master_category") or r.get("category", ""),
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
    # 再出品済み除外 + 在庫ゲート用にスプシを読む (B列 + 監視くんの売り切れ/チェック時間)
    print("📊 スプシ読込中 (再出品済み除外 + 在庫ゲート: 監視くん『売り切れ』に従う)...")
    try:
        stock_index = load_sheet_index()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"⚠ {e}\n  → 再出品済み/在庫の判定ができないため中断 (二重再出品・仕入不可再出品の防止)。再実行してください。")
    b_map = {k: v["b"] for k, v in stock_index.items()}
    # ②が再出品できるカテゴリのみ取り下げる (取下げ→再出品漏れ防止)。dispatch を単一の正本に。
    try:
        import relist_add_from_pending as rap
        supported = set(rap.CATEGORY_DISPATCH.keys())
    except Exception:  # noqa: BLE001
        supported = {"Wristwatches", "Reels"}
    picked, total_relist, skipped_no_supply, skipped_already, skipped_oos, skipped_unsupported = select(
        rows, sheet_b_map=b_map, stock_index=stock_index, supported_categories=supported)
    print(f"RELIST候補(NO_SEARCH+NO_CLICK) = {total_relist}件 → 取下げ {len(picked)}件 (価格高い順・上限{CAP})")
    if skipped_already:
        print(f"  ✓ 再出品済み(B列更新済)を除外 = {skipped_already}件 → 同じfunnelで次の10件を出力")
    if skipped_oos:
        print(f"  🔴 仕入不可で除外 = {skipped_oos}件 (監視くん『売り切れ』○ / 在庫確認が古い(>{STOCK_FRESH_HOURS}h) / スプシ行無し = fail-closed)")
    if skipped_unsupported:
        print(f"  ⛔ ②未対応カテゴリで除外 = {skipped_unsupported}件 (取り下げない=再出品漏れ防止。TCG等は専用パイプラインで対応) 対応={sorted(supported)}")
    if skipped_no_supply:
        print(f"  ⚠ supply_url(仕入元URL)欠落で除外 = {skipped_no_supply}件 (②再出品/③書戻しで追えないため対象外)")
    if not picked:
        print("候補なし(未着手 かつ 仕入可能な RELIST が0件)。全消化済 / 在庫切れ / ファネル再分析が必要。")
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

    # ①②CSVを1フォルダに集約(煩雑解消・2026-06-28)。日付+時刻で一意=1日複数バッチでも混ざらない。
    # ① は End CSV をここに格納し、② がこの最新フォルダに Add CSV を足す(アップは1箇所で済む)。
    up_dir = os.path.join(END_DIR, "UP_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(up_dir, exist_ok=True)
    shutil.copy(end_path, up_dir)

    # 候補確認はスプシ「取下再出品」タブで見る (デスクトップCSV出力は廃止 2026-06-07)

    print(f"\n📁 集約フォルダ: {up_dir} (End CSV 格納済。②が Add を同フォルダに追加)")
    print(f"End CSV (eBayアップで取下げ・{len(picked)}件): {end_path}")
    print(f"保留リスト (②再出品・初回{len(relist_picks)}件): {pending_path}")
    print(f"\n▶ ① 取下げ: End CSV を eBay FileExchange にアップ → {len(picked)}件 終了")
    if relist_picks:
        print(f"▶ ② 再出品: ②ボタンで 初回 {len(relist_picks)}件 を即live再出品 (2回目以降{len(end_only_picks)}件は再出品しない=停止)")
    else:
        print(f"▶ ② 再出品: 今回は初回0件 → 再出品なし (全{len(end_only_picks)}件が2回目以降=停止のみ)")
    print("▶ ③ 書戻し: ③ボタンで Add結果→スプシB列に新ItemID")
    print("※ watcher有は候補外 / 2回目以降は relist打ち切り(効果なし実証)")

    # 進捗ダッシュボード更新 (全体像可視化・非致命)。読込済の rows/b_map/stock_index を再利用
    try:
        import relist_dashboard as rd
        drows, dsummary = rd.build_rows(rows, b_map, stock_index=stock_index,
                                        times_map=load_relist_times())
        rd.write_dashboard(drows, dsummary, os.path.basename(src))
        print(f"\n📋 進捗スプシ更新: タブ「{rd.DASH_TAB}」"
              f"(総数{dsummary['total']}/✅済{dsummary['done']}/⏳未{dsummary['todo']}/🔴在庫切れ{dsummary['oos']}・あと{-(-dsummary['todo']//CAP)}バッチ)")
    except Exception as _e:  # noqa: BLE001
        print(f"\n⚠ 進捗スプシ更新スキップ: {type(_e).__name__}: {_e}")


if __name__ == "__main__":
    main()
