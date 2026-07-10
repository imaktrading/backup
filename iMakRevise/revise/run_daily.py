# -*- coding: utf-8 -*-
"""run_daily.py - リバイスくん 日次自動 revise (生成 → 自動UP → 結果メール).

フロー (毎日 04:30 JST タスク起動想定):
  1. run_price_revise() で価格 revise CSV + review.xlsx を生成
     - 異常 delta 判定分は元々 UP CSV に含まれない (revisable のみ CSV 化)
       = 「異常ゲート通過分のみ自動UP」は生成ロジックで自動的に満たされる
  2. 生成された UP CSV 3 本 (single / variation 価格 / variation 送料) を
     variation_upload 経由で FileExchange へ自動 UP
     - 送信後 verify、失敗は同 run 内で短間隔リトライ (silent drop 禁止)
  3. 結果サマリ (revise 件数 / 異常保留件数 / UP 成否) + review.xlsx を自分宛メール
     - UP 失敗が 1 件でもあれば件名を ⚠️要対応 にする (fail-OPEN 防止)

資格情報 / SMTP は send_reminder と共有 (DPAPI blob 経由、二重管理なし)。

Usage:
    python -m revise.run_daily            # 実 UP + メール
    python -m revise.run_daily --dry-run  # 生成のみ、UP せず、メール本文表示
"""
from __future__ import annotations

import argparse
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
PKG_ROOT = THIS_DIR.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

JST = timezone(timedelta(hours=9))
LOG_PATH = PKG_ROOT / "decision_log" / "daily_revise.log"

# UP 失敗時の同 run 内リトライ (silent drop 禁止 / fail-closed same-cycle completion)
UPLOAD_MAX_ATTEMPTS = 3
UPLOAD_RETRY_WAIT_SEC = 90

# メール送信リトライ (早朝は DNS 未準備のことがある)
MAIL_MAX_ATTEMPTS = 5
MAIL_RETRY_WAIT_SEC = 60


def _log(line: str) -> None:
    msg = f"{datetime.now(JST):%Y-%m-%d %H:%M:%S} {line}"
    print(msg)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def _upload_one(csv_path: Path, label: str, dry_run: bool) -> dict:
    """1 本の CSV を verify + リトライ付きで UP。

    Returns: {"label", "csv", "success", "attempts", "error"}
    """
    from revise.variation_upload import upload_variation_csv

    last_err = None
    for attempt in range(1, UPLOAD_MAX_ATTEMPTS + 1):
        try:
            result = upload_variation_csv(csv_path, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001 - 予期せぬ例外も要対応として拾う
            result = {"success": False, "error": f"例外: {e}"}
        if result.get("success"):
            _log(f"[daily] UP 成功 [{label}] {csv_path.name} (attempt {attempt}/{UPLOAD_MAX_ATTEMPTS})")
            return {"label": label, "csv": csv_path.name, "success": True,
                    "attempts": attempt, "error": None}
        last_err = result.get("error") or result.get("message") or "unknown"
        _log(f"[daily] UP 失敗 [{label}] {csv_path.name} "
             f"attempt {attempt}/{UPLOAD_MAX_ATTEMPTS}: {last_err}")
        if attempt < UPLOAD_MAX_ATTEMPTS:
            time.sleep(UPLOAD_RETRY_WAIT_SEC)
    return {"label": label, "csv": csv_path.name, "success": False,
            "attempts": UPLOAD_MAX_ATTEMPTS, "error": last_err}


def _build_summary_body(result, uploads: list, dry_run: bool) -> str:
    now = datetime.now(JST)
    n_revise = len(result.revisable)
    n_single = sum(1 for c in result.revisable if not c.is_variation)
    n_var = sum(1 for c in result.revisable if c.is_variation)
    n_abn = len(result.abnormal)
    n_skip = len(result.skipped)

    lines = [
        f"リバイスくん 日次自動 revise 結果 ({now:%Y-%m-%d %H:%M} JST)"
        + ("  ※ --dry-run (UP せず)" if dry_run else ""),
        "",
        f"■ 生成",
        f"  revise 対象   : {n_revise} 件 (single {n_single} / variation {n_var})",
        f"  異常保留      : {n_abn} 件  ← UP せず。要目視 (review.xlsx 参照)",
        f"  その他 skip   : {n_skip} 件",
        "",
        f"■ 自動UP",
    ]
    if not uploads:
        lines.append("  (UP 対象なし = revise 0 件)")
    for u in uploads:
        if u.get("would_upload"):
            mark = "予定 (dry-run)"
        else:
            mark = "OK" if u["success"] else "NG ⚠️要対応"
        err = "" if u["success"] else f"  err={u['error']}"
        lines.append(f"  [{mark}] {u['label']}: {u['csv']} (attempt {u['attempts']}){err}")

    if n_abn:
        lines += ["", "■ 異常保留 (自動UPせず、人手確認要) 上位:"]
        for c in result.abnormal[:10]:
            lines.append(f"  - [{c.source_sheet}] item={c.item_id} {c.decision_details}")

    lines += ["", "詳細は添付 review.xlsx を参照。"]
    return "\n".join(lines)


def _send_summary(result, uploads: list, dry_run: bool) -> int:
    from revise.send_reminder import load_config

    all_ok = all(u["success"] for u in uploads)
    now = datetime.now(JST)
    subj_state = "完了" if all_ok else "⚠️要対応 (UP失敗あり)"
    body = _build_summary_body(result, uploads, dry_run)

    cfg = load_config()
    if dry_run:
        cfg = cfg or {"sender": "(復号未確認)", "recipient": "(復号未確認)"}
        print("[daily] --dry-run メール本文 (送信しません)")
        print("-" * 60)
        print(f"To: {cfg['recipient']}")
        print(f"Subject: 【リバイスくん】日次revise {subj_state} ({now:%m/%d %a})")
        print()
        print(body)
        return 0

    if not cfg:
        _log("[daily] 資格情報 復号失敗 → メール送信 skip (フェイルセーフ)")
        return 1

    msg = EmailMessage()
    msg["Subject"] = f"【リバイスくん】日次revise {subj_state} ({now:%m/%d %a})"
    msg["From"] = cfg["sender"]
    msg["To"] = cfg["recipient"]
    msg.set_content(body)

    xlsx = getattr(result, "review_xlsx_path", None)
    if xlsx and Path(xlsx).exists():
        data = Path(xlsx).read_bytes()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=Path(xlsx).name,
        )

    ctx = ssl.create_default_context()
    last_err = None
    for attempt in range(1, MAIL_MAX_ATTEMPTS + 1):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as server:
                server.login(cfg["sender"], cfg["app_password"])
                server.send_message(msg)
            _log(f"[daily] 結果メール送信完了 → {msg['To']} (attempt {attempt})")
            return 0
        except (OSError, smtplib.SMTPException) as e:
            last_err = e
            _log(f"[daily] メール送信失敗 attempt {attempt}/{MAIL_MAX_ATTEMPTS}: {e}")
            if attempt < MAIL_MAX_ATTEMPTS:
                time.sleep(MAIL_RETRY_WAIT_SEC)
    _log(f"[daily] 全 {MAIL_MAX_ATTEMPTS} attempt メール送信失敗: {last_err}")
    return 1


def run_daily(dry_run: bool = False) -> int:
    from revise.price_revise import run_price_revise

    _log(f"[daily] === 日次 revise 開始 (dry_run={dry_run}) ===")

    # Step 1: 生成 (snapshot 自動取得込み、review.xlsx 付き、全 sheet)
    # dry_run は生成側にも伝播 → スプシ O 列更新をスキップ (テスト時の副作用防止)
    try:
        result = run_price_revise(review_xlsx=True, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 - snapshot stale 等は run 中止だが通知は残す
        _log(f"[daily] [FATAL] revise 生成失敗 → UP せず中止: {e}")
        raise

    # Step 2: UP 対象 CSV を収集 (存在するものだけ)
    targets: list[tuple[Path, str]] = []
    if result.csv_path and Path(result.csv_path).exists():
        targets.append((Path(result.csv_path), "single"))
    if result.var_price_path and Path(result.var_price_path).exists():
        targets.append((Path(result.var_price_path), "variation価格"))
    if result.var_shipping_path and Path(result.var_shipping_path).exists():
        targets.append((Path(result.var_shipping_path), "variation送料"))

    # Step 3: 自動 UP (verify + リトライ)。dry-run では UP を一切呼ばず「予定」だけ記録
    uploads: list[dict] = []
    for csv_path, label in targets:
        if dry_run:
            uploads.append({"label": label, "csv": csv_path.name, "success": True,
                            "attempts": 0, "error": None, "would_upload": True})
        else:
            uploads.append(_upload_one(csv_path, label, dry_run=False))

    # Step 4: 結果メール
    mail_rc = _send_summary(result, uploads, dry_run=dry_run)

    all_ok = all(u["success"] for u in uploads)
    _log(f"[daily] === 完了 revise={len(result.revisable)} 異常保留={len(result.abnormal)} "
         f"UP成功={sum(1 for u in uploads if u['success'])}/{len(uploads)} "
         f"mail_rc={mail_rc} ===")
    # UP 失敗 or メール失敗があれば非ゼロ (タスク履歴で気づけるように)
    return 0 if (all_ok and mail_rc == 0) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="リバイスくん 日次自動 revise")
    ap.add_argument("--dry-run", action="store_true",
                    help="生成のみ。UP せず、メールは本文表示のみ")
    args = ap.parse_args()
    return run_daily(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
