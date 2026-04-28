"""rarara - CSV 内 outlier 検出器 (汎用、全 program 共通).

設計思想:
  ユーザーが目視で「あれ？他と違う」と気付くレベルを機械化.
  カテゴリ別ルール / eBay フィルタ enum 辞書 を一切持たない汎用検出器.
  「同 batch (1 CSV 内) の他行と比較して多数派と違う」だけで判定.

検出する 3 種類の異常:
  1. 値の outlier        … 同列で多数派と違う値 (例: 10件 Porter / 1件 HEAD PORTER)
  2. 形式の混在          … 寸法系で dual format と裸数値が混在 等
  3. 空欄の混在          … 多数埋まってるのに 1件だけ空欄

閾値 (tiered):
  多数派 ≥ 80%  : 残り (≤20%) を 🔴 強い WARN
  多数派 60-80%  : 残り (20-40%) を 🟡 弱い WARN
  多数派 < 60%   : 商品ごと違うとみなし検査スキップ

タイトル列の特別処理:
  全件の Title 値そのものは違って当然 → スキップ
  ただし「先頭 2 トークン」だけは prefix として比較 (YOSHIDA PORTER vs PORTER 等)

責務範囲外:
  - 自動修正 (rarara は検出のみ)
  - eBay 公式フィルタ正規値との突合 (= category 知識、別レイヤー)
  - 原因究明 (Vision OCR ノイズ等の特定は Claude or 人間の役目)

使用例:
    python rarara.py path/to/some.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional


# ============================================================================
# 設定
# ============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPORTS_DIR = SCRIPT_DIR.parent.parent / "iMakHQ" / "rarara_reports"

# 比較対象外列 (Description / 価格 / SKU 等は per-item で違って当然)
SKIP_COLUMNS = {
    "*Description", "ConditionDescription", "PicURL",
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "ScheduleTime", "CustomLabel", "*StartPrice",
}
SKIP_COLUMN_PATTERNS = [
    re.compile(r"^\*Action\b"),  # Action 列の bom 付き等
]

# Title 列名の判定 (eBay FileExchange は "*Title")
TITLE_COLUMNS = {"*Title"}

# 長すぎる cell (HTML 等) は処理スキップ
MAX_CELL_LEN = 200

# 閾値
THRESHOLD_STRONG = 0.80  # ≥80% で強 WARN
THRESHOLD_WEAK = 0.60    # 60-80% で弱 WARN


# ============================================================================
# データクラス
# ============================================================================
@dataclass
class Anomaly:
    severity: str            # "WARN_STRONG" | "WARN_WEAK"
    type: str                # "value_outlier" | "format_mismatch" | "missing_mixed" | "title_prefix_outlier"
    column: str
    row_indices: List[int]   # 1-based 行番号 (CSV header を 0 と数えた時の data 行)
    issue_description: str   # 「おかしい点」(人間可読)
    outlier_values: List[str]
    majority_pattern: str    # 多数派の値 or 形式
    majority_count: int
    total_count: int


@dataclass
class Report:
    csv_path: str
    row_count: int
    column_count: int
    timestamp: str
    anomalies: List[Anomaly] = field(default_factory=list)
    consistent_columns: List[str] = field(default_factory=list)  # 全件一致した列


# ============================================================================
# 形式パターン分類 (汎用、ヒューリスティック)
# ============================================================================
def detect_pattern(val) -> str:
    """セル値を pattern signature に分類."""
    if val is None:
        return "EMPTY"
    s = str(val).strip()
    if not s:
        return "EMPTY"
    # 数値のみ
    if re.match(r"^-?\d+(\.\d+)?$", s):
        return "NUM_BARE"
    # 数値 + cm
    if re.match(r"^-?\d+(\.\d+)?\s*cm$", s, re.IGNORECASE):
        return "NUM_CM"
    # 数値 + in / inch / inches
    if re.match(r"^-?\d+(\.\d+)?\s*(in|inch|inches|\")$", s, re.IGNORECASE):
        return "NUM_IN"
    # dual format: "X.X in (X.X cm)"
    if re.match(r"^-?\d+(\.\d+)?\s*(in|inch|inches|\")\s*\([^)]*cm\s*\)$", s, re.IGNORECASE):
        return "DUAL_INCM"
    # 数値 + 他単位 (lb / mm / m / g / kg etc.)
    if re.match(r"^-?\d+(\.\d+)?\s*[A-Za-z]+$", s):
        return "NUM_UNIT_OTHER"
    # 通常テキスト
    return "TEXT"


# ============================================================================
# 列スキップ判定
# ============================================================================
def should_skip_column(col_name: str, sample_values: list) -> bool:
    if col_name in SKIP_COLUMNS:
        return True
    for pat in SKIP_COLUMN_PATTERNS:
        if pat.search(col_name):
            return True
    # 長すぎる cell が含まれる (HTML 等)
    if any(len(str(v)) > MAX_CELL_LEN for v in sample_values):
        return True
    return False


# ============================================================================
# 値の outlier 検出
# ============================================================================
def analyze_value_distribution(col_name: str, values: list) -> Optional[Anomaly]:
    """同一値の多数派 vs outlier 検出 (TEXT 列向け)."""
    n = len(values)
    if n < 2:
        return None
    counter = Counter(values)
    # 最頻値とその count
    top_val, top_count = counter.most_common(1)[0]
    ratio = top_count / n
    if ratio < THRESHOLD_WEAK:
        return None  # 多数派なし、検査スキップ
    # outlier 抽出
    outlier_indices = [i + 1 for i, v in enumerate(values) if v != top_val]
    outlier_values = sorted({values[i - 1] for i in outlier_indices})
    if not outlier_indices:
        return None  # 全件一致 (consistent)
    severity = "WARN_STRONG" if ratio >= THRESHOLD_STRONG else "WARN_WEAK"
    issue = f"{col_name} の値が他と違う"
    return Anomaly(
        severity=severity,
        type="value_outlier",
        column=col_name,
        row_indices=outlier_indices,
        issue_description=issue,
        outlier_values=[str(v) for v in outlier_values],
        majority_pattern=str(top_val),
        majority_count=top_count,
        total_count=n,
    )


# ============================================================================
# 形式の混在検出
# ============================================================================
def analyze_format_distribution(col_name: str, values: list) -> Optional[Anomaly]:
    """同列で複数の pattern signature が混在してるか検出.

    例: 8件 DUAL_INCM / 3件 NUM_BARE → 形式混在 WARN
    EMPTY と他形式の混在もここで検出 (missing_mixed として).
    """
    n = len(values)
    if n < 2:
        return None
    patterns = [detect_pattern(v) for v in values]
    pat_counter = Counter(patterns)
    # 全部同じなら問題なし
    if len(pat_counter) == 1:
        return None
    # EMPTY 以外で多数派を見る
    non_empty_patterns = [p for p in patterns if p != "EMPTY"]
    if not non_empty_patterns:
        return None
    nonempty_counter = Counter(non_empty_patterns)
    top_pat, top_count = nonempty_counter.most_common(1)[0]
    nonempty_n = len(non_empty_patterns)
    ratio = top_count / nonempty_n if nonempty_n else 0
    # EMPTY と TEXT 等の混在は別として扱う (missing_mixed 検出)
    empty_count = pat_counter.get("EMPTY", 0)
    if empty_count > 0 and empty_count < n:
        # 一部だけ空 = 空欄混在
        empty_indices = [i + 1 for i, p in enumerate(patterns) if p == "EMPTY"]
        non_empty_n = n - empty_count
        # 空欄が少数派なら WARN
        if non_empty_n / n >= THRESHOLD_WEAK:
            severity = "WARN_STRONG" if non_empty_n / n >= THRESHOLD_STRONG else "WARN_WEAK"
            return Anomaly(
                severity=severity,
                type="missing_mixed",
                column=col_name,
                row_indices=empty_indices,
                issue_description=f"{col_name} が空欄、他 {non_empty_n} 件は埋まっている",
                outlier_values=[""] * len(empty_indices),
                majority_pattern=f"埋まっている (例: {non_empty_patterns[0]})",
                majority_count=non_empty_n,
                total_count=n,
            )
    # TEXT 同士は値の比較 (analyze_value_distribution の担当) なのでスキップ
    if top_pat == "TEXT" and all(p in ("TEXT", "EMPTY") for p in patterns):
        return None
    # 形式混在 (例: NUM_CM / NUM_BARE / DUAL_INCM)
    if ratio < THRESHOLD_WEAK:
        return None
    outlier_indices = [
        i + 1 for i, p in enumerate(patterns) if p != top_pat and p != "EMPTY"
    ]
    if not outlier_indices:
        return None
    outlier_pats = [patterns[i - 1] for i in outlier_indices]
    outlier_vals = [values[i - 1] for i in outlier_indices]
    severity = "WARN_STRONG" if ratio >= THRESHOLD_STRONG else "WARN_WEAK"
    return Anomaly(
        severity=severity,
        type="format_mismatch",
        column=col_name,
        row_indices=outlier_indices,
        issue_description=(
            f"{col_name} の形式が他と違う "
            f"(他 {top_count} 件は {_describe_pattern(top_pat)}、"
            f"これらは {','.join(set(_describe_pattern(p) for p in outlier_pats))})"
        ),
        outlier_values=[str(v) for v in outlier_vals],
        majority_pattern=_describe_pattern(top_pat),
        majority_count=top_count,
        total_count=nonempty_n,
    )


def _describe_pattern(p: str) -> str:
    return {
        "DUAL_INCM": "dual format `X in (X cm)`",
        "NUM_CM": "cm 単独 `X cm`",
        "NUM_IN": "in 単独 `X in`",
        "NUM_BARE": "単位なし数値",
        "NUM_UNIT_OTHER": "別単位付き",
        "TEXT": "文字列",
        "EMPTY": "空欄",
    }.get(p, p)


# ============================================================================
# Title prefix の outlier 検出
# ============================================================================
def analyze_title_prefix(col_name: str, values: list, prefix_words: int = 2) -> Optional[Anomaly]:
    """Title 列の先頭 N 単語 (prefix) を比較して outlier 検出."""
    n = len(values)
    if n < 2:
        return None
    prefixes = []
    for v in values:
        s = str(v).strip()
        # PSA 系は先頭 "PSA 10" を skip して prefix を取る
        s_after_psa = re.sub(r"^PSA\s+\d+\s*", "", s, flags=re.IGNORECASE)
        tokens = s_after_psa.split()[:prefix_words]
        prefixes.append(" ".join(tokens).upper())
    counter = Counter(prefixes)
    top_pre, top_count = counter.most_common(1)[0]
    ratio = top_count / n
    if ratio < THRESHOLD_WEAK:
        return None
    outlier_indices = [i + 1 for i, p in enumerate(prefixes) if p != top_pre]
    if not outlier_indices:
        return None
    outlier_titles = [str(values[i - 1])[:60] for i in outlier_indices]
    severity = "WARN_STRONG" if ratio >= THRESHOLD_STRONG else "WARN_WEAK"
    return Anomaly(
        severity=severity,
        type="title_prefix_outlier",
        column=col_name,
        row_indices=outlier_indices,
        issue_description=(
            f"タイトル先頭が他 {top_count} 件と違う "
            f"(他は \"{top_pre}\" で始まる)"
        ),
        outlier_values=outlier_titles,
        majority_pattern=top_pre,
        majority_count=top_count,
        total_count=n,
    )


# ============================================================================
# メイン解析
# ============================================================================
def analyze_csv(csv_path: str) -> Report:
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return Report(csv_path=csv_path, row_count=0, column_count=0,
                      timestamp=datetime.now().isoformat(timespec="seconds"))
    header = rows[0]
    data = rows[1:]
    n_rows = len(data)
    n_cols = len(header)

    report = Report(
        csv_path=csv_path,
        row_count=n_rows,
        column_count=n_cols,
        timestamp=datetime.now().isoformat(timespec="seconds"),
    )

    for col_idx, col_name in enumerate(header):
        # 当該列の値抽出
        values = [r[col_idx] if col_idx < len(r) else "" for r in data]

        if should_skip_column(col_name, values):
            continue

        # Title 列は prefix のみ比較
        if col_name in TITLE_COLUMNS:
            anom = analyze_title_prefix(col_name, values)
            if anom:
                report.anomalies.append(anom)
            continue

        # 形式の混在 (寸法系等) を先にチェック
        anom_fmt = analyze_format_distribution(col_name, values)
        if anom_fmt:
            report.anomalies.append(anom_fmt)
            continue  # 形式混在を検出した列は値比較スキップ (重複防止)

        # 値の outlier (Brand / Country 等)
        # 形式が全件 TEXT (or EMPTY) の場合のみ値比較
        patterns = [detect_pattern(v) for v in values]
        unique_pats = {p for p in patterns if p != "EMPTY"}
        if unique_pats <= {"TEXT"}:
            anom_val = analyze_value_distribution(col_name, values)
            if anom_val:
                report.anomalies.append(anom_val)
            else:
                # 全件一致 = consistent
                non_empty_vals = [v for v in values if v]
                if non_empty_vals and len(set(non_empty_vals)) == 1:
                    report.consistent_columns.append(col_name)

    return report


# ============================================================================
# レンダリング (console + log file 用テキスト)
# ============================================================================
def render_text(report: Report) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("=== rarara report ===")
    lines.append("=" * 60)
    lines.append(f"日時:  {report.timestamp}")
    lines.append(f"対象:  {report.csv_path}")
    lines.append(f"件数:  {report.row_count} listings × {report.column_count} columns")
    lines.append("")

    strong = [a for a in report.anomalies if a.severity == "WARN_STRONG"]
    weak = [a for a in report.anomalies if a.severity == "WARN_WEAK"]

    if strong:
        lines.append("🔴 強い WARN (多数派 ≥80%)")
        lines.append("-" * 60)
        for a in strong:
            lines.append(_render_anomaly(a))
            lines.append("")

    if weak:
        lines.append("🟡 弱い WARN (多数派 60-80%)")
        lines.append("-" * 60)
        for a in weak:
            lines.append(_render_anomaly(a))
            lines.append("")

    if report.consistent_columns:
        lines.append("✅ 全件一致 (参考)")
        lines.append("-" * 60)
        for c in report.consistent_columns:
            lines.append(f"  {c}: 全 {report.row_count} 件で同値")
        lines.append("")

    lines.append("=" * 60)
    lines.append("=== 集計 ===")
    lines.append(f"  🔴 強 WARN : {len(strong)} 件")
    lines.append(f"  🟡 弱 WARN : {len(weak)} 件")
    lines.append(f"  ✅ 一致確認 : {len(report.consistent_columns)} 列")
    lines.append("=" * 60)
    return "\n".join(lines)


def _render_anomaly(a: Anomaly) -> str:
    rows_str = ",".join(f"#{i}" for i in a.row_indices)
    out = []
    out.append(f"  [{rows_str}] {a.column}")
    out.append(f"    おかしい点 : {a.issue_description}")
    if a.type == "missing_mixed":
        out.append(f"    これらの行 : 空欄")
    else:
        sample = ", ".join(repr(v) for v in a.outlier_values[:3])
        if len(a.outlier_values) > 3:
            sample += f" ...他 {len(a.outlier_values) - 3} 件"
        out.append(f"    これらの行 : {sample}")
    out.append(
        f"    多数派     : \"{a.majority_pattern}\" "
        f"({a.majority_count}/{a.total_count} 件、"
        f"{int(100 * a.majority_count / a.total_count)}%)"
    )
    return "\n".join(out)


# ============================================================================
# 永続化
# ============================================================================
def save_report(report: Report, reports_dir: Optional[Path] = None) -> tuple:
    """log + json をファイル化. (log_path, json_path) を返す."""
    rd = reports_dir or DEFAULT_REPORTS_DIR
    rd.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = rd / f"rarara_{ts}.log"
    json_path = rd / f"rarara_{ts}.json"
    log_text = render_text(report)
    log_path.write_text(log_text, encoding="utf-8")
    # json は dataclass を asdict
    json_data = {
        "csv_path": report.csv_path,
        "row_count": report.row_count,
        "column_count": report.column_count,
        "timestamp": report.timestamp,
        "anomalies": [asdict(a) for a in report.anomalies],
        "consistent_columns": report.consistent_columns,
    }
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path, json_path


# ============================================================================
# CLI
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="rarara: CSV 内 outlier 検出 (汎用)")
    parser.add_argument("csv_path", help="解析対象の CSV ファイルパス")
    parser.add_argument("--no-save", action="store_true", help="ファイル保存しない (console のみ)")
    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"[rarara] CSV が見つかりません: {args.csv_path}", file=sys.stderr)
        sys.exit(1)

    report = analyze_csv(args.csv_path)
    text = render_text(report)
    print(text)

    if not args.no_save:
        log_path, json_path = save_report(report)
        print(f"\n[rarara] 保存:")
        print(f"  log : {log_path}")
        print(f"  json: {json_path}")

    # 終了コード: 強 WARN ありで 1 (将来 orchestrator で判定可)
    has_strong = any(a.severity == "WARN_STRONG" for a in report.anomalies)
    sys.exit(1 if has_strong else 0)


if __name__ == "__main__":
    main()
