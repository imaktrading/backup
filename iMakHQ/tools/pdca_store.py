"""pdca_store — PSA出品 Check の知見を蓄積する SQLite 層 (PDCA spiral-up Phase1)。

設計: discussion/2026-06-15_pdca_spiralup_design.md
役割: 毎回捨てていた Check 結果 (競合TOPセラー値分布 / 競合頻出語 / 監査指摘) を
  クエリ可能な資産として蓄積し、改善キュー (improvement_queue) で dedup/優先度/再発を捌く。
原則: ここは「蓄積」だけ。catalog への反映は Catalog が裏取りして実施 (SSOT・fail-closed)。
  HQ は推測値を catalog に自動書込しない。依頼の発行 (層A/層B) は別モジュール。

純関数 (compute_priority / dedup_key / parse_request_md) は DB 非依存=テスト可能。
"""
from __future__ import annotations
import os
import re
import sqlite3
from pathlib import Path

DB_PATH = r"C:/dev/iMak_data/audit/pdca.db"

# 指摘種別の重要度係数 (priority 計算用)。誤出品直結ほど高い。
_SEVERITY = {
    "catalog_gap": 5.0,        # 未収録/誤マップ = 出品不能/誤出品リスク
    "consistency_mismatch": 4.0,
    "必須Item Specific": 3.0,
    "形式逸脱": 3.0,
    "program": 4.0,
    "seo_weak": 1.0,
    "推奨": 0.8,
    "competitor_intel": 1.5,   # 競合intel候補 (推測・要裏取り)
    "other": 1.0,
}


def severity_of(finding_type: str) -> float:
    """finding_type → 重要度係数 (前方一致・未知は other)。純関数。"""
    ft = (finding_type or "").strip()
    for key, val in _SEVERITY.items():
        if ft.startswith(key):
            return val
    return _SEVERITY["other"]


def compute_priority(finding_type: str, seen_count: int = 1, confidence: float = 1.0,
                     affected_items: int = 1) -> float:
    """優先度スコア = 重要度 × 再発回数 × 確信度 × 影響アイテム数 (純関数)。

    再発 (seen_count↑) ほど・影響広いほど・確信高いほど優先。
    """
    sev = severity_of(finding_type)
    sc = max(1, int(seen_count))
    ai = max(1, int(affected_items))
    cf = min(max(float(confidence), 0.0), 1.0)
    return round(sev * sc * (0.5 + 0.5 * cf) * ai, 3)


def dedup_key(category: str, item_id: str, target_field: str, suggested_value: str = "") -> str:
    """改善キューの重複判定キー (純関数)。同一 item×field×値 は1件に集約。"""
    return "|".join([(category or "").strip(), (item_id or "").strip(),
                     (target_field or "").strip(), (suggested_value or "").strip()])


def parse_request_md(path: str) -> dict:
    """catalog 依頼 .md を棚卸し用に最小パース (純関数・I/Oは呼び出し側)。

    filename 規約 `YYYY-MM-DD_<topic>[ _processed|_response ].md` から
    date/topic/status を、本文先頭から件数を best-effort 抽出。
    Returns: {date, topic, status, item_count, raw_name}
    """
    name = Path(path).name
    stem = re.sub(r"\.md$", "", name)
    # processed/response/result/expired = 対応済/失効 → done として取込 (再発検知の基準)
    status = "done" if re.search(r"_(processed|response|result|expired)$", stem) else "pending"
    topic = re.sub(r"_(processed|response|result|expired)$", "", stem)
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)$", topic)
    date = m.group(1) if m else ""
    topic_only = m.group(2) if m else topic
    return {"date": date, "topic": topic_only, "status": status,
            "raw_name": name, "stem": stem}


# ---- DB 層 ----
_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, ts TEXT, category TEXT, item_id TEXT,
  finding_type TEXT, details TEXT, is_recurrent INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS aspect_intel (
  category_id TEXT, aspect_name TEXT, aspect_value TEXT,
  usage_rate REAL, sample_size INTEGER, last_calc_ts TEXT,
  PRIMARY KEY (category_id, aspect_name, aspect_value)
);
CREATE TABLE IF NOT EXISTS gap_keywords (
  card_id TEXT, keyword TEXT, competitor_usage_rate REAL,
  occurrences INTEGER DEFAULT 1, last_seen_ts TEXT,
  PRIMARY KEY (card_id, keyword)
);
CREATE TABLE IF NOT EXISTS improvement_queue (
  queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
  dkey TEXT UNIQUE,
  category TEXT, item_id TEXT, target_field TEXT, suggested_value TEXT,
  evidence TEXT, source TEXT, layer TEXT, confidence REAL,
  finding_type TEXT, seen_count INTEGER DEFAULT 1, priority REAL,
  status TEXT DEFAULT 'pending',
  created_ts TEXT, updated_ts TEXT, reviewed_ts TEXT
);
"""


def connect(db_path: str = None) -> sqlite3.Connection:
    # 既定値は呼出時に DB_PATH を参照 (def時固定だと monkeypatch/再代入が効かない)
    if db_path is None:
        db_path = DB_PATH
    d = os.path.dirname(db_path)
    if d and db_path != ":memory:":
        os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def record_finding(con, run_id, category, item_id, finding_type, details, is_recurrent=False, ts=""):
    con.execute(
        "INSERT INTO findings_log (run_id, ts, category, item_id, finding_type, details, is_recurrent)"
        " VALUES (?,?,?,?,?,?,?)",
        (run_id, ts, category, item_id, finding_type, details, 1 if is_recurrent else 0))


def upsert_aspect_intel(con, category_id, aspect_name, aspect_value, usage_rate, sample_size, ts=""):
    con.execute(
        "INSERT INTO aspect_intel (category_id, aspect_name, aspect_value, usage_rate, sample_size, last_calc_ts)"
        " VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(category_id, aspect_name, aspect_value) DO UPDATE SET"
        " usage_rate=excluded.usage_rate, sample_size=excluded.sample_size, last_calc_ts=excluded.last_calc_ts",
        (category_id, aspect_name, aspect_value, usage_rate, sample_size, ts))


def upsert_gap_keyword(con, card_id, keyword, rate, ts=""):
    con.execute(
        "INSERT INTO gap_keywords (card_id, keyword, competitor_usage_rate, occurrences, last_seen_ts)"
        " VALUES (?,?,?,1,?)"
        " ON CONFLICT(card_id, keyword) DO UPDATE SET"
        " competitor_usage_rate=excluded.competitor_usage_rate,"
        " occurrences=gap_keywords.occurrences+1, last_seen_ts=excluded.last_seen_ts",
        (card_id, keyword, rate, ts))


def upsert_improvement(con, category, item_id, target_field, suggested_value="", *,
                       evidence="", source="", layer="A", confidence=1.0,
                       finding_type="other", ts=""):
    """改善候補を upsert。既存(同 dkey)なら seen_count++ で再発を数え priority 再計算。

    done 済の dkey が再発したら status を pending に戻す (= 直したのにまた出た → 再発行対象)。
    """
    dk = dedup_key(category, item_id, target_field, suggested_value)
    row = con.execute("SELECT queue_id, seen_count, status FROM improvement_queue WHERE dkey=?", (dk,)).fetchone()
    if row:
        seen = (row["seen_count"] or 1) + 1
        new_status = "pending" if row["status"] == "done" else row["status"]
        pri = compute_priority(finding_type, seen, confidence)
        con.execute(
            "UPDATE improvement_queue SET seen_count=?, priority=?, status=?, evidence=?,"
            " confidence=?, updated_ts=? WHERE queue_id=?",
            (seen, pri, new_status, evidence, confidence, ts, row["queue_id"]))
        return row["queue_id"]
    pri = compute_priority(finding_type, 1, confidence)
    cur = con.execute(
        "INSERT INTO improvement_queue (dkey, category, item_id, target_field, suggested_value,"
        " evidence, source, layer, confidence, finding_type, seen_count, priority, status, created_ts, updated_ts)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,1,?, 'pending', ?, ?)",
        (dk, category, item_id, target_field, suggested_value, evidence, source, layer,
         confidence, finding_type, pri, ts, ts))
    return cur.lastrowid


def set_status(con, queue_id, status, ts=""):
    con.execute("UPDATE improvement_queue SET status=?, reviewed_ts=? WHERE queue_id=?", (status, ts, queue_id))


def list_queue(con, status=None, limit=200):
    if status:
        rows = con.execute("SELECT * FROM improvement_queue WHERE status=? ORDER BY priority DESC, queue_id LIMIT ?",
                           (status, limit)).fetchall()
    else:
        rows = con.execute("SELECT * FROM improvement_queue ORDER BY priority DESC, queue_id LIMIT ?",
                           (limit,)).fetchall()
    return [dict(r) for r in rows]


def queue_stats(con):
    """KPI/可視化用サマリー。"""
    rows = con.execute("SELECT status, COUNT(*) n FROM improvement_queue GROUP BY status").fetchall()
    by_status = {r["status"]: r["n"] for r in rows}
    total = sum(by_status.values())
    return {"total": total, "by_status": by_status,
            "pending": by_status.get("pending", 0), "done": by_status.get("done", 0)}


def _queue_table(items):
    rows = ["| pri | item | field | 候補値 | 確信度 | 根拠 |", "|--:|---|---|---|--:|---|"]
    for r in items:
        rows.append(f"| {r['priority']} | {r['item_id']} | {r['target_field']} | "
                    f"{(r['suggested_value'] or '')[:24]} | {r.get('confidence','')} | {(r['evidence'] or '')[:50]} |")
    return rows


def emit_consolidated_request(con, category, out_dir, today):
    """pending 改善候補を **1本の dedup済 catalog 依頼 .md** に集約発行 (Phase2/3・自動)。

    層A(客観ギャップ=即対応)と層B(競合intel候補=要裏取り)を分節で出力。
    毎回新規 .md を量産せず日付単位1ファイルに上書き(滞留スパム停止)。
    catalog 反映は Catalog が裏取りして実施 (SSOT/fail-closed)。Returns: 発行件数。
    """
    pend = [r for r in list_queue(con, status="pending", limit=10000) if r.get("source") != "md_import"]
    layer_a = [r for r in pend if r.get("layer") == "A"]
    layer_b = [r for r in pend if r.get("layer") == "B"]
    if not pend:
        return 0
    body = [
        f"# 自動依頼 (PDCA改善キュー → Catalog): {category}",
        f"- 発行日: {today} / 発行者: HQ pdca_store / フェーズ: 本実装",
        "- 改善キュー(pdca.db)からの**集約・重複排除済**依頼。毎回の .md 量産を置換。",
        "- 完了したら `_processed.md` 等にリネーム → 次回 sync で queue=done に同期。",
        "",
        f"## 層A 客観ギャップ(即対応) {len(layer_a)} 件",
        "(catalog 事実と突合した確実な不足/誤り。優先度降順)",
        *(_queue_table(layer_a) if layer_a else ["(なし)"]),
        "",
        f"## 層B 競合intel候補(★要裏取り・推測) {len(layer_b)} 件",
        "(TOPセラー使用値。fail-closed=自動採用せず Catalog が裏取り後に判断。誤りなら却下可)",
        *(_queue_table(layer_b) if layer_b else ["(なし)"]),
    ]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / f"{today}_pdca_catalog_queue_{category}.md").write_text("\n".join(body), encoding="utf-8")
    return len(pend)


def sync_processed(con, requests_dir, ts=""):
    """requests_dir の処理済 .md (_processed/_response/_expired) を queue=done に同期 (ループ閉じ)。

    Catalog が依頼を処理 → ファイル名が done を示す → 対応 topic の queue を done に。
    Returns: done 同期した件数。
    """
    p = Path(requests_dir)
    if not p.is_dir():
        return 0
    synced = 0
    for md in p.glob("*.md"):
        meta = parse_request_md(str(md))
        if meta["status"] != "done":
            continue
        cur = con.execute(
            "UPDATE improvement_queue SET status='done', reviewed_ts=?"
            " WHERE item_id=? AND status='pending'", (ts, meta["topic"]))
        synced += cur.rowcount
    return synced


def import_missing_models(con, path, ts=""):
    """psa_to_csv が書く missing_models.csv (catalog未登録カード) を改善キューに取込む。

    形式: category,model,detected_at。1行=1未登録カード → 層A catalog_gap として upsert
    (dedup で同カードは集約)。= 「入稿しない catalog-miss」が PDCA に乗り Catalog 依頼に流れる。
    Returns: 取込件数。
    """
    p = Path(path)
    if not p.is_file():
        return 0
    import csv as _csv
    n = 0
    try:
        with p.open(encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                model = (row.get("model") or "").strip()
                category = (row.get("category") or "tcg").strip()
                if not model:
                    continue
                upsert_improvement(con, category, model, "catalog_add", "",
                                   evidence="missing_models (catalog未登録→入稿せず)",
                                   source="missing_models", layer="A",
                                   finding_type="catalog_gap", ts=ts)
                n += 1
    except Exception:
        return n
    return n


def generate_report(con, out_path, limit=50):
    """改善キューを優先度順に markdown 可視化 (Phase1 簡易ビューア)。"""
    st = queue_stats(con)
    lines = [
        "# PDCA 改善キュー (pdca.db)",
        "",
        f"- 合計: {st['total']} / pending: **{st['pending']}** / done: {st['done']}",
        "- 優先度 = 重要度 × 再発回数 × 確信度 (高いほど先に対応)",
        "",
        f"## pending 優先度 TOP{limit}",
        "| pri | item | field | 値 | seen | layer | source |",
        "|--:|---|---|---|--:|---|---|",
    ]
    for r in list_queue(con, status="pending", limit=limit):
        lines.append(f"| {r['priority']} | {r['item_id']} | {r['target_field']} | "
                     f"{(r['suggested_value'] or '')[:20]} | {r['seen_count']} | {r['layer']} | {r['source']} |")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    return st


def import_request_dir(con, requests_dir, category, ts=""):
    """既存 catalog 依頼 .md 群を queue にインポート (滞留244棚卸し)。

    1 .md = 1 queue 行 (item_id=topic, target_field='catalog_request')。
    _processed/_response は status=done で取込 (再発検知の基準になる)。
    Returns: {imported, pending, done}。
    """
    p = Path(requests_dir)
    if not p.is_dir():
        return {"imported": 0, "pending": 0, "done": 0}
    imported = pending = done = 0
    for md in sorted(p.glob("*.md")):
        meta = parse_request_md(str(md))
        qid = upsert_improvement(
            con, category, meta["topic"], "catalog_request", "",
            evidence=f"file={meta['raw_name']}", source="md_import", layer="A",
            finding_type="catalog_gap", ts=ts)
        # filename が done を示すなら status 反映 (再発でなければ done に落とす)
        if meta["status"] == "done":
            con.execute("UPDATE improvement_queue SET status='done', reviewed_ts=? WHERE queue_id=? AND status='pending'",
                        (ts, qid))
            done += 1
        else:
            pending += 1
        imported += 1
    return {"imported": imported, "pending": pending, "done": done}
