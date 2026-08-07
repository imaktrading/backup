"""monitor_listings - HIGH/LOW 商品管理シート専用の在庫監視 (Phase 2).

対象スプシ (Takaaki さん確定 2026-04-29):
  - HIGH: 19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk (約 421 商品)
  - LOW : 1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0 (約 650 商品)
  - 共通 gid: 851100680 (商品管理シート タブ)

スプシ構造:
  A: URL (Mercari/Amazon)
  B: itemID (eBay)
  C: タイトル
  D: 売り切れ ← 本ツールが "○" を書き込む
  ...
  O: 売り切れチェック時間 ← 本ツールが timestamp を書き込む

注: 在庫管理スプシ (101KL6...) は別運用 (バリエ/バンドル特殊管理用)。
本ツールが対象とするのは HIGH/LOW (通常出品) のみ。

実行:
  python monitor_listings.py --sheet high --dry-run --limit 50    # HIGH 最初 50 行 dry-run
  python monitor_listings.py --sheet high                          # HIGH 全件 LIVE
  python monitor_listings.py --sheet both                          # HIGH + LOW 全件
  python monitor_listings.py --sheet high --start 100 --end 150    # 特定行範囲

在庫判定:
  - mercari_scraper / amazon_scraper の `in_stock` フィールドを判定基準とする
  - 取得失敗 (None) → fail-closed: 「自動 ○ 化しない」(=既存 D 列値を維持)
  - 仕入元在庫切れ → D="○" を書く
  - 仕入元在庫あり → D="" にリセット (人手 "○" を上書きする可能性に注意)

Phase 3 連携: 本ツールが書いた "○" を読み取って Revise CSV を生成する。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# 同階層モジュール import
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sheet_updater import (  # noqa: E402
    HIGH_SHEET_ID,
    LOW_SHEET_ID,
    LISTINGS_GID,
    LISTINGS_COL_PRICE_NOW_M,
    LISTINGS_COL_PRICE_NOW,
    PRICE_SURGE_THRESHOLD,
    _col_letter,
    open_sheet_by_id,
    get_listings_worksheet,
    read_listings_rows,
    update_listings_sold_marks,
    paint_backup_url_cells,
    clear_sold_backup_cells,
    ensure_sold_at_header,
    append_rescue_log_rows,
    detect_supplier,
    _domain_of,
    ensure_listings_err_header,
    is_one_off_url,
)
from err_flag import (  # noqa: E402
    build_err_marker, marker_count, PERSISTENT_THRESHOLD, DEAD_SOURCE_THRESHOLD,
)
from scrapers.mercari_scraper import fetch_product_inventory as fetch_mercari  # noqa: E402
from scrapers.mercari_scraper import create_driver as create_mercari_driver  # noqa: E402
from scrapers.amazon_scraper import fetch_product_inventory as fetch_amazon  # noqa: E402
from scrapers.amazon_scraper import create_amazon_driver  # noqa: E402
from scrapers.fril_scraper import fetch_product_inventory as fetch_fril  # noqa: E402
from scrapers.snkrdunk_scraper import fetch_product_inventory as fetch_snkrdunk  # noqa: E402

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DECISION_LOG_DIR = SCRIPT_DIR / "decision_log"
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Mercari/Amazon 1 リクエストごとの sleep 秒 (anti-bot 対策)
DEFAULT_SLEEP_SEC = 2
# Mercari driver の連続 None で driver を再起動する閾値 (anti-bot 復帰試行)
# Phase 9: 旧 MAX_CONSEC_FAILURES (=8) で全 supplier 早期 abort していたが、
# 漏れ NG 原則のため abort 廃止し、driver 再起動 + ループ続行で全件処理する
# 2026-06-11: 5→3 に低下。 巡回深度で driver が疲弊し localhost ReadTimeout が cluster
# する事象 (rows 747-757 等) で、 5 連続待ち = 約10分 + 5行 unknown を浪費していた。
# 3 に下げて自己修復を速め、 浪費を約4分 + 2行に圧縮する。
MERCARI_RESTART_THRESHOLD = 3

# 2026-06-25: amazon driver も連続 crash で自動再起動する (旧: mercari のみ再起動ありで
# amazon は無再起動 = driver セッション死後に残り全行が盲目化した)。
# 2026-06-23 06:30 LOW cycle で amazon driver が InvalidSessionIdException で死亡 →
# row418〜831 (396行) が 6 秒で全滅 = 1 cycle 盲目 (一過性で翌 cycle 回復したが、
# 持続したら mercari 297 連続失敗事故 [[driver_restart_trigger_extended]] と同型)。
AMAZON_RESTART_THRESHOLD = 3

# 予防的 driver 再起動: mercari の実 scrape をこの件数こなすごとに driver をリサイクルする
# (= 疲弊する前に refresh)。 ReadTimeout cluster は「累積作業で driver がへたる」のが主因なので、
# 反応的再起動 (連続失敗で復旧) より根本的。 0 で無効化。 1 件 ~10-20s の restart コスト。
MERCARI_PREVENTIVE_RESTART_EVERY = 150


def _log_path() -> Path:
    return LOG_DIR / f"listings_{datetime.now().strftime('%Y-%m-%d')}.log"


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(_log_path(), "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================================
# 1 行 (1 listing) の在庫チェック
# ============================================================================
# ── ヨドバシ在庫スナップショット (Harvest 供給、2026-07-26) ────────────────────
# G-shock 補仕入元。Harvest が LOW cycle 直前に HTTP(requests+bs4) で全型番の在庫+価格を snapshot 化
# (Selenium 不要・Akamai challenge 無を Harvest 実測)。監視くんは型番(AI列)で JSON を lookup するだけ =
# cycle 負荷ゼロ。snkrdunk listing_live_price と同型。fail-closed: 欠損/古い/型番無 → uncertain(min対象外)。
YODOBASHI_SNAPSHOT_PATH = Path(r"C:\dev\iMak_data\harvest\yodobashi_stock_snapshot.json")
YODOBASHI_SNAPSHOT_MAX_AGE_H = 12   # generated_at がこれ超に古い → 使わない (fail-closed)
_yodo_snap_cache: dict = {}         # {"loaded":bool, "data":dict|None} (cycle 内 1 回 load)


def _load_yodobashi_snapshot():
    """ヨドバシ在庫 snapshot を load (cycle 内キャッシュ)。古い/欠損なら None (= 全 lookup uncertain)."""
    if _yodo_snap_cache.get("loaded"):
        return _yodo_snap_cache.get("data")
    data = None
    try:
        if YODOBASHI_SNAPSHOT_PATH.exists():
            raw = json.loads(YODOBASHI_SNAPSHOT_PATH.read_text(encoding="utf-8"))
            gen = raw.get("generated_at")
            fresh = False
            if gen:
                try:
                    dt = datetime.fromisoformat(gen)
                    ref = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
                    fresh = (ref - dt).total_seconds() / 3600.0 <= YODOBASHI_SNAPSHOT_MAX_AGE_H
                except Exception:
                    fresh = False
            if fresh:
                data = {k: v for k, v in raw.items() if k != "generated_at"}
    except Exception:
        data = None
    _yodo_snap_cache["loaded"] = True
    _yodo_snap_cache["data"] = data
    _yodo_snap_cache.pop("url_index", None)   # snapshot が変われば URL 逆引き index も作り直す
    return data


def _yodobashi_url_key(url: str) -> str:
    """ヨドバシ URL から突合キーを作る (表記ゆれで外さないための正規化)。

    canonical な productId (`/product/<digits>/`) を優先。取れなければ scheme/www/クエリ/
    末尾スラッシュを落とした小文字 URL を使う。空文字は「キー無し」= 突合しない。
    """
    u = (url or "").strip()
    if not u:
        return ""
    m = re.search(r"/product/(\d+)", u)
    if m:
        return m.group(1)
    u = u.split("#", 1)[0].split("?", 1)[0].lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def _yodobashi_entry_by_url(snap: dict, url: str):
    """snapshot を URL で逆引き (AI列=型番 が空/不一致の行の救済)。無ければ None (fail-closed)。"""
    key = _yodobashi_url_key(url)
    if not key or not snap:
        return None
    index = _yodo_snap_cache.get("url_index")
    if index is None:                      # snapshot 1 回 load につき 1 回だけ構築
        index = {}
        for model, ent in snap.items():
            if not isinstance(ent, dict):
                continue
            k = _yodobashi_url_key(ent.get("url") or "")
            if k:
                index.setdefault(k, ent)
        _yodo_snap_cache["url_index"] = index
    ent = index.get(key)
    return ent if isinstance(ent, dict) else None


def _check_single_url(url: str, sleep_sec: float = DEFAULT_SLEEP_SEC,
                      mercari_driver=None, amazon_driver=None,
                      model_number: str = "") -> dict:
    """1 URL に対する scraper 呼出 + 結果 dict 返却 (純粋 helper).

    Returns: {url, supplier, is_sold (True/False/None), raw_status, error, price_jpy}
        - is_sold=False: 在庫あり (= 取下げ対象外)
        - is_sold=True : 売切 (= 取下げ候補)
        - is_sold=None : 不確定 (scraper 失敗等、error 必ず非 None)

    model_number: yodobashi 補URL の snapshot lookup キー (行の AI列=型番)。他 supplier では未使用。
    """
    domain = _domain_of(url)
    supplier = detect_supplier(domain)
    out = {"url": url, "supplier": supplier, "is_sold": None,
           "raw_status": "", "error": None, "price_jpy": None, "points_jpy": None}

    # ★ yodobashi: scraper を叩かず Harvest snapshot を lookup (fail-closed)。
    #   ① AI列(型番) で引く → ② 引けなければ **補URL 自体で逆引き** (2026-08-03 窓口 GO)。
    #   ②を足した理由: AI列は「未出品行に KEY を書くと orphan KEY になる」ため意図的に空の行が
    #   34 行あり、その行は在庫があっても永久に判定不能だった (row827/832 の実害)。
    #   snapshot は各エントリに url を持つので、AI列に一切書かずにコード側で吸収できる。
    if supplier == "yodobashi":
        snap = _load_yodobashi_snapshot()
        entry = (snap or {}).get((model_number or "").strip())
        if snap and not isinstance(entry, dict):
            entry = _yodobashi_entry_by_url(snap, url)
        if not snap or not isinstance(entry, dict):
            out["error"] = "yodobashi snapshot 欠損/古い/型番無 (fail-closed=min対象外)"
            return out
        ins = entry.get("in_stock")
        if ins is True:
            out["is_sold"] = False
            out["raw_status"] = "yodobashi_in_stock"
            p = entry.get("price_jpy")
            if isinstance(p, int) and not isinstance(p, bool) and p >= 0:
                out["price_jpy"] = p   # M-min に効かせる
        elif ins is False:
            out["is_sold"] = True
            out["raw_status"] = "yodobashi_sold"
        else:
            out["error"] = "yodobashi in_stock=None (判定不能, fail-closed)"
        return out

    if supplier == "mercari":
        try:
            info = fetch_mercari(url, driver=mercari_driver, use_selenium_fallback=False)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
            return out
    elif supplier == "amazon":
        try:
            info = fetch_amazon(url, driver=amazon_driver, use_selenium_fallback=True)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
            return out
    elif supplier == "fril":
        try:
            info = fetch_fril(url)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
            return out
    elif supplier == "snkrdunk":
        try:
            info = fetch_snkrdunk(url)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
            return out
    else:
        out["error"] = f"unsupported supplier: {supplier} ({domain})"
        return out

    time.sleep(sleep_sec)

    if info is None:
        out["error"] = "scraper returned None (fail-closed)"
        return out
    skus = info.get("skus") or []
    if not skus:
        out["error"] = "no skus returned"
        return out

    # HQ 2026-06-03 § fail-closed bug fix: skus[0]["in_stock"] が None / 欠落 →
    # is_sold=None で skip (= D 触らない)。 旧 logic: bool(... or False) で default
    # False=売切 に倒れる致命バグ (= LOW 152 件 偽 OOS の真因)。
    raw_in_stock = skus[0].get("in_stock")
    if raw_in_stock is None:
        out["error"] = "in_stock indeterminate (scraper returned dict without resolved in_stock)"
        return out
    in_stock = bool(raw_in_stock)
    out["is_sold"] = not in_stock
    out["raw_status"] = info.get("status") or ("in_stock" if in_stock else "out_of_stock")

    raw_price = skus[0].get("price_jpy")
    if isinstance(raw_price, int) and not isinstance(raw_price, bool) and raw_price >= 0:
        out["price_jpy"] = raw_price

    # 基本ポイント(円): amazon の在庫あり時のみ scraper が値 or None を返す (HQ 2026-07-22)。
    # None は「表示なし or 検証不能」= 区別は update 構築側 (fetch 成否) で行う。ここは素通し。
    raw_points = skus[0].get("points_jpy")
    if isinstance(raw_points, int) and not isinstance(raw_points, bool) and raw_points >= 0:
        out["points_jpy"] = raw_points

    return out


def check_one_row(row: dict, sleep_sec: float = DEFAULT_SLEEP_SEC,
                  mercari_driver=None, amazon_driver=None) -> dict:
    """1 listing 行の在庫状況を取得し判定結果を返す (主 URL のみ、後方互換 API).

    補仕入URL を含む短絡評価が必要な場合は check_one_row_with_fallback を使うこと。
    """
    sub = _check_single_url(row["url"], sleep_sec, mercari_driver, amazon_driver)
    return _build_row_result(row, [sub], hit_index=(0 if sub["is_sold"] is False else -1))


def check_one_row_with_fallback(row: dict, sleep_sec: float = DEFAULT_SLEEP_SEC,
                                 mercari_driver=None, amazon_driver=None) -> dict:
    """主 URL + 補仕入URL 1〜5 を全候補チェック.

    判定ルール (出品の正確性原則: Precision 100%):
        - 1 候補でも明確に在庫あり (is_sold=False) → 在庫あり判定 (最初の hit を採用)
        - 全候補売切 + error 無し → newly_sold 判定
        - error が 1 件でも残る + 全候補 in_stock=False 確認できず → uncertain (取下げ skip)

    補設定 row でも全候補を毎 cycle scrape する (= 短絡しない)。理由は AC-AG セルの色塗り
    のために各補 URL の状態を可視化するため。性能影響: backup_urls 空の row は 1 候補のまま。

    Returns: 既存 check_one_row と同じ形式 + sub_results (在庫判定用、実 URL のみ) +
             backup_slot_results (色塗り/消込用、AC-AG 固定 5 枠 positional、空枠=None)。

    ★ 2026-07-25: sub_results は「実 scrape した候補のみ」(判定ロジックは position-agnostic なので
      不変)。色塗り/消込は「どの列か」の位置が要るため backup_slot_results (len 5) を別に持つ。
      空詰め index で列を推定しない (懸念1: 穴で誤セルを消す事故を構造的に防ぐ)。
    """
    # 固定 5 枠 positional (read が付ける)。旧 backup_urls しか無い呼出には fallback で slots 化。
    slots = row.get("backup_url_slots")
    if slots is None:
        _bu = row.get("backup_urls", []) or []
        slots = list(_bu) + [None] * (5 - len(_bu))
    slots = list(slots)[:5] + [None] * max(0, 5 - len(slots))

    _model = row.get("key_number", "")   # AI列=型番 (yodobashi 補URL の snapshot lookup キー)

    # 主 URL は必ず scrape (index 0)
    main_sub = _check_single_url(row["url"], sleep_sec, mercari_driver, amazon_driver,
                                 model_number=_model)
    sub_results = [main_sub]
    hit_index = 0 if main_sub["is_sold"] is False else -1

    # 補 URL: 埋まっている枠だけ scrape。 枠位置 (0-4 = AC-AG) を保った結果を別途保持。
    backup_slot_results = []
    for slot_i, burl in enumerate(slots):
        if not burl:
            backup_slot_results.append(None)   # 空枠 (色塗り "unknown" / 消込対象外)
            continue
        sub = _check_single_url(burl, sleep_sec, mercari_driver, amazon_driver,
                                model_number=_model)
        sub_results.append(sub)
        if sub["is_sold"] is False and hit_index < 0:
            hit_index = len(sub_results) - 1   # sub_results 内の index (価格採用に使う)
        backup_slot_results.append({
            "slot": slot_i,                    # 0-4 = AC-AG (列 29+slot_i)
            "url": burl,
            "is_sold": sub["is_sold"],         # True=売切 / False=在庫あり / None=不確定
            "error": sub["error"],
        })

    result = _build_row_result(row, sub_results, hit_index=hit_index)
    result["backup_slot_results"] = backup_slot_results

    # ★ 補URL救済 signal (フック2、2026-07-25 HQ Phase1 測定用)。
    #   救済 = 主URL(A) が is_sold=True 確定 (取得成功) AND 補URL≥1本が in_stock 確定。
    #   ★ fail-closed: 主が None/error (uncertain) は救済に数えない (raw_status="in_stock@backup#N" は
    #     主 uncertain でも発火し得るため proxy に使わず、main_sub.is_sold を直接判定)。
    #   通常在庫 (主 in_stock) は救済でない (主が死んだ時のみ)。
    main_is_sold = (main_sub["is_sold"] is True)
    alive_backups = [s for s in backup_slot_results if s and s.get("is_sold") is False]
    result["rescued"] = bool(main_is_sold and alive_backups)
    if result["rescued"]:
        saver = alive_backups[0]   # 最初の生存補 (= 延命した URL)
        result["rescue_detail"] = {
            "backup_slot": saver["slot"],                       # 0-4 = AC-AG
            "backup_url":  saver["url"],
            "main_status": main_sub["raw_status"] or "out_of_stock",
        }
    return result


def _build_row_result(row: dict, sub_results: list, hit_index: int) -> dict:
    """sub_results 群から row 単位の最終結果 dict を組み立てる.

    Args:
        sub_results: _check_single_url の出力 list (1 件以上)
        hit_index:   短絡 hit した sub の index (= 在庫あり)、-1 なら短絡なし
    """
    main_sub = sub_results[0]
    if hit_index >= 0:
        # 在庫あり確定 (短絡 hit)
        hit = sub_results[hit_index]
        is_sold = False
        error = None
        if hit_index == 0:
            raw_status = hit["raw_status"] or "in_stock"
        else:
            raw_status = f"in_stock@backup#{hit_index} ({hit['raw_status'] or 'in_stock'})"
        # ★ 2026-07-26 HQ依頼: M(価格) は「在庫あり かつ 価格取得できた候補の min」= 実効仕入れ値 (今買える
        #   最安の生きた供給)。旧実装は「順序上最初の在庫あり」1本で、主売切+複数補が別価格生存時に最安を
        #   採らず N(仕入れ値) が過大/過小になる GAP があった。在庫判定(取下げ可否)は hit_index のまま不変
        #   (=1本でも在庫あり→取下げない)。判定と価格採用を分離。
        #   ★K(points)整合: min を採った "同一URL" の points を使う (別URLのM − 別URLのpt で N過小になる
        #   落とし穴を回避)。amazon 以外 points=None は従来どおり (caller が amazon 行のみ K 書込)。
        _priced_live = [s for s in sub_results
                        if s.get("is_sold") is False
                        and isinstance(s.get("price_jpy"), int)
                        and not isinstance(s.get("price_jpy"), bool)
                        and s.get("price_jpy") >= 0]
        if _priced_live:
            _cheapest = min(_priced_live, key=lambda s: s["price_jpy"])
            price_jpy = _cheapest["price_jpy"]
            points_jpy = _cheapest.get("points_jpy")
        else:
            # 在庫ありだが価格取得できた候補ゼロ (snkrdunk は is_listing_live で価格なし等) → M 不触 (fail-closed)
            price_jpy = None
            points_jpy = None
    else:
        # 短絡 hit なし: 全候補 is_sold=True (全部売切) or error 含む
        has_error = any(s["error"] for s in sub_results)
        all_sold_clean = all(s["is_sold"] is True for s in sub_results)
        if all_sold_clean and not has_error:
            is_sold = True
            error = None
            n = len(sub_results)
            raw_status = f"all_sold ({n}/{n})" if n > 1 else (main_sub["raw_status"] or "out_of_stock")
            # 全部売切 → 価格は意味ないが、主 URL の最終価格を残す
            price_jpy = main_sub["price_jpy"]
            points_jpy = None  # 売切は K 触らない (price と同様)
        else:
            # error 含む → 不確定 (Precision 100%、取下げ skip)
            is_sold = None
            err_count = sum(1 for s in sub_results if s["error"])
            n = len(sub_results)
            if n == 1:
                error = main_sub["error"] or "unknown"
            else:
                # 複数候補で 1 つ以上エラー → 主 URL のエラーを優先表示
                first_err = next((s["error"] for s in sub_results if s["error"]), None)
                error = f"uncertain: {err_count}/{n} candidates errored ({first_err})"
            raw_status = ""
            price_jpy = None
            points_jpy = None  # 不確定は K 触らない (fail-closed)

    result = {
        "row_index":         row["row_index"],
        "url":               row["url"],
        "item_id":           row.get("item_id", ""),
        "title":             row.get("title", ""),
        "supplier":          main_sub["supplier"],
        "is_sold":           is_sold,
        "raw_status":        raw_status,
        "current_sold":      row.get("current_sold", ""),
        "delta":             "uncertain",
        "error":             error,
        "price_jpy":         price_jpy,
        "points_jpy":        points_jpy,   # 基本ポイント(円): amazon 在庫あり時のみ int、他 None
        "candidates_checked": len(sub_results),
        # AH 列 (前期 N) 用: read 時に取得した N 列値を引き継ぐ。書込時にここを AH へコピー
        "current_n_jpy_str": row.get("current_n_jpy_str", ""),
        # 価格急増ガード用: 前 cycle に書いた M(現在価格)。新 price_jpy と like-with-like 比較する
        "current_m_jpy_str": row.get("current_m_jpy_str", ""),
        # AK 列 (巡回ERR) 前 cycle marker を引き継ぐ。2026-06-16 追加: これが欠落していたため
        # 書込ループの clear_err が常に False = 成功してもクリア不発火 (古い marker が無限残留)、
        # かつ error 再mark 時も count が常に ×1 (= PERSISTENT_THRESHOLD「要手動chk」永久不発火)。
        # 両 bug の真因。 read_listings_rows が付ける err_flag_prev を result まで運ぶ。
        "err_flag_prev": row.get("err_flag_prev", ""),
        # AC-AG (補 URL) セル色塗り用: 各候補の state を保存 (主は index=0)
        "sub_results":       sub_results,
    }

    # delta 判定
    cur_marked_sold = result["current_sold"] in ("○", "〇")
    if is_sold is True and not cur_marked_sold:
        result["delta"] = "newly_sold"
    elif is_sold is False and cur_marked_sold:
        result["delta"] = "newly_in_stock"
    elif is_sold in (True, False):
        result["delta"] = "unchanged"
    # is_sold=None (error) は uncertain のまま

    return result


# ============================================================================
# decision_log
# ============================================================================
def append_decision_log(sheet_label: str, results: list, dry_run: bool):
    """decision_log/listings_<ts>.jsonl に追記."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DECISION_LOG_DIR / f"listings_{sheet_label}_{ts}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({
                "ts":           datetime.now().isoformat(timespec="seconds"),
                "sheet":        sheet_label,
                "dry_run":      dry_run,
                **r,
            }, ensure_ascii=False) + "\n")
    log(f"  decision_log: {path}")


# ============================================================================
# pending_revise queue (Phase 3 連携)
# ============================================================================
# 「Phase 2 で今回新規に〇を付与した行のみ」を Phase 3 (Revise CSV) に流す。
# スプシに既存していた手動 〇 や、過去の Inventory 処理で付与された 〇 は
# このキューには入らない → Phase 3/4 で誤って取り下げ対象にしない。
PENDING_REVISE_FILE = DECISION_LOG_DIR / "pending_revise.jsonl"
# HQ 2026-06-10 FINAL 指示 B: silent 除外を禁止。 newly_sold だが item_id 空欄等で
# revise 不能な entry は action_required.jsonl に記録、 cycle report で要対応として明示
ACTION_REQUIRED_FILE = DECISION_LOG_DIR / "action_required.jsonl"
# 補URL救済ログ (フック2、2026-07-25)。救済 = 主URL死 AND 補URL≥1本 在庫あり (Phase1 救済率 signal)。
RESCUE_EVENTS_FILE = DECISION_LOG_DIR / "rescue_events.jsonl"   # 監査用 (実書込の証跡)
# 補URL消込の復元用アーカイブ (2026-07-25)。消したセル (row/slot/col/url) を全て記録 →
# 誤削除でも URL を残し復元可能にする (データ安全)。cell を消しても値はここに残る。
CLEARED_BACKUPS_ARCHIVE = DECISION_LOG_DIR / "cleared_backups_archive.jsonl"
# ★ 2026-08-07 revive_qty1_impl §6 復活パス:
# pending_revive.jsonl = 2 cycle 連続 in_stock 確定した行 (= 誤検知1回で誤復活しない)。
# newly_in_stock_state.json = 1 cycle 目に検知した (label, item_id) を暫定記録し、
#   2 cycle 目でも in_stock なら pending_revive に enqueue。 消えたら state から掃除。
# 対称: pending_revise.jsonl (取下げ) / newly_sold は 1 cycle で送る (漏れ=Defect直撃)
#       pending_revive.jsonl (復活)   / newly_in_stock は 2 cycle 確定 (誤復活=BAN 直撃)
PENDING_REVIVE_FILE = DECISION_LOG_DIR / "pending_revive.jsonl"
NEWLY_IN_STOCK_STATE_FILE = DECISION_LOG_DIR / "newly_in_stock_state.json"


def _rescue_key(r: dict) -> str:
    """救済 dedup のキー。 item_id 優先、 空欄は row: fallback。"""
    return (r.get("item_id") or "").strip() or f"row:{r['row_index']}"


def load_rescue_state(sheet_label: str) -> set:
    """前 cycle に「救済状態」だったキー集合を読む (遷移ベース dedup 用)。"""
    p = DECISION_LOG_DIR / f"rescue_state_{sheet_label}.json"
    if p.exists():
        try:
            return set(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_rescue_state(sheet_label: str, keys: set) -> None:
    """今 cycle の救済状態キー集合を保存 (次 cycle の遷移判定基準)。"""
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    p = DECISION_LOG_DIR / f"rescue_state_{sheet_label}.json"
    p.write_text(json.dumps(sorted(keys), ensure_ascii=False), encoding="utf-8")


def append_pending_revise(sheet_label: str, result: dict, dry_run: bool) -> None:
    """delta="newly_sold" の行を pending queue に append.
    dry_run でも記録する (queue 状態の追跡用、ただし Phase 3 側で dry_run flag を尊重)。
    """
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts":           datetime.now().isoformat(timespec="seconds"),
        "sheet":        sheet_label,
        "row_index":    result["row_index"],
        "url":          result["url"],
        "item_id":      result["item_id"],
        "title":        result.get("title", ""),
        "supplier":     result["supplier"],
        "raw_status":   result["raw_status"],
        "dry_run":      dry_run,
    }
    with open(PENDING_REVISE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ============================================================================
# 復活 (revive) パス — 2 cycle 連続確定 state + pending_revive enqueue
# ============================================================================
def load_newly_in_stock_state() -> dict:
    """{"HIGH": {"<item_id>": {"first_seen_at": iso, "cycles": N}}, ...} を読む。

    形式不正/読み失敗は空 dict (fail-safe: 復活 gate は「未確定」に倒れる)。
    """
    if not NEWLY_IN_STOCK_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(NEWLY_IN_STOCK_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def save_newly_in_stock_state(state: dict) -> None:
    """newly_in_stock_state.json を書出。 sheet 別 dict of dict を保存。"""
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    NEWLY_IN_STOCK_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def append_pending_revive(sheet_label: str, result: dict, dry_run: bool) -> None:
    """delta="newly_in_stock" が 2 cycle 連続確定した行を pending queue に append.

    ★ pending_revise (取下げ) と対称構造。 dry_run でも記録する (queue 状態の追跡用)。
    revive_csv_generator (mode="revive") がここを読んで gate 4段を掛け qty=1 化 CSV を作る。
    """
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts":           datetime.now().isoformat(timespec="seconds"),
        "sheet":        sheet_label,
        "row_index":    result["row_index"],
        "url":          result["url"],
        "item_id":      result["item_id"],
        "title":        result.get("title", ""),
        "supplier":     result.get("supplier", ""),
        "raw_status":   result.get("raw_status", ""),
        "dry_run":      dry_run,
    }
    with open(PENDING_REVIVE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def confirm_and_enqueue_revive(
    sheet_label: str,
    results: list,
    dry_run: bool,
    state: Optional[dict] = None,
) -> dict:
    """cycle 内 results から newly_in_stock を拾い、 2 cycle 連続確定を判定して enqueue。

    state 遷移 (per (sheet_label, item_id)):
      - 今 cycle に newly_in_stock 検知 &&  state 未登録    → cycles=1 で state に記録
                                                              (pending_revive には積まない)
      - 今 cycle に newly_in_stock 検知 or in_stock (unchanged で D=空 かつ is_sold=False) &&
        state 登録 && cycles>=1                              → 2 cycle 確定 = enqueue、 state 削除
      - 今 cycle に is_sold=True (売切に反転) or item_id 変化 → state から削除
        (幻の in_stock を state に残さない)
      - state 登録済で今 cycle に見なかった (skip 等)         → 温存 (次 cycle まで待つ)

    ★ Amazon の Featured Offer flakiness (= 1 cycle だけ誤って in_stock に見える) を弾く
    のが本 gate の目的。 pending_revive まで進んだ行はさらに URL/3点/採算/二重出品 gate を
    revive_csv_generator が掛ける。

    Args:
        sheet_label: "HIGH" / "LOW" / "SHEET"
        results:     monitor サイクルの results list
        dry_run:     True なら pending_revive/state 書込を skip
        state:       テスト用 injection (省略で load_newly_in_stock_state() から取得)

    Returns: {"promoted": N, "first_seen": M, "cleared": K, "stayed": L}
    """
    if state is None:
        state = load_newly_in_stock_state()
    sheet_state = state.setdefault(sheet_label, {})
    ts_now = datetime.now().isoformat(timespec="seconds")

    promoted = 0
    first_seen = 0
    cleared = 0
    stayed = 0

    # 今 cycle に 何らかの判定が出た item_id 集合 (state 掃除用)
    observed_ids = set()
    for r in results:
        iid = (r.get("item_id") or "").strip()
        if not iid:
            continue
        observed_ids.add(iid)
        delta = r.get("delta")
        is_sold = r.get("is_sold")
        cur_sold_marked = (r.get("current_sold") or "").strip() in ("○", "〇")
        # 判定不能 (エラー/uncertain) は state に触らない (前状態温存 = fail-closed)
        if is_sold is None or delta == "uncertain":
            if iid in sheet_state:
                stayed += 1
            continue
        # 売切 (is_sold=True) → state から削除 (幻の in_stock を持ち越さない)
        if is_sold is True:
            if iid in sheet_state:
                del sheet_state[iid]
                cleared += 1
            continue
        # 以下 is_sold=False (在庫あり判定) のパス
        if delta == "newly_in_stock":
            # ○→空 に変化した cycle
            if iid not in sheet_state:
                sheet_state[iid] = {"first_seen_at": ts_now, "cycles": 1}
                first_seen += 1
            else:
                # 既に state 登録済 (前 cycle) + 今も in_stock → 2 cycle 確定 = enqueue
                sheet_state[iid]["cycles"] = int(sheet_state[iid].get("cycles", 1)) + 1
                append_pending_revive(sheet_label, r, dry_run=dry_run)
                del sheet_state[iid]
                promoted += 1
        elif delta == "unchanged" and not cur_sold_marked:
            # D=空 のまま in_stock 継続 (= 復活後の追いかけ判定)
            if iid in sheet_state:
                # 前 cycle newly_in_stock 記録済 + 今も in_stock → 確定
                sheet_state[iid]["cycles"] = int(sheet_state[iid].get("cycles", 1)) + 1
                append_pending_revive(sheet_label, r, dry_run=dry_run)
                del sheet_state[iid]
                promoted += 1
            # state に無ければ何もしない (元から在庫あり、 変化なし)

    # 今 cycle に見なかった state entry は保持 (次 cycle まで温存、 stayed に加算)
    for iid in list(sheet_state.keys()):
        if iid not in observed_ids:
            stayed += 1

    if not dry_run:
        try:
            save_newly_in_stock_state(state)
        except OSError as e:
            log(f"  [!] newly_in_stock_state 保存失敗: {type(e).__name__}: {e}")

    return {
        "promoted": promoted,
        "first_seen": first_seen,
        "cleared": cleared,
        "stayed": stayed,
    }


def append_action_required(sheet_label: str, result: dict, reason: str,
                            dry_run: bool) -> None:
    """HQ 2026-06-10 FINAL 指示 B: silent 除外禁止。

    newly_sold だが revise 不能な entry (= item_id 空欄 / 引き直し不能 等) を
    action_required.jsonl に記録。 cycle report 冒頭の 「⚠️ 要対応 Y件」 集計対象。

    reason 値:
      - "item_id_empty"           : sheet B 列 itemID 空欄、 引き直し未実装
      - "verify_qty_gt0_giveup"   : revise + in-cycle retry 後も eBay qty>0 残存
      - "supplier_not_supported"  : URL から supplier 判定不能
    """
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    item_id = result.get("item_id") or ""
    row_index = result["row_index"]
    # ★ 2026-07-07: 冪等化 (dedup)。 burst guard は pending queue の同一 item を毎 cycle
    # HOLD するため、 dedup が無いと同一 (item, reason) が延々追記され肥大化 (実測 335 item /
    # 2227 entry = 平均 6.6 重複、 07-04〜07 の deadlock で発生)。 同一 keyの entry が既にあれば
    # 追記しない (= 記録は 1 度きり、 silent 化はしない)。 key は item_id 優先、 空欄は row_index。
    dedup_key = (item_id or f"row:{row_index}", reason)
    if ACTION_REQUIRED_FILE.exists():
        try:
            for line in ACTION_REQUIRED_FILE.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ek = (e.get("item_id") or f"row:{e.get('row_index')}", e.get("reason"))
                if ek == dedup_key:
                    return  # 既記録 = 追記 skip (dedup)
        except Exception:
            pass  # 読込失敗時は保守的に追記 (silent 化しない方を優先)
    entry = {
        "ts":           datetime.now().isoformat(timespec="seconds"),
        "sheet":        sheet_label,
        "row_index":    row_index,
        "url":          result["url"],
        "item_id":      item_id,
        "title":        result.get("title", ""),
        "supplier":     result.get("supplier", ""),
        "raw_status":   result.get("raw_status", ""),
        "reason":       reason,
        "dry_run":      dry_run,
    }
    with open(ACTION_REQUIRED_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ============================================================================
# orphan chrome 一掃 (cycle 開始時の clean slate 確保、2026-06-12)
# ============================================================================
# 自分の scraper が使う chrome profile (= kill 対象を自分の資産に限定するための指紋)
def _own_profile_dirs() -> tuple:
    from scrapers import mercari_scraper, amazon_scraper  # noqa: PLC0415
    dirs = []
    for mod, attr in ((mercari_scraper, "CHROME_PROFILE_DIR"),
                      (amazon_scraper, "EBAY_AMAZON_PROFILE_DIR")):
        v = getattr(mod, attr, None)
        if isinstance(v, str) and v.strip():
            dirs.append(v.strip().lower())
    return tuple(dirs)


def _select_stale_scraper_pids(procs, profile_dirs, self_pid: int = 0) -> list:
    """kill すべき PID を選ぶ純粋関数 (2026-07-28 に無差別 kill から限定 kill へ)。

    ★ 旧実装は「--headless な chrome.exe 全部 + undetected_chromedriver 全部」をマシン全体で
      kill していた。これは他プロジェクト (公式監視くん check_ebay_login / Catalog / Harvest 等)
      の headless chrome も巻き込む越境事故になる。自分の資産だけを対象にする:

      - chrome.exe            : --headless かつ **自分の profile dir を指しているもの**
      - undetected_chromedriver: **親プロセスが既に死んでいる真の orphan のみ**
                                 (他プロジェクトの稼働中 driver は親 python が生きているので残る)

      CommandLine が取れないプロセスは **kill しない** (fail-safe: 判定不能なら触らない)。
    """
    live = {int(p.get("ProcessId") or 0) for p in procs if p.get("ProcessId")}
    out = []
    for p in procs:
        try:
            pid = int(p.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if not pid or pid == self_pid:
            continue
        name = (p.get("Name") or "").lower()
        cmd = (p.get("CommandLine") or "")
        if name == "chrome.exe":
            low = cmd.lower()
            if "--headless" not in low:
                continue                        # ユーザーの通常ブラウザは温存
            if not any(d and d in low for d in profile_dirs):
                continue                        # 他プロジェクトの headless chrome は触らない
            out.append(pid)
        elif name.startswith("undetected_chromedriver"):
            try:
                ppid = int(p.get("ParentProcessId") or 0)
            except (TypeError, ValueError):
                continue
            if ppid and ppid not in live:        # 親が死んでいる = 前 cycle の残骸
                out.append(pid)
    return out


def _kill_stale_scraper_chrome(log=print) -> None:
    """自分の scraper が残した orphan chrome / driver だけを kill (clean slate).

    driver 生成"前"(並走 driver 皆無の安全な時点) でのみ呼ぶこと
    (cycle 途中で呼ぶと並走中の他 supplier driver の chrome を巻き込む)。
    """
    if sys.platform != "win32":
        return
    import subprocess  # noqa: PLC0415
    ps = ("Get-CimInstance Win32_Process | "
          "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress -Depth 2")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        procs = json.loads((r.stdout or "").strip() or "[]")
        if isinstance(procs, dict):
            procs = [procs]
        pids = _select_stale_scraper_pids(procs, _own_profile_dirs(), self_pid=os.getpid())
        if not pids:
            log("  [cleanup] orphan chrome/driver なし (自分の profile 配下のみ対象)")
            return
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Stop-Process -Id " + ",".join(str(p) for p in pids) + " -Force -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log(f"  [cleanup] 自分の orphan chrome/driver {len(pids)} 個を一掃 (他プロジェクトは不触)")
    except Exception as e:
        log(f"  [cleanup] orphan kill skip ({type(e).__name__}: {e})")


# ============================================================================
# 1 spreadsheet (HIGH or LOW) を処理
# ============================================================================
def process_sheet(
    sheet_id: str,
    sheet_label: str,
    start_row: int = 2,
    end_row: Optional[int] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    progress_callback=None,
    supplier_filter: str = "all",
):
    log("=" * 60)
    log(f"商品管理シート [{sheet_label}] 開始 (sheet_id={sheet_id[:20]}..., dry_run={dry_run})")
    log("=" * 60)

    sh = open_sheet_by_id(sheet_id)
    log(f"  open: {sh.title}")
    ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
    log(f"  worksheet: {ws.title} (id={ws.id}, total_rows={ws.row_count})")

    # AK 列 (巡回ERR) ヘッダを一度だけ設定 (既存なら no-op)
    if not dry_run:
        try:
            if ensure_listings_err_header(ws):
                log("  AK1 に「巡回ERR」ヘッダを新規設定")
        except Exception as e:
            log(f"  [!] AK ヘッダ設定 skip ({type(e).__name__}: {e})")

    rows = read_listings_rows(ws, start_row=start_row, end_row=end_row, only_with_url=True)
    log(f"  active rows (URL あり): {len(rows)}")

    if supplier_filter != "all":
        before = len(rows)
        rows = [r for r in rows if detect_supplier(_domain_of(r["url"])) == supplier_filter]
        log(f"  --supplier {supplier_filter} で絞込: {before} → {len(rows)} 件")

    if limit is not None:
        rows = rows[:limit]
        log(f"  --limit {limit} で絞込: {len(rows)} 件")

    if not rows:
        log("  対象 0 件、終了")
        return {"processed": 0, "newly_sold": 0, "newly_in_stock": 0, "errors": 0}

    # supplier 内訳
    by_sup = {}
    for r in rows:
        sup = detect_supplier(_domain_of(r["url"]))
        by_sup[sup] = by_sup.get(sup, 0) + 1
    log(f"  supplier 内訳: {by_sup}")

    # === cycle 開始時の orphan chrome 一掃 (2026-06-12 制定・再発防止) ===
    # 前 cycle で driver 再起動が失敗すると headless chrome が orphan として残り、
    # 累積すると新規 driver が「chrome not reachable」で起動不能になる
    # (2026-06-12 21:30 cycle で mercari driver が 6分 blind → 累積で完全不動の事故)。
    # 旧 kill (`taskkill /IM chromedriver.exe` + WINDOWTITLE filter) は (a) uc は
    # undetected_chromedriver.exe で名前不一致 (b) headless chrome は window title 無し、
    # の二重バグで一つも kill できていなかった。 driver 生成"前"(= 並走 driver 皆無の安全な
    # 時点) に、 --headless chrome (= scraper 専用、 ユーザーの通常ブラウザは非 headless で温存)
    # と undetected_chromedriver を確実に kill する。
    _kill_stale_scraper_chrome(log)

    # Mercari URL がある場合は driver を 1 つ生成して再利用 (起動コスト削減)
    mercari_driver = None
    needs_mercari = by_sup.get("mercari", 0) > 0
    if needs_mercari:
        log("  Mercari driver 起動中...")
        try:
            mercari_driver = create_mercari_driver(headless=True)
            log("  [OK] Mercari driver 起動完了 (再利用 mode)")
        except Exception as e:
            log(f"  [!] Mercari driver 起動失敗: {type(e).__name__}: {e}")
            log("     → 各 row で都度 driver 生成に fallback (遅い)")
            mercari_driver = None

    # Amazon URL がある場合は login 済 profile で driver を 1 つ生成 (大量 run の robust path)
    # HQ 2026-06-03 § (b) bot 検知対策: driver 起動失敗 → kill chrome process + retry。
    # それでも失敗 → cycle abort (= driver 無しで burst すると bot 検知で偽 OOS 大量化、
    # 致命的、 一旦止めて 人手で profile 復旧)。
    amazon_driver = None
    needs_amazon = by_sup.get("amazon", 0) > 0
    if needs_amazon:
        log("  Amazon driver 起動中 (login profile)...")
        last_err = None
        for attempt in (1, 2):
            try:
                amazon_driver = create_amazon_driver(headless=True, use_login_profile=True)
                log(f"  [OK] Amazon driver 起動完了 (login profile 再利用、 attempt={attempt})")
                break
            except Exception as e:
                last_err = e
                log(f"  [!] Amazon driver 起動失敗 attempt={attempt}: {type(e).__name__}: {str(e)[:120]}")
                if attempt == 1:
                    # chrome process kill (= profile lock 解放)
                    try:
                        import subprocess  # noqa: PLC0415
                        subprocess.run(["taskkill", "/F", "/IM", "chromedriver.exe"],
                                       capture_output=True, timeout=10)
                        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/FI", "WINDOWTITLE eq *iMakInventory*"],
                                       capture_output=True, timeout=10)
                        log("     → chrome/chromedriver process kill 実行、 5s wait で retry")
                        time.sleep(5)
                    except Exception as ke:
                        log(f"     → kill 失敗 ({type(ke).__name__}): {ke}")
        if amazon_driver is None:
            # cycle abort: amazon が大量にある状態で driver なし = burst で bot 検知 →
            # 大量偽 OOS = 主力誤取下げ。 一旦止めて 人手で profile 復旧を促す。
            log(f"  [FATAL] Amazon driver 起動 2 回失敗、 cycle abort (= 大量偽 OOS 防止)")
            log(f"  最終 error: {type(last_err).__name__}: {last_err}")
            log(f"  対処: chrome process 全 kill + iMakInventory profile lock file 削除 + 再 cycle")
            raise RuntimeError(
                f"Amazon driver 起動失敗 (= bot 検知防止のため cycle abort): {last_err}"
            )

    results = []
    mercari_consec_none = 0  # Phase 9: mercari driver 自動再起動用カウンタ
    amazon_consec_dead = 0   # 2026-06-25: amazon driver 自動再起動用カウンタ
    mercari_scrape_count = 0  # 2026-06-11: 予防的 driver 再起動用 (実 scrape 件数)
    total_rows = len(rows)
    if progress_callback is not None:
        try:
            progress_callback(phase="monitor", processed=0, total=total_rows, errors=0,
                              sheet_label=sheet_label)
        except Exception:
            pass
    for i, row in enumerate(rows, start=1):
        prefix = f"  [{i}/{total_rows}] row{row['row_index']:>4} "
        # 2026-05-25 mercari D=○ skip (= 監視くん最適化):
        # 主 URL が mercari + D=○ = 主補全 sold 確定 + 復活機能なし → scrape 完全 skip
        # 1 点もの中心の mercari は売切後に同 URL から復活しない、 scrape する実益ゼロ。
        # HIGH 295 + LOW 23 = 318 件 削減 (mercari 全 645 中 49%)、 cycle 時間 半減効果。
        # 関連: [[amazon_restore_after_scrape_reliability]] (= amazon は別途継続 chk)
        # ★ 2026-06-25 除外: mercari SHOPS (jp.mercari.com/shops/product/...) は業者出品で
        # 復活 (restock) する。 1点もの前提の skip を SHOPS に適用すると、 売切→D=○ 後に
        # 源が復活しても永久 skip で検知できず D=○ が stale 化する (iid=358705341664 の偽 ✕)。
        # SHOPS は通常 mercari item と違い再入荷するので skip せず毎 cycle 再 scrape する。
        row_supplier = detect_supplier(_domain_of(row["url"]))
        cur_sold = (row.get("current_sold") or "").strip()
        # === item_id 空欄 = 未出品 も巡回対象にする (2026-06-21 user 指示で方針反転) ===
        # 旧 (2026-06-10): item_id 空欄 = 未出品 = scrape skip だった。
        # 新 (2026-06-21): 未出品も scrape する。 理由: 出品くんが CSV 作成 → 出品 した後に
        # 「実は仕入元売切だった」 が発覚するのを防ぐため、 出品前に源在庫を D 列へ反映しておく。
        # 取下げ対象 (eBay listing) は無いので revise/pending/要対応 には入れない。
        # 売切検知時の扱いは下段 (newly_sold && item_id 空欄 → 「未出品扱い、 検知のみ記録、
        # revise なし、 alert なし」) で既に正しく分岐済 = D 列だけ更新される。
        # ★ 2026-08-07 revive_qty1_impl §② (HIGH の巡回漏れ解消): D=○ の 1点もの URL は
        # 復活が原理的にありえないので巡回打切り (旧: mercari 個人のみ / 新: 1点もの全般)。
        # 実測: 1,139件中665件が対象 → HIGH の「戻らない638件」を巡回から外し、「再入荷する
        # 142件」に visit budget を回す。 fail-closed 対称: is_restockable_url が生きてる URL
        # 群は従来どおり毎 cycle 再 scrape する (mercari SHOPS 等 = 再入荷しうる)。
        if cur_sold in ("○", "〇") and is_one_off_url(row.get("url") or ""):
            log(f"{prefix}{row_supplier:<7} - skip (D=○、1点もの 復活機会なし)")
            results.append({
                "row_index":         row["row_index"],
                "url":               row["url"],
                "item_id":           row.get("item_id", ""),
                "title":             row.get("title", ""),
                "supplier":          row_supplier,
                "is_sold":           True,
                # raw_status は下流 (書込ループ) の完全 skip 判定に使うので
                # 「skipped_mercari_sold」 と同型のマーカーを付ける (別名にすると下流が
                # スプシ書込を掛けてしまう)。 名前はレガシー継承で意味は「1点もの skip」。
                "raw_status":        "skipped_mercari_sold",
                "current_sold":      cur_sold,
                "delta":             "unchanged",
                "error":             None,
                "price_jpy":         None,    # 価格 chk もしない → N列触らない
                "candidates_checked": 0,
                "current_n_jpy_str": row.get("current_n_jpy_str", ""),
                "sub_results":       [],
            })
            continue

        try:
            res = check_one_row_with_fallback(
                row, sleep_sec=sleep_sec,
                mercari_driver=mercari_driver,
                amazon_driver=amazon_driver)
        except Exception as e:
            res = {
                "row_index": row["row_index"],
                "url": row["url"],
                "item_id": row.get("item_id", ""),
                "supplier": detect_supplier(_domain_of(row["url"])),
                "is_sold": None,
                "raw_status": "",
                "current_sold": row.get("current_sold", ""),
                "delta": "uncertain",
                "error": f"{type(e).__name__}: {e}",
            }

        # ログ表示
        sup = res["supplier"][:7].ljust(7)
        if res["error"]:
            # 連続失敗 → driver 再起動を試行 (mercari / amazon 共通の crash 検知)
            # 2026-05-24: trigger 拡張. 旧 "scraper returned None" のみ → driver crash
            # (MaxRetryError / HTTPConnectionPool / WebDriverException) も catch.
            # 5/24 cycle で 18:04 driver 死亡後 297 連続 MaxRetryError、再起動 0 回事故。
            # 2026-06-25: "invalid session id" 追加 (amazon driver セッション死の主シグナル、
            # 06-23 LOW で 396 連続失敗の真因)。
            err_s = res["error"] or ""
            driver_dead = (
                "scraper returned None" in err_s
                or "MaxRetryError" in err_s
                or "HTTPConnectionPool" in err_s
                or "WebDriverException" in err_s
                or "chrome not reachable" in err_s.lower()
                or "no such window" in err_s.lower()
                or "session deleted" in err_s.lower()
                or "invalid session id" in err_s.lower()
                or "invalidsessionid" in err_s.lower()
            )
            if res["supplier"] == "mercari" and driver_dead:
                mercari_consec_none += 1
                if mercari_consec_none >= MERCARI_RESTART_THRESHOLD:
                    log(f"  [!] mercari 連続 None {mercari_consec_none} 件 → driver 再起動を試行")
                    if mercari_driver is not None:
                        try:
                            mercari_driver.quit()
                        except Exception:
                            pass
                    try:
                        mercari_driver = create_mercari_driver(headless=True)
                        log("    [OK] mercari driver 再起動完了 (続行)")
                        mercari_consec_none = 0
                    except Exception as _restart_err:
                        log(f"    [NG] mercari driver 再起動失敗: {_restart_err} (mercari は失敗継続、他 supplier は処理する)")
                        mercari_driver = None
                        mercari_consec_none = 0  # 再起動失敗を loop しないようリセット
            if res["supplier"] == "amazon" and driver_dead:
                amazon_consec_dead += 1
                if amazon_consec_dead >= AMAZON_RESTART_THRESHOLD:
                    log(f"  [!] amazon 連続 driver crash {amazon_consec_dead} 件 → driver 再起動を試行")
                    if amazon_driver is not None:
                        try:
                            amazon_driver.quit()
                        except Exception:
                            pass
                    try:
                        amazon_driver = create_amazon_driver(headless=True, use_login_profile=True)
                        log("    [OK] amazon driver 再起動完了 (続行)")
                        amazon_consec_dead = 0
                    except Exception as _restart_err:
                        # 再起動失敗 → amazon_driver=None で続行 (残り amazon 行は error 計上 =
                        # silent でなく次 cycle 再試行)。 fail-closed (d23ad99) で None は偽 OOS に
                        # ならず is_sold=None=error に倒れるので burst 誤取下げは起きない。
                        log(f"    [NG] amazon driver 再起動失敗: {_restart_err} (amazon は失敗継続、他 supplier は処理する)")
                        amazon_driver = None
                        amazon_consec_dead = 0  # 再起動失敗を loop しないようリセット
            if (res["error"] or "").startswith("unsupported supplier"):
                log(f"{prefix}{sup} - skip ({res['error'][:60]})")
            else:
                log(f"{prefix}{sup} [!] {res['error'][:60]}")
        else:
            # 成功した supplier に対応するカウンタをリセット
            if res["supplier"] == "mercari":
                mercari_consec_none = 0
            elif res["supplier"] == "amazon":
                amazon_consec_dead = 0
            mark = "○" if res["is_sold"] else "·"
            delta_emoji = {
                "newly_sold":      "[v]",
                "newly_in_stock":  "[^]",
                "unchanged":       " ",
                "uncertain":       "?",
            }.get(res["delta"], "?")
            log(f"{prefix}{sup} {mark} [{res['raw_status'][:14]}] {delta_emoji} {res['delta']}: {row['title'][:30]}")

            # Q2: 「今回新規に〇を付与した行」のみ pending queue に積む
            # → Phase 3 (Revise CSV) は queue から取る = 既存〇は対象外
            if res["delta"] == "newly_sold":
                if res.get("item_id"):
                    append_pending_revise(sheet_label, res, dry_run=dry_run)
                else:
                    # ユーザー指示 2026-06-10: itemID 空欄 = 未出品 (= 監視予定行)、 正常状態。
                    # 旧実装は HQ 指示 B 「silent 除外禁止」 を誤適用して action_required に積んでいた。
                    # 真の silent loss (= 出品済だが itemID 未記録) と 未出品 を区別不能なため、
                    # ユーザー判断尊重 (= 「itemID 空欄なら未出品扱い」)。 log のみ記録、 alert なし。
                    log(f"    [info] item_id 空欄 = 未出品扱い (newly_sold 検知のみ記録、 revise なし)")

        results.append(res)

        # 予防的 driver 再起動: mercari の実 scrape を一定件数こなしたら driver を refresh。
        # 巡回深度で driver が疲弊し ReadTimeout が cluster する事象 (rows 747-757 等) の根本対策。
        # 反応的再起動 (連続失敗) を待たず、 疲弊する前にリサイクルする。
        if res["supplier"] == "mercari":
            mercari_scrape_count += 1
            if (MERCARI_PREVENTIVE_RESTART_EVERY > 0
                    and mercari_driver is not None
                    and mercari_scrape_count % MERCARI_PREVENTIVE_RESTART_EVERY == 0):
                log(f"  [i] mercari 予防再起動 ({mercari_scrape_count} 件 scrape 済 → driver refresh)")
                try:
                    mercari_driver.quit()
                except Exception:
                    pass
                try:
                    mercari_driver = create_mercari_driver(headless=True)
                    mercari_consec_none = 0
                    log("    [OK] mercari driver 予防再起動完了")
                except Exception as _prev_err:
                    log(f"    [NG] mercari driver 予防再起動失敗: {_prev_err} (継続)")
                    mercari_driver = None

        # ライブ進捗通知 (callback は throttle を内部で管理)
        if progress_callback is not None:
            try:
                progress_callback(
                    phase="monitor",
                    processed=i,
                    total=total_rows,
                    errors=sum(1 for r in results if r.get("error")),
                    sheet_label=sheet_label,
                )
            except Exception:
                pass

        # Phase 9 修正: 早期 abort 廃止 (漏れ NG 原則)
        # 全 421 件処理しきる方針。mercari 不調は driver 再起動で復旧試行。

    # driver 後始末
    if mercari_driver is not None:
        try:
            mercari_driver.quit()
        except Exception:
            pass
    if amazon_driver is not None:
        try:
            amazon_driver.quit()
        except Exception:
            pass

    # 集計
    newly_sold = sum(1 for r in results if r["delta"] == "newly_sold")
    newly_in_stock = sum(1 for r in results if r["delta"] == "newly_in_stock")
    errors = sum(1 for r in results if r["error"])
    # 不正 URL (unsupported supplier) を抽出して目立たせる ─ 漏れ NG 原則
    url_alerts = [
        {"row_index": r["row_index"], "url": r.get("url", ""), "error": r["error"]}
        for r in results
        if (r.get("error") or "").startswith("unsupported supplier")
    ]
    # ユーザー指示 2026-06-10: ⚠️/❌ のとき何を確認すべきか load-bearing に。
    # error 詳細 row を email で出す用 (上位 20 件)。
    error_rows = [
        {
            "row_index":  r["row_index"],
            "item_id":    r.get("item_id", ""),
            "url":        (r.get("url") or "")[:120],
            "title":      (r.get("title") or "")[:50],
            "error":      (r.get("error") or "")[:150],
            "supplier":   r.get("supplier", ""),
        }
        for r in results if r.get("error")
    ][:20]
    log("")
    log(f"  === 集計 [{sheet_label}] ===")
    log(f"    処理: {len(results)} / 対象 {len(rows)}")
    log(f"    新規売切: {newly_sold} / 新規復活: {newly_in_stock} / 変化なし: {len(results) - newly_sold - newly_in_stock - errors} / エラー: {errors}")
    if url_alerts:
        log(f"  [!] URL 不正で在庫検出スキップ: {len(url_alerts)} 件 (スプシ修正必要)")
        for a in url_alerts[:10]:
            log(f"    row{a['row_index']:>4} {a['url'][:80]}  ← {a['error'][:60]}")
        if len(url_alerts) > 10:
            log(f"    ... +{len(url_alerts) - 10} 件")

    # 書込 (Phase 9 修正: trabajo 同等の O 列全件更新仕様)
    #   - O 列: 巡回処理した全行に時刻書込 (エラー含む)
    #   - D 列: 「変化があった行」のみ更新 (人手書込を尊重)
    #   - N 列: scrape で価格取得できた行のみ更新 (None なら触らない、purely additive)
    checked_at_now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    err_now = datetime.now()  # AK 列 marker 用 (= checked_at と同 cycle 時刻)
    updates = []
    # AK 列 (巡回ERR) 連続エラー回数が PERSISTENT_THRESHOLD 以上の行 = 持続エラー (要手動 chk)
    persistent_err_rows = []
    # ×DEAD_SOURCE_THRESHOLD 以上 = 自己回復しない仕入元 (URL 差替が要る) → 別枠
    dead_source_rows = []
    # 2026-05-25 純粋抽出化 (依頼: monitor_pure_extract_implementation): 異常値ガード撤廃
    # 監視くんは scrape 値そのまま N列書込、 異常値判定 / warning / alert は全て下流
    # (リバイスくん / 出品くん / 別 logger worker) に委譲。 1 機能 1 worker 原則。
    # 旧 placeholder 残置 listing (= ¥22,222 vs ¥9,999 で ratio 0.45) で逆作動した
    # 反省から、 採用判断の責任を分離。 関連: [[scraper_price_vulnerability]]
    for r in results:
        # 2026-05-25 mercari D=○ skip 行は scrape していないので sheet 書込 完全 skip
        # (= O 列 checked_at も更新しない、 触らない方針)
        # 2026-06-10 item_id 空欄 = 未出品 skip 行も同様に完全 skip (= 触らない)
        if r.get("raw_status") in ("skipped_mercari_sold", "skipped_no_item_id"):
            continue
        price_jpy = r.get("price_jpy")  # None の場合 update dict には乗せない (= N 列触らない)
        prev_n = r.get("current_n_jpy_str", "")  # AH 列用 (= read 時の N 列値)
        if r["error"] or r["is_sold"] is None:
            # 取得不能 → O 列だけ更新 (D 列は既存維持、fail-closed 維持)
            #          N 列は price_jpy=None なので触らない (既存値維持)
            #          AK 列 = 連続エラー marker (前 cycle の marker から回数累積)
            marker = build_err_marker(
                r["error"] or "in_stock indeterminate",
                r.get("err_flag_prev", ""),
                now=err_now,
            )
            upd = {
                "row_index":  r["row_index"],
                "checked_at": checked_at_now,
                "o_only":     True,
                "err_flag":   marker,
            }
            if price_jpy is not None:
                upd["price_jpy"] = price_jpy   # → sheet_updater が M列(12) に書込
                upd["prev_n_jpy_str"] = prev_n
                # K列(11) 基本ポイント: amazon の在庫あり行のみ (HQ 2026-07-22)。
                # 表示なし→0 (確定観測)、 fetch 失敗は上の price_jpy=None で弾かれ不触。
                # = 同一フェッチ・同一巡回で M と K を一貫更新 (旧F−現pt の N過小を構造的に防ぐ)。
                if r.get("supplier") == "amazon":
                    _pts = r.get("points_jpy")
                    upd["points_jpy"] = (_pts if isinstance(_pts, int)
                                         and not isinstance(_pts, bool) and _pts >= 0 else 0)
            updates.append(upd)
            if marker_count(marker) >= PERSISTENT_THRESHOLD:
                # 出品が生きている (item_id あり かつ D≠○) 行だけが在庫不明 = 取下げ判断に効く。
                # D=○ / 未出品は「在庫は分からないが出品リスクは無い」ので triage 用に明示する。
                _iid = (r.get("item_id") or "").strip()
                entry = {
                    "row_index": r["row_index"],
                    "item_id":   r.get("item_id", ""),
                    "url":       (r.get("url") or "")[:120],
                    "title":     (r.get("title") or "")[:50],
                    "count":     marker_count(marker),
                    "error":     (r.get("error") or "")[:150],
                    "supplier":  r.get("supplier", ""),
                    "listing_risk": bool(_iid and _iid != "9999"
                                         and not (r.get("current_sold") or "").strip()),
                }
                # ★ ×DEAD_SOURCE_THRESHOLD 以上は「回復待ち」から外して「死んだ仕入元」枠へ
                #   (HQ 2026-07-28 指摘: 降りる経路が自己回復しかなく要対応リストが墓場化する)
                if marker_count(marker) >= DEAD_SOURCE_THRESHOLD:
                    dead_source_rows.append(entry)
                else:
                    persistent_err_rows.append(entry)
            continue
        # D 列に変化があるかどうか判定
        new_d = "○" if r["is_sold"] else ""
        old_d = (r.get("current_sold") or "").strip()
        # 成功行の AK clear は「前 cycle に marker があった行のみ」(= 無駄な全行書込を回避)
        clear_err = bool((r.get("err_flag_prev") or "").strip())
        if new_d == old_d:
            # 変化なし → O 列のみ更新 (D 列はそのまま)
            #   AK 列 = 成功したので clear ("") → 前 cycle のエラー marker を消す (自己修復)
            upd = {
                "row_index":  r["row_index"],
                "checked_at": checked_at_now,
                "o_only":     True,
            }
            if clear_err:
                upd["err_flag"] = ""
            if price_jpy is not None:
                upd["price_jpy"] = price_jpy   # → sheet_updater が M列(12) に書込
                upd["prev_n_jpy_str"] = prev_n
                # K列(11) 基本ポイント: amazon の在庫あり行のみ (HQ 2026-07-22)。
                # 表示なし→0 (確定観測)、 fetch 失敗は上の price_jpy=None で弾かれ不触。
                # = 同一フェッチ・同一巡回で M と K を一貫更新 (旧F−現pt の N過小を構造的に防ぐ)。
                if r.get("supplier") == "amazon":
                    _pts = r.get("points_jpy")
                    upd["points_jpy"] = (_pts if isinstance(_pts, int)
                                         and not isinstance(_pts, bool) and _pts >= 0 else 0)
            updates.append(upd)
        else:
            # 変化あり → D + O 両方更新 (前 cycle marker あれば AK も clear)
            upd = {
                "row_index":  r["row_index"],
                "is_sold":    r["is_sold"],
                "checked_at": checked_at_now,
            }
            if clear_err:
                upd["err_flag"] = ""
            # 売切日時 (AO): 行が完全売切 (newly_sold = D ""→○) になった瞬間を 1 回記録 (churn 用)。
            if r.get("delta") == "newly_sold":
                upd["sold_at"] = checked_at_now
            # ★ 在庫復活 (newly_in_stock = D ○→空) では AO を clear する (2026-07-29 HQ 指摘)。
            #   AO は「その行が今 売切である日時」の意味。復活後も残すと在庫あり行に売切日時が
            #   残り、Days to Sell 集計・CULL/RESTOCK 判断・人の目視を誤らせる (実測 39 行)。
            #   売切→復活の履歴は decision_log (listings_*.jsonl / diff_*.md) に残るので失われない。
            elif r.get("delta") == "newly_in_stock":
                upd["clear_sold_at"] = True
            if price_jpy is not None:
                upd["price_jpy"] = price_jpy   # → sheet_updater が M列(12) に書込
                upd["prev_n_jpy_str"] = prev_n
                # K列(11) 基本ポイント: amazon の在庫あり行のみ (HQ 2026-07-22)。
                # 表示なし→0 (確定観測)、 fetch 失敗は上の price_jpy=None で弾かれ不触。
                # = 同一フェッチ・同一巡回で M と K を一貫更新 (旧F−現pt の N過小を構造的に防ぐ)。
                if r.get("supplier") == "amazon":
                    _pts = r.get("points_jpy")
                    upd["points_jpy"] = (_pts if isinstance(_pts, int)
                                         and not isinstance(_pts, bool) and _pts >= 0 else 0)
            updates.append(upd)

    # ── 補URL 売切消込の候補収集 (懸念2: fail-closed) ──
    # backup_slot_results (固定 5 枠 positional) の is_sold=True 枠のみ = 売切確定の補URL。
    # error/None (uncertain) は消さない。主URL (slot 概念外) は対象外。実 clear は下で compare-and-clear。
    clear_candidates = []
    for r in results:
        slots = r.get("backup_slot_results")
        if not slots:
            continue
        for s in slots:
            if s and s.get("is_sold") is True and s.get("url"):
                clear_candidates.append({
                    "row_index":    r["row_index"],
                    "slot":         s["slot"],           # 0-4 = AC-AG
                    "expected_url": s["url"],
                })

    price_surge_held: list = []    # 価格急増ガードで M/K を HOLD した supplier (return で run_cycle へ)
    price_surge_stats: dict = {}
    backup_clear_result: dict = {"cleared": 0, "skipped_mismatch": [], "held": False,
                                 "candidate_count": len(clear_candidates), "surge": False}
    if dry_run:
        log("  [DRY RUN] スプシ書込 skip")
        for r in [x for x in results if x["delta"] in ("newly_sold", "newly_in_stock")][:10]:
            log(f"    変化検知サンプル: row{r['row_index']} {r['delta']} {r['url'][:50]}")
        # POC 実証: 補URL消込の候補を dry-run で提示 (実書込なし)。fail-closed で is_sold=True のみ。
        if clear_candidates:
            log(f"  [DRY RUN] 補URL消込 候補 {len(clear_candidates)} 件 (is_sold=True 確定のみ、実 clear なし):")
            for c in clear_candidates[:15]:
                log(f"    row{c['row_index']} slot{c['slot']}({_col_letter(29 + c['slot'])}) "
                    f"→ clear対象 {c['expected_url'][:55]}")
    elif updates:
        d_count = sum(1 for u in updates if not u.get("o_only"))
        n_count = sum(1 for u in updates if u.get("price_jpy") is not None)
        o_count = len(updates)
        e_count = sum(1 for u in updates if "err_flag" in u)
        log(f"  スプシ書込中... 全 {o_count} 行 (D 列変化 {d_count} 件 + N 列価格 {n_count} 件 + O 列 {o_count} 件 + AK巡回ERR {e_count} 件)")
        try:
            # ★ per-sheet ゲート (HQ 一連の依頼):
            #   移行済シートは現在価格を M(13)、未移行は従来 N(14) に書く (col13 破損回避)。
            #   2026-07-22: LOW 移行 → 2026-07-22: HIGH も col13='現在価格(円)'/〇0件 準備完了で移行
            #   (high_migration_go、実機再確認済 col11='ポイント(円)'/col13='現在価格(円)')。
            #   K(ポイント): 2026-07-23 抽出 defect 修正 (3a58a60 同期) 完了 → 再開 (enable_points=True、
            #   points_write_resume_go)。両シート対象、表示なし=0/fetch失敗=不触/Amazon行のみ。
            MIGRATED_SHEET_IDS = {LOW_SHEET_ID, HIGH_SHEET_ID}
            migrated = (sheet_id in MIGRATED_SHEET_IDS)
            price_col = LISTINGS_COL_PRICE_NOW_M if migrated else LISTINGS_COL_PRICE_NOW
            # AO ヘッダ (売切日時) を先に用意 (sold_at 書込 or 消込候補があれば)。消込候補の有無に依らず
            # newly_sold 行の sold_at が書かれる時にヘッダが付くようにする (別ラベル在なら no-op=破損回避)。
            if any(u.get("sold_at") for u in updates) or clear_candidates:
                try:
                    ensure_sold_at_header(ws)
                except Exception as _he:
                    log(f"  [!] 売切日時ヘッダ設定 skip: {type(_he).__name__}: {_he}")
            res = update_listings_sold_marks(
                ws, updates, price_col_idx=price_col, enable_points=True)
            _price_letter = _col_letter(price_col)
            log(f"  [OK] updated={res['updated']} (d_writes={res.get('d_writes', '?')} / price[{_price_letter}]_writes={res.get('m_writes', '?')} / k_writes={res.get('k_writes', '?')} / o_writes={res.get('o_writes', '?')} / err_writes={res.get('err_writes', '?')} / sold_at_writes={res.get('sold_at_writes', 0)} / sold_at_clears={res.get('sold_at_clears', 0)})")
            # ★ 価格急増ガード: HOLD 対象 supplier があれば prominent に告知 (非 silent)。
            #   D/O(取下げ) は書けている = fail-OPEN ではない。M/K(価格) のみ保留 = 誤汚染を防ぐ側。
            price_surge_held = res.get("surge_held") or []
            price_surge_stats = res.get("surge_stats") or {}
            if price_surge_held:
                _held_desc = ", ".join(
                    f"{s}({price_surge_stats.get(s, {}).get('surged', '?')}/{price_surge_stats.get(s, {}).get('total', '?')})"
                    for s in price_surge_held)
                log(f"  [★価格急増ガード発火] supplier={_held_desc} の M/K 書込を HOLD "
                    f"(前M比 ±{int(PRICE_SURGE_THRESHOLD*100)}%超が過半)。見送り {res.get('m_held', 0)} 行。"
                    f"scraper 系統崩壊疑い → 要 DOM 検体確認。D/O は正常書込。")

            # ★ 補URL 売切消込 (compare-and-clear + 消込急増ガード)。sold_at と別 API (書込直前 re-read)。
            #   D/O(取下げ) は上で書けている = 消込の HOLD/mismatch は fail-OPEN ではない (延命枠の衛生管理)。
            if clear_candidates:
                backup_clear_result = clear_sold_backup_cells(ws, clear_candidates)
                # ★ 消したものを復元用アーカイブに追記 (データ安全: 誤削除でも URL を残す)。
                _cleared_entries = backup_clear_result.get("cleared_entries") or []
                if _cleared_entries:
                    try:
                        with open(CLEARED_BACKUPS_ARCHIVE, "a", encoding="utf-8") as _af:
                            for _e in _cleared_entries:
                                _af.write(json.dumps(
                                    {**_e, "sheet": sheet_label, "item_id":
                                     next((r.get("item_id", "") for r in results
                                           if r["row_index"] == _e["row_index"]), ""),
                                     "ts": checked_at_now, "reason": "cycle_auto_clear"},
                                    ensure_ascii=False) + "\n")
                    except Exception as _ae:
                        log(f"  [!] 消込アーカイブ追記失敗 (削除は成功): {type(_ae).__name__}: {_ae}")
                bc = backup_clear_result
                if bc.get("surge") or bc.get("held"):
                    log(f"  [★補URL消込 急増ガード発火] 候補 {bc['candidate_count']} 件 > 閾値 "
                        f"→ 一括消込を保留。snkrdunk 正確化済のため通常 genuine backlog → "
                        f"`python -m tools.supervised_backup_drain --label HIGH [--execute]` で消込。")
                else:
                    log(f"  [OK] 補URL消込: cleared={bc['cleared']} / candidate={bc['candidate_count']} "
                        f"/ skipped(HQ差替等 mismatch)={len(bc['skipped_mismatch'])}")
                    if bc["skipped_mismatch"]:
                        log(f"  [⚠要対応] 補URL消込 mismatch {len(bc['skipped_mismatch'])} 件 "
                            f"(セル値≠確認URL = HQ差替/変化、silent drop せず記録)")
        except Exception as e:
            log(f"  [NG] スプシ書込失敗: {type(e).__name__}: {e}")
            log(traceback.format_exc())

        # AC-AG (補 URL) 色塗り: 補 URL 設定 row のみ paint。売切は赤字、それ以外は黒字。
        # ★ 2026-07-25: backup_slot_results (固定 5 枠 positional、空枠=None) を列番号ベースで参照。
        #   旧実装は sub_results の詰めた index を列に対応させており、消込で穴ができるとズレた (懸念1)。
        paints = []
        for r in results:
            slots = r.get("backup_slot_results")
            if not slots or all(s is None for s in slots):
                continue   # 補 URL なし → スキップ
            states = []
            for slot_i in range(5):   # slot 0-4 = AC-AG (列 29-33)
                s = slots[slot_i] if slot_i < len(slots) else None
                if s is None:
                    states.append("unknown")           # 補 URL 空欄
                elif s.get("is_sold") is True:
                    states.append("sold")
                elif s.get("is_sold") is False:
                    states.append("in_stock")
                elif s.get("error"):
                    states.append("error")
                else:
                    states.append("unknown")
            paints.append({"row_index": r["row_index"], "states": states})
        if paints:
            log(f"  AC-AG セル色塗り中... {len(paints)} 行")
            try:
                pres = paint_backup_url_cells(ws, paints)
                log(f"  [OK] 色塗り完了 (赤={pres['red_cells']} / 黒={pres['default_cells']})")
            except Exception as e:
                log(f"  [!] 色塗り失敗 (本筋に影響なし): {type(e).__name__}: {e}")
    else:
        log("  書込対象なし")

    # decision_log は dry_run でも記録
    append_decision_log(sheet_label, results, dry_run)

    # ── 補URL救済ログ (フック2、遷移ベース dedup) ──
    # 救済 = 主URL死確定 AND 補URL≥1本 在庫あり (Phase1 救済率 signal)。前 cycle に救済状態でなかった
    # キーが今 cycle 救済 = 「救済状態への遷移」= 1 回記録 (延べ cycle 水増し防止)。復活→再死は再カウント。
    rescue_result = {"new_events": 0, "current_rescued": 0, "appended": 0}
    rescued_now = {}
    for r in results:
        if r.get("rescued"):
            rescued_now[_rescue_key(r)] = r
    rescue_result["current_rescued"] = len(rescued_now)
    prev_rescued = load_rescue_state(sheet_label)
    new_keys = [k for k in rescued_now if k not in prev_rescued]
    if new_keys:
        events = []
        for k in new_keys:
            r = rescued_now[k]
            d = r.get("rescue_detail", {})
            events.append({
                "date":        checked_at_now,
                "item_id":     r.get("item_id", ""),
                "title":       r.get("title", ""),
                "backup_slot": _col_letter(29 + d.get("backup_slot", 0)),  # AC-AG
                "main_status": d.get("main_status", ""),
                "backup_url":  d.get("backup_url", ""),
            })
        rescue_result["new_events"] = len(events)
        # 監査用ローカル jsonl は dry_run でも残す (証跡)
        try:
            with open(RESCUE_EVENTS_FILE, "a", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps({**e, "sheet": sheet_label, "dry_run": dry_run},
                                       ensure_ascii=False) + "\n")
        except Exception as _re:
            log(f"  [!] 救済ログ jsonl 追記失敗: {type(_re).__name__}: {_re}")
        log(f"  [補URL救済] 新規救済 {len(events)} 件 (主死→補で延命)。現在救済中 {len(rescued_now)} 件。")
        if not dry_run:
            try:
                ap = append_rescue_log_rows(ws.spreadsheet, events)
                rescue_result["appended"] = ap["appended"]
                log(f"  [OK] 補URL救済ログ タブ追記 {ap['appended']} 件 → {ap['tab']}")
            except Exception as _ae:
                log(f"  [!] 補URL救済ログ タブ追記失敗 (jsonl は保存済): {type(_ae).__name__}: {_ae}")
    # 状態保存は実巡回のみ (dry_run は遷移基準を汚さない = 実巡回で確実に記録させる)
    if not dry_run:
        try:
            save_rescue_state(sheet_label, set(rescued_now.keys()))
        except Exception as _se:
            log(f"  [!] 救済 state 保存失敗: {type(_se).__name__}: {_se}")

    if persistent_err_rows:
        _risk = sum(1 for e in persistent_err_rows if e.get("listing_risk"))
        log(f"  ⚠️ 持続エラー (連続{PERSISTENT_THRESHOLD}〜{DEAD_SOURCE_THRESHOLD - 1}回、回復待ち): "
            f"{len(persistent_err_rows)} 件 (うち出品生存 {_risk} 件)")
        for er in persistent_err_rows[:10]:
            log(f"     row{er['row_index']} ×{er['count']} {er['url'][:60]}")
    if dead_source_rows:
        _risk = sum(1 for e in dead_source_rows if e.get("listing_risk"))
        log(f"  ⚠️ 死んだ仕入元 (連続{DEAD_SOURCE_THRESHOLD}回以上 = 自己回復しない、URL 差替が要る): "
            f"{len(dead_source_rows)} 件 (うち出品生存 {_risk} 件)")
        for er in dead_source_rows[:10]:
            log(f"     row{er['row_index']} ×{er['count']} "
                f"{'[出品生存]' if er.get('listing_risk') else '[出品リスク無]'} {er['url'][:60]}")

    # ── 復活 (revive) パス — 2 cycle 連続確定判定 → pending_revive.jsonl enqueue ──
    # ★ 2026-08-07 revive_qty1_impl §6: newly_in_stock は 1 cycle だけの誤検知
    # (Amazon Featured Offer flakiness 等) を弾くため 2 cycle 連続で確定した行のみ enqueue。
    # ここで pending に積むだけで、 URL白 / 3点セット / 採算 / 二重出品 の 4 gate は
    # revive_csv_generator (Phase 2.5/3.5) が改めて掛ける (fail-closed 多層)。
    revive_result = {"promoted": 0, "first_seen": 0, "cleared": 0, "stayed": 0}
    try:
        revive_result = confirm_and_enqueue_revive(sheet_label, results, dry_run=dry_run)
        if revive_result["promoted"] or revive_result["first_seen"]:
            log(f"  [復活 gate] promoted={revive_result['promoted']} "
                f"(2cycle 確定 → pending_revive.jsonl) / "
                f"first_seen={revive_result['first_seen']} (1cycle 目、次回確定待ち) / "
                f"cleared={revive_result['cleared']} (幻の in_stock 削除) / "
                f"stayed={revive_result['stayed']} (温存)")
    except Exception as _re:
        log(f"  [!] revive gate 例外 (本筋に影響なし): {type(_re).__name__}: {_re}")

    log(f"  完了 [{sheet_label}]")
    return {
        "processed":            len(results),
        "newly_sold":           newly_sold,
        "newly_in_stock":       newly_in_stock,
        "errors":               errors,
        "url_alerts":           url_alerts,
        "error_rows":           error_rows,
        "persistent_err_rows":  persistent_err_rows,
        "dead_source_rows":     dead_source_rows,
        "price_surge_held":     price_surge_held,   # 価格急増ガードで HOLD した supplier 一覧
        "price_surge_stats":    price_surge_stats,
        "backup_clear":         backup_clear_result,  # 補URL消込結果 (cleared/skipped_mismatch/held/surge)
        "rescue":               rescue_result,        # 補URL救済 (new_events/current_rescued/appended)
        "revive":               revive_result,        # 復活 2cycle 確定 (promoted/first_seen/cleared/stayed)
    }


# ============================================================================
# main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="HIGH/LOW 商品管理シートの在庫監視 (Phase 2)")
    parser.add_argument("--sheet", choices=["high", "low", "both"], default="high",
                        help="対象 spreadsheet (default: high)")
    parser.add_argument("--start", type=int, default=2, help="開始行 (1-based, default: 2)")
    parser.add_argument("--end", type=int, default=None, help="終了行 (inclusive, None なら全件)")
    parser.add_argument("--limit", type=int, default=None, help="最大処理件数 (start からの相対)")
    parser.add_argument("--dry-run", action="store_true", help="スプシ書込なし、判定のみ")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SEC,
                        help=f"1リクエストごとの sleep 秒 (default: {DEFAULT_SLEEP_SEC})")
    parser.add_argument("--supplier",
                        choices=["all", "mercari", "amazon", "fril", "snkrdunk"],
                        default="all",
                        help="特定 supplier のみ処理 (default: all)")
    # TEST スプシ向けの sheet ID 上書き (env var fallback)
    parser.add_argument("--high-sheet-id", default=os.environ.get("INVENTORY_HIGH_SHEET_ID"),
                        help="HIGH 用 spreadsheet ID 上書き (env: INVENTORY_HIGH_SHEET_ID)")
    parser.add_argument("--low-sheet-id", default=os.environ.get("INVENTORY_LOW_SHEET_ID"),
                        help="LOW 用 spreadsheet ID 上書き (env: INVENTORY_LOW_SHEET_ID)")
    # 単一スプシ mode (Phase 6a): HIGH/LOW なしで任意 1 件指定
    parser.add_argument("--sheet-id", default=None,
                        help="単一スプシ mode: 指定 ID のみ処理 "
                             "(--high-sheet-id/--low-sheet-id と排他、--sheet 引数は無視)")
    parser.add_argument("--sheet-label", default="SHEET",
                        help="--sheet-id 使用時のラベル (decision_log ファイル名用、default: SHEET)")
    args = parser.parse_args()

    # 単一スプシ mode (Phase 6a)
    if args.sheet_id:
        if args.high_sheet_id or args.low_sheet_id:
            log("[NG] --sheet-id と --high-sheet-id/--low-sheet-id は併用不可")
            sys.exit(2)
        log(f"  単一スプシ mode: label={args.sheet_label} id={args.sheet_id[:25]}...")
        targets = [(args.sheet_label, args.sheet_id)]
    else:
        # 既存 HIGH/LOW モード (互換維持)
        high_id = args.high_sheet_id or HIGH_SHEET_ID
        low_id = args.low_sheet_id or LOW_SHEET_ID
        if args.high_sheet_id or args.low_sheet_id:
            log(f"  [!] TEST モード: HIGH={high_id[:25]}... LOW={low_id[:25]}...")
        targets = []
        if args.sheet in ("high", "both"):
            targets.append(("HIGH", high_id))
        if args.sheet in ("low", "both"):
            targets.append(("LOW", low_id))

    grand = {"processed": 0, "newly_sold": 0, "newly_in_stock": 0, "errors": 0}
    for label, sid in targets:
        try:
            stats = process_sheet(
                sheet_id=sid,
                sheet_label=label,
                start_row=args.start,
                end_row=args.end,
                limit=args.limit,
                dry_run=args.dry_run,
                sleep_sec=args.sleep,
                supplier_filter=args.supplier,
            )
            for k, v in stats.items():
                grand[k] = grand[k] + v
        except Exception as e:
            log(f"[NG] [{label}] 例外: {type(e).__name__}: {e}")
            log(traceback.format_exc())

    log("=" * 60)
    log(f"全体集計: {grand}")
    log("=" * 60)


if __name__ == "__main__":
    main()
