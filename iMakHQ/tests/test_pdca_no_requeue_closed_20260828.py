# -*- coding: utf-8 -*-
"""「不要」で閉じた pdca 行を翌日また起票しない (2026-08-28)。

何が起きていたか: tcg キューの層A が 8/26・8/27・8/28 と3日連続で同じ中身で、全件
catalog に行が在り、毎回「不要」で返させていた。原因は3つ:
  (a) `missing_models.csv` は消えない台帳なので毎回全行読み直され、閉じた行が復活する
  (b) 同じカードが `cert155040105` / `cert155040105 <brand> …` と別 item_id で2行に割れ、
      同じ依頼の中に pri20 と pri5 の重複行として並ぶ
  (c) 走行の頭で作った判定のまま送るので、その日のうちに入った行/画像を聞き直す
      (OP12-079_AN03 は 18:49 投入済なのに 19:12 に起票)
  (d) resolver が cert 鍵の行を product_id として引くため永久に auto-close されない

出典: hq/requests/2026-08-28_catalog_pdca_requeue_closed_items_response.md
      hq/requests/2026-08-28_act_code_proposals_tcg_response.md 提案4
"""
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import pdca_store as ps       # noqa: E402


def _up(con, ts, item="cert155040105", **kw):
    return ps.upsert_improvement(con, "one_piece_tcg", item, "catalog_add",
                                 finding_type="catalog_gap", ts=ts, **kw)


def _row(con, qid=None):
    q = "SELECT * FROM improvement_queue"
    return con.execute(q + (" WHERE queue_id=?" if qid else ""),
                       (qid,) if qid else ()).fetchone()


# ------------------------------------------------- (a) 閉じた行を再起票しない

def test_closed_row_stays_closed_when_reobserved_same_day():
    """閉じた日と同じ日の観測では戻さない (台帳の読み直しで復活しない)。"""
    con = ps.connect(":memory:")
    qid = _up(con, "2026-08-27")
    ps.set_status(con, qid, "done", "2026-08-28")
    _up(con, "2026-08-28", observed_ts="2026-08-27", reopen_closed=True)
    assert _row(con, qid)["status"] == "done"


def test_closed_row_stays_closed_when_catalog_unchanged():
    """カタログ側が閉じた時と同じなら、日をまたいでも送り直さない。

    同じ状態のまま聞き直しても、返ってくる答えは前回と同じ「不要」。
    """
    con = ps.connect(":memory:")
    qid = _up(con, "2026-08-27", catalog_state="GAP|recovery不一致 (set_code=ST)")
    ps.set_status(con, qid, "done", "2026-08-27")
    _up(con, "2026-08-28", catalog_state="GAP|recovery不一致 (set_code=ST)",
        reopen_closed=True)
    assert _row(con, qid)["status"] == "done"


def test_reopens_when_catalog_state_changed():
    """カタログ側の見え方が変わった時だけ pending に戻す (握り潰さない)。"""
    con = ps.connect(":memory:")
    qid = _up(con, "2026-08-27", catalog_state="GAP|recovery不一致 (set_code=ST)")
    ps.set_status(con, qid, "done", "2026-08-27")
    _up(con, "2026-08-28", catalog_state="GAP|別の理由", reopen_closed=True)
    assert _row(con, qid)["status"] == "pending"


def test_reopens_on_new_day_when_state_unknown():
    """catalog_state を渡さない呼び出しは従来どおり (新しい観測なら戻す)。"""
    con = ps.connect(":memory:")
    qid = _up(con, "2026-08-27")
    ps.set_status(con, qid, "done", "2026-08-27")
    _up(con, "2026-08-28", reopen_closed=True)
    assert _row(con, qid)["status"] == "pending"


def test_live_redetection_still_reopens_same_day():
    """今その場で再検出した分は同じ日でも戻す (閉じた行の再発をスルーしない = fail-OPEN 防止)。

    観測日で止めるのは、台帳のように **いつ見たか** が行に書いてある呼び出しだけ。
    """
    con = ps.connect(":memory:")
    qid = _up(con, "2026-08-28")
    ps.set_status(con, qid, "done", "2026-08-28")
    _up(con, "2026-08-28")                      # observed_ts を渡さない = 今その場の再検出
    assert _row(con, qid)["status"] == "pending"


def test_should_reopen_ignores_non_closed_rows():
    con = ps.connect(":memory:")
    qid = _up(con, "2026-08-28")
    assert ps.should_reopen(_row(con, qid), "2026-08-29", "", True) is False


def test_missing_models_ledger_reread_does_not_reopen(tmp_path):
    """消えない台帳を毎回読み直しても、古い行は復活しない (3日連続の主因)。"""
    con = ps.connect(":memory:")
    csv_path = tmp_path / "missing_models.csv"
    csv_path.write_text(
        "category,model,detected_at\n"
        "one_piece_tcg,cert155040105 ONE PIECE [BOA HANCOCK] #004 (auto=該当なし),2026-08-26\n",
        encoding="utf-8")
    ps.import_missing_models(con, str(csv_path), ts="2026-08-26")
    qid = _row(con)["queue_id"]
    ps.set_status(con, qid, "done", "2026-08-27")
    ps.import_missing_models(con, str(csv_path), ts="2026-08-28")     # 翌日も同じ台帳
    assert _row(con, qid)["status"] == "done", "台帳の読み直しは新しい観測ではない"


# ------------------------------------------------- (b) 同一キュー内の重複を潰す

def test_dedupe_queue_items_folds_same_card_and_keeps_higher_priority():
    items = [
        {"category": "pokemon_tcg", "item_id": "cert55281762", "target_field": "catalog_add",
         "priority": 5.0},
        {"category": "pokemon_tcg", "item_id": "cert55281762 POKEMON [FA/DITTO V] #323 (auto)",
         "target_field": "catalog_add", "priority": 20.0},
    ]
    kept, folded = ps.dedupe_queue_items(items)
    assert folded == 1
    assert len(kept) == 1 and kept[0]["priority"] == 20.0


def test_dedupe_queue_items_keeps_different_cards():
    items = [{"category": "tcg", "item_id": "cert1000001", "target_field": "catalog_add",
              "priority": 5.0},
             {"category": "tcg", "item_id": "cert1000002", "target_field": "catalog_add",
              "priority": 5.0}]
    kept, folded = ps.dedupe_queue_items(items)
    assert (len(kept), folded) == (2, 0)


# ------------------------------------------------- (d) resolver が候補 pid を見る

def _catalog(tmp_path, rows):
    db = tmp_path / "products.sqlite"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE products (product_id TEXT, alias_of TEXT, category TEXT,"
                " images TEXT, specs TEXT)")
    con.executemany("INSERT INTO products (product_id, alias_of, category, images, specs)"
                    " VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return str(db)


def test_candidate_ids_picks_variant_product_id():
    """`ST17-004_p1` は末尾 `_p1` があり、従来の正規表現では1件も拾えなかった。"""
    ids = ps.candidate_ids("cert155040105 候補=ST17-004_p1")["ids"]
    assert "ST17-004_p1" in ids


def test_resolver_uses_hints_from_evidence(tmp_path):
    db = _catalog(tmp_path, [("ST17-004_p1", None, "one_piece_tcg", '["u"]', "{}")])
    resolve = ps.make_catalog_resolver(db)
    assert resolve("one_piece_tcg", "cert155040105") is False, "cert 鍵だけでは引けない"
    assert resolve("one_piece_tcg", "cert155040105", "候補=ST17-004_p1") is True


# ------------------------------------------------- (c) 発行の直前に catalog を読み直す

def test_row_solved_ignores_program_fix():
    row = {"finding_type": "program_fix", "target_field": "program_fix",
           "category": "tcg", "item_id": "program:PSA 画像が1枚も無い"}
    assert ps.row_solved_in_catalog(row, resolve_fn=lambda *a: True) is False


def test_row_solved_by_cert_lookup():
    """cert 鍵の行は catalog を引き直して解決を見る (product_id では永久に当たらない)。"""
    row = {"finding_type": "catalog_gap", "target_field": "catalog_add",
           "category": "one_piece_tcg", "item_id": "cert155040105", "identity": "", "evidence": ""}
    assert ps.row_solved_in_catalog(row, resolve_fn=lambda *a: False,
                                    cert_fn=lambda c: c == "155040105") is True


def test_row_solved_images_needs_image_present():
    row = {"finding_type": "catalog_gap", "target_field": "images",
           "category": "one_piece_tcg", "item_id": "PSA10-151301749",
           "identity": "OP12-079_AN03 | (画像なし) | one_piece_tcg", "evidence": ""}
    assert ps.row_solved_in_catalog(row, images_fn=lambda c, t: "OP12-079_AN03" in t) is True
    assert ps.row_solved_in_catalog(row, images_fn=lambda c, t: False) is False


def test_cert_number_reads_both_spellings():
    assert ps.cert_number("cert155040105") == "155040105"
    assert ps.cert_number("PSA10-151301749") == "151301749"
    assert ps.cert_number("GA-010GGB-1A9") == ""


def test_pre_emit_verifier_closes_row_whose_image_arrived(tmp_path):
    """当日入った画像を「無い」と聞き直さない (OP12-079_AN03)。"""
    db = _catalog(tmp_path, [("OP12-079_AN03", None, "one_piece_tcg", '["https://x/1.jpg"]', "{}")])
    verify = ps.make_pre_emit_verifier(db, classify_fn=lambda *a: {}, certs_dir=str(tmp_path))
    assert verify({"finding_type": "catalog_gap", "target_field": "images",
                   "category": "one_piece_tcg", "item_id": "PSA10-151301749",
                   "identity": "OP12-079_AN03 | (画像なし) | one_piece_tcg",
                   "evidence": ""}) is True


def test_pre_emit_verifier_keeps_row_without_image(tmp_path):
    db = _catalog(tmp_path, [("OP12-079_AN03", None, "one_piece_tcg", "", "{}")])
    verify = ps.make_pre_emit_verifier(db, classify_fn=lambda *a: {}, certs_dir=str(tmp_path))
    assert verify({"finding_type": "catalog_gap", "target_field": "images",
                   "category": "one_piece_tcg", "item_id": "PSA10-151301749",
                   "identity": "OP12-079_AN03 | (画像なし) | one_piece_tcg",
                   "evidence": ""}) is False


def test_emit_closes_verified_rows_and_folds_duplicates(tmp_path):
    con = ps.connect(":memory:")
    _up(con, "2026-08-28", identity="BOA HANCOCK #004")                       # 解決済
    _up(con, "2026-08-28", item="cert156843873", identity="DON!! #")          # 未解決
    _up(con, "2026-08-28", item="cert156843873 ONE PIECE [DON!! CARD] #",
        identity="DON!! #")                                                   # 上と同じカード
    stats = {}
    n = ps.emit_consolidated_request(
        con, "tcg", str(tmp_path), "2026-08-28",
        verify_fn=lambda r: ps.cert_number(r["item_id"]) == "155040105", stats=stats)
    assert stats == {"verified_closed": 1, "folded": 0}, "解決済1件を閉じる"
    assert n == 1, "残るのは DON!! の1件 (dkey で既に1行に畳まれている)"
    body = (tmp_path / "2026-08-28_pdca_catalog_queue_tcg.md").read_text(encoding="utf-8")
    assert "cert155040105" not in body, "当日 catalog に在ると分かった行は送らない"


def test_emit_without_verify_fn_sends_everything(tmp_path):
    """読み直しが使えない環境でも、送るべき行を握り潰さない (fail-closed)。"""
    con = ps.connect(":memory:")
    _up(con, "2026-08-28", identity="BOA HANCOCK #004")
    assert ps.emit_consolidated_request(con, "tcg", str(tmp_path), "2026-08-28") == 1
