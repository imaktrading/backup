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


def _keep_category(recorded: str, confirmed: str, category: str = "") -> str:
    """人が確定した PID を採るが、**ゲーム名 (category) は落とさない** (2026-08-23)。

    viewer が返す確定 PID は `ST02-001` のように category 前置きが無い。そのまま採ると
    ワンピとガンダムで同じ product_id が両方に在る (283件) ため、後段がどちらの
    ゲームか決められなくなる。build_row が控えた `one_piece_tcg:ST02-001...` の
    前半だけを引き継いで `one_piece_tcg:<人が選んだPID>` にする。
    人が別候補を選んでも候補は同じゲーム内なので、前置きの引き継ぎは安全。

    ★2026-08-31: `recorded` が空 (build_row の lookup 自体が失敗した cert) だと
      前置きを引き継げず、確定 PID が裸のまま残っていた
      (実害: cert84299672 "ST11-004_P" が裸で監査の catalog 突合から漏れた)。
      呼び出し側が CSV 行から確定させた `category` (franchise / `C:Game`) を渡せば、
      `recorded` が空でもそちらを使う。推測ではなく、その行が既に持っている確定値。
      出典: hq/requests/2026-08-31_act_code_proposals_tcg_response.md 提案2
    """
    confirmed = (confirmed or "").strip()
    if not confirmed or ":" in confirmed:
        return confirmed
    if ":" in (recorded or ""):
        return f"{recorded.split(':', 1)[0]}:{confirmed}"
    if category:
        return f"{category}:{confirmed}"
    return confirmed


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
    category_by_cert=None,
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
        category_by_cert: {cert: catalog category} (例 "one_piece_tcg")。build_row の
            lookup が失敗して `pid_by_cert` に前置きが無い cert でも、CSV 行から
            確定している category を `_keep_category` に渡す (2026-08-31 提案2)
    Returns:
        書き出した sidecar のパス
    """
    merged = {str(c): str(p) for c, p in (pid_by_cert or {}).items() if p}
    for c, p in (confirmed_pids or {}).items():
        if p:
            merged[str(c)] = _keep_category(
                merged.get(str(c), ""), str(p),
                category=(category_by_cert or {}).get(str(c), ""))

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
