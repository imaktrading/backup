#!/usr/bin/env python3
"""iMak Trading Japan - Decision audit log (Step 8 minimum logger).

各リスティング決定（出品/HOLD/REJECT）を JSONL で記録し、後追い再現性を確保する。
ChatGPT 推奨最小セット: 入力 / 最終値 / config_version / エラー時スタックトレース。

ログ場所: iMakHQ/decision_logs/decisions.jsonl
1日1ファイル: decisions_YYYYMMDD.jsonl

使用例:
    from decision_log import log_decision

    log_decision(
        project="iMakTCG",
        sku="PSA-12345678",
        title="...",
        category="TCG(PSA10)",
        price_usd=199.99,
        shipping_jpy=2000,
        status="OK",            # OK / HOLD / REJECT / ERROR
        reason="3AI agreed PASS",
    )

    # エラー時:
    try:
        ...
    except Exception as e:
        log_decision(project="iMakTCG", sku="PSA-12345678",
                     status="ERROR", error=e)
"""
from __future__ import annotations
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent

LOG_DIR = WORKSPACE_ROOT / "iMakHQ" / "decision_logs"

# config_loader を遅延 import （decision_log を import するだけで yaml 読込が走らないように）
def _get_config_version() -> str:
    try:
        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))
        import config_loader
        return config_loader.get_version()
    except Exception:
        return "unknown"


def _today_log_path() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"decisions_{datetime.now().strftime('%Y%m%d')}.jsonl"


def log_decision(
    *,
    project: str,
    sku: str,
    title: str = "",
    category: str = "",
    price_usd: Optional[float] = None,
    shipping_jpy: Optional[int] = None,
    status: str = "OK",
    reason: str = "",
    error: Optional[BaseException] = None,
    extra: Optional[dict] = None,
) -> Path:
    """1件の決定を JSONL に追記.

    Args:
        project: プロジェクト名 (iMakTCG / iMakG-shock / iMakMercari / iMak_ichibankuji)
        sku: SKU / cert # / 商品ID
        title: eBay 出品タイトル
        category: yaml カテゴリ名 (TCG(PSA10) 等)
        price_usd: 最終 USD 価格
        shipping_jpy: 送料 (JPY)
        status: "OK" / "HOLD" / "REJECT" / "ERROR"
        reason: 判定理由（短文）
        error: 例外オブジェクト。指定時はスタックトレースも記録
        extra: 追加情報 dict（task固有のキー）

    Returns:
        書込先のログファイルパス
    """
    record: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "project": project,
        "sku": str(sku),
        "title": title,
        "category": category,
        "price_usd": price_usd,
        "shipping_jpy": shipping_jpy,
        "status": status,
        "reason": reason,
        "config_version": _get_config_version(),
    }
    if error is not None:
        record["error_type"] = type(error).__name__
        record["error_msg"] = str(error)
        record["traceback"] = traceback.format_exc()
    if extra:
        record["extra"] = extra

    path = _today_log_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def log_csv_batch(
    *,
    project: str,
    category: str,
    output_path: str,
    row_count: int,
    extra: Optional[dict] = None,
) -> Path:
    """CSV 1ファイル生成完了の summary record (4 メイン実行パス共通呼出).

    Step 8 拡張 (2026-04-25): 「どの Config Version を使い、どの値を参照したか」
    を CSV 生成のたびに必ず刻印するための共通呼出口。

    Args:
        project: "iMakTCG" / "iMakG-shock" / "iMakMercari" / "iMak_ichibankuji"
        category: yaml カテゴリ名 ("TCG(PSA10)" / "G-SHOCK" 等)
        output_path: 生成 CSV のフルパス
        row_count: 書込行数
        extra: 追加情報 (任意)

    Returns:
        ログファイルパス
    """
    # 使用された FVF/shipping/exchange_rate も同時刻印 (yaml の値が反映されたか後追い可能)
    try:
        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))
        from profit_params import get_check_csv_params
        params = get_check_csv_params(category)
        fvf = params["ebay_fee_rate"]
        shipping_jpy = params["shipping_jpy"]
        exchange_rate = params["exchange_rate"]
    except Exception as e:
        fvf = None
        shipping_jpy = None
        exchange_rate = None
        if extra is None:
            extra = {}
        extra["param_lookup_error"] = f"{type(e).__name__}: {e}"

    record_extra = {
        "kind": "csv_batch",
        "output_path": str(output_path),
        "row_count": row_count,
        "fvf_used": fvf,
        "exchange_rate_used": exchange_rate,
    }
    if extra:
        record_extra.update(extra)

    return log_decision(
        project=project,
        sku=f"BATCH-{datetime.now().strftime('%H%M%S')}",
        title=f"CSV batch generated ({row_count} rows)",
        category=category,
        shipping_jpy=shipping_jpy,
        status="OK",
        reason=f"CSV写出完了 → {output_path}",
        extra=record_extra,
    )


def read_today_decisions() -> list:
    """本日のログをリストで返す（後追い解析用）"""
    path = _today_log_path()
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # smoke test
    p = log_decision(
        project="iMakTCG",
        sku="TEST-12345",
        title="Test Listing",
        category="TCG(PSA10)",
        price_usd=199.99,
        shipping_jpy=2000,
        status="OK",
        reason="smoke test entry",
    )
    print(f"Wrote test entry to: {p}")
    print(f"Today's decisions: {len(read_today_decisions())}")
