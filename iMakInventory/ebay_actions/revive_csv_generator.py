"""revive_csv_generator - 復活 (qty=0 → qty=1) 用 FileExchange CSV を生成.

対称構造: revise_csv_generator (取下げ) の対称。 pending_revive.jsonl から候補を取り、
4 段 gate (URL白 → 3点セット → 二重出品 → 採算) を掛けて qty=1 化 CSV を出力する。

★ 2026-08-07 revive_qty1_impl_response.md の本実装。 依頼書 §「仕様」 の5点と
「完了条件」 の6点を満たす。 gate 順序は「API を消費する採算を最後」 原則で組む
(上流で落とせるものは先に落とす)。

入力:
  decision_log/pending_revive.jsonl  (monitor_listings.confirm_and_enqueue_revive が
    2 cycle 連続 in_stock 確定した行を enqueue したもの)

gate 順:
  ① URL白リスト     : 「在庫数を持つ仕入元」 のみ復活 (fail-closed)
  ② 3点セット       : D=空 AND AK(巡回ERR)=空 AND O(チェック時刻)=直近cycle内
  ③ 二重出品        : 同 canonical KEY (AI列) の別 itemID が live かつ qty>0 なら復活しない
  ④ 採算            : pricing_engine 推奨価格 ≤ 現在の出品価格 なら OK (書かない)

出力:
  csv_output/revive_<sheet_label>_<ts>.csv  (FileExchange 形式 / Quantity=1)
  decision_log/revive_<ts>.jsonl            (INCLUDED / DEFERRED / HOLD 各理由付き)
  decision_log/revive_price_hold_<ts>.jsonl (採算割れ = 「価格改定待ち」 別出力)

急増ガード:
  INVENTORY_REVIVE_BURST_THRESHOLD (env、初期値 10) 超で全件 HOLD → action_required.jsonl。
  誤検知で大量復活が発火すると履行不能 → BAN 直撃なので、 対称 (newly_sold burst) より厳しめ。

初回スパイク用:
  --max-per-cycle N で 1 cycle で流す件数を絞る (窓口: 初回 20 件ずつ 5 バッチ分割)。

使用例:
  python -m ebay_actions.revive_csv_generator --dry-run
  python -m ebay_actions.revive_csv_generator --sheet both
  python -m ebay_actions.revive_csv_generator --max-per-cycle 20
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# pricing_engine (別ディレクトリ、 同一 worktree の iMakeBayAPI 配下) を通す
_PRICING_ENGINE_PATH = ROOT_DIR.parent / "iMakeBayAPI"
if str(_PRICING_ENGINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PRICING_ENGINE_PATH))

from sheet_updater import (  # noqa: E402
    HIGH_SHEET_ID,
    LOW_SHEET_ID,
    LISTINGS_GID,
    open_sheet_by_id,
    get_listings_worksheet,
    read_listings_rows,
    is_restockable_url,
    resolve_pricing_category,
)


DECISION_LOG_DIR = ROOT_DIR / "decision_log"
CSV_OUTPUT_DIR = ROOT_DIR / "csv_output"
PENDING_REVIVE_FILE = DECISION_LOG_DIR / "pending_revive.jsonl"
PROCESSED_REVIVE_FILE = DECISION_LOG_DIR / "processed_revive.jsonl"

SOLD_MARKERS = ("○", "〇")

# FileExchange 標準ヘッダ (取下げ CSV と同一、 Quantity のみ "1")
CSV_HEADER = [
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "ItemID",
    "*Quantity",
]
CSV_ACTION = "Revise"
CSV_QUANTITY = "1"

# ★ 急増ガード: 誤検知で大量復活 → 履行不能 → BAN の血流を作らない (fail-closed)。
# 対称の newly_sold burst (30) より厳しい 10 = 「復活は毎日 1〜数件、10 超は構造異常疑い」。
# 依頼書 §「仕様」 の④「INVENTORY_REVIVE_BURST_THRESHOLD 新設、初期値 10」 に合わせる。
DEFAULT_REVIVE_BURST_THRESHOLD = int(
    os.environ.get("INVENTORY_REVIVE_BURST_THRESHOLD", "10")
)

# per-cycle 上限。 ★ 2026-08-13: 既定 None (無制限) → 50。
# 誤復活を止める本体は「新規基準の急増ガード」(下記) であって、この上限ではない。上限を
# 絞りすぎると backlog の解消に何日もかかり、その間ずっと売れない (機会損失)。
# 50 = 通常の新規発生 (実測 ~30/日) を 1 cycle で捌ける値。CLI --max-per-cycle で override。
DEFAULT_MAX_PER_CYCLE: Optional[int] = int(
    os.environ.get("INVENTORY_REVIVE_MAX_PER_CYCLE", "50")
)

# 急増ガードの「新規」判定窓 (前回実行時刻が取れない初回のみの fallback)。
# ★ 総数で判定すると、詰まった backlog 自体が毎 cycle ガードを発火させ、永久に 1 件も
#   復活しない (08-08〜08-13 に実際そうなった)。系統崩壊は「新規が一気に湧く」形で出る。
# 通常は revive_last_run.json の「前回実行以降」= 1 cycle 分で数える (24h 固定窓だと
# 4〜8h 間隔の cycle 数回分をまとめて数えてしまい、正常でも閾値を超える)。
REVIVE_BURST_NEW_WINDOW_H = int(
    os.environ.get("INVENTORY_REVIVE_BURST_WINDOW_H", "8")
)

_JST_DT_FMT = "%Y/%m/%d %H:%M:%S"


# ============================================================================
# pending_revive queue 読込
# ============================================================================
def read_pending_revive() -> list:
    """pending_revive.jsonl を読込、 entry list を返す (壊れた行は skip)。"""
    if not PENDING_REVIVE_FILE.exists():
        return []
    entries = []
    with open(PENDING_REVIVE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def drain_pending_revive(consumed_item_ids: list[str]) -> int:
    """upload 成功 item を processed_revive.jsonl に archive、 pending から除去。

    revise 側の drain_pending_queue 対称。 失敗 item は pending 残置 → 次 cycle 再試行。
    """
    if not PENDING_REVIVE_FILE.exists() or not consumed_item_ids:
        return 0
    consumed = set(consumed_item_ids)
    moved = 0
    keep = []
    with open(PENDING_REVIVE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                keep.append(line)
                continue
            if entry.get("item_id") in consumed:
                entry["consumed_at"] = datetime.now().isoformat(timespec="seconds")
                with open(PROCESSED_REVIVE_FILE, "a", encoding="utf-8") as af:
                    af.write(json.dumps(entry, ensure_ascii=False) + "\n")
                moved += 1
            else:
                keep.append(line)
    PENDING_REVIVE_FILE.write_text(
        ("\n".join(keep) + "\n") if keep else "",
        encoding="utf-8",
    )
    return moved


DISCARDED_REVIVE_FILE = DECISION_LOG_DIR / "discarded_revive.jsonl"
REVIVE_PENDING_MAX_AGE_DAYS = 7


def prune_unresolvable_pending_revive(skipped: list) -> int:
    """シート上に itemID が存在しない古い entry を queue から退避する。

    ★ 2026-08-13: pending_revive は「復活できた時」しか drain されない設計だったため、
      行が消えた商品の entry が永久に残り、queue が単調増加していた (08-08→08-13 で 145 件)。
      解決不能かつ古いものは archive に逃がす。誤って捨てても discarded_revive.jsonl から
      復元できる (silent drop 禁止)。

    条件: skip_reason が row_not_found_by_item_id で、queue 投入から
          REVIVE_PENDING_MAX_AGE_DAYS 日以上経過。
    """
    stale_ids = set()
    now = datetime.now()
    for s in skipped:
        if s.get("skip_reason") != "row_not_found_by_item_id":
            continue
        ts = (s.get("ts") or s.get("queue_ts") or "")[:19]
        try:
            age_days = (now - datetime.fromisoformat(ts)).days
        except ValueError:
            continue
        if age_days >= REVIVE_PENDING_MAX_AGE_DAYS and s.get("item_id"):
            stale_ids.add(s["item_id"])
    if not stale_ids or not PENDING_REVIVE_FILE.exists():
        return 0

    moved, keep = 0, []
    with open(PENDING_REVIVE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                keep.append(line)
                continue
            if entry.get("item_id") in stale_ids:
                entry["discarded_at"] = now.isoformat(timespec="seconds")
                entry["discard_reason"] = "row_not_found_by_item_id_expired"
                with open(DISCARDED_REVIVE_FILE, "a", encoding="utf-8") as af:
                    af.write(json.dumps(entry, ensure_ascii=False) + "\n")
                moved += 1
            else:
                keep.append(line)
    PENDING_REVIVE_FILE.write_text(
        ("\n".join(keep) + "\n") if keep else "", encoding="utf-8")
    return moved


# ============================================================================
# gate ② 3点セット (D=空 AND AK=空 AND O=直近 cycle 内)
# ============================================================================
def is_actively_in_stock(row: dict, cycle_started_at: datetime) -> tuple[bool, str]:
    """(D=空 AND AK=空 AND O が cycle_started_at 以降) を満たすか。

    満たさない = 判定不能で前状態が残っているだけ (fail-closed で復活しない)。

    Returns: (ok: bool, reason: str)
    """
    if (row.get("current_sold") or "").strip():
        return False, "d_marked_sold"
    if (row.get("err_flag_prev") or "").strip():
        return False, "ak_has_err_marker"
    checked_at = (row.get("checked_at") or "").strip()
    if not checked_at:
        return False, "o_empty"
    try:
        t = datetime.strptime(checked_at, _JST_DT_FMT)
    except ValueError:
        return False, "o_unparseable"
    if t < cycle_started_at:
        return False, "o_older_than_current_cycle"
    return True, "ok"


# ============================================================================
# gate ③ 二重出品 (同 KEY の別 itemID が live かつ qty>0)
# ============================================================================
def check_no_duplicate_live(row: dict, active_qty_map: Optional[dict],
                             sheet_key_map: dict) -> tuple[bool, str]:
    """同 canonical KEY (AI列) の別 itemID が eBay で live かどうか。

    Args:
        active_qty_map: {item_id: qty}。 None なら「eBay 状態不明」 = 温存 (fail-open だが
                        KEY 突合で候補が0件のときは判定不要 = call しない)
        sheet_key_map:  {KEY: [item_id, ...]} = シートから構築

    Returns: (ok=True, "ok") / (ok=False, reason)
      KEY 空欄は突合 skip (= "no_key" 通し、 decision_log で計上)
    """
    key = (row.get("key_number") or "").strip()
    if not key:
        # 依頼書 §12-2 追記: KEY 空欄行は元々 1点もの中心 = 復活対象外なので実害小、
        # ただし件数を decision_log に必ず載せる (窓口が見張る)
        return True, "no_key"
    own_iid = (row.get("item_id") or "").strip()
    same_key_ids = [iid for iid in sheet_key_map.get(key, []) if iid and iid != own_iid]
    if not same_key_ids:
        return True, "ok_no_same_key_others"
    if active_qty_map is None:
        # qty_map 無し = eBay 状態不明 → 「同 KEY の別 iid あり、 生存状況不明」 で温存
        # (fail-closed 側: 復活しない)。 依頼書 §5 「窓口の今日の実測では衝突0件」 = 通常
        # ここには来ないが、 レア発生時は「復活しない」 を選ぶ
        return False, f"duplicate_key_unknown_qty_key={key}_others={len(same_key_ids)}"
    for iid in same_key_ids:
        qty = active_qty_map.get(iid) or 0
        if qty > 0:
            return False, f"duplicate_live_key={key}_iid={iid}_qty={qty}"
    return True, "ok"


def build_sheet_key_map(rows: list) -> dict:
    """{KEY: [item_id, ...]} を作る。 KEY 空欄・itemID 空欄は含めない。"""
    m: dict = {}
    for r in rows:
        key = (r.get("key_number") or "").strip()
        iid = (r.get("item_id") or "").strip()
        if not key or not iid:
            continue
        m.setdefault(key, []).append(iid)
    return m


# ============================================================================
# gate ④ 採算 (pricing_engine)
# ============================================================================
def _load_pricing_engine():
    """遅延 import (import failure でも monitor 本体は動く fail-safe)。"""
    from pricing_engine import compute_listing_price  # noqa: PLC0415
    return compute_listing_price


def _parse_int_yen(s) -> Optional[int]:
    """スプシ生文字列 (¥1,500 / '1500' / '') → int(円)。 不能 → None。"""
    if s is None:
        return None
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def resolve_cost_jpy(row: dict) -> Optional[int]:
    """行から仕入値 (円) を解決。

    V8 SSOT: 「今の最安値 = M または F」 を採る (memory: amazon_points_net_cost_system +
    an_column_abolished)。 M 列 (現在価格) を優先 → 空なら F 列 (出品時価格)。
    """
    m = _parse_int_yen(row.get("current_m_jpy_str"))
    if m is not None and m > 0:
        return m
    # F 列は read_listings_rows の "price" (LISTINGS_COL_PRICE=6)。 raw 文字列を parse。
    f = _parse_int_yen(row.get("price"))
    if f is not None and f > 0:
        return f
    return None


def check_pricing_gate(row: dict, cur_price_usd: Optional[float],
                        compute_fn=None) -> tuple[str, dict]:
    """採算 gate。 「推奨価格 ≤ 現在の出品価格 → 復活可」 の単純比較のみ。

    Args:
        row:          read_listings_rows dict (+ pending entry 由来)
        cur_price_usd: eBay GetItem で取った現在の StartPrice (USD)。 None なら
                      "skip_no_price" (復活しない、 fail-closed)
        compute_fn:   pricing_engine.compute_listing_price (テスト用 injection)

    Returns: (verdict, detail)
      verdict:
        "ok"                     : 復活可
        "hold_below_recommended" : 推奨価格 > 現在価格 = 価格改定待ち
        "skip_no_cost"           : 仕入値が取れず fail-closed
        "skip_no_price"          : eBay 現在価格が取れず fail-closed
        "skip_no_category"       : R 列 カテゴリ不明 / CAT2CALC 未対応
        "skip_pricing_engine_err": pricing_engine.compute_listing_price が ValueError 等
    """
    cost_jpy = resolve_cost_jpy(row)
    if cost_jpy is None:
        return "skip_no_cost", {"reason": "no_cost_source"}
    if cur_price_usd is None:
        return "skip_no_price", {"reason": "no_ebay_start_price"}

    cat_pricing = resolve_pricing_category(row.get("category") or "")
    if cat_pricing is None:
        # 依頼書 §12-1: 変換できないカテゴリは fail-closed で復活させない
        # ("価格改定待ち" ではなく skip_no_category として別計上)
        return "skip_no_category", {
            "reason": "cat_not_in_map",
            "cat_sheet": row.get("category") or "",
        }
    if compute_fn is None:
        try:
            compute_fn = _load_pricing_engine()
        except Exception as e:
            return "skip_pricing_engine_err", {
                "reason": "import_failed",
                "error": f"{type(e).__name__}: {e}",
            }
    try:
        # median_usd=None = 「中央値なしモード」 → NO_MEDIAN status で price だけ返る
        rec = compute_fn(cost_jpy, None, cat_pricing)
    except Exception as e:
        return "skip_pricing_engine_err", {
            "reason": "compute_failed",
            "error": f"{type(e).__name__}: {e}",
            "cat_sheet": row.get("category") or "",
            "cat_pricing": cat_pricing,
            "cost_jpy": cost_jpy,
        }
    rec_price = rec.get("price") if isinstance(rec, dict) else None
    if rec_price is None:
        return "skip_pricing_engine_err", {"reason": "no_price_in_result"}

    if cur_price_usd >= rec_price:
        return "ok", {
            "cost_jpy": cost_jpy,
            "rec_usd": rec_price,
            "cur_usd": cur_price_usd,
            "cat_pricing": cat_pricing,
        }
    gap_pct = round((rec_price - cur_price_usd) / rec_price * 100, 1) if rec_price else 0.0
    return "hold_below_recommended", {
        "cost_jpy": cost_jpy,
        "rec_usd": rec_price,
        "cur_usd": cur_price_usd,
        "cat_pricing": cat_pricing,
        "gap_pct": gap_pct,
    }


# ============================================================================
# eBay GetItem — 現在 StartPrice (USD) と available qty を 1 call で取る
# ============================================================================
def _fetch_ebay_start_price_and_qty(item_id: str, token: str) -> tuple[Optional[float], Optional[int]]:
    """GetItem で <StartPrice> (USD) と available qty を取る。 verify GetItem と兼用。

    Returns: (start_price_usd, available_qty)
      失敗時: (None, None)
      err 17 (Item not found / ended): (None, 0)
    """
    if not item_id:
        return None, None
    # 循環 import 回避
    from ebay_actions.trading_api_client import _call_trading  # noqa: PLC0415
    import re as _re  # noqa: PLC0415
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f'<ItemID>{item_id}</ItemID></GetItemRequest>'
    )
    try:
        # ★ 2026-08-13: raw_xml_cap 既定 2000 文字だと <StartPrice> が切り落とされ、
        #   price=None → 採算 gate が skip_no_price で fail-closed → **復活が永久に 0 件**。
        #   実測: 09:30 cycle の deferred 149 件中 61 件がこれ。GetItem の応答は 1 商品でも
        #   2000 文字を軽く超える (同型: 単品 verify の QuantitySold 取りこぼし commit 0b7f566)。
        res = _call_trading("GetItem", body, access_token=token, raw_xml_cap=None)
    except Exception:
        return None, None
    if res.get("error_code") == "17":
        return None, 0
    if not res.get("success"):
        return None, None
    xml = res.get("raw_xml", "") or ""
    price = None
    qty = None
    m = _re.search(r'<StartPrice[^>]*>([\d.]+)</StartPrice>', xml)
    if m:
        try:
            price = float(m.group(1))
        except ValueError:
            price = None
    q_m = _re.search(r"<Quantity>(\d+)</Quantity>", xml)
    sold_m = _re.search(r"<QuantitySold>(\d+)</QuantitySold>", xml)
    if q_m:
        try:
            total_qty = int(q_m.group(1))
            sold = int(sold_m.group(1)) if sold_m else 0
            qty = max(0, total_qty - sold)
        except ValueError:
            qty = None
    return price, qty


# ============================================================================
# 候補収集 (pending_revive → sheet 突合)
# ============================================================================
def _row_key(sheet_label: str, row_index: int) -> tuple:
    return (sheet_label, row_index)


LAST_REVIVE_RUN_FILE = DECISION_LOG_DIR / "revive_last_run.json"


def load_last_revive_run(label: str) -> Optional[datetime]:
    """前回 revive を実行した時刻 (label 別)。無ければ None。"""
    try:
        d = json.loads(LAST_REVIVE_RUN_FILE.read_text(encoding="utf-8"))
        return datetime.fromisoformat(d[label])
    except Exception:
        return None


def save_last_revive_run(label: str, ts: datetime) -> None:
    try:
        d = {}
        if LAST_REVIVE_RUN_FILE.exists():
            d = json.loads(LAST_REVIVE_RUN_FILE.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                d = {}
        d[label] = ts.isoformat(timespec="seconds")
        DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        LAST_REVIVE_RUN_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass          # state が書けなくても cycle は止めない (次回は時間窓 fallback)


def count_new_candidates(candidates: list, cycle_started_at: datetime,
                          since: Optional[datetime] = None) -> int:
    """急増ガードの判定基準 = 「前回 revive 実行以降に queue へ入った候補」の数。

    ★ 2026-08-13: 当初 24h 固定窓にしたが、cycle は 4〜8h 間隔で回るため 24h では
      3〜6 cycle 分の到着をまとめて数えてしまい、正常運転でも閾値 10 を軽く超える
      (13:30 cycle で 57 と数えて全件 HOLD した)。窓は「前回実行以降」= 1 cycle 分が正しい。
    since が None (初回) のときのみ REVIVE_BURST_NEW_WINDOW_H の時間窓に fallback。
    queue_ts が読めないものは安全側 (新規扱い) に倒す。
    """
    cutoff = since or (cycle_started_at - timedelta(hours=REVIVE_BURST_NEW_WINDOW_H))
    n = 0
    for c in candidates:
        ts = (c.get("queue_ts") or "")[:19]
        try:
            if datetime.fromisoformat(ts) >= cutoff:
                n += 1
        except ValueError:
            n += 1
    return n


def _relocate_row(sheet_state: dict, label: str, item_id: str, url: str):
    """row_index がずれた entry を itemID (+URL) でシート上から引き直す。

    - itemID 一致が 1 行 → その行
    - 複数行 (同 itemID を別仕入元で管理) → URL 一致で一意に決まればその行、
      決まらなければ {"_ambiguous": True} (fail-closed: 誤った行で復活させない)
    - 0 行 → None
    """
    if not item_id:
        return None
    hits = [r for k, r in sheet_state.items()
            if k[0] == label and (r.get("item_id") or "").strip() == item_id]
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    if url:
        by_url = [r for r in hits if (r.get("url") or "").strip() == url]
        if len(by_url) == 1:
            return by_url[0]
    return {"_ambiguous": True}


def collect_from_pending_revive(
    sheet_filter: str = "both",
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    single_sheet_id: Optional[str] = None,
    single_sheet_label: Optional[str] = None,
) -> tuple[list, list, dict]:
    """pending_revive.jsonl → シート最新値と突合して候補を返す。

    ★ pending に積まれた時点 (2 cycle 前) の情報だけでは gate ②③④ を掛けられないので
    必ずシートを引き直す。 シート側で D=○ に戻っている / itemID が変わっている行は skip。

    Returns:
      candidates: gate に入れる candidate list (シート最新値 merge 済)
      skipped:    シート verify で外れた entry list (理由付き)
      sheet_key_maps: {label: {KEY: [item_id, ...]}} (二重出品 gate 用)
    """
    queue = read_pending_revive()
    if not queue:
        return [], [], {}
    # ★ 2026-08-13: 同一 itemID が cycle ごとに再投入され最大 7 重複していた。重複したまま
    #   gate に流すと候補数も急増ガードの数え上げも水増しされる。itemID 単位で最新 1 件に畳む。
    _dedup: dict = {}
    for q in queue:
        k = ((q.get("sheet") or ""), (q.get("item_id") or "").strip() or f"row:{q.get('row_index')}")
        cur = _dedup.get(k)
        if cur is None or (q.get("ts") or "") >= (cur.get("ts") or ""):
            _dedup[k] = q
    queue = list(_dedup.values())

    # sheet_state を label ごとに構築 (row_index → 最新 row dict)、
    # sheet_key_map も同時に構築
    if single_sheet_id:
        targets = [(single_sheet_label or "SHEET", single_sheet_id)]
    else:
        targets = []
        h_id = high_sheet_id or HIGH_SHEET_ID
        l_id = low_sheet_id or LOW_SHEET_ID
        if sheet_filter in ("high", "both"):
            targets.append(("HIGH", h_id))
        if sheet_filter in ("low", "both"):
            targets.append(("LOW", l_id))

    sheet_state: dict = {}
    sheet_key_maps: dict = {}
    for label, sid in targets:
        try:
            sh = open_sheet_by_id(sid)
            ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
            rows = read_listings_rows(ws, only_with_url=False)
        except Exception as e:
            print(f"  [!] [{label}] シート読込失敗: {type(e).__name__}: {e}")
            return [], queue, {}
        for r in rows:
            sheet_state[_row_key(label, r["row_index"])] = r
        sheet_key_maps[label] = build_sheet_key_map(rows)

    candidates = []
    skipped = []
    for q in queue:
        label = q.get("sheet") or ""
        # sheet_filter 適用
        if single_sheet_id:
            if label != (single_sheet_label or "SHEET"):
                skipped.append({**q, "skip_reason": "filter_single_label_mismatch"})
                continue
        else:
            if sheet_filter == "high" and label != "HIGH":
                skipped.append({**q, "skip_reason": "filter_high"})
                continue
            if sheet_filter == "low" and label != "LOW":
                skipped.append({**q, "skip_reason": "filter_low"})
                continue

        key = _row_key(label, q.get("row_index", -1))
        cur_row = sheet_state.get(key)
        q_iid = (q.get("item_id") or "").strip()
        if cur_row is not None and (cur_row.get("item_id") or "").strip() == q_iid:
            pass                                   # 行が動いていない (fast path)
        else:
            # ★ 2026-08-13: row_index は当てにならない。シートは行の挿入/削除で常時ずれる
            #   ので、queue に積んだ時の row_index は数日で別商品を指す。row_index だけで
            #   突合していたため 145 件中 84 件が item_id_changed / row_not_found として
            #   **永久に deferred**、6 日間 1 件も復活しなかった (在庫が戻っても qty=0 のまま)。
            #   itemID (+ URL) で引き直す = シート上の identity で突合する。
            cur_row = _relocate_row(sheet_state, label, q_iid, (q.get("url") or "").strip())
            if cur_row is None:
                skipped.append({**q, "skip_reason": "row_not_found_by_item_id"})
                continue
            if cur_row.get("_ambiguous"):
                # 同 itemID 複数行で URL でも一意に決まらない → fail-closed (誤復活しない)
                skipped.append({**q, "skip_reason": "ambiguous_rows_for_item_id"})
                continue
        # 復活候補: シート最新の row をそのまま candidate に載せる (gate はここから読む)
        candidates.append({
            **cur_row,
            "sheet_label": label,
            "queue_ts":    q.get("ts", ""),
            "queue_supplier": q.get("supplier", ""),
        })
    return candidates, skipped, sheet_key_maps


# ============================================================================
# gate 適用 (URL白 → 3点セット → 二重出品 → 採算)
# ============================================================================
def apply_gates(
    candidates: list,
    sheet_key_maps: dict,
    cycle_started_at: datetime,
    active_qty_map: Optional[dict],
    fetch_price_fn=None,
    compute_fn=None,
) -> tuple[list, list, list]:
    """4 段 gate 適用。

    Args:
        fetch_price_fn: (item_id) -> (start_price_usd, available_qty) の callable。
                        None なら _fetch_ebay_start_price_and_qty を token load して使う。
        compute_fn:     pricing_engine.compute_listing_price (テスト用 injection)。

    Returns: (allowed, deferred, price_hold)
      allowed:    CSV 出力対象 (qty=1 化する行)
      deferred:   fail-closed で復活しない行 (URL/3点/二重出品/カテゴリ/仕入不明 等)
      price_hold: 採算割れ (価格改定待ち) = revive_price_hold jsonl 別出力
    """
    allowed, deferred, price_hold = [], [], []

    # fetch_price_fn の遅延生成 (テスト時は injection、 本番は token 1 回 load)
    _token_holder: dict = {"token": None}

    def _resolve_price_qty(iid: str):
        if fetch_price_fn is not None:
            return fetch_price_fn(iid)
        if _token_holder["token"] is None:
            from ebay_actions.trading_api_client import load_access_token  # noqa: PLC0415
            _token_holder["token"] = load_access_token()
        return _fetch_ebay_start_price_and_qty(iid, _token_holder["token"])

    for c in candidates:
        # ① URL 白リスト
        if not is_restockable_url(c.get("url") or ""):
            deferred.append({**c, "skip_reason": "url_not_restockable",
                             "gate": "url_whitelist"})
            continue

        # ② 3点セット (D=空 AND AK=空 AND O=直近 cycle 内)
        ok, reason = is_actively_in_stock(c, cycle_started_at)
        if not ok:
            deferred.append({**c, "skip_reason": reason, "gate": "three_point"})
            continue

        # ③ 二重出品 (同 KEY の別 iid が qty>0)
        label = c.get("sheet_label", "")
        km = sheet_key_maps.get(label, {})
        ok, reason = check_no_duplicate_live(c, active_qty_map, km)
        if not ok:
            deferred.append({**c, "skip_reason": reason, "gate": "duplicate_live"})
            continue

        # ④ 採算 (最後: eBay API 消費するので上流で落とせるものは先に落とす)
        iid = (c.get("item_id") or "").strip()
        cur_price_usd = None
        if iid:
            price, ebay_qty = _resolve_price_qty(iid)
            cur_price_usd = price
            # 追加安全策: eBay がすでに qty>0 (= 何らかの理由で既に復活済) なら skip
            if ebay_qty is not None and ebay_qty > 0:
                deferred.append({**c, "skip_reason": f"ebay_already_qty_{ebay_qty}",
                                 "gate": "already_live"})
                continue
        verdict, detail = check_pricing_gate(c, cur_price_usd, compute_fn=compute_fn)
        if verdict == "ok":
            allowed.append({**c, "gate_detail": detail})
        elif verdict == "hold_below_recommended":
            price_hold.append({**c, "skip_reason": verdict, "gate": "pricing",
                               "gate_detail": detail})
        else:
            deferred.append({**c, "skip_reason": verdict, "gate": "pricing",
                             "gate_detail": detail})
    return allowed, deferred, price_hold


# ============================================================================
# CSV 出力 / decision_log
# ============================================================================
def write_revive_csv(allowed: list, output_path: Path) -> int:
    """FileExchange 形式の Revive CSV を書出 (Quantity=1)。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(CSV_HEADER)
        for c in allowed:
            iid = (c.get("item_id") or "").strip()
            if iid:
                w.writerow([CSV_ACTION, iid, CSV_QUANTITY])
    return sum(1 for c in allowed if (c.get("item_id") or "").strip())


def append_decision_log(
    sheet_labels: list,
    allowed: list,
    deferred: list,
    price_hold: list,
    csv_path: Optional[Path],
    reason: str,
    dry_run: bool,
) -> tuple[Path, Optional[Path]]:
    """decision_log/revive_<ts>.jsonl と revive_price_hold_<ts>.jsonl を書く。"""
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    main_path = DECISION_LOG_DIR / f"revive_{ts}.jsonl"
    _keep = ("sheet_label", "row_index", "item_id", "url", "title", "supplier",
             "queue_ts", "queue_supplier", "key_number", "category",
             "current_sold", "checked_at", "err_flag_prev",
             "skip_reason", "gate", "gate_detail")

    def _row(c: dict, decision: str) -> dict:
        base = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "phase": "revive_csv",
            "decision": decision,
            "csv_path": str(csv_path) if csv_path else None,
            "dry_run": dry_run,
            "reason": reason,
            "sheets": sheet_labels,
        }
        for k in _keep:
            if k in c:
                base[k] = c[k]
        return base

    with open(main_path, "w", encoding="utf-8") as f:
        for c in allowed:
            f.write(json.dumps(_row(c, "INCLUDED"), ensure_ascii=False) + "\n")
        for c in deferred:
            f.write(json.dumps(_row(c, "DEFERRED"), ensure_ascii=False) + "\n")

    hold_path = None
    if price_hold:
        hold_path = DECISION_LOG_DIR / f"revive_price_hold_{ts}.jsonl"
        with open(hold_path, "w", encoding="utf-8") as f:
            for c in price_hold:
                f.write(json.dumps(_row(c, "PRICE_HOLD"), ensure_ascii=False) + "\n")
    return main_path, hold_path


# ============================================================================
# run — main entry
# ============================================================================
def run(
    sheet: str = "both",
    dry_run: bool = False,
    max_per_cycle: Optional[int] = DEFAULT_MAX_PER_CYCLE,
    burst_threshold: Optional[int] = None,
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    single_sheet_id: Optional[str] = None,
    single_sheet_label: Optional[str] = None,
    cycle_started_at: Optional[datetime] = None,
    provided_qty_map: Optional[dict] = None,
    fetch_price_fn=None,
    compute_fn=None,
) -> dict:
    """復活 CSV を生成。 gate 4段 + 急増ガード + per-cycle 上限。

    cycle_started_at 省略時は現在時刻。 3点セット gate の O 列比較用。 テストや
    多段 cycle 統合時は run_cycle.py から明示指定する。
    """
    burst = burst_threshold if burst_threshold is not None else DEFAULT_REVIVE_BURST_THRESHOLD
    cycle_started_at = cycle_started_at or datetime.now()

    print(f"=== Revive CSV 生成 (sheet={sheet}, dry_run={dry_run}, "
          f"burst_threshold={burst}, max_per_cycle={max_per_cycle}) ===")

    candidates, skipped, sheet_key_maps = collect_from_pending_revive(
        sheet_filter=sheet,
        high_sheet_id=high_sheet_id, low_sheet_id=low_sheet_id,
        single_sheet_id=single_sheet_id,
        single_sheet_label=single_sheet_label,
    )
    print(f"  pending_revive queue → {len(candidates)} 件 (sheet verify で skip {len(skipped)})")

    allowed_raw, deferred, price_hold = apply_gates(
        candidates=candidates,
        sheet_key_maps=sheet_key_maps,
        cycle_started_at=cycle_started_at,
        active_qty_map=provided_qty_map,
        fetch_price_fn=fetch_price_fn,
        compute_fn=compute_fn,
    )
    print(f"  gate 後: allowed={len(allowed_raw)} / deferred={len(deferred)} / "
          f"price_hold={len(price_hold)}")

    # 急増ガード: gate 通過数が閾値超 → 全件 HOLD + action_required
    reason = "OK"
    burst_hold = []
    _guard_label = single_sheet_label or sheet.upper()
    new_allowed = count_new_candidates(allowed_raw, cycle_started_at,
                                       since=load_last_revive_run(_guard_label))
    if new_allowed > burst:
        print(f"  [★revive burst guard 発火] 新規 {new_allowed} 件 > 閾値 {burst} 件 "
              f"(候補 {len(allowed_raw)} 件)")
        print(f"      (= 誤検知で大量復活疑い、 fail-closed で全件 HOLD → 履行不能 → BAN 直撃を防ぐ)")
        try:
            from monitor_listings import append_action_required  # noqa: PLC0415
            for c in allowed_raw:
                append_action_required(
                    sheet_label=c.get("sheet_label", ""),
                    result={
                        "row_index": c.get("row_index", -1),
                        "url":       c.get("url", ""),
                        "item_id":   c.get("item_id", ""),
                        "title":     c.get("title", ""),
                        "supplier":  c.get("queue_supplier", "") or c.get("supplier", ""),
                        "raw_status": "revive_burst_holdout",
                    },
                    reason="revive_burst_guard_holdout",
                    dry_run=dry_run,
                )
            print(f"      → {len(allowed_raw)} 件を action_required.jsonl に記録 (silent 化禁止)")
        except Exception as e:
            print(f"  [!] action_required 記録失敗: {type(e).__name__}: {e}")
        burst_hold = allowed_raw
        allowed_raw = []
        reason = "REVIVE_BURST_HOLD"

    # per-cycle 上限適用 (初回スパイクは 20 件ずつ流す)
    truncated = []
    if max_per_cycle is not None and len(allowed_raw) > max_per_cycle:
        truncated = allowed_raw[max_per_cycle:]
        allowed = allowed_raw[:max_per_cycle]
        for c in truncated:
            deferred.append({**c, "skip_reason": "per_cycle_cap_exceeded",
                             "gate": "per_cycle_cap"})
        print(f"  [per-cycle cap] {len(allowed)} 件 revive、 残り {len(truncated)} 件は次 cycle へ")
        reason = "PER_CYCLE_CAP" if reason == "OK" else reason
    else:
        allowed = allowed_raw

    # 各 skip した pending entry を deferred に載せる (revive_csv の decision_log に写す)
    for s in skipped:
        deferred.append({**s, "gate": "pre_verify"})

    # ★ 2026-08-13: 二度と解決しない entry を queue から落とす (肥大化・恒久 deferred 防止)。
    #   itemID がシートのどこにも無い = 行が消えた/出品を畳んだ。復活のしようがないので
    #   捨てる (証跡は discarded archive に残す = silent drop にしない)。
    if not dry_run:
        try:
            n_pruned = prune_unresolvable_pending_revive(skipped)
            if n_pruned:
                print(f"  [prune] 解決不能な pending entry {n_pruned} 件を archive へ退避")
        except Exception as e:
            print(f"  [!] pending_revive prune 失敗: {type(e).__name__}: {e}")

    csv_path = None
    if not dry_run and allowed:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sheet_part = sheet.upper() if sheet != "both" else "BOTH"
        csv_path = CSV_OUTPUT_DIR / f"revive_{sheet_part}_{ts}.csv"
        n = write_revive_csv(allowed, csv_path)
        print(f"  [OK] CSV 出力: {csv_path} ({n} 行)")
    elif dry_run and allowed:
        print(f"  [DRY RUN] CSV 出力 skip ({len(allowed)} 行が対象だった)")
        for c in allowed[:5]:
            print(f"    {c.get('sheet_label')} row{c.get('row_index')}: "
                  f"{CSV_ACTION},{c.get('item_id')},{CSV_QUANTITY} "
                  f"({(c.get('title') or '')[:30]})")

    # decision_log
    log_path, hold_path = append_decision_log(
        sheet_labels=[t[0] for t in ([("HIGH", None), ("LOW", None)]
                                     if sheet == "both" and not single_sheet_id
                                     else ([( single_sheet_label or "SHEET", None )]
                                           if single_sheet_id
                                           else [(sheet.upper(), None)]))],
        allowed=allowed,
        deferred=deferred,
        price_hold=price_hold,
        csv_path=csv_path,
        reason=reason,
        dry_run=dry_run,
    )
    print(f"  decision_log: {log_path}")
    if hold_path:
        print(f"  price_hold_log: {hold_path}  (窓口 / リバイスくんが拾う)")

    # 次回の急増ガードの基準時刻 (= ここまでに queue へ入ったものは以後 backlog 扱い)
    if not dry_run:
        save_last_revive_run(_guard_label, cycle_started_at)

    return {
        "candidates": len(candidates),
        "allowed": len(allowed),
        "deferred": len(deferred),
        "price_hold": len(price_hold),
        "burst_hold": len(burst_hold),
        "reason": reason,
        "csv_path": str(csv_path) if csv_path else None,
        "log_path": str(log_path),
        "price_hold_path": str(hold_path) if hold_path else None,
        "allowed_item_ids": [(c.get("item_id") or "").strip() for c in allowed
                              if (c.get("item_id") or "").strip()],
    }


def main():
    parser = argparse.ArgumentParser(
        description="復活 (qty=1) 用 FileExchange CSV 生成 (Revise CSV の対称)")
    parser.add_argument("--sheet", choices=["high", "low", "both"], default="both")
    parser.add_argument("--dry-run", action="store_true", help="CSV 出力なし、判定のみ")
    parser.add_argument("--max-per-cycle", type=int, default=None,
                        help="1 cycle で流す最大件数 (初回スパイク時は 20 推奨)")
    parser.add_argument("--burst-threshold", type=int, default=None,
                        help="急増ガード閾値 (default: INVENTORY_REVIVE_BURST_THRESHOLD or 10)")
    parser.add_argument("--high-sheet-id", default=os.environ.get("INVENTORY_HIGH_SHEET_ID"))
    parser.add_argument("--low-sheet-id", default=os.environ.get("INVENTORY_LOW_SHEET_ID"))
    parser.add_argument("--sheet-id", default=None,
                        help="単一スプシ mode (--high-sheet-id/--low-sheet-id と排他)")
    parser.add_argument("--sheet-label", default="SHEET")
    args = parser.parse_args()

    if args.sheet_id and (args.high_sheet_id or args.low_sheet_id):
        print("[NG] --sheet-id と --high-sheet-id/--low-sheet-id は併用不可")
        sys.exit(2)

    result = run(
        sheet=args.sheet,
        dry_run=args.dry_run,
        max_per_cycle=args.max_per_cycle,
        burst_threshold=args.burst_threshold,
        high_sheet_id=args.high_sheet_id,
        low_sheet_id=args.low_sheet_id,
        single_sheet_id=args.sheet_id,
        single_sheet_label=args.sheet_label,
    )
    print()
    print(f"=== 結果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
