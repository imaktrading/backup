# -*- coding: utf-8 -*-
"""解決済(done化)した model を missing_models.csv から missing_models_processed.csv へ移す (2026-09-06)。

台帳7行中6行が既に回答済(catalog側は解決済/②側)なのに16日残っていて、Act が毎回手で消していた。
依頼書: hq/requests/2026-09-06_act_code_proposals_tcg.md 提案4
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.normpath(os.path.join(_HERE, "..", "tools"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import csv_auditor as ca  # noqa: E402


def _write_missing(path, rows):
    import csv
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "model", "detected_at"])
        for r in rows:
            w.writerow(r)


def _read(path):
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_resolved_rows_move_from_missing_to_processed(tmp_path, monkeypatch):
    missing = tmp_path / "missing_models.csv"
    processed = tmp_path / "missing_models_processed.csv"
    _write_missing(missing, [
        ("tcg", "cert95043896 SV7-130", "2026-08-21"),
        ("tcg", "WEIRD-UNRESOLVED-XYZ", "2026-08-22"),
    ])
    monkeypatch.setattr(ca, "MISSING_MODELS_PATH", str(missing))
    monkeypatch.setattr(ca, "MISSING_MODELS_PROCESSED_PATH", str(processed))

    moved = ca._move_resolved_missing_models(["cert95043896 SV7-130"])

    assert moved == 1
    remaining = _read(missing)
    assert [r["model"] for r in remaining] == ["WEIRD-UNRESOLVED-XYZ"], \
        "解決済でない行まで消してしまった"
    done = _read(processed)
    assert [r["model"] for r in done] == ["cert95043896 SV7-130"]


def test_appends_to_existing_processed_file(tmp_path, monkeypatch):
    missing = tmp_path / "missing_models.csv"
    processed = tmp_path / "missing_models_processed.csv"
    _write_missing(missing, [("tcg", "A", "2026-08-01")])
    _write_missing(processed, [("tcg", "OLD", "2026-07-01")])
    monkeypatch.setattr(ca, "MISSING_MODELS_PATH", str(missing))
    monkeypatch.setattr(ca, "MISSING_MODELS_PROCESSED_PATH", str(processed))

    moved = ca._move_resolved_missing_models(["A"])

    assert moved == 1
    done = _read(processed)
    assert {r["model"] for r in done} == {"OLD", "A"}, "追記ではなく上書きした"


def test_no_ids_is_noop(tmp_path, monkeypatch):
    missing = tmp_path / "missing_models.csv"
    _write_missing(missing, [("tcg", "A", "2026-08-01")])
    monkeypatch.setattr(ca, "MISSING_MODELS_PATH", str(missing))
    assert ca._move_resolved_missing_models([]) == 0
    assert ca._move_resolved_missing_models(None) == 0


def test_missing_file_absent_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "MISSING_MODELS_PATH", str(tmp_path / "nope.csv"))
    assert ca._move_resolved_missing_models(["X"]) == 0
