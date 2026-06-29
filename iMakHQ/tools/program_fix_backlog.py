#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""program修正 backlog — 生成プログラムのバグ指摘を catalog 依頼と対称の閉ループで回す。

背景 (2026-06-29): CSV監査くんの2大役割は「catalog依頼」と「program修正アラート」。
前者は requests/ → Catalog Claude → _processed で閉じる閉ループがあるが、後者は
review_logs/ に .md を書くだけ(報告のみ)で backlog も status も無く、実装する出口が
無いため毎監査で再発し続けていた(過去 6回分スルー)。本ツールで program 指摘も
pdca improvement_queue(finding_type='program_fix')に乗せ、surface→実装→mark_done で
閉じる。再発は upsert_improvement の自動 reopen(done→pending)で検知される。

closure の定義: HQ が generator を直す → 回帰テストを足す(バグ=テスト追加の不文律) →
`done <item_id>` で閉じる。直っていなければ次監査で同症状が再 upsert され done→pending に
自動復活する(= 客観的な「直った」証跡はテスト緑 + 再発ゼロ)。

usage:
  python program_fix_backlog.py                # 未対応(pending)一覧 (既定)
  python program_fix_backlog.py done <item_id> [メモ]   # 実装完了 → done
  python program_fix_backlog.py migrate        # 過去の review_logs/*audit_program_fix*.md を queue へ取込
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdca_store as pdca

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW_DIR = os.path.join(os.path.dirname(_HERE), "review_logs")
FINDING_TYPE = "program_fix"


def program_signature(msg):
    """program バグ症状を安定クラスに正規化(別SKUでの再発を1件に集約=クラスの慢性度を数える)。

    csv_auditor._program_signature と同一実装(SSOT。片方変えたら両方)。テスト対象。
    """
    m = str(msg)
    if "禁止ワード" in m:
        return "banned_word_in_title"
    if "'#'" in m:
        return "title_missing_card_number"
    if "spec不一致" in m:
        return "title_spec_mismatch"
    if "タイトル形式逸脱" in m:
        return "title_format_deviation"
    if "必須Item Specific" in m or "推奨Item Specific" in m:
        return "missing_item_specific"
    return "program:" + m[:40]


def load_open(con, limit=200):
    rows = con.execute(
        "SELECT queue_id, category, item_id, seen_count, evidence, created_ts, updated_ts "
        "FROM improvement_queue WHERE finding_type=? AND status='pending' "
        "ORDER BY seen_count DESC, updated_ts DESC LIMIT ?", (FINDING_TYPE, limit)).fetchall()
    return [dict(r) for r in rows]


def _cmd_list(con):
    rows = load_open(con)
    if not rows:
        print("✅ 未対応 program修正 backlog: 0件")
        return
    print(f"🛠️ 未対応 program修正 backlog: {len(rows)}件 (実装=HQ / `done <item_id>` で閉じる)")
    print(f"{'seen':>4}  {'category':<14} {'item_id(症状クラス)':<28} 最新エビデンス")
    for r in rows:
        print(f"{r['seen_count']:>4}  {r['category']:<14} {str(r['item_id']):<28} "
              f"{(r['evidence'] or '')[:50]}")


def _cmd_done(con, item_id, note=""):
    ts = pdca._today() if hasattr(pdca, "_today") else ""
    rows = con.execute(
        "SELECT queue_id FROM improvement_queue WHERE finding_type=? AND item_id=? AND status='pending'",
        (FINDING_TYPE, item_id)).fetchall()
    if not rows:
        print(f"⚠️ pending な program_fix '{item_id}' が見つからない (一覧で item_id を確認)")
        return
    for r in rows:
        pdca.set_status(con, r["queue_id"], "done", ts=ts)
        if note:
            con.execute("UPDATE improvement_queue SET evidence=? WHERE queue_id=?",
                        (f"[done] {note}", r["queue_id"]))
    con.commit()
    print(f"✅ done: {item_id} ({len(rows)}件) {('— ' + note) if note else ''}")
    print("   ※ 直っていなければ次監査で同症状が再upsertされ done→pending に自動復活する")


def _cmd_migrate(con):
    """過去の review_logs/*audit_program_fix*.md を解析して queue へ取込(取りこぼし回収)。"""
    files = sorted(glob.glob(os.path.join(REVIEW_DIR, "*audit_program_fix*.md")))
    if not files:
        print("過去 program_fix レポートなし")
        return
    row_re = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$")
    n = 0
    for path in files:
        base = os.path.basename(path)
        m = re.search(r"audit_program_fix_(\w+)\.md", base)
        project = m.group(1) if m else "generic"
        ts = base[:10]
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                mm = row_re.match(line)
                if not mm:
                    continue
                sku, sym = mm.group(1), mm.group(2)
                if sku in ("SKU/識別", "---") or sym in ("症状", "---"):
                    continue
                sig = program_signature(sym)
                pdca.upsert_improvement(con, project, sig, "program_fix", "",
                                        evidence=f"{sku}: {sym[:80]}", source="migrate",
                                        layer="code", finding_type=FINDING_TYPE, ts=ts)
                n += 1
    con.commit()
    print(f"✅ migrate 完了: 過去 {len(files)}ファイル / {n}行 を queue へ取込(症状クラスで dedup 集約)")
    print()
    _cmd_list(con)


def main(argv):
    con = pdca.connect()
    if not argv:
        _cmd_list(con)
    elif argv[0] == "done" and len(argv) >= 2:
        _cmd_done(con, argv[1], " ".join(argv[2:]))
    elif argv[0] == "migrate":
        _cmd_migrate(con)
    else:
        print(__doc__)
    con.close()


if __name__ == "__main__":
    main(sys.argv[1:])
