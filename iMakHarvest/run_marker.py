"""run_marker - 手動の長時間収集 (トレジャーハント等) が「途中で止まった」ことを示す印.

HQ/ADV 依頼 `2026-09-24_resume_after_crash` (②): 手動の長時間収集は自動再開しない
(手で `--resume-from-json` を撃つ運用のまま)。 だが PC が落ちて走行が消えた時、
**止まったこと自体に気付けない**のは困るので、開始時に印を書き、正常終了でだけ消す。

- 印が残っている = 前回、正常終了せずに途中で止まった (クラッシュ / kill 等)
- 印には dump_path (= `--resume-from-json` にそのまま渡せるパス) を持たせる

呼び出し側 (run_harvest_mercari_treasure.py 等) は:
  mark_started(MARKER_PATH, dump_path)   # 収集開始時
  ... 収集 ...
  mark_finished(MARKER_PATH)             # 正常終了時のみ (例外/クラッシュでは呼ばれない)

セッション開始時にこの印が残っていないか見るのは呼出側 (skill / daily_report) の役割。
この module は書く/消す/読むだけ。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def mark_started(marker_path: Path, dump_path: Path, **extra) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": datetime.now().astimezone().isoformat(),
        "dump_path": str(dump_path),
        **extra,
    }
    marker_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_finished(marker_path: Path) -> None:
    """正常終了時に呼ぶ。 印が無くても (dry-run 等) 何もしない."""
    try:
        marker_path.unlink()
    except FileNotFoundError:
        pass


def check_stale(marker_path: Path) -> dict | None:
    """印が残っていれば中身を返す (= 前回 途中で止まった)。 無ければ None."""
    if not marker_path.exists():
        return None
    try:
        return json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"dump_path": None, "started_at": None, "unreadable": True}
