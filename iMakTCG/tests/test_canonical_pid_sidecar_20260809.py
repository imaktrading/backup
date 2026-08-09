"""canonical product_id サイドカー JSON 出力の回帰テスト (2026-08-09).

回答書: iMak_data/hq/requests/2026-08-09_rarity_exclusion_needs_canonical_product_id_response.md

守るべき invariants:
- CSV には列を足さない (=呼出側が指定した pid_by_cert dict を並置 JSON に書くだけ)
- キーは cert / 値は canonical PID (S8b-101 等)
- 空欄・None は書かない (推測禁止)
- CSV に載ったのに canonical PID が取れなかった cert は silent drop せず stdout に出す
- verify_mode の `_confirmed_pids` (人が確定した PID) は最強権威で上書き
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import pytest

_HERE = os.path.abspath(os.path.dirname(__file__))
_TCG = os.path.abspath(os.path.join(_HERE, ".."))
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

import canonical_pid_sidecar as mod  # noqa: E402


# ============================================================================
# サイドカー パス / payload
# ============================================================================
def test_sidecar_path_replaces_csv_suffix(tmp_path):
    p = str(tmp_path / "tcg_upload_20260809_120000.csv")
    assert mod.sidecar_path_for(p) == str(
        tmp_path / "tcg_upload_20260809_120000.canonical.json"
    )


def test_sidecar_path_appends_when_no_csv_suffix(tmp_path):
    p = str(tmp_path / "weird_name.txt")
    assert mod.sidecar_path_for(p) == str(
        tmp_path / "weird_name.txt.canonical.json"
    )


def test_build_payload_includes_basename_not_full_path(tmp_path):
    csv_p = str(tmp_path / "foo.csv")
    payload = mod.build_payload(csv_p, {"1": "S8b-101"}, now=datetime(2026, 8, 9, 12, 0, 0))
    assert payload["source_csv"] == "foo.csv"
    assert payload["generated_at"] == "2026-08-09T12:00:00"
    assert payload["by_cert"] == {"1": "S8b-101"}


def test_build_payload_strips_empty_values():
    payload = mod.build_payload("x.csv", {"1": "S8b-101", "2": "", "3": None})
    assert payload["by_cert"] == {"1": "S8b-101"}


def test_build_payload_coerces_keys_and_values_to_str():
    payload = mod.build_payload("x.csv", {12345: "OP08-057"})
    # int cert キーも str 化 (CSV は文字列で cert を持つため突合できるようにする)
    assert payload["by_cert"] == {"12345": "OP08-057"}


# ============================================================================
# write_sidecar
# ============================================================================
def test_write_sidecar_creates_file_with_expected_shape(tmp_path):
    csv_p = str(tmp_path / "tcg_upload_20260809_120000.csv")
    with open(csv_p, "w") as f:
        f.write("stub\n")  # 実体だけ用意
    out = mod.write_sidecar(csv_p, {"111": "S8b-101", "222": "OP08-057"})
    assert out.endswith(".canonical.json")
    payload = json.load(open(out, encoding="utf-8"))
    assert payload["source_csv"] == "tcg_upload_20260809_120000.csv"
    assert payload["by_cert"] == {"111": "S8b-101", "222": "OP08-057"}
    assert "generated_at" in payload


def test_write_sidecar_filters_to_certs_in_csv(tmp_path):
    """CSV に無い cert (先に skip されたもの) は sidecar に出さない。"""
    csv_p = str(tmp_path / "t.csv")
    with open(csv_p, "w") as f:
        f.write("stub\n")
    pid_by_cert = {
        "111": "S8b-101",
        "222": "OP08-057",
        "999": "DROPPED-9",  # skip 済 (CSV に載っていない)
    }
    out = mod.write_sidecar(csv_p, pid_by_cert, certs_in_csv={"111", "222"})
    payload = json.load(open(out, encoding="utf-8"))
    assert payload["by_cert"] == {"111": "S8b-101", "222": "OP08-057"}
    assert "999" not in payload["by_cert"]


def test_write_sidecar_reports_missing_certs_no_silent_drop(tmp_path):
    """CSV に載ったのに canonical PID が取れなかった cert を stdout に出す。"""
    csv_p = str(tmp_path / "t.csv")
    with open(csv_p, "w") as f:
        f.write("stub\n")
    printed = []
    mod.write_sidecar(
        csv_p,
        {"111": "S8b-101"},
        certs_in_csv={"111", "222", "333"},  # 222, 333 は canonical 取れず
        print_fn=printed.append,
    )
    assert len(printed) == 1, "silent drop 禁止=1件は必ず通知"
    msg = printed[0]
    assert "222" in msg and "333" in msg
    assert "2 件" in msg  # 件数明示


def test_write_sidecar_no_message_when_all_matched(tmp_path):
    csv_p = str(tmp_path / "t.csv")
    with open(csv_p, "w") as f:
        f.write("stub\n")
    printed = []
    mod.write_sidecar(
        csv_p,
        {"111": "S8b-101", "222": "OP08-057"},
        certs_in_csv={"111", "222"},
        print_fn=printed.append,
    )
    assert printed == []


def test_write_sidecar_confirmed_pids_override(tmp_path):
    """verify_mode で人が確定した PID は resolver 値を上書きする (最強権威)。"""
    csv_p = str(tmp_path / "t.csv")
    with open(csv_p, "w") as f:
        f.write("stub\n")
    out = mod.write_sidecar(
        csv_p,
        {"111": "OLD-1", "222": "S8b-101"},
        certs_in_csv={"111", "222"},
        confirmed_pids={"111": "S8b-101"},  # 人が確定
    )
    payload = json.load(open(out, encoding="utf-8"))
    assert payload["by_cert"]["111"] == "S8b-101"


def test_write_sidecar_confirmed_pids_adds_certs_not_in_pid_by_cert(tmp_path):
    """resolver は空でも confirmed 単独で PID を持てる cert は載る (人の確定値も価値がある)。"""
    csv_p = str(tmp_path / "t.csv")
    with open(csv_p, "w") as f:
        f.write("stub\n")
    out = mod.write_sidecar(
        csv_p,
        {},  # resolver 側 miss
        certs_in_csv={"111"},
        confirmed_pids={"111": "OP08-057"},
    )
    payload = json.load(open(out, encoding="utf-8"))
    assert payload["by_cert"]["111"] == "OP08-057"


def test_write_sidecar_ignores_empty_confirmed(tmp_path):
    """confirmed_pids の空文字値では resolver 値を消さない。"""
    csv_p = str(tmp_path / "t.csv")
    with open(csv_p, "w") as f:
        f.write("stub\n")
    out = mod.write_sidecar(
        csv_p,
        {"111": "S8b-101"},
        certs_in_csv={"111"},
        confirmed_pids={"111": ""},
    )
    payload = json.load(open(out, encoding="utf-8"))
    assert payload["by_cert"]["111"] == "S8b-101"


def test_write_sidecar_utf8_no_bom(tmp_path):
    """CSV 出力規約に合わせ、JSON も UTF-8 (BOM なし) で書く。"""
    csv_p = str(tmp_path / "t.csv")
    with open(csv_p, "w") as f:
        f.write("stub\n")
    out = mod.write_sidecar(csv_p, {"111": "S8b-101"})
    with open(out, "rb") as f:
        head = f.read(3)
    assert head != b"\xef\xbb\xbf", "BOM が付いている (utf-8-sig ではないか)"


# ============================================================================
# 「CSV には列を足さない」の invariant を build_row 側でも守る
# ============================================================================
def _load_psa_to_csv_source():
    src_path = os.path.join(_TCG, "psa_to_csv.py")
    with open(src_path, "r", encoding="utf-8") as f:
        return f.read()


def test_csv_headers_unchanged_no_canonical_column():
    """psa_to_csv.py の headers に CanonicalProductID 列が生えていないこと。

    回答書の絶対条件「入稿 CSV の列構成は1文字も変えないでください」担保。
    """
    src = _load_psa_to_csv_source()
    assert "CanonicalProductID" not in src, (
        "CSV に canonical PID 列が復活している。sidecar 方式維持 (回答書 §変更点)"
    )


def test_build_row_accepts_pid_by_cert_kwarg():
    """build_row(pid_by_cert=...) を受け付ける = sidecar 集約点が生きている。"""
    src = _load_psa_to_csv_source()
    assert "def build_row(cert_number, price, data, description, driver=None, catalog_misses=None, pid_by_cert=None)" in src


def test_sidecar_write_wired_after_csv_write():
    """psa_to_csv.py 本流が write_sidecar を呼んでいる = 生成物として出る配線がある。"""
    src = _load_psa_to_csv_source()
    assert "from canonical_pid_sidecar import write_sidecar" in src
    # CSV 書出 → sidecar 書出 の順 (sidecar が先だと空になる懸念があるため順序担保)
    csv_write_idx = src.index('writer.writerows(rows)')
    sidecar_idx = src.index("_write_pid_sidecar")
    assert csv_write_idx < sidecar_idx


def test_franchise_hits_record_canonical_pid():
    """各 franchise の catalog hit block が canonical PID を記録している。"""
    src = _load_psa_to_csv_source()
    # 各分岐で _record_canonical_pid が呼ばれていること
    # (bandai / pokemon / db_full_id / gd_card_id / Energy Marker のうち少なくとも4つ)
    count = src.count("_record_canonical_pid(")
    assert count >= 5, f"canonical PID 記録点が少ない ({count})。5 franchise 経路で回収する設計"
