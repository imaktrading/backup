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
  identity TEXT DEFAULT '',
  created_ts TEXT, updated_ts TEXT, reviewed_ts TEXT
);
"""

# 既存DBに後付けする列 (CREATE TABLE IF NOT EXISTS は既存テーブルを変更しないため)
_ADD_COLUMNS = {"identity": "TEXT DEFAULT ''"}


def _migrate(con):
    """不足列を ALTER で追加 (冪等)。既存 pdca.db を作り直さず前進させる。"""
    have = {r[1] for r in con.execute("PRAGMA table_info(improvement_queue)")}
    for col, decl in _ADD_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE improvement_queue ADD COLUMN {col} {decl}")


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
    _migrate(con)
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
                       finding_type="other", identity="", ts=""):
    """改善候補を upsert。既存(同 dkey)なら seen_count++ で再発を数え priority 再計算。

    done 済の dkey が再発したら status を pending に戻す (= 直したのにまた出た → 再発行対象)。

    identity: item_id が何の商品かを Catalog が解決できる手掛かり (TCG なら
      「カード番号 | カード名 | セット名」)。item_id (m*/PSA10-* = 出品ID) 単体では
      Catalog が対象カードを特定できず backfill 不能 → 依頼が永久に再掲される
      (2026-07-15 発覚)。dedup_key には含めない (= 既存行の同一性を保ち、
      再検出時に空の既存行へ後から埋まる)。
    """
    dk = dedup_key(category, item_id, target_field, suggested_value)
    row = con.execute("SELECT queue_id, seen_count, status, identity FROM improvement_queue WHERE dkey=?",
                      (dk,)).fetchone()
    if row:
        seen = (row["seen_count"] or 1) + 1
        new_status = "pending" if row["status"] == "done" else row["status"]
        pri = compute_priority(finding_type, seen, confidence)
        # identity は「空の既存行に埋める / 新しい値で更新」。取得できなかった時に
        # 既存の解決手掛かりを空で潰さない (fail-closed)。
        ident = (identity or "").strip() or (row["identity"] or "")
        con.execute(
            "UPDATE improvement_queue SET seen_count=?, priority=?, status=?, evidence=?,"
            " confidence=?, identity=?, updated_ts=? WHERE queue_id=?",
            (seen, pri, new_status, evidence, confidence, ident, ts, row["queue_id"]))
        return row["queue_id"]
    pri = compute_priority(finding_type, 1, confidence)
    cur = con.execute(
        "INSERT INTO improvement_queue (dkey, category, item_id, target_field, suggested_value,"
        " evidence, source, layer, confidence, finding_type, seen_count, priority, status,"
        " identity, created_ts, updated_ts)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,1,?, 'pending', ?, ?, ?)",
        (dk, category, item_id, target_field, suggested_value, evidence, source, layer,
         confidence, finding_type, pri, (identity or "").strip(), ts, ts))
    return cur.lastrowid


def set_status(con, queue_id, status, ts=""):
    con.execute("UPDATE improvement_queue SET status=?, reviewed_ts=? WHERE queue_id=?", (status, ts, queue_id))


def prune_resolved_gaps(con, resolve_fn, ts="", sources=("missing_models",)):
    """解決済の catalog_gap を queue から落とす(status='done')= 「真の未解決のみ」に保つ。

    catalog に後から収録/索引修正された model は、resolve_fn(category,item_id)→True を返す。
    これを done 化しないと emit_consolidated_request が毎回 stale を再発行し、Catalog に同じ
    依頼が積み続ける(2026-06-18 Catalog 指摘B: pending の約60%が解決済 stale)。

    Args:
        resolve_fn: (category, item_id) -> bool。catalog で解決可能(=もう gap でない)なら True。
        sources: prune 対象の source(既定: psa_to_csv 由来の missing_models のみ。md_import 等は触らない)。
    Returns:
        {"pruned": n, "checked": m, "remaining_pending": k}
    """
    ph = ",".join("?" * len(sources))
    rows = con.execute(
        f"SELECT queue_id, category, item_id FROM improvement_queue "
        f"WHERE status='pending' AND source IN ({ph})", tuple(sources)).fetchall()
    pruned = 0
    for r in rows:
        try:
            ok = resolve_fn(r["category"], r["item_id"])
        except Exception:
            ok = False                       # 解決判定失敗は触らない(fail-closed=残す)
        if ok:
            set_status(con, r["queue_id"], "done", ts)
            pruned += 1
    con.commit()
    remaining = con.execute(
        "SELECT COUNT(*) FROM improvement_queue WHERE status='pending'").fetchone()[0]
    return {"pruned": pruned, "checked": len(rows), "remaining_pending": remaining}


def prune_stale_findings(con, today, max_age_days=21, sources=None):
    """長期未解決の pending を 'stale' に退役させる(digest の恒久ノイズを断つ=K1/K5)。

    created_ts(=初回検出)が max_age_days より古い pending を stale 化。catalog_gap は毎ラン
    missing_models から再 import されて seen_count が永遠に増える(SWSH Family seen×14 等)が、
    upsert は 'stale' を sticky に保つ(done 以外は status 維持)ので再 import でも復活しない
    = オシレーションなし。新規の別 item_id(別cert)は別 finding として pending で出るので
    新規取りこぼしは無い。fail-closed: ts 不正な行は触らない。
    Returns: {"pruned": n, "checked": m}。
    """
    try:
        from datetime import date, timedelta
        cutoff = (date.fromisoformat(str(today)[:10]) - timedelta(days=max_age_days)).isoformat()
    except Exception:
        return {"pruned": 0, "checked": 0}
    q = "SELECT queue_id, created_ts FROM improvement_queue WHERE status='pending'"
    params = []
    if sources:
        q += " AND source IN (%s)" % ",".join("?" * len(sources))
        params = list(sources)
    rows = con.execute(q, params).fetchall()
    pruned = 0
    for r in rows:
        ct = (r["created_ts"] or "")[:10]
        if len(ct) == 10 and ct < cutoff:        # ISO 日付の辞書順 = 時系列順
            set_status(con, r["queue_id"], "stale", today)
            pruned += 1
    con.commit()
    return {"pruned": pruned, "checked": len(rows)}


def make_catalog_resolver(catalog_db):
    """catalog products.sqlite を引いて (category,item_id)->bool を返す resolve_fn を生成。

    解決 = item_id が catalog の product_id(or alias_of)として実在。gshock 型番はこの exact 一致で
    大半が落ちる(後から収録済 = stale)。TCG の崩れた model 文字列は exact で当たらず pending 維持
    (= resolver/正規化 側の課題として残る。ここでは安全側に倒す)。接続は呼出側で使い回せるよう
    クロージャに閉じる。
    """
    con = sqlite3.connect(catalog_db)
    con.row_factory = sqlite3.Row
    cache = {}

    def _resolve(category, item_id):
        key = (category, item_id)
        if key in cache:
            return cache[key]
        hit = con.execute(
            "SELECT 1 FROM products WHERE (product_id=? OR alias_of=?) LIMIT 1",
            (item_id, item_id)).fetchone() is not None
        cache[key] = hit
        return hit

    return _resolve


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
    rows = ["| pri | item | 商品(identity) | field | 候補値 | 確信度 | 根拠 |",
            "|--:|---|---|---|---|--:|---|"]
    for r in items:
        ident = (r.get("identity") or "").strip() or "**(不明=要調査)**"
        rows.append(f"| {r['priority']} | {r['item_id']} | {ident} | {r['target_field']} | "
                    f"{(r['suggested_value'] or '')[:24]} | {r.get('confidence','')} | {(r['evidence'] or '')[:50]} |")
    return rows


def category_in_project(cat, project):
    """queue item の category が発行対象 project に属すか (純関数, test可)。

    2026-07-02: emit_consolidated_request が category 無関係に全pendingをダンプし、gshock発行時に
    TCG項目が gshock ラベルの依頼に混入していた(Catalog 指摘)。project→category族で振り分ける。
    TCG は fine-grained (pokemon_tcg/one_piece_tcg/dragonball_scg/gundam_tcg/yugioh_tcg) と粗い 'tcg' が
    混在するので、'tcg' project は '*_tcg'/'*_scg'/'tcg' を包含。gshock/mercari/ichibankuji は厳密一致。
    """
    cat = (cat or "").strip().lower()
    project = (project or "").strip().lower()
    if cat == project:
        return True
    if project == "tcg":
        return cat.endswith("_tcg") or cat.endswith("_scg")
    return False


def emit_consolidated_request(con, category, out_dir, today):
    """pending 改善候補を **1本の dedup済 catalog 依頼 .md** に集約発行 (Phase2/3・自動)。

    層A(客観ギャップ=即対応)と層B(競合intel候補=要裏取り)を分節で出力。
    毎回新規 .md を量産せず日付単位1ファイルに上書き(滞留スパム停止)。
    catalog 反映は Catalog が裏取りして実施 (SSOT/fail-closed)。Returns: 発行件数。
    発行は **当該 project(category)に属す項目のみ**(他カテゴリ混入防止=Catalog 誤ルーティング根治)。
    """
    pend = [r for r in list_queue(con, status="pending", limit=10000)
            if r.get("source") != "md_import" and category_in_project(r.get("category"), category)]
    layer_a = [r for r in pend if r.get("layer") == "A"]
    layer_b = [r for r in pend if r.get("layer") == "B"]
    if not pend:
        return 0
    body = [
        f"# 自動依頼 (PDCA改善キュー → Catalog): {category}",
        f"- 発行日: {today} / 発行者: HQ pdca_store / フェーズ: 本実装",
        "- 改善キュー(pdca.db)からの**集約・重複排除済**依頼。毎回の .md 量産を置換。",
        "- 完了したら `_processed.md` 等にリネーム → 次回 sync で queue=done に同期。",
        "- `item` は出品ID (m*=メルカリ / PSA10-*=PSA cert)。**どのカードかは `商品(identity)` 列**"
        " (カード番号 | カード名 | セット名) で引く。identity が (不明) の行は HQ 側で解決できなかった分。",
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


_MISSING_MODEL_IDENTITY_RE = re.compile(
    r"^cert(\d+)\s+(?P<brand>.+?)\s+\[(?P<subject>.+?)\]\s+#(?P<cardno>\S+)"
)


def parse_missing_model_identity(model: str) -> str:
    """post_psa_review が書く missing_models.csv の model 列から identity を抽出 (純関数)。

    書式: `cert{N} {BRAND} [{SUBJECT}] #{CARDNUMBER} (auto候補...=該当なし 要調査)`
    (iMakHQ/tools/post_psa_review.py:_route_none_to_catalog 由来)

    identity = "CARDNUMBER | SUBJECT | BRAND"。マッチ失敗は "" (fail-safe)。

    2026-07-27 Advisor 発覚: 経路 B (missing_models → pdca queue) は identity を渡して
    おらず、model 列に素材があるのに使っていなかった (queue 540/543/544 で実測)。素材を
    そのまま identity に転記する = Catalog が「どのカード」を解決できる材料を渡す。
    """
    if not model:
        return ""
    m = _MISSING_MODEL_IDENTITY_RE.match(model.strip())
    if not m:
        return ""
    parts = [m.group("cardno").strip(), m.group("subject").strip(), m.group("brand").strip()]
    parts = [p for p in parts if p]
    return " | ".join(parts)[:120]


def import_missing_models(con, path, ts=""):
    """psa_to_csv が書く missing_models.csv (catalog未登録カード) を改善キューに取込む。

    形式: category,model,detected_at。1行=1未登録カード → 層A catalog_gap として upsert
    (dedup で同カードは集約)。= 「入稿しない catalog-miss」が PDCA に乗り Catalog 依頼に流れる。

    2026-07-30: model 列から identity を parse して同送 (parse_missing_model_identity)。
    post_psa_review 由来の書式 `cert{N} {BRAND} [{SUBJECT}] #{CARDNUMBER} (...)` は既に
    identity 素材を含むので、Catalog が「どのカード」を解決できるように転記する。
    (2026-07-27 Advisor 経路 B の穴を塞ぐ)。

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
                ident = parse_missing_model_identity(model)
                upsert_improvement(con, category, model, "catalog_add", "",
                                   evidence="missing_models (catalog未登録→入稿せず)",
                                   source="missing_models", layer="A",
                                   finding_type="catalog_gap",
                                   identity=ident, ts=ts)
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
        "| pri | item | 商品(identity) | field | 値 | seen | layer | source |",
        "|--:|---|---|---|---|--:|---|---|",
    ]
    for r in list_queue(con, status="pending", limit=limit):
        lines.append(f"| {r['priority']} | {r['item_id']} | {(r.get('identity') or '') or '(不明)'} | "
                     f"{r['target_field']} | "
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
