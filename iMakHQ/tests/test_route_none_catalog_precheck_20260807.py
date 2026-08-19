# -*- coding: utf-8 -*-
"""`_route_none_to_catalog` の catalog 実在 pre-check 回帰テスト (2026-08-07).

回答書: `2026-08-06_act_code_proposals_tcg_response.md` (提案1 実装 GO).

★2026-08-19 契約更新 (`2026-08-19_act_code_proposals_tcg_response.md` の 4):
  1 は **skip をやめた**。log には catalog 依頼へ昇格する経路が無く握り潰しだったため、
  「行は在るのに人が該当なしと言う = variant (別絵柄) 欠落の疑い」として
  missing_models にも理由付きで流す。log は経緯用に残す。

固定する挙動 (3-way + fail-closed):
  1. expected PID が catalog に (category, product_id) 完全一致で存在 →
     viewer_disagreement.log に残し、**かつ** missing_models.csv に
     `variant欠落の疑い` の理由で書く
  2. expected PID が catalog に無い (= adapter 提案 PID が本当に未収録) →
     従来どおり missing_models.csv に書く (auto_catalog_add 経路に流す)
  3. expected == "無" (adapter が候補すら出せなかった真の gap) →
     従来どおり missing_models.csv に書く (見落とし禁止 = fail-closed)
  4. DB 不在等で判定不能 → missing_models.csv に書く (fail-closed = 見落とし側に倒さない)
  5. カテゴリ跨ぎで PID が偶然一致しても実在扱いしない
     (SM12-112 が one_piece_tcg に紛れても pokemon_tcg 実在で救わない)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import post_psa_review as p  # noqa: E402


# --- fixtures ---------------------------------------------------------------


def _seed_catalog(tmp_path: Path) -> Path:
    """products.sqlite に「実在」PID を仕込む."""
    db = tmp_path / "products.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE products ("
        "id INTEGER PRIMARY KEY, category TEXT NOT NULL, product_id TEXT NOT NULL,"
        "name TEXT NOT NULL, specs TEXT NOT NULL, source TEXT NOT NULL,"
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    # 提案1 に出てくる実例 3 件 (窓口が実機で裏取り済)
    rows = [
        ("dragonball_scg", "FB01-071_PARA", "Son Gohan : Childhood"),
        ("pokemon_tcg",    "SM12-112",      "Arceus & Dialga & Palkia-GX"),
        ("pokemon_tcg",    "XY-030",        "Raichu"),
    ]
    for cat, pid, name in rows:
        conn.execute(
            "INSERT INTO products(category,product_id,name,specs,source,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (cat, pid, name, "{}", "seed", "2026-01-01", "2026-01-01"),
        )
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def stub_meta(monkeypatch):
    """`_get_psa_cache` を差し替え (in-scope brand を返す = tcg_scope で弾かれない)."""
    def _fake(cert):
        # ★2026-08-19: brand は **実データと同じ形** (`POKEMON JAPANESE …`) にする。
        #   裸の `POKEMON` は psa_cache 1,070件に1件も無く、非日本語 Pokemon の
        #   scope gate (回答書 2026-08-19 の 2) に引っかかって全件 skip されてしまう。
        return {"Brand": "POKEMON JAPANESE SV4A SHINY TREASURE EX",
                "Subject": "TEST", "CardNumber": "001"}
    monkeypatch.setattr(p, "_get_psa_cache", _fake)


@pytest.fixture()
def paths(tmp_path):
    return {
        "missing": tmp_path / "missing_models.csv",
        "vd":      tmp_path / "viewer_disagreement.log",
        "db":      _seed_catalog(tmp_path),
    }


# --- tests: catalog 実在 pre-check ------------------------------------------


def test_expected_exists_in_catalog_is_routed_as_variant_gap(stub_meta, paths):
    """1) expected PID が catalog に実在 → log に残し、**かつ** variant 欠落として流す.

    ★2026-08-19 変更前は written==0 (握り潰し) だった。log の読み手は status_now の
      表示5行だけで catalog 依頼へ昇格する経路が0本 = 人の「該当なし」が捨てられていた。
    """
    recs = [{"cert": "158452539", "category": "pokemon_tcg", "expected": "XY-030"}]
    written = p._route_none_to_catalog(
        recs,
        missing_path=paths["missing"],
        trigger_request=False,
        viewer_disagreement_path=paths["vd"],
        catalog_db=paths["db"],
    )
    assert written == 1, "実在 PID を握り潰している (旧 continue が残っている)"
    body = paths["missing"].read_text(encoding="utf-8")
    assert "cert158452539" in body
    assert "variant欠落の疑い" in body, f"理由が書き分けられていない: {body}"
    assert "auto候補XY-030=該当なし" not in body, "未収録と同じ理由文にしない"
    # 経緯用の viewer_disagreement は残す
    assert paths["vd"].exists()
    vd = paths["vd"].read_text(encoding="utf-8")
    assert "cert158452539" in vd
    assert "pokemon_tcg" in vd
    assert "XY-030" in vd


def test_expected_missing_from_catalog_is_written(stub_meta, paths):
    """2) expected PID が catalog に無い → 従来どおり missing_models に書く."""
    recs = [{"cert": "999999999", "category": "pokemon_tcg", "expected": "ZZ-999"}]
    written = p._route_none_to_catalog(
        recs,
        missing_path=paths["missing"],
        trigger_request=False,
        viewer_disagreement_path=paths["vd"],
        catalog_db=paths["db"],
    )
    assert written == 1
    body = paths["missing"].read_text(encoding="utf-8")
    assert "cert999999999" in body
    assert "auto候補ZZ-999=該当なし" in body
    # viewer_disagreement には書かれない
    assert not paths["vd"].exists() or "cert999999999" not in paths["vd"].read_text(encoding="utf-8")


def test_expected_無_is_written(stub_meta, paths):
    """3) expected == "無" (adapter 候補ゼロ = 真の gap) → missing_models に書く."""
    recs = [{"cert": "888888888", "category": "pokemon_tcg", "expected": "無"}]
    written = p._route_none_to_catalog(
        recs,
        missing_path=paths["missing"],
        trigger_request=False,
        viewer_disagreement_path=paths["vd"],
        catalog_db=paths["db"],
    )
    assert written == 1
    body = paths["missing"].read_text(encoding="utf-8")
    assert "cert888888888" in body


def test_db_missing_falls_back_to_missing_models(stub_meta, paths, tmp_path):
    """4) DB 不在で pre-check 判定不能 → 従来どおり missing_models に書く (fail-closed)."""
    recs = [{"cert": "777777777", "category": "pokemon_tcg", "expected": "XY-030"}]
    written = p._route_none_to_catalog(
        recs,
        missing_path=paths["missing"],
        trigger_request=False,
        viewer_disagreement_path=paths["vd"],
        catalog_db=tmp_path / "does_not_exist.sqlite",
    )
    assert written == 1, "判定不能なら見落とし禁止 (missing_models 側に倒す)"
    body = paths["missing"].read_text(encoding="utf-8")
    assert "cert777777777" in body


def test_cross_category_pid_collision_is_not_saved(stub_meta, paths):
    """5) 別カテゴリで PID が偶然一致しても実在扱いしない (=依然として missing_models へ)."""
    # dragonball_scg の FB01-071_PARA を pokemon_tcg で問い合わせても実在扱いしない
    recs = [{"cert": "666666666", "category": "pokemon_tcg", "expected": "FB01-071_PARA"}]
    written = p._route_none_to_catalog(
        recs,
        missing_path=paths["missing"],
        trigger_request=False,
        viewer_disagreement_path=paths["vd"],
        catalog_db=paths["db"],
    )
    assert written == 1
    body = paths["missing"].read_text(encoding="utf-8")
    assert "cert666666666" in body


def test_mixed_batch_partitions_correctly(stub_meta, paths):
    """混在 batch: 実在1 / 未収録1 / 無1 → **3件とも** missing_models、log は実在1件のみ.

    ★2026-08-19: 実在1件も流すようになったので 2 → 3。理由文だけが違う。
    """
    recs = [
        {"cert": "111", "category": "pokemon_tcg", "expected": "SM12-112"},  # 実在 → skip
        {"cert": "222", "category": "pokemon_tcg", "expected": "XX-000"},    # 未収録 → 書く
        {"cert": "333", "category": "pokemon_tcg", "expected": "無"},        # 真の gap → 書く
    ]
    written = p._route_none_to_catalog(
        recs,
        missing_path=paths["missing"],
        trigger_request=False,
        viewer_disagreement_path=paths["vd"],
        catalog_db=paths["db"],
    )
    assert written == 3
    body = paths["missing"].read_text(encoding="utf-8")
    assert "cert111" in body and "variant欠落の疑い" in body
    assert "cert222" in body and "auto候補XX-000=該当なし" in body
    assert "cert333" in body
    vd = paths["vd"].read_text(encoding="utf-8")
    assert "cert111" in vd
    assert "cert222" not in vd
    assert "cert333" not in vd


# --- tests: _catalog_has_pid (純関数) -----------------------------------------


def test_catalog_has_pid_true_for_exact_match(paths):
    assert p._catalog_has_pid("pokemon_tcg", "XY-030", db_path=paths["db"]) is True


def test_catalog_has_pid_false_for_absent(paths):
    assert p._catalog_has_pid("pokemon_tcg", "NOPE-999", db_path=paths["db"]) is False


def test_catalog_has_pid_none_for_empty_or_unknown_pid(paths):
    # 空 / "無" は判定材料なし = None (呼出側は書く側に倒す)
    assert p._catalog_has_pid("pokemon_tcg", "", db_path=paths["db"]) is None
    assert p._catalog_has_pid("pokemon_tcg", "無", db_path=paths["db"]) is None


def test_catalog_has_pid_none_when_db_missing(tmp_path):
    # DB 不在は None (判定不能 = fail-closed で書く側に倒す)
    assert p._catalog_has_pid("pokemon_tcg", "XY-030",
                              db_path=tmp_path / "no_such_db.sqlite") is None


def test_catalog_has_pid_no_name_fallback(paths):
    """名前検索フォールバック禁止: 名前 "Raichu" では実在扱いしない (canonical KEY 完全一致のみ)."""
    assert p._catalog_has_pid("pokemon_tcg", "Raichu", db_path=paths["db"]) is False
