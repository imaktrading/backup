# -*- coding: utf-8 -*-
"""audit_false_catalog_misses.py — 過去の auto_catalog_add 依頼書から
「auto候補<PID>=該当なし 要調査」として catalog に自動投入された cert のうち、
**実は catalog に PID が存在していた** ものを洗い出す (調査専用、修正しない)。

背景 (2026-08-03 依頼 `2026-08-03_psa_to_csv_false_catalog_miss_response.md` Q2):
  post_psa_review::_route_none_to_catalog が NONE/NG cert を missing_models.csv
  経由で auto_catalog_add に流している。人が NONE と判定した理由が adapter の
  誤 variant 選択 (例: OP01-024_PRB01 base を返すが実は ALTERNATE ART の
  OP01-024_PRB01_p が正解) の場合、この経路は「PID は catalog に存在するのに
  該当なし依頼が飛ぶ」= **自動化された無駄依頼の再生産**になる。

出力:
  - 対象 (原本 md ファイル) 走査件数 / auto候補行 総数 (無 除く)
  - False-miss 数 = 該当 PID が products.sqlite に存在する行数
  - 割合
  - 同じ cert / 同じ PID が何回別日で起票されたか (上位)
  - JSON: 全 false-miss 詳細 (--json 指定時)

修正はしない (=依頼書 Q2 指示)。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_REQUESTS_DIR = Path("C:/dev/iMak_data/catalog/requests")
DEFAULT_DB = Path("C:/dev/iMak_data/catalog/products.sqlite")

# 原本判定: `YYYY-MM-DD_auto_catalog_add_<category>.md`
#   末尾 category の後ろに追加 suffix (_processed / _response / _hq_resolved / _draft
#   / _question 等) が無いもの。処理後 rename されたコピーを重複カウントしないため。
#   category は `_` を含みうる (one_piece_tcg 等) ので regex だけでは
#   `one_piece_tcg_processed` を弾けない → 明示 suffix ブラックリストで判定する。
_FNAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_auto_catalog_add_(?P<cat>[a-z_]+)\.md$"
)
_COPY_SUFFIXES = (
    "_processed", "_response", "_hq_resolved",
    "_draft", "_question", "_note", "_reply", "_done",
)


def FNAME_ORIG(fname: str):
    """原本 md なら re.Match 相当 (date/cat groups)、コピーなら None."""
    m = _FNAME_RE.match(fname)
    if not m:
        return None
    cat = m.group("cat")
    for suf in _COPY_SUFFIXES:
        if cat.endswith(suf):
            return None
    return m

# 行フォーマット (post_psa_review.py:1020):
#   cert<CERT> <BRAND> [<SUBJECT>] #<CARDNO> (auto候補<PID>=該当なし 要調査)
# `auto候補「PID=` の「 は過去ログの表記揺れ、両方許容。
LINE_RE = re.compile(
    r"cert(?P<cert>\d+)\s+(?P<brand>.+?)\s+\[(?P<subject>.*?)\]\s+#(?P<cardno>[^\s()]+)"
    r"\s+\(auto候補[「]?(?P<pid>[^=）)]+?)=該当なし"
)


def _iter_original_files(requests_dir: Path):
    """原本 md のみ列挙 (_processed / _response 等の suffix を持つコピーは除外)."""
    for p in sorted(requests_dir.glob("*_auto_catalog_add_*.md")):
        if FNAME_ORIG(p.name):
            yield p


def _parse_category_from_filename(fname: str) -> str | None:
    m = FNAME_ORIG(fname)
    return m.group("cat") if m else None


def scan_requests(requests_dir: Path) -> list[dict]:
    """原本の全 auto候補 行を list[dict] で返す (無 も含める、下流で除外).

    dict = {file, date, category, cert, brand, subject, cardno, pid}
    """
    out: list[dict] = []
    for p in _iter_original_files(requests_dir):
        m_name = FNAME_ORIG(p.name)
        date = m_name.group("date")
        category = m_name.group("cat")
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in LINE_RE.finditer(text):
            out.append({
                "file": p.name,
                "date": date,
                "category": category,
                "cert": m.group("cert"),
                "brand": m.group("brand").strip(),
                "subject": m.group("subject").strip(),
                "cardno": m.group("cardno").strip(),
                "pid": m.group("pid").strip(),
            })
    return out


def check_pid_exists(conn: sqlite3.Connection, category: str, pid: str) -> bool:
    """catalog に (category, product_id) が存在するか。False で "該当なし" が正当。"""
    cur = conn.execute(
        "SELECT 1 FROM products WHERE category = ? AND product_id = ? LIMIT 1",
        (category, pid),
    )
    return cur.fetchone() is not None


def classify(rows: list[dict], conn: sqlite3.Connection) -> dict:
    """全 auto候補 行を分類:
       - `no_candidate`: `auto候補無=` (adapter が候補すら出せなかった正当な該当なし)
       - `false_miss`  : PID が catalog に存在する = 誤って該当なし判定した無駄依頼
       - `true_miss`   : PID が catalog に存在しない = 正当な追加依頼
    """
    result: dict[str, list[dict]] = {"no_candidate": [], "false_miss": [], "true_miss": []}
    for r in rows:
        if r["pid"] in ("無", ""):
            result["no_candidate"].append(r)
            continue
        if check_pid_exists(conn, r["category"], r["pid"]):
            result["false_miss"].append(r)
        else:
            result["true_miss"].append(r)
    return result


def summarize(classified: dict) -> dict:
    """レポート用サマリー。"""
    total = sum(len(v) for v in classified.values())
    with_cand = total - len(classified["no_candidate"])
    fm = classified["false_miss"]
    pct = (len(fm) / with_cand * 100.0) if with_cand else 0.0

    # 同じ cert が何回別日 (別ファイル) で起票されたか
    cert_days: dict[str, set] = defaultdict(set)
    pid_days: dict[tuple[str, str], set] = defaultdict(set)
    for r in fm:
        cert_days[r["cert"]].add(r["date"])
        pid_days[(r["category"], r["pid"])].add(r["date"])

    cert_repeat = sorted(
        ((c, len(ds)) for c, ds in cert_days.items()),
        key=lambda x: (-x[1], x[0]),
    )
    pid_repeat = sorted(
        ((f"{cat}:{pid}", len(ds)) for (cat, pid), ds in pid_days.items()),
        key=lambda x: (-x[1], x[0]),
    )

    return {
        "total_lines": total,
        "no_candidate": len(classified["no_candidate"]),
        "with_candidate": with_cand,
        "false_miss": len(fm),
        "true_miss": len(classified["true_miss"]),
        "false_miss_pct_of_with_candidate": round(pct, 2),
        "unique_false_miss_certs": len(cert_days),
        "unique_false_miss_pids": len(pid_days),
        "top_repeated_certs": cert_repeat[:10],
        "top_repeated_pids": pid_repeat[:10],
    }


def render_text(summary: dict) -> str:
    lines: list[str] = []
    lines.append("=== auto_catalog_add 空振り依頼 監査 (調査専用・修正しない) ===")
    lines.append(f"総 auto候補 行数        : {summary['total_lines']}")
    lines.append(f"  うち auto候補=無      : {summary['no_candidate']}")
    lines.append(f"  うち auto候補=PID あり: {summary['with_candidate']}")
    lines.append(f"False-miss (実は catalog に存在): {summary['false_miss']} "
                 f"({summary['false_miss_pct_of_with_candidate']}% of with_candidate)")
    lines.append(f"True-miss  (正当な追加依頼)     : {summary['true_miss']}")
    lines.append(f"ユニーク cert  (false-miss): {summary['unique_false_miss_certs']}")
    lines.append(f"ユニーク PID   (false-miss): {summary['unique_false_miss_pids']}")
    lines.append("")
    lines.append("同じ cert が別日で再起票された top10 (false-miss のみ):")
    for c, n in summary["top_repeated_certs"]:
        lines.append(f"  cert{c}: {n} 日")
    lines.append("")
    lines.append("同じ PID が別日で再起票された top10 (false-miss のみ):")
    for pid, n in summary["top_repeated_pids"]:
        lines.append(f"  {pid}: {n} 日")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--requests-dir", type=Path, default=DEFAULT_REQUESTS_DIR)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--json", action="store_true",
                   help="JSON (summary + false_miss 全件詳細) を stdout に出力")
    args = p.parse_args(argv)

    if not args.requests_dir.exists():
        print(f"requests dir 無し: {args.requests_dir}", file=sys.stderr)
        return 2
    if not args.db.exists():
        print(f"catalog DB 無し: {args.db}", file=sys.stderr)
        return 2

    rows = scan_requests(args.requests_dir)
    conn = sqlite3.connect(str(args.db))
    try:
        classified = classify(rows, conn)
    finally:
        conn.close()

    summary = summarize(classified)

    if args.json:
        payload = {
            "summary": summary,
            "false_miss_rows": classified["false_miss"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
