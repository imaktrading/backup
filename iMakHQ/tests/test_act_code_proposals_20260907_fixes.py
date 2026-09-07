"""2026-09-07 の Act 提案4件を直したことを固定する (実装GO: 2026-09-08).

出典: hq/requests/2026-09-07_act_code_proposals_tcg{,_response}.md
どれも「数字や台帳が実態を映していない」系。再現条件をそのままテストにする。
"""
import csv
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import csv_auditor as A  # noqa: E402
import pdca_store as P  # noqa: E402
import auto_catalog_add_request as R  # noqa: E402


# --- 提案1: セット記号 regex ------------------------------------------------
def test_set_hint_catches_letter_digit_letter():
    """`M2a` `SV7a` 型 (数字のあとに英字) を拾う。旧 regex は 0件だった."""
    for code in ("M2A", "SV7A", "S8B"):
        assert P._SETHINT_RE.findall(code) == [code], code


def test_set_hint_catches_two_digit_codes():
    """`ST01` `OP09` `EB01` `PRB02` も旧 regex では 0件だった (提案書より広い実害)."""
    for code in ("ST01", "OP09", "EB01", "PRB02", "CP3"):
        assert P._SETHINT_RE.findall(code) == [code], code


def test_set_hint_ignores_single_letter():
    assert P._SETHINT_RE.findall("A") == []


def test_candidate_ids_picks_up_the_real_case():
    """9/07 に効かなかった実物 (レックウザ 127/193 m2a)."""
    c = P.candidate_ids("番号不明 レックウザ 127/193 m2a")
    assert "M2A" in c["hints"] and "127/193" in c["numbers"]


# --- 提案3: 失敗ログの単独行 ------------------------------------------------
def test_lone_failure_line_is_counted():
    """PSA が取れない時 `失敗` は **単独行**で出る (#936643273 が数え落とされていた)."""
    log = ("取得中(確認用): #936643273...\n"
           " [DEBUG] リクエストされたページが見つかりませんでした\n"
           " 失敗\n")
    assert A.scan_log_lines(log) == ["error: 1件"]


def test_success_summary_line_is_not_counted():
    """`成功: 13件 / 失敗: 0件` は行頭が「成功」なので当たらない (誤検出を増やさない)."""
    assert A.scan_log_lines("成功: 13件 / 失敗: 0件\n") == []


# --- 提案2: digest を作る前に状態を直す --------------------------------------
def test_prune_runs_before_digest_is_read():
    """解決済が `pending` のまま digest に載らないよう、prune を前に出したこと."""
    src = (TOOLS / "csv_auditor.py").read_text(encoding="utf-8")
    i_prune = src.index("_pdca_prune_resolved(dry_run)")
    i_digest = src.index("recurring = filter_recurring_for_project(")
    assert i_prune < i_digest, "prune は digest を読む前に走らせること"


def test_prune_is_noop_on_dry_run():
    assert A._pdca_prune_resolved(True) == 0


# --- 提案4: 台帳の列で「依頼した」と「解決した」を分ける ----------------------
def test_processed_rows_default_to_requested(tmp_path, monkeypatch):
    """`reason` 列が無い既存行は requested 扱い (解決済にしない = 二度と出ないのを防ぐ)."""
    f = tmp_path / "p.csv"
    with f.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["category", "model", "detected_at"])
        w.writerow(["gundam_tcg", "X-001", "2026-09-01"])
    monkeypatch.setattr(R, "PROCESSED_CSV", f)
    rows = R.load_processed_rows()
    assert rows == [{"category": "gundam_tcg", "model": "X-001",
                     "detected_at": "2026-09-01", "reason": "requested"}]


def test_resolved_rows_are_written_with_reason():
    """解決側 (csv_auditor) は resolved と書くこと."""
    src = (TOOLS / "csv_auditor.py").read_text(encoding="utf-8")
    i = src.index("def _move_resolved_missing_models(")
    body = src[i:src.index("\ndef ", i + 10)]
    assert '"resolved"' in body
    assert '"category", "model", "detected_at", "reason"' in body


def test_load_processed_sentinel_ignores_resolved_rows(tmp_path, monkeypatch):
    """resolved (=解決済) を sentinel に含めると、再発時に黙って依頼を出さなくなる
    (fail-OPEN)。`_load_processed` は requested だけを読むこと."""
    f = tmp_path / "p.csv"
    with f.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(R.PROCESSED_HEADER)
        w.writerow(["gundam_tcg", "X-001", "2026-09-01", "requested"])
        w.writerow(["gundam_tcg", "X-002", "2026-09-02", "resolved"])
    monkeypatch.setattr(R, "PROCESSED_CSV", f)
    keys = R._load_processed()
    assert ("gundam_tcg", "X-001") in keys
    assert ("gundam_tcg", "X-002") not in keys


def test_ensure_processed_header_migrates_old_file_in_place(tmp_path):
    """既存191行のような旧形式 (reason列なし) は requested 付きへ移行し、行数を保つ."""
    f = tmp_path / "p.csv"
    with f.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["category", "model", "detected_at"])
        w.writerow(["gundam_tcg", "X-001", "2026-09-01"])
        w.writerow(["gshock", "GM-5640GEM-1JR", "2026-05-09 15:38:14"])
    R.ensure_processed_header(f)
    with f.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert all(r["reason"] == "requested" for r in rows)
    # 冪等: 2回目は何もしない (壊れない)
    R.ensure_processed_header(f)
    with f.open(encoding="utf-8") as fh:
        rows2 = list(csv.DictReader(fh))
    assert rows2 == rows
