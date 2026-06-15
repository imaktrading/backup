"""pdca_store 回帰テスト (PDCA spiral-up Phase1・2026-06-15)。

固定: 純関数 (priority/dedup/md parse) + 蓄積/再発/棚卸しの不変条件。
DB は :memory: で隔離 (実 pdca.db 非依存)。
"""
import os
import sys

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import pdca_store as P  # noqa: E402


def _con():
    return P.connect(":memory:")


# ---- 純関数 ----
def test_severity_and_priority_ordering():
    # catalog_gap > seo_weak、再発で priority 上昇
    assert P.severity_of("catalog_gap") > P.severity_of("seo_weak")
    p1 = P.compute_priority("catalog_gap", seen_count=1)
    p3 = P.compute_priority("catalog_gap", seen_count=3)
    assert p3 > p1                       # 再発ほど優先
    # 確信度が低いと下がる
    assert P.compute_priority("competitor_intel", confidence=1.0) > \
           P.compute_priority("competitor_intel", confidence=0.3)


def test_dedup_key_stable():
    a = P.dedup_key("tcg", "S8b-241", "C:Rarity", "CSR")
    b = P.dedup_key("tcg", "S8b-241", "C:Rarity", "CSR")
    c = P.dedup_key("tcg", "S8b-241", "C:Rarity", "")
    assert a == b and a != c


def test_parse_request_md_status_and_topic():
    a = P.parse_request_md("2026-06-15_gshock_color_fix.md")
    assert a["status"] == "pending" and a["date"] == "2026-06-15" and a["topic"] == "gshock_color_fix"
    b = P.parse_request_md("2026-06-13_kai_irida_processed.md")
    assert b["status"] == "done" and b["topic"] == "kai_irida"
    c = P.parse_request_md("2026-06-12_old_topic_expired.md")
    assert c["status"] == "done" and c["topic"] == "old_topic"


# ---- 蓄積/再発 ----
def test_upsert_improvement_dedup_and_recurrence():
    con = _con()
    q1 = P.upsert_improvement(con, "tcg", "S8b-241", "C:Rarity", "CSR", finding_type="必須Item Specific")
    q2 = P.upsert_improvement(con, "tcg", "S8b-241", "C:Rarity", "CSR", finding_type="必須Item Specific")
    assert q1 == q2                       # 同一は1件に集約 (dup作らない)
    row = con.execute("SELECT seen_count, priority FROM improvement_queue WHERE queue_id=?", (q1,)).fetchone()
    assert row["seen_count"] == 2         # 再発カウント
    # 別値は別行
    q3 = P.upsert_improvement(con, "tcg", "S8b-241", "C:Rarity", "Rare")
    assert q3 != q1


def test_done_reopens_on_recurrence():
    con = _con()
    qid = P.upsert_improvement(con, "tcg", "X-1", "catalog_request", finding_type="catalog_gap")
    P.set_status(con, qid, "done")
    # 直したのにまた出た → pending に戻す (再発行対象)
    P.upsert_improvement(con, "tcg", "X-1", "catalog_request", finding_type="catalog_gap")
    row = con.execute("SELECT status, seen_count FROM improvement_queue WHERE queue_id=?", (qid,)).fetchone()
    assert row["status"] == "pending" and row["seen_count"] == 2


def test_aspect_and_gap_upsert():
    con = _con()
    P.upsert_aspect_intel(con, "183454", "Features", "Full Art", 0.8, 40)
    P.upsert_aspect_intel(con, "183454", "Features", "Full Art", 0.85, 50)  # 上書き
    r = con.execute("SELECT usage_rate, sample_size FROM aspect_intel WHERE aspect_value='Full Art'").fetchone()
    assert r["usage_rate"] == 0.85 and r["sample_size"] == 50
    P.upsert_gap_keyword(con, "SV4a-350", "shiny", 0.6)
    P.upsert_gap_keyword(con, "SV4a-350", "shiny", 0.7)  # occurrences++
    g = con.execute("SELECT occurrences, competitor_usage_rate FROM gap_keywords WHERE keyword='shiny'").fetchone()
    assert g["occurrences"] == 2 and g["competitor_usage_rate"] == 0.7


def test_queue_stats_and_list_priority_order():
    con = _con()
    P.upsert_improvement(con, "tcg", "lo", "f", finding_type="seo_weak")          # 低
    hi = P.upsert_improvement(con, "tcg", "hi", "f", finding_type="catalog_gap")  # 高
    listed = P.list_queue(con, status="pending")
    assert listed[0]["queue_id"] == hi     # priority 降順
    st = P.queue_stats(con)
    assert st["total"] == 2 and st["pending"] == 2


def test_import_request_dir(tmp_path):
    con = _con()
    (tmp_path / "2026-06-10_a.md").write_text("x", encoding="utf-8")
    (tmp_path / "2026-06-10_a_processed.md").write_text("x", encoding="utf-8")  # done
    (tmp_path / "2026-06-11_b.md").write_text("x", encoding="utf-8")
    res = P.import_request_dir(con, str(tmp_path), "tcg")
    assert res["imported"] == 3
    # a と a_processed は同 topic 'a' → dedup で1件 (processed で done)
    rows = P.list_queue(con)
    topics = {r["item_id"] for r in rows}
    assert topics == {"a", "b"}
