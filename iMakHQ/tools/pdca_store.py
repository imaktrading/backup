"""pdca_store — PSA出品 Check の知見を蓄積する SQLite 層 (PDCA spiral-up Phase1)。

設計: discussion/2026-06-15_pdca_spiralup_design.md
役割: 毎回捨てていた Check 結果 (競合TOPセラー値分布 / 競合頻出語 / 監査指摘) を
  クエリ可能な資産として蓄積し、改善キュー (improvement_queue) で dedup/優先度/再発を捌く。
原則: ここは「蓄積」だけ。catalog への反映は Catalog が裏取りして実施 (SSOT・fail-closed)。
  HQ は推測値を catalog に自動書込しない。依頼の発行 (層A/層B) は別モジュール。

純関数 (compute_priority / dedup_key / parse_request_md) は DB 非依存=テスト可能。
"""
from __future__ import annotations
import inspect
import json
import os
import re
import re as _re
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


# item_id に混ざる cert 番号。ここから先の言い回しは鍵に入れない (2026-08-26)。
_CERT_IN_ITEM_RE = re.compile(r"cert(\d{6,})")


def normalize_item_key(item_id: str) -> str:
    """同じカードを指す item_id を1つの鍵に揃える (純関数)。

    ★2026-08-26: item_id が missing_models.csv 由来の **長文**で、依頼文の言い回しが
      変わるたびに別の鍵になっていた。実測 cert139291730 は
        queue 444 (…(auto△=該当なし 要調査))      seen 26 / scope_out
        queue 529 (…(auto…SM9a-067=該当なし …))    seen  1 / done
        queue 561 (…(catalog SM9a-067 は在るが…))  seen  1 / done
      の **3行に割れて全部クローズ済**。それでも同じ cert が毎日落ちていたのに、
      再発 (`status='pending' AND seen_count>=2`) には構造的に載らない。
      cert が読み取れる item_id は `cert<番号>` だけを鍵にする。
      依頼書: hq/requests/2026-08-26_act_code_proposals_tcg.md 提案4 (付随)
    """
    s = (item_id or "").strip()
    m = _CERT_IN_ITEM_RE.search(s)
    return f"cert{m.group(1)}" if m else s


def dedup_key(category: str, item_id: str, target_field: str, suggested_value: str = "") -> str:
    """改善キューの重複判定キー (純関数)。同一 item×field×値 は1件に集約。

    item_id に cert 番号が在る時は **(category, cert)** だけで揃える (言い回しは入れない)。
    """
    return "|".join([(category or "").strip(), normalize_item_key(item_id),
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
  finding_type TEXT, seen_count INTEGER DEFAULT 1, seen_days INTEGER DEFAULT 1, priority REAL,
  status TEXT DEFAULT 'pending',
  identity TEXT DEFAULT '',
  catalog_state TEXT DEFAULT '',
  last_writer TEXT DEFAULT '',
  created_ts TEXT, updated_ts TEXT, reviewed_ts TEXT
);
"""

# 既存DBに後付けする列 (CREATE TABLE IF NOT EXISTS は既存テーブルを変更しないため)
_ADD_COLUMNS = {"identity": "TEXT DEFAULT ''", "seen_days": "INTEGER DEFAULT 1",
                "catalog_state": "TEXT DEFAULT ''", "last_writer": "TEXT DEFAULT ''"}

# 列を足した直後だけ流す backfill (冪等: 列が既に有れば実行されない)。
_BACKFILL = {
    # seen_days の初期値は「作った日と最後に見た日が違うなら 2」。
    # 一律 1 にすると、既に何日も消えていない既存の再発が全部 消えてしまう。
    "seen_days": "UPDATE improvement_queue SET seen_days = 2"
                 " WHERE substr(COALESCE(created_ts,''),1,10)"
                 "    <> substr(COALESCE(updated_ts,''),1,10)",
}


def _migrate(con):
    """不足列を ALTER で追加 (冪等)。既存 pdca.db を作り直さず前進させる。"""
    have = {r[1] for r in con.execute("PRAGMA table_info(improvement_queue)")}
    for col, decl in _ADD_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE improvement_queue ADD COLUMN {col} {decl}")
            if col in _BACKFILL:
                con.execute(_BACKFILL[col])
                con.commit()   # UPDATE はトランザクションを開くので commit しないと消える


def day_of(ts) -> str:
    """ts ('2026-08-28' / '2026-08-28 15:08') → 日付部分。取れなければ '' (純関数)。"""
    return str(ts or "").strip()[:10]


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


def should_reopen(row, observed_ts="", catalog_state="", reopen_closed=False):
    """閉じた行を pending に戻してよいか (純関数)。

    ★2026-08-28: 「不要」で閉じた行が翌日また起票され、tcg の層A は 8/26・8/27・8/28 と
      **3日連続で同じ中身**になっていた。全件 catalog に行が在り、毎回「不要」で返させていた。
      戻してよいのは次の2つが揃った時だけ:
        (a) **新しい観測**である (閉じた日より後に見た)。
            `missing_models.csv` のような **消えない台帳**は毎回読み直されるので、
            古い行の再読込を「今日また落ちた」と解釈すると永久に復活し続ける。
        (b) **カタログ側が閉じた時と変わっている** (catalog_state が違う)。
            同じ状態のまま送り直しても、返ってくる答えは前回と同じ「不要」。
      catalog_state を渡さない呼び出しは (b) を判定できないので (a) だけで決める
      (従来の挙動を残す)。
      依頼書: hq/requests/2026-08-28_catalog_pdca_requeue_closed_items.md /
              2026-08-28_act_code_proposals_tcg.md 提案4
    """
    status = (row["status"] if row else "") or ""
    closed = ("done", "scope_out", "stale", "resolved", "resolver_gap")
    if not (status == "done" or (reopen_closed and status in closed)):
        return False
    closed_day = day_of(row["reviewed_ts"] if _has(row, "reviewed_ts") else "") \
        or day_of(row["updated_ts"])
    obs_day = day_of(observed_ts)
    if obs_day and closed_day and obs_day <= closed_day:
        return False                     # (a) 閉じた後の新しい観測ではない
    prev_state = (row["catalog_state"] if _has(row, "catalog_state") else "") or ""
    now_state = (catalog_state or "").strip()
    if now_state and prev_state and now_state == prev_state:
        return False                     # (b) カタログ側が閉じた時から変わっていない
    return True


def _caller_filename() -> str:
    """`upsert_improvement` を呼んだ直接の呼出元ファイル名 (純関数寄り、失敗時は '')。

    ★2026-09-04: queue の evidence が REVIEW 固定のまま seen_count だけ増える経路があり、
      台帳が「誰の観測か」を持っていないため特定できなかった (実測: queue 610 の evidence は
      8/28 の resolver 修正以降も更新されていないのに seen_count は 99→540 に増えた)。
      `source` 引数だけでは `import_missing_models` と `_queue_resolver_drop` が同じ
      `source="missing_models"` を渡すため衝突する。呼出元ファイル名を別に持つ。
      依頼書: hq/requests/2026-09-03_act_code_proposals_tcg.md 提案4
    """
    try:
        return Path(inspect.stack()[2].filename).name
    except Exception:                                          # noqa: BLE001
        return ""


def _has(row, col):
    """sqlite3.Row にその列が在るか (古い DB / 部分 SELECT を跨いでも落ちない)。"""
    try:
        return col in row.keys()
    except Exception:                                          # noqa: BLE001
        return False


def upsert_improvement(con, category, item_id, target_field, suggested_value="", *,
                       evidence="", source="", layer="A", confidence=1.0,
                       finding_type="other", identity="", ts="", reopen_closed=False,
                       observed_ts=None, catalog_state=""):
    """改善候補を upsert。既存(同 dkey)なら seen_count++ で再発を数え priority 再計算。

    done 済の dkey が再発したら status を pending に戻す (= 直したのにまた出た → 再発行対象)。

    reopen_closed=True: **今日また実際に落ちた**という新しい観測を積む時だけ渡す。
      done 以外のクローズ済 (scope_out / stale / resolved) からも pending に戻す。
      ★2026-08-26: cert139291730 は 3行に割れて全部クローズ済のまま、毎日 GAP で
        落ち続けていた。「閉じたのに直っていない」を見えるようにする。
        既定 False = 従来どおり (missing_models.csv の毎日の再 import で stale が
        復活する オシレーションは起こさない)。
      依頼書: hq/requests/2026-08-26_act_code_proposals_tcg.md 提案4 (付随)

    identity: item_id が何の商品かを Catalog が解決できる手掛かり (TCG なら
      「カード番号 | カード名 | セット名」)。item_id (m*/PSA10-* = 出品ID) 単体では
      Catalog が対象カードを特定できず backfill 不能 → 依頼が永久に再掲される
      (2026-07-15 発覚)。dedup_key には含めない (= 既存行の同一性を保ち、
      再検出時に空の既存行へ後から埋まる)。
    """
    dk = dedup_key(category, item_id, target_field, suggested_value)
    # last_writer: 「誰がこの観測を書いたか」= source 引数 + 呼出元ファイル名。source だけでは
    # 別の呼出元が同じ source 文字列 (例 "missing_models") を渡すと衝突するため両方持つ。
    writer = f"{(source or '').strip()}:{_caller_filename()}".strip(":")
    row = con.execute("SELECT queue_id, seen_count, seen_days, status, identity, updated_ts,"
                      " reviewed_ts, catalog_state"
                      " FROM improvement_queue WHERE dkey=?",
                      (dk,)).fetchone()
    if row:
        seen = (row["seen_count"] or 1) + 1
        # ★2026-08-28: 同じCSVをその日に2回監査しただけで「再発」にしない。
        #   seen_count は観測回数のまま (優先度の材料)。「複数日 消えていない」は
        #   seen_days で数える。日付が取れない時は増やさない (水増ししない側に倒す)。
        #   出典: hq/requests/2026-08-28_act_code_proposals_gshock_response.md 提案3
        days = int(row["seen_days"] or 1)
        _today, _last = day_of(ts), day_of(row["updated_ts"])
        if _today and _today != _last:
            days += 1
        # observed_ts を渡さない呼び出し = 「今その場で再検出した」ので観測日で止めない
        # (止めると close_if_core_fills で閉じた行が同じ日の再発を拾えなくなる = fail-OPEN)。
        _obs = observed_ts
        new_status = ("pending"
                      if should_reopen(row, _obs, catalog_state, reopen_closed)
                      else row["status"])
        pri = compute_priority(finding_type, seen, confidence)
        # identity は「空の既存行に埋める / 新しい値で更新」。取得できなかった時に
        # 既存の解決手掛かりを空で潰さない (fail-closed)。
        ident = (identity or "").strip() or (row["identity"] or "")
        state = (catalog_state or "").strip() or (
            (row["catalog_state"] if _has(row, "catalog_state") else "") or "")
        con.execute(
            "UPDATE improvement_queue SET seen_count=?, seen_days=?, priority=?, status=?, evidence=?,"
            " confidence=?, identity=?, catalog_state=?, last_writer=?, updated_ts=? WHERE queue_id=?",
            (seen, days, pri, new_status, evidence, confidence, ident, state, writer, ts,
             row["queue_id"]))
        return row["queue_id"]
    pri = compute_priority(finding_type, 1, confidence)
    cur = con.execute(
        "INSERT INTO improvement_queue (dkey, category, item_id, target_field, suggested_value,"
        " evidence, source, layer, confidence, finding_type, seen_count, seen_days, priority, status,"
        " identity, catalog_state, last_writer, created_ts, updated_ts)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,1,1,?, 'pending', ?, ?, ?, ?, ?)",
        (dk, category, item_id, target_field, suggested_value, evidence, source, layer,
         confidence, finding_type, pri, (identity or "").strip(),
         (catalog_state or "").strip(), writer, ts, ts))
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
        f"SELECT queue_id, category, item_id, identity, evidence FROM improvement_queue "
        f"WHERE status='pending' AND source IN ({ph})", tuple(sources)).fetchall()
    pruned = 0
    for r in rows:
        # 候補 pid は identity/evidence に書いてあるので resolver に渡す (2026-08-28)。
        hints = f"{r['identity'] or ''} {r['evidence'] or ''}".strip()
        try:
            try:
                ok = resolve_fn(r["category"], r["item_id"], hints)
            except TypeError:
                ok = resolve_fn(r["category"], r["item_id"])   # 旧2引数の resolve_fn
        except Exception:
            ok = False                       # 解決判定失敗は触らない(fail-closed=残す)
        if ok:
            set_status(con, r["queue_id"], "done", ts)
            pruned += 1
    con.commit()
    remaining = con.execute(
        "SELECT COUNT(*) FROM improvement_queue WHERE status='pending'").fetchone()[0]
    return {"pruned": pruned, "checked": len(rows), "remaining_pending": remaining}


def close_not_redetected(con, category, seen_dkeys, audited_item_ids, ts="", *,
                         sources=("auditor",), finding_types=None, audited_rows=0):
    """今回の走行で **再検出されなかった** pending を done 化する (証拠で閉じる)。

    ★2026-08-03: auditor 由来の finding は「時間が経ったから閉じる」しかなかった
      (`prune_resolved_gaps` の resolver は catalog の product_id で照合するが、auditor 行の
       item_id は メルカリ item id (`m81161788422`) なので必ず False = 永久に pending)。
      だが監査くんは毎回「その走行で検出した全件」を持っている。pending なのにそこに居ない
      = **今回のCSVでは再現しなかった** = 解決済。時間の閾値を持つ必要がない。

    復活: 再発したら `upsert_improvement` が done → pending に戻す (既存の revival がそのまま効く)。
      だから新ステータスを作らない。閉じた理由は evidence に残す。

    ★fail-closed: **今回何も検出できなかった走行では1件も閉じない**。
      CSVが空/0行/例外で終わった走行を「全部解決した」と解釈すると、未解決の指摘を全消しする
      ([[failclosed_must_skip_not_destructive]])。呼出側は audited_rows に実際に監査した行数を渡す。

    ★★ 対象は **今回の監査対象に入っていた item_id だけ**。
      監査は毎回「その日のCSV1本」しか見ないので、別の日のCSV由来の finding は永久に
      再検出されない。母集団を絞らないと **未解決の backlog を全部消す**
      (実測: tcg/auditor の pending 13件のうち12件は過去CSV由来の 必須Item Specific。
       絞らずに走らせたら13件全部 done になった)。
      「今日そのSKUを監査した。そして指摘は出なかった」= 解決、が唯一の証拠。

    Args:
        seen_dkeys: 今回 upsert した dedup_key の集合。
        audited_item_ids: 今回の走行で **実際に監査した SKU** の集合 (= 母集団)。
        audited_rows: 今回監査した CSV 行数。0 なら何もしない。
    Returns: {"closed": n, "checked": m, "skipped_reason": str}
    """
    seen = set(seen_dkeys or ())
    pop = {str(x).strip() for x in (audited_item_ids or ()) if str(x).strip()}
    if audited_rows <= 0:
        return {"closed": 0, "checked": 0, "skipped_reason": "監査行0件 → 閉じない(fail-closed)"}
    if not pop:
        return {"closed": 0, "checked": 0,
                "skipped_reason": "今回の監査対象SKUを特定できず → 閉じない(fail-closed)"}
    ph = ",".join("?" * len(sources))
    sql = ("SELECT queue_id, dkey, item_id, evidence FROM improvement_queue "
           f"WHERE status='pending' AND category=? AND source IN ({ph})")
    args = [category, *sources]
    if finding_types:
        sql += " AND finding_type IN (%s)" % ",".join("?" * len(finding_types))
        args += list(finding_types)
    rows = con.execute(sql, tuple(args)).fetchall()
    closed = 0
    for r in rows:
        if r["item_id"] not in pop:
            continue          # 今回そのSKUを見ていない = 解決の証拠が無い(残す)
        if r["dkey"] in seen:
            continue          # 今回も出た = 未解決
        note = f"auto-closed: 再検出なし ({str(ts)[:10]})"
        ev = (r["evidence"] or "").strip()
        con.execute("UPDATE improvement_queue SET status='done', evidence=?, updated_ts=? "
                    "WHERE queue_id=?",
                    ((ev + " / " + note) if ev else note, ts, r["queue_id"]))
        closed += 1
    con.commit()
    return {"closed": closed, "checked": len(rows), "skipped_reason": ""}


def close_if_core_fills(con, category, core_fills_fn, ts="", *,
                        sources=("auditor",), finding_types=("必須Item Specific",)):
    """**今のコアで作り直したら埋まる** spec 指摘を閉じる (証拠で閉じる / 再検出を待たない)。

    ★2026-08-18: `close_not_redetected` は母集団を「その日のCSV1本」に絞っている
      (別の日のCSV由来の未解決を全消ししないため。これは正しい)。その代償として
      **別の日のCSVで見つかった指摘は二度と再検出されず、21日の stale 退役まで pending に残る**。
      その間ずっと `emit_consolidated_request` が毎日カタログに同じ質問を出す。
      実害: OP02-059 / OP03-001 の `C:Set` 空を **4日連続**で catalog に聞いた
      (2026-08-17 に手で close: queue_id 550/560)。

      → 「今日そのSKUを監査したか」ではなく **「今のコードで生成し直したら埋まるか」** で閉じる。
        CSV に載っていなくても判定できるので、待ち時間がゼロになる。

    core_fills_fn: (item_id, target_field) -> True (今は埋まる) / False (まだ空) /
      None (判定不能)。**None と例外は触らない** (fail-closed = 消さずに残す)。

    status は `close_not_redetected` と同じ **'done'** にする。'resolved'/'stale' は
    `upsert_improvement` が復活させない sticky な状態なので、ここで使うと
    **同じ不具合が再発しても二度と上がってこない** (fail-OPEN)。
    Returns: {"closed": n, "checked": m}
    """
    ph = ",".join("?" * len(sources))
    sql = ("SELECT queue_id, item_id, target_field, evidence FROM improvement_queue "
           f"WHERE status='pending' AND category=? AND source IN ({ph})")
    args = [category, *sources]
    if finding_types:
        sql += " AND finding_type IN (%s)" % ",".join("?" * len(finding_types))
        args += list(finding_types)
    rows = con.execute(sql, tuple(args)).fetchall()
    closed = 0
    for r in rows:
        try:
            ok = core_fills_fn(r["item_id"], r["target_field"])
        except Exception:
            ok = None
        if ok is not True:
            continue
        note = f"auto-closed: 今のコアで再生成したら埋まった ({str(ts)[:10]})"
        ev = (r["evidence"] or "").strip()
        con.execute("UPDATE improvement_queue SET status='done', evidence=?, updated_ts=? "
                    "WHERE queue_id=?",
                    ((ev + " / " + note) if ev else note, ts, r["queue_id"]))
        closed += 1
    con.commit()
    return {"closed": closed, "checked": len(rows)}


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


# ★2026-08-16: **カタログに在るのに「未登録」と5日連続で言い続けていた**。
#   queue の item_id は `missing_models.csv` 由来の **崩れた長文字列**
#   (例: "OP12-034 psa10 ペローナ SR [OP12-034](プロモ…)") で、resolver は product_id の
#   完全一致しか見ていなかったため永久に外れる。実測: OP12-034 も CLF-001 も catalog に実在。
#   → 突合用の候補を **文字列から取り出してから**照合する。
_SETCODE_RE = _re.compile(r"\b([A-Z]{1,4}\d{1,2}[a-z]?-\d{1,4})\b", _re.I)
# ★2026-08-28: 変種つき product_id (`ST17-004_p1` `OP12-079_AN03`)。`_SETCODE_RE` は
#   末尾 `\b` が `_` の前で成立せず **1件も拾えなかった**。queue の evidence/identity には
#   候補 pid がそのまま書いてあるのに、resolver がそれを見ていなかった
#   (実測: `('one_piece_tcg','cert155040105')` → False で永久に auto-close されない)。
_PID_VARIANT_RE = _re.compile(r"\b([A-Z]{1,4}\d{1,2}[a-z]?-\d{1,4}(?:_[A-Za-z0-9]+)+)", _re.I)
_PRINTNO_RE = _re.compile(r"\b(\d{2,3}/[A-Z0-9\-]{2,6})\b", _re.I)
_SETHINT_RE = _re.compile(r"\b([A-Z]{2,4}\d?)\b")


def candidate_ids(item_id):
    """queue の item_id → catalog 突合に使う候補 (純関数)。

    戻り: {"ids": [product_id 候補], "numbers": [印刷番号], "hints": [セット記号]}
    """
    s = str(item_id or "").strip()
    ids = [s] if s else []
    # 変種つき pid を先に (`ST17-004_p1` は `ST17-004` より具体的)
    ids += [m.group(1) for m in _PID_VARIANT_RE.finditer(s)]
    ids += [m.group(1).upper() for m in _SETCODE_RE.finditer(s)]
    nums = [m.group(1).upper() for m in _PRINTNO_RE.finditer(s)]
    hints = [h.upper() for h in _SETHINT_RE.findall(s.upper())
             if not any(h in i for i in ids[1:])]
    seen, out = set(), []
    for v in ids:
        if v and v not in seen:
            seen.add(v); out.append(v)
    return {"ids": out, "numbers": list(dict.fromkeys(nums)),
            "hints": list(dict.fromkeys(hints))[:6]}


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

    def _resolve(category, item_id, hints=""):
        """hints: identity / evidence 等、**候補 pid が書かれている文字列** (2026-08-28)。

        cert 番号を鍵にした行は item_id からは何も引けないが、evidence に
        `候補=ST17-004_p1` と書いてある。それを見れば catalog に在ることが分かる。
        """
        key = (category, item_id, hints)
        if key in cache:
            return cache[key]
        c = candidate_ids(f"{item_id} {hints}".strip() if hints else item_id)
        hit = False
        for cid in c["ids"]:
            if con.execute("SELECT 1 FROM products WHERE (product_id=? OR alias_of=?) LIMIT 1",
                           (cid, cid)).fetchone():
                hit = True
                break
        # 印刷番号 (001/032) はセット記号と組でだけ照合する。番号だけで当てると
        # 別セットの同番号を「解決済」にしてしまう (fail-closed)。
        if not hit:
            for num in c["numbers"]:
                for hint in c["hints"]:
                    if con.execute(
                            "SELECT 1 FROM products WHERE product_id LIKE ? "
                            "AND json_extract(specs,'$.card_number_text')=? LIMIT 1",
                            (hint + "-%", num)).fetchone():
                        hit = True
                        break
                if hit:
                    break
        cache[key] = hit
        return hit

    return _resolve


# item_id に書かれた cert 番号 (`cert155040105` / `PSA10-151301749` の両方)。
_CERT_ANY_RE = _re.compile(r"(?:cert|PSA10-)(\d{6,})", _re.I)


def cert_number(item_id) -> str:
    """item_id から PSA cert 番号を取り出す。無ければ '' (純関数)。"""
    m = _CERT_ANY_RE.search(str(item_id or ""))
    return m.group(1) if m else ""


def row_solved_in_catalog(row, *, resolve_fn=None, images_fn=None, cert_fn=None):
    """発行の直前に「その行はもう catalog で解決している」かを判定する (純関数・I/Oは引数)。

    ★2026-08-28: 走行の頭で作った判定のまま送っていたので、その日のうちに入った行や画像を
      「無い」と聞き直していた (OP12-079_AN03 は 18:49 投入済なのに 19:12 に起票)。
      catalog を見て分かるものだけを見る:
        - `catalog_add` … 候補 pid か **cert を引き直して** 行が在るか
        - `images`      … その pid に画像が入ったか
      program_fix 等 catalog では判定できない行は触らない (False=送る / fail-closed)。
      依頼書: hq/requests/2026-08-28_catalog_pdca_requeue_closed_items.md (3)
    """
    if (row.get("finding_type") or "").strip() != "catalog_gap":
        return False
    cat = (row.get("category") or "").strip()
    item = str(row.get("item_id") or "")
    hints = f"{row.get('identity') or ''} {row.get('evidence') or ''}".strip()
    field = (row.get("target_field") or "").strip()
    if field in ("images", "image"):
        return bool(images_fn) and bool(images_fn(cat, f"{item} {hints}".strip()))
    if field != "catalog_add":
        return False
    if resolve_fn and resolve_fn(cat, item, hints):
        return True
    cert = cert_number(item)
    return bool(cert) and bool(cert_fn) and bool(cert_fn(cert))


def make_pre_emit_verifier(catalog_db, classify_fn=None, certs_dir=None):
    """`emit_consolidated_request(verify_fn=...)` に渡す「catalog 読み直し」判定を作る。

    cert 鍵の行は catalog を product_id で引いても永久に当たらないので、PSA cache から
    **preflight で引き直す** (実測: cert155040105 → RESOLVED ST17-004_p1)。
    preflight が使えない環境では cert 判定だけ落とす (他の判定は動く)。
    """
    con = sqlite3.connect(catalog_db)
    con.row_factory = sqlite3.Row
    resolve_fn = make_catalog_resolver(catalog_db)

    def _images(category, text):
        for cid in candidate_ids(text)["ids"]:
            r = con.execute("SELECT images FROM products WHERE (product_id=? OR alias_of=?) LIMIT 1",
                            (cid, cid)).fetchone()
            if r and str(r["images"] or "").strip() not in ("", "[]", "null"):
                return True
        return False

    _classify, _dir = classify_fn, certs_dir
    if _classify is None:
        try:
            import psa_preflight as _pf                        # 同 dir (iMakHQ/tools)
            _classify, _dir = _pf.classify, (_dir or _pf.PSA_CERTS_DIR)
        except Exception:                                      # noqa: BLE001
            _classify = None

    def _cert(cert):
        if _classify is None or not _dir:
            return False
        f = Path(_dir) / f"{cert}.json"
        if not f.is_file():
            return False
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
            return (_classify(str(cert), meta, con) or {}).get("status") == "RESOLVED"
        except Exception:                                      # noqa: BLE001
            return False

    return lambda row: row_solved_in_catalog(
        row, resolve_fn=resolve_fn, images_fn=_images, cert_fn=_cert)


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


_OPAQUE_ID_RE = re.compile(r"^(PSA10-\d+|m\d{8,})$", re.IGNORECASE)


def is_opaque_listing_id(item_id) -> bool:
    """item_id が「出品IDだけでは商品を特定できない」形式か (純関数, test可)。

    PSA10-<cert> / m<メルカリID> は出品IDであって商品IDではない。identity が空のまま
    Catalog へ送ると「どのカードか分からず原理的に着手不能」= 無駄往復になる
    (2026-07-27 Advisor 指摘 §3)。一方 gshock の item_id は型番そのもの (= 特定可能)、
    program_fix の item_id は症状シグネチャで Catalog へは出ないので、ここで True に
    しない = 既存の依頼経路を塞がない (silent drop 防止)。
    """
    return bool(_OPAQUE_ID_RE.match((item_id or "").strip()))


def backfill_identities(con, resolve_fn, ts="", status="pending"):
    """identity 空の行を resolve_fn で後埋め (既存行の救済)。

    identity 解決は upsert 時に渡す設計だが、解決経路を後から実装した場合 (2026-07-31)
    **既に積まれている行は空のまま**で、再検出されるまで永久に (不明) で出続ける。
    毎監査ここを通して既存行も救う。

    Args:
        resolve_fn: item_id -> identity 文字列 (解決不能は "")。例外は握り潰す (監査を止めない)。
    Returns: {"filled": n, "checked": m}
    """
    rows = con.execute(
        "SELECT queue_id, item_id FROM improvement_queue"
        " WHERE status=? AND TRIM(COALESCE(identity,''))=''", (status,)).fetchall()
    filled = 0
    for r in rows:
        try:
            ident = (resolve_fn(r["item_id"]) or "").strip()
        except Exception:
            ident = ""
        if ident:
            con.execute("UPDATE improvement_queue SET identity=?, updated_ts=? WHERE queue_id=?",
                        (ident[:120], ts, r["queue_id"]))
            filled += 1
    con.commit()
    return {"filled": filled, "checked": len(rows)}


def parse_identity_fields(identity):
    """identity "CARDNUMBER | カード名 | セット名 ..." → (番号, 名前) (純関数, test可)。

    番号/名前が取れない形は ("", "") = 判定材料なし → 呼出側は触らない (fail-closed)。
    """
    parts = [p.strip() for p in str(identity or "").split("|")]
    num = parts[0] if parts and parts[0] else ""
    name = parts[1] if len(parts) > 1 else ""
    return num, name


def prune_non_applicable_specs(con, still_required_fn, ts="", status="pending"):
    """「今の監査ルールではもう必須でない」spec 指摘を queue から落とす (status='resolved')。

    2026-07-29/30 に Catalog 実機判定で「公式に存在しない」と確定した種別
    (Gundam RESOURCE / DBSCG ENERGY MARKER / Pokemon hi-class 等) は check_csv 側で
    必須から外したが、**それ以前に積まれた queue 行はそのまま残る**。放置すると
    「空欄維持で確定した項目」を Catalog に依頼してしまう (2026-08-01 実在: E-60 Energy Marker
    の C:Rarity が発行対象に載っていた)。

    Args:
        still_required_fn: (番号, 名前, target_field) -> bool。今も必須なら True。
            例外/判定不能は True 側に倒す = 消さない (fail-closed)。
    Returns: {"pruned": n, "checked": m}
    """
    rows = con.execute(
        "SELECT queue_id, item_id, identity, target_field FROM improvement_queue"
        " WHERE status=? AND finding_type='必須Item Specific'", (status,)).fetchall()
    pruned = 0
    for r in rows:
        num, name = parse_identity_fields(r["identity"])
        if not num and not name:
            continue                                   # 判定材料なし → 触らない
        try:
            # ★2026-08-09: item_id も渡す。identity 先頭は **印刷番号** (`746/742`) で、
            #   除外リストの canonical prefix (`mc-`) と噛み合わない。呼び手側で
            #   cert → canonical product_id を引けるようにするため。
            #   旧シグネチャ (3引数) の実装も壊さない。
            try:
                still = still_required_fn(num, name, r["target_field"], r["item_id"])
            except TypeError:
                still = still_required_fn(num, name, r["target_field"])
        except Exception:
            still = True
        if not still:
            set_status(con, r["queue_id"], "resolved", ts)
            pruned += 1
    con.commit()
    return {"pruned": pruned, "checked": len(rows)}


def partition_by_identity(items):
    """Catalog へ送れる行 / 送っても着手不能な行 に分ける (純関数, test可)。

    送らない = identity 空 **かつ** item_id が出品ID形式 (is_opaque_listing_id)。
    それ以外 (gshock 型番等) は従来どおり送る。
    Returns: (sendable, held)
    """
    sendable, held = [], []
    for r in items:
        ident = (r.get("identity") or "").strip()
        if not ident and is_opaque_listing_id(r.get("item_id")):
            held.append(r)
        else:
            sendable.append(r)
    return sendable, held


def write_unresolved_note(held, out_path, today, category=""):
    """identity 未解決で送らなかった分を **毎回全件再掲** する残件リストを書く。

    黙って落とすと no_partial_shipping_with_todo / 状態同期原則2 (silent drop 禁止) に触れる。
    毎回上書き = 「今この瞬間の未解決全件」が常に 1 ファイルに載る (増殖しない)。
    held が空なら「0件」と書く (ファイルを消さない = 見に行った時に必ず状態が読める)。
    """
    lines = [
        f"# HQ 保留箱: identity 未解決 (Catalog へ送っていない) — {category or 'all'}",
        f"- 更新: {today} / 発行者: HQ pdca_store (毎監査 上書き = 常に全件)",
        "- ここに載る行は **出品ID しか無く、どの商品か HQ 側で解決できなかった**分。",
        "  Catalog に送っても着手不能なので送らない (fail-closed)。解決したら自動で依頼に載る。",
        "",
        f"## 未解決 {len(held)} 件",
    ]
    if held:
        lines += ["| item | category | field | 根拠 | seen |", "|---|---|---|---|--:|"]
        for r in held:
            lines.append(f"| {r['item_id']} | {r.get('category','')} | {r['target_field']} | "
                         f"{(r.get('evidence') or '')[:60]} | {r.get('seen_count','')} |")
    else:
        lines.append("(なし = 未解決ゼロ)")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    return len(held)


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


def dedupe_queue_items(items):
    """同じカードを指す行を1行に畳む (純関数)。残すのは priority が高い方。

    ★2026-08-28 Catalog 指摘: 同じ依頼の中に S4a-323 が **pri20 と pri5 の2行**在った。
      dkey が (category, item_id, field) で、item_id が producer ごとに
      `cert55281762` / `cert55281762 <brand> [SUBJ] #323 (…)` と別物になるため。
      `normalize_item_key` で cert を取り出せば同じ鍵になる。
      依頼書: hq/requests/2026-08-28_catalog_pdca_requeue_closed_items.md (2)
    戻り: (残す行, 畳んだ行数)
    """
    best, order = {}, []
    for r in items or []:
        k = ((r.get("category") or "").strip(),
             normalize_item_key(r.get("item_id")),
             (r.get("target_field") or "").strip())
        cur = best.get(k)
        if cur is None:
            best[k] = r
            order.append(k)
        elif (r.get("priority") or 0) > (cur.get("priority") or 0):
            best[k] = r
    return [best[k] for k in order], max(0, len(items or []) - len(order))


def emit_consolidated_request(con, category, out_dir, today, held_out=None, verify_fn=None,
                              stats=None):
    """pending 改善候補を **1本の dedup済 catalog 依頼 .md** に集約発行 (Phase2/3・自動)。

    層A(客観ギャップ=即対応)と層B(競合intel候補=要裏取り)を分節で出力。
    毎回新規 .md を量産せず日付単位1ファイルに上書き(滞留スパム停止)。
    catalog 反映は Catalog が裏取りして実施 (SSOT/fail-closed)。Returns: 発行件数。
    発行は **当該 project(category)に属す項目のみ**(他カテゴリ混入防止=Catalog 誤ルーティング根治)。
    """
    pend_all = [r for r in list_queue(con, status="pending", limit=10000)
                if r.get("source") != "md_import" and category_in_project(r.get("category"), category)]
    # ★2026-08-28: **発行の直前に catalog を読み直す**。画像や行はその日のうちに入ることが
    #   あり (OP12-079_AN03 は 18:49 投入済なのに 19:12 に起票された)、
    #   走行の頭で作った判定のまま送ると「もう在るもの」を聞くことになる。
    #   依頼書: hq/requests/2026-08-28_catalog_pdca_requeue_closed_items.md (3)
    _closed = 0
    if verify_fn is not None:
        _fresh = []
        for r in pend_all:
            try:
                solved = verify_fn(r)
            except Exception:                                  # noqa: BLE001
                solved = False               # 判定できなければ送る (fail-closed=握り潰さない)
            if solved:
                set_status(con, r["queue_id"], "done", today)
                _closed += 1
            else:
                _fresh.append(r)
        pend_all = _fresh
    # 同じカードが別 item_id で2行に割れている分を畳む (pri の高い方を残す)
    pend_all, _folded = dedupe_queue_items(pend_all)
    if stats is not None:
        stats["verified_closed"] = _closed
        stats["folded"] = _folded
    # identity 未解決 (出品IDのみ) は送らない = Catalog が着手不能な依頼を積まない。
    # 落とした分は held_out で呼出側へ返し、残件リストに毎回再掲する (silent drop 禁止)。
    pend, held = partition_by_identity(pend_all)
    if held_out is not None:
        held_out.extend(held)
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
                # ★2026-08-28: missing_models.csv は **消えない台帳**で毎回全行読み直す。
                #   行の detected_at を「いつ見たか」として渡し、閉じた後の新しい観測でない
                #   限り pending に戻さない (3日連続で同じ依頼を送っていた原因の1つ)。
                upsert_improvement(con, category, model, "catalog_add", "",
                                   evidence="missing_models (catalog未登録→入稿せず)",
                                   source="missing_models", layer="A",
                                   finding_type="catalog_gap",
                                   identity=ident, ts=ts,
                                   observed_ts=(row.get("detected_at") or "").strip())
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
