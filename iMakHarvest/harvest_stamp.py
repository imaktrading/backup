"""harvest_stamp - cron 完走スタンプの読取/書込ヘルパ.

背景 (2026-07-29 事故):
  21:00 / 21:30 / 22:00 の cron が silent に (LastTaskResult=0x800704A6 電源理由で)
  途中死し、収集ゼロが「正常」に見えた。Task Scheduler 側でバッテリー停止と Hidden 化は
  Advisor 側で解除済 (依頼書 2026-07-29_battery_stop_disabled_and_stamp_GO.md §1)。
  この module は「そもそも Python が完走したか」を **共有領域に永続化** することで、
  Task Scheduler 側のガードとは独立に silent 即死を検知可能にする。

役割:
  - stamp = 「そもそも完走したか」の一次証拠 (共有領域に置き、窓口が鮮度確認できる)
  - `check_previous_stamp`: 不在 or 古い → **stderr に warn print + return** (stop しない)
  - `write_stamp`: `ok_at` (ISO 現在時刻) + 呼び出し側が渡した metadata を JSON で書込

失敗 flag (`CRON_FAILED_*.flag`) とは役割違い:
  - flag = 生きて失敗した (503/DNS など)
  - stamp = そもそも完走したか
  両方あって初めて silent 死を塞ぐ (依頼書 §3 / _response.md §2)。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def check_previous_stamp(
    stamp_path: Path,
    stale_hours: float,
    *,
    timestamp_key: str = "ok_at",
    label: str = "stamp",
    now: datetime | None = None,
    stream=None,
) -> None:
    """前回スタンプが不在 / 古い / 読取不能 なら stderr に warn を出す (stop はしない).

    fail-open で続行する (収集を止める方が損失が大きい。 依頼書 _response.md §2)。
    silent 死の検知が目的なので、warn が出ないと機能しない = テストで固定する。

    now / stream はテスト注入用 (省略時は now=aware datetime, stream=sys.stderr)。
    """
    out = stream if stream is not None else sys.stderr
    if not stamp_path.exists():
        print(f"[{label}] warning: 前回スタンプ不在 (初回 or 前回死亡): {stamp_path}",
              file=out)
        return
    try:
        prev = json.loads(stamp_path.read_text(encoding="utf-8"))
        prev_at = datetime.fromisoformat(prev[timestamp_key])
    except Exception as e:  # noqa: BLE001
        print(f"[{label}] warning: 前回スタンプ読取失敗 ({type(e).__name__}): {e}",
              file=out)
        return
    ref = now if now is not None else datetime.now().astimezone()
    age_h = (ref - prev_at).total_seconds() / 3600
    if age_h > stale_hours:
        print(f"[{label}] warning: 前回成功から {age_h:.1f}h 経過 "
              f"(>{stale_hours}h): {stamp_path}", file=out)


def write_stamp(stamp_path: Path, payload: dict[str, Any],
                *, now: datetime | None = None) -> dict[str, Any]:
    """スタンプ JSON を書込 (`ok_at` は自動付与、 既存キーは尊重).

    dry_run 時は呼び出さないこと (= 呼出側で分岐)。「本番が回っていない」を dry_run で
    隠さないための最重要判断 (依頼書 _response.md §2)。 Returns: 書込んだ payload。
    """
    ref = now if now is not None else datetime.now().astimezone()
    body = {"ok_at": ref.isoformat(), **payload}
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return body
