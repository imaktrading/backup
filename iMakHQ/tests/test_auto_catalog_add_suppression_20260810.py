# -*- coding: utf-8 -*-
"""`auto_catalog_add_request` の A群 suppression list 回帰テスト (2026-08-10).

回答書: `C:/dev/iMak_data/hq/requests/2026-08-10_catalog_auto_request_suppress_known_no_image_response.md`
元依頼 (routing 草案): `_routed/2026-08-10_catalog_to_hq_auto_request_suppress_known_no_image.md`

固定する挙動:
  T1: suppression に載る A群 pid (SM9a-067 の NO_IMAGE 形 model) → 依頼書に載らず
      missing_models.csv からも落ちる + viewer_disagreement.log には書かない
      (A群は disagreement ではなく HQ 確定 skip)
  T2: suppression に載る pid でもカテゴリが違う → 従来どおり依頼書に載る (誤救出防止)
  T3: NO_IMAGE 形 model で pid が suppression に無い → 従来どおり依頼書に載る
      (2026-08-09 の意図的な NO_IMAGE→catalog 経路を保つ)
  T4: JSON が壊れている / ファイル不在 → 例外を握らず空 suppression として処理継続
      (fail-safe)
  T5: 通常の Case1/Case2 は既存 test と挙動不変 (regression)
  T6: `_extract_expected_pid` の or 分岐が `(catalog SM9a-067 は在るが...)` を抜けること
      の unit test (2026-08-10 追加 regex の固定)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import auto_catalog_add_request as a  # noqa: E402


# --- fixtures ---------------------------------------------------------------


def _seed_catalog(tmp_path: Path) -> Path:
    db = tmp_path / "products.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE products ("
        "id INTEGER PRIMARY KEY, category TEXT NOT NULL, product_id TEXT NOT NULL,"
        "name TEXT NOT NULL, specs TEXT NOT NULL, source TEXT NOT NULL,"
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    # SM9a-067 / SM11-112 は catalog に行はある (画像は無い前提だが、テスト schema には
    # images 列がないので _catalog_pid_state は _PID_OK に倒れる = 行あり判定になる)。
    for cat, pid, name in [
        ("pokemon_tcg", "SM9a-067",  "Gardevoir & Sylveon-GX"),
        ("pokemon_tcg", "SM11-112",  "Dragonite-GX"),
        ("pokemon_tcg", "SM12-112",  "Arceus & Dialga & Palkia-GX"),
    ]:
        conn.execute(
            "INSERT INTO products(category,product_id,name,specs,source,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (cat, pid, name, "{}", "seed", "2026-01-01", "2026-01-01"),
        )
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def vd_log(tmp_path, monkeypatch):
    """viewer_disagreement.log を tmp に逃がす (本番 log を汚さない)."""
    path = tmp_path / "viewer_disagreement.log"
    real = a._load_catalog_probe

    def fake():
        has_pid, _ = real()
        return has_pid, path

    monkeypatch.setattr(a, "_load_catalog_probe", fake)
    return path


def _row(category: str, model: str) -> dict:
    return {"model": model, "detected_at": "2026-08-10", "category": category}


def _write_supp(tmp_path: Path, payload: dict | str) -> Path:
    p = tmp_path / "known_no_image_a_group.json"
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# post_psa_review が NO_IMAGE で emit する model の実例 (missing_models_processed.csv 実測):
NOIMAGE_SM9A067 = (
    "cert139291730 POKEMON JAPANESE SUN & MOON STRENGTH EXPANSION PACK NIGHT UNISON "
    "[FA/GRDVR. & SYLVN. GX NIGHT UNISON-HYPER] #067 "
    "(catalog SM9a-067 は在るが画像が無く目視できない 画像を追加してほしい)"
)
NOIMAGE_SM11_112 = (
    "cert141208100 POKEMON JAPANESE SUN & MOON MIRACLE TWINS "
    "[FA/DRAGONITE GX MIRACLE TWINS-HYPER] #112 "
    "(catalog SM11-112 は在るが画像が無く目視できない 画像を追加してほしい)"
)
# suppression に載らない NO_IMAGE (新規発見の画像欠 = 2026-08-09 意図経路を保つ用)
NOIMAGE_NEW_PID = (
    "cert900000000 POKEMON JAPANESE X [FOO] #001 "
    "(catalog SV99-001 は在るが画像が無く目視できない 画像を追加してほしい)"
)
CASE1_PRESENT = "cert154233090 ONE PIECE [SABO] #118 (auto候補OP07-118=該当なし 要調査)"
CASE1_ABSENT = "cert999999999 ONE PIECE [X] #999 (auto候補OP99-999=該当なし 要調査)"
CASE2 = "ONE PIECE JAPANESE 3RD ANNIVERSARY SET-118"


# --- T1: suppression の A群 pid は依頼書に載らず、csv からも落ち、log には書かない ---


def test_t1_a_group_pid_is_dropped_and_not_logged(tmp_path, vd_log):
    supp_path = _write_supp(tmp_path, {
        "pokemon_tcg": {
            "SM9a-067": {"decided_at": "2026-08-10",
                         "reason": "pokemon-card.com index 外", "ref": "done.md"},
        }
    })
    supp = a._load_suppression(supp_path)
    assert "pokemon_tcg" in supp and "SM9a-067" in supp["pokemon_tcg"]

    row = _row("pokemon_tcg", NOIMAGE_SM9A067)
    unique = {("pokemon_tcg", NOIMAGE_SM9A067): row}
    new_by_cat = {"pokemon_tcg": [row]}

    removed = a._filter_suppression(new_by_cat, unique, supp)
    assert removed == 1
    assert "pokemon_tcg" not in new_by_cat, "A群なのに依頼対象に残っている"
    assert ("pokemon_tcg", NOIMAGE_SM9A067) not in unique, \
        "missing_models.csv から落ちないと毎日再検出される"
    # A群 skip は disagreement ではないので viewer_disagreement.log に書かない
    if vd_log.exists():
        assert "SM9a-067" not in vd_log.read_text(encoding="utf-8")


# --- T2: カテゴリ跨ぎでは救わない (誤救出防止) --------------------------------


def test_t2_cross_category_pid_is_not_suppressed(tmp_path, vd_log):
    """pokemon の SM12-112 を one_piece の依頼で drop してはいけない."""
    supp_path = _write_supp(tmp_path, {
        "pokemon_tcg": {
            "SM12-112": {"decided_at": "2026-08-10", "reason": "x", "ref": "y"},
        }
    })
    supp = a._load_suppression(supp_path)
    # one_piece 側の依頼に (auto候補SM12-112=…) が紛れ込んでも suppression では落とさない
    row = _row("one_piece_tcg", "cert1 X (auto候補SM12-112=該当なし 要調査)")
    new_by_cat = {"one_piece_tcg": [row]}
    assert a._filter_suppression(new_by_cat, None, supp) == 0
    assert len(new_by_cat["one_piece_tcg"]) == 1


# --- T3: suppression に無い NO_IMAGE 行は従来通り依頼書に載る -----------------


def test_t3_no_image_not_in_supp_still_requested(tmp_path, vd_log):
    """2026-08-09 の意図的 NO_IMAGE→catalog 経路を破壊しないこと."""
    supp_path = _write_supp(tmp_path, {
        "pokemon_tcg": {
            "SM9a-067": {"decided_at": "2026-08-10", "reason": "x", "ref": "y"},
        }
    })
    supp = a._load_suppression(supp_path)
    row = _row("pokemon_tcg", NOIMAGE_NEW_PID)
    new_by_cat = {"pokemon_tcg": [row]}
    assert a._filter_suppression(new_by_cat, None, supp) == 0
    assert len(new_by_cat["pokemon_tcg"]) == 1


def test_t3b_no_image_survives_catalog_present_prefilter(tmp_path, vd_log):
    """行が catalog に在るからと言って catalog_present で drop してはいけない
    (NO_IMAGE 経路は 2026-08-09 の意図的挙動。 A群 除外は suppression 側の責務)."""
    db = _seed_catalog(tmp_path)  # SM9a-067 は catalog に seed 済
    row = _row("pokemon_tcg", NOIMAGE_SM9A067)
    new_by_cat = {"pokemon_tcg": [row]}
    unique = {("pokemon_tcg", NOIMAGE_SM9A067): row}
    removed = a._filter_catalog_present(new_by_cat, unique, db_path=db)
    assert removed == 0, "catalog_present が NO_IMAGE 行を勝手に drop している"
    assert len(new_by_cat["pokemon_tcg"]) == 1


# --- T4: JSON 破損 / ファイル不在 → fail-safe -------------------------------


def test_t4_missing_json_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    supp = a._load_suppression(missing)
    assert supp == {}


def test_t4_broken_json_returns_empty_and_continues(tmp_path, capsys):
    p = _write_supp(tmp_path, "{ this is not valid json")
    supp = a._load_suppression(p)
    assert supp == {}
    err = capsys.readouterr().out
    assert "warn" in err.lower(), "silent drop している (warn を出すこと)"


def test_t4_invalid_entry_is_dropped_but_valid_kept(tmp_path, capsys):
    p = _write_supp(tmp_path, {
        "pokemon_tcg": {
            "SM9a-067": {"decided_at": "2026-08-10", "reason": "ok", "ref": "y"},
            "":         {"decided_at": "2026-08-10", "reason": "empty pid", "ref": "z"},
            "BAD-999":  {"decided_at": "not-a-date", "reason": "bad date", "ref": "z"},
        }
    })
    supp = a._load_suppression(p)
    assert supp == {"pokemon_tcg": {"SM9a-067":
                                    {"decided_at": "2026-08-10", "reason": "ok", "ref": "y"}}}


def test_t4_suppression_pipeline_survives_missing_file(tmp_path, vd_log):
    """本番運用 file が消えても main 経路が例外にならず、全件が従来通り依頼される."""
    row = _row("pokemon_tcg", NOIMAGE_SM9A067)
    new_by_cat = {"pokemon_tcg": [row]}
    supp = a._load_suppression(tmp_path / "nope.json")
    assert a._filter_suppression(new_by_cat, None, supp) == 0
    assert len(new_by_cat["pokemon_tcg"]) == 1


# --- T5: 既存 Case1/Case2 の挙動不変 (regression) --------------------------


def test_t5_case1_present_still_dropped_by_catalog_present(tmp_path, vd_log):
    db = _seed_catalog(tmp_path)
    # one_piece の Case1 で pokemon カテゴリ実在 pid を使うのは cross-cat test なので、
    # ここは pokemon 内で catalog 実在 → auto候補 経路が従来通り落ちることを確認する
    row = _row("pokemon_tcg", "cert1 X (auto候補SM12-112=該当なし 要調査)")
    new_by_cat = {"pokemon_tcg": [row]}
    unique = {("pokemon_tcg", row["model"]): row}
    removed = a._filter_catalog_present(new_by_cat, unique, db_path=db)
    assert removed == 1
    assert "pokemon_tcg" not in new_by_cat


def test_t5_case1_absent_still_kept(tmp_path, vd_log):
    db = _seed_catalog(tmp_path)
    row = _row("pokemon_tcg", "cert1 X (auto候補ZZ99-999=該当なし 要調査)")
    new_by_cat = {"pokemon_tcg": [row]}
    assert a._filter_catalog_present(new_by_cat, db_path=db) == 0
    assert len(new_by_cat["pokemon_tcg"]) == 1


def test_t5_case2_still_undecidable_and_kept(tmp_path, vd_log):
    db = _seed_catalog(tmp_path)
    row = _row("pokemon_tcg", CASE2)
    new_by_cat = {"pokemon_tcg": [row]}
    assert a._filter_catalog_present(new_by_cat, db_path=db) == 0
    assert len(new_by_cat["pokemon_tcg"]) == 1


# --- T6: `_extract_expected_pid` の NO_IMAGE 分岐 -------------------------


def test_t6_extract_pid_matches_no_image_format():
    assert a._extract_expected_pid(NOIMAGE_SM9A067) == "SM9a-067"
    assert a._extract_expected_pid(NOIMAGE_SM11_112) == "SM11-112"
    # BDK-005 は response で外されているが regex 自体は抜けること
    m = "cert1 X (catalog BDK-005 は在るが画像が無く目視できない ...)"
    assert a._extract_expected_pid(m) == "BDK-005"


def test_t6_extract_pid_auto_candidate_still_wins():
    """auto候補 と NO_IMAGE 両方の pattern が同じ文字列に居る奇形は前者を優先."""
    m = "cert1 (auto候補OP07-118=該当なし) catalog SM9a-067 は在るが画像が無く目視できない"
    assert a._extract_expected_pid(m) == "OP07-118"


def test_t6_extract_pid_none_for_unmatchable():
    assert a._extract_expected_pid("") is None
    assert a._extract_expected_pid("何も無い") is None
    assert a._extract_expected_pid(CASE2) is None


# --- integration: production JSON (9 件) の妥当性 --------------------------


def test_production_json_has_9_entries_and_no_bdk():
    """response 訂正 (2026-08-11): BDK-005/006 は画像取得済で除外、初期は 9件."""
    supp = a._load_suppression()
    if not supp:  # 本番ファイルが未配置なら skip 相当 (別 CI では読めない可能性)
        pytest.skip("known_no_image_a_group.json が読めない環境")
    assert "pokemon_tcg" in supp
    entries = supp["pokemon_tcg"]
    assert len(entries) == 9, f"想定 9件、実際 {len(entries)}件"
    expected = {"SM11-112", "SM12-112", "SM12a-214", "SM12a-224", "SM9a-067",
                "CLF-002", "CLF-015", "CLK-008", "EBB-045"}
    assert set(entries.keys()) == expected
    # BDK-005/006 が入っていないこと (2026-08-10 pcg-search で画像を取得済)
    assert "BDK-005" not in entries
    assert "BDK-006" not in entries
