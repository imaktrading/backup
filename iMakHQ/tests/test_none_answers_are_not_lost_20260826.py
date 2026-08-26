# -*- coding: utf-8 -*-
"""人が「該当なし」と答えた札を消さない (2026-08-26).

cert163955605 は目視で NONE と答えられ missing_models.csv に1件書かれたが、直後に
watcher の resolver pre-check が `REVIEW P-001, P-001_B, …` を根拠に「別 id で
catalog に在る」と判断して行を消した。missing_models / processed /
viewer_disagreement / pdca queue の **どこにも残らなかった**。
しかも正解 (`ST21-001_p2`) は候補に出ていなかった。

  (a) 候補は PSA Brand ↔ catalog の set_name_official でも照合して前に出す
  (b) 人が NONE と答えた cert では REVIEW を「不足なし」に数えない。
      落とす時も log だけにせず pdca queue に pending で積む
  付随 dkey を (category, cert) にして言い回しを鍵に含めない +
      クローズ済でも「また落ちた」で pending に戻す

依頼書: hq/requests/2026-08-26_act_code_proposals_tcg.md 提案4
回答書: hq/requests/2026-08-26_act_code_proposals_tcg_response.md (6)
"""
import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import pdca_store as P  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name, str(_TOOLS / f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── (a) セット名でも候補を探す ──────────────────────────────────

def test_brand_matches_set_name_finds_the_right_set():
    pf = _load("psa_preflight")
    brand = "ONE PIECE JAPANESE LIMITED CARD COLLECTION VOL.1"
    assert pf._brand_matches_set_name(
        brand, "ONE PIECEカードゲーム BASE SHOPリミテッドカードコレクションvol.1")
    # 番号だけ一致した無関係なプロモは当たらない
    assert not pf._brand_matches_set_name(brand, "プロモーションカード")
    assert not pf._brand_matches_set_name(brand, "Promotion Card")


def test_brand_matches_set_name_is_blank_safe():
    pf = _load("psa_preflight")
    assert not pf._brand_matches_set_name("", "Promotion Card")
    assert not pf._brand_matches_set_name("ONE PIECE FILM RED", "")


def test_set_name_candidates_come_first(monkeypatch):
    """正解が [:8] で切り捨てられないよう、セット名一致を先頭に出す。"""
    pf = _load("psa_preflight")
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE products (category TEXT, product_id TEXT, name_en TEXT,"
                " name TEXT, set_name_official TEXT)")
    rows = [("one_piece_tcg", f"P-001_{i}", "Monkey D. Luffy", "", "プロモーションカード")
            for i in range(10)]
    rows.append(("one_piece_tcg", "ST21-001_p2", "Monkey D. Luffy", "",
                 "ONE PIECEカードゲーム BASE SHOPリミテッドカードコレクションvol.1"))
    con.executemany("INSERT INTO products VALUES (?,?,?,?,?)", rows)
    con.commit()
    monkeypatch.setattr(pf, "_ensure_catalog", lambda: None)
    monkeypatch.setattr(pf, "_FRANCHISE",
                        {"one_piece_tcg": (lambda *a, **k: None, lambda b: None)},
                        raising=False)
    monkeypatch.setattr(pf, "_confirmed_pid", lambda cert: None)
    monkeypatch.setattr(pf, "_out_of_scope", lambda: {})
    res = pf.classify("163955605",
                      {"Brand": "ONE PIECE JAPANESE LIMITED CARD COLLECTION VOL.1",
                       "CardNumber": "001", "Subject": "MONKEY D. LUFFY"}, con)
    assert res["status"] == "REVIEW"
    assert "ST21-001_p2" in res["candidates"], \
        f"正解が候補に出ていない (8件で切られている): {res['candidates']}"
    assert res["candidates"][0] == "ST21-001_p2", "セット名一致を先頭に出していない"
    assert res["set_name_match"] == ["ST21-001_p2"]


# ── (b) 人が NONE と答えた cert は落とさない ──────────────────

def test_human_none_cert_is_not_dropped_by_review(tmp_path, monkeypatch):
    a = _load("auto_catalog_add_request")
    monkeypatch.setattr(a, "_human_said_none", lambda cert: cert == "163955605")
    dropped = []
    monkeypatch.setattr(a, "_queue_resolver_drop",
                        lambda *args: dropped.append(args[1]))

    class _FakePF:
        CATALOG_DB = ":memory:"
        PSA_CERTS_DIR = tmp_path

        @staticmethod
        def classify(cert, meta, con):
            return {"status": "REVIEW", "candidates": ["P-001", "P-001_B"]}

    (tmp_path / "163955605.json").write_text("{}", encoding="utf-8")
    (tmp_path / "999999999.json").write_text("{}", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "psa_preflight", _FakePF)

    by_cat = {"one_piece_tcg": [
        {"model": "cert163955605 LUFFY #001 (該当なし 要調査)"},
        {"model": "cert999999999 OTHER #002 (該当なし 要調査)"},
    ]}
    removed = a._filter_resolver_resolves(by_cat)
    kept = [r["model"] for r in by_cat.get("one_piece_tcg", [])]
    assert any("163955605" in k for k in kept), "人が NONE と答えた cert を落としている"
    assert removed == 1 and dropped == ["999999999"], (removed, dropped)


# ── 付随: dkey と再オープン ────────────────────────────────

def test_dedup_key_ignores_wording():
    """同じ cert なら依頼文の言い回しが変わっても1つの鍵。"""
    a = P.dedup_key("pokemon_tcg", "cert139291730 POKEMON … (auto△=該当なし 要調査)",
                    "catalog_add")
    b = P.dedup_key("pokemon_tcg", "cert139291730 POKEMON … (catalog SM9a-067 は在るが画像が無い)",
                    "catalog_add")
    assert a == b == "pokemon_tcg|cert139291730|catalog_add|"


def test_dedup_key_unchanged_without_cert():
    """cert が無い item_id (G-shock の型番等) は従来どおり。"""
    assert P.dedup_key("gshock", "GA-2100-1A1", "C:Color", "Black") == \
        "gshock|GA-2100-1A1|C:Color|Black"


def _mem_db():
    return P.connect(":memory:")


def test_closed_finding_reopens_when_it_happens_again():
    con = _mem_db()
    qid = P.upsert_improvement(con, "pokemon_tcg", "cert139291730", "catalog_add",
                               source="generator", finding_type="catalog_gap", ts="2026-08-01")
    P.set_status(con, qid, "scope_out", "2026-08-02")
    P.upsert_improvement(con, "pokemon_tcg", "cert139291730 (別の言い回し)", "catalog_add",
                         source="generator", finding_type="catalog_gap", ts="2026-08-26",
                         reopen_closed=True)
    rows = con.execute("SELECT queue_id, status, seen_count FROM improvement_queue").fetchall()
    assert len(rows) == 1, f"言い回し違いで行が割れている: {[dict(r) for r in rows]}"
    assert rows[0]["status"] == "pending", "クローズ済のまま = 再発が digest に載らない"
    assert rows[0]["seen_count"] == 2


def test_stale_stays_sticky_without_the_flag():
    """既定 (reopen_closed=False) では stale は復活しない (毎日の再 import で暴れない)。"""
    con = _mem_db()
    qid = P.upsert_improvement(con, "pokemon_tcg", "cert111111111", "catalog_add",
                               source="missing_models", ts="2026-08-01")
    P.set_status(con, qid, "stale", "2026-08-02")
    P.upsert_improvement(con, "pokemon_tcg", "cert111111111", "catalog_add",
                         source="missing_models", ts="2026-08-26")
    r = con.execute("SELECT status FROM improvement_queue").fetchone()
    assert r["status"] == "stale"


def test_recurring_now_sees_the_repeat():
    """再発 (pending かつ seen>=2) に載ること = 8/26 の `recurring_missing 0` の解消。"""
    con = _mem_db()
    qid = P.upsert_improvement(con, "pokemon_tcg", "cert139291730 (言い回しA)", "catalog_add",
                               source="generator", finding_type="catalog_gap", ts="2026-08-01")
    P.set_status(con, qid, "done", "2026-08-02")
    P.upsert_improvement(con, "pokemon_tcg", "cert139291730 (言い回しB)", "catalog_add",
                         source="generator", finding_type="catalog_gap", ts="2026-08-26",
                         reopen_closed=True)
    n = con.execute("SELECT COUNT(*) FROM improvement_queue "
                    "WHERE status='pending' AND seen_count>=2").fetchone()[0]
    assert n == 1, "再発として数えられていない"
