"""出品くん cycle 後 hook: NO-GO 除外 cert を スプシ HIGH K 列に sentinel (= 赤字) 書込.

設計 (= 5/28 ユーザー指示):
- 価格 NO-GO 除外された cert は itemID NULL のまま → 毎 cycle 再抽出 → 無駄ループ
- スプシ HIGH の K 列 (= col 11 「未使用」) に sentinel 「出品見合せ（仕入高）」 を **赤字** で書込
- 次 cycle で出品くんが K 列空 condition で抽出対象外 → 永久 NO-GO 除外

呼出 source: control_panel.py poll_queue 内 Step 6 (= post_psa_review 後)
"""
import os
import sys
import csv
from pathlib import Path

SENTINEL_TEXT = "出品見合せ（仕入高）"
HIGH_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
HIGH_GID = 851100680
HIGH_CERT_COL = 9   # col I = Title (cert)
HIGH_K_COL = 11     # col K = 「未使用」 (= sentinel 用)
GSHEET_CREDS = r"C:/dev/iMak/double-hold-421922-7c0d38d3f73d.json"


def _get_no_go_certs_from_bak(csv_path: str) -> list[str]:
    """元 CSV (= .bak、 NO-GO 除外前) と 現 CSV を比較、 除外された cert list 返却."""
    csv_p = Path(csv_path)
    bak = csv_p.with_suffix(".csv.bak")
    if not bak.exists():
        return []  # 除外なし or hook 動作前
    # bak の全 cert
    bak_certs = set()
    try:
        with open(bak, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                c = (row.get("CDA:Certification Number - (ID: 27503)") or "").strip()
                if c:
                    bak_certs.add(c)
    except Exception:
        return []
    # 現 CSV の残存 cert
    now_certs = set()
    if csv_p.exists():
        try:
            with open(csv_p, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    c = (row.get("CDA:Certification Number - (ID: 27503)") or "").strip()
                    if c:
                        now_certs.add(c)
        except Exception:
            pass
    # 差分 = 除外 cert
    return sorted(bak_certs - now_certs)


def _write_sentinel_red(certs: list[str], append_log_func) -> dict:
    """各 cert の HIGH row K 列に sentinel 「出品見合せ（仕入高）」 を赤字書込.

    Returns {processed, errors}.
    """
    summary = {"processed": 0, "skipped": 0, "errors": []}
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(GSHEET_CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(HIGH_SHEET_ID)
        ws = sh.get_worksheet_by_id(HIGH_GID)
    except Exception as e:
        summary["errors"].append(f"gspread init: {type(e).__name__}: {e}")
        return summary

    cert_col_values = ws.col_values(HIGH_CERT_COL)
    for cert in certs:
        try:
            row = None
            for i, v in enumerate(cert_col_values, 1):
                if str(v).strip() == cert:
                    row = i
                    break
            if not row:
                summary["errors"].append(f"cert {cert}: HIGH row not found")
                continue
            # 既存値 check (= 既書込なら skip)
            existing = ws.cell(row, HIGH_K_COL).value
            if existing and existing.strip():
                summary["skipped"] += 1
                continue
            # 書込 + 赤字 format
            ws.update_cell(row, HIGH_K_COL, SENTINEL_TEXT)
            # A1 notation で format 指定 (= row, K 列 = "K{row}")
            ws.format(f"K{row}", {"textFormat": {"foregroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}, "bold": True}})
            summary["processed"] += 1
            append_log_func(f"    ✏️ row {row} (cert {cert}): K 列に sentinel 赤字書込\n")
        except Exception as e:
            summary["errors"].append(f"cert {cert} write: {type(e).__name__}: {e}")
    return summary


def run_post_no_go_sentinel(csv_path: str, append_log_func) -> None:
    """control_panel.py poll_queue から呼出される entry point."""
    append_log_func("\n======================================================================\n")
    append_log_func("▶ post_no_go_sentinel (NO-GO 除外 cert に スプシ K 列 sentinel 書込)\n")
    append_log_func("======================================================================\n")

    no_go_certs = _get_no_go_certs_from_bak(csv_path)
    if not no_go_certs:
        append_log_func("  ✅ NO-GO 除外 cert なし、 skip\n")
        return

    append_log_func(f"  NO-GO 除外 cert: {len(no_go_certs)} 件\n")
    for c in no_go_certs:
        append_log_func(f"    - {c}\n")

    summary = _write_sentinel_red(no_go_certs, append_log_func)
    append_log_func(f"\n  📝 K 列 sentinel 書込結果:\n")
    append_log_func(f"     processed: {summary['processed']}\n")
    append_log_func(f"     skipped (既書込): {summary['skipped']}\n")
    if summary["errors"]:
        append_log_func(f"     errors: {len(summary['errors'])}\n")
        for e in summary["errors"]:
            append_log_func(f"       - {e}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python post_no_go_sentinel.py <csv_path>")
        sys.exit(1)
    run_post_no_go_sentinel(sys.argv[1], print)
