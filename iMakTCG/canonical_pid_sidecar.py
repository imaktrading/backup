"""Canonical product_id sidecar 出力 (2026-08-09).

CSV は 1 文字も触らない (回答書 2026-08-09_rarity_exclusion_needs_canonical_product_id_response.md)。
出品 CSV と並置で `<basename>.canonical.json` を書き、`cert → canonical_pid` を保存する。
"""
from __future__ import annotations

import json
import os
from datetime import datetime


def sidecar_path_for(csv_path: str) -> str:
    """CSV パス → sidecar パス。"""
    if csv_path.endswith(".csv"):
        return csv_path[:-4] + ".canonical.json"
    return csv_path + ".canonical.json"


def build_payload(csv_path: str, by_cert: dict, now=None) -> dict:
    """sidecar の JSON payload を作る (純関数、test 可)。"""
    ts = (now or datetime.now()).isoformat(timespec="seconds")
    clean = {str(c): str(p) for c, p in by_cert.items() if p}
    return {
        "generated_at": ts,
        "source_csv": os.path.basename(csv_path),
        "by_cert": clean,
    }


def write_sidecar(
    csv_path: str,
    pid_by_cert: dict,
    certs_in_csv=None,
    confirmed_pids=None,
    print_fn=print,
    now=None,
) -> str:
    """sidecar JSON を書き出す。

    Args:
        csv_path: 出品 CSV の絶対パス
        pid_by_cert: build_row が集めた {cert: canonical_pid}
        certs_in_csv: CSV に実際に載った cert の iterable (None なら pid_by_cert 全部を使う)。
            指定した時は fail-closed に「CSV に載ったのに canonical PID が取れなかった」cert を
            silent drop 禁止で標準出力に列挙する
        confirmed_pids: verify_mode の `_confirmed_pids` (人が確定した PID)。ある cert に
            entry があればそちらで上書きする (最強権威 = 人が選んだ PID)
        print_fn: 通知に使う print (test 用に注入可)
        now: datetime を注入 (test 用)

    Returns:
        書き出した sidecar のパス
    """
    merged = {str(c): str(p) for c, p in (pid_by_cert or {}).items() if p}
    for c, p in (confirmed_pids or {}).items():
        if p:
            merged[str(c)] = str(p)

    if certs_in_csv is not None:
        want = {str(c) for c in certs_in_csv}
        filtered = {c: p for c, p in merged.items() if c in want}
        missing = sorted(want - set(filtered.keys()))
        if missing:
            # silent drop 禁止: 標準出力に件数と cert を出す (回答書 §仕様 4項)
            print_fn(
                f"⚠️ canonical PID sidecar: CSV に {len(want)} 件載ったが "
                f"canonical PID を取れなかった cert が {len(missing)} 件: {missing}"
            )
        payload = build_payload(csv_path, filtered, now=now)
    else:
        payload = build_payload(csv_path, merged, now=now)

    out = sidecar_path_for(csv_path)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out
