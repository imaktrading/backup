"""excluder - check_csv が NO-GO 判定した行を CSV から物理除外 (独立モジュール).

設計原則 (修正連鎖を生まないため):
  - 既存 listing script / check_csv.py を一切修正しない
  - check_csv の stdout 出力を parse して NO-GO 行 index を抽出
  - 元 CSV の該当行を削除して上書き、元ファイルは .bak バックアップ

なぜ必要か:
  memory `dual_gate_disagreement.md` の CRITICAL 問題:
  - psa_to_csv の市場ゲート (出力時) と check_csv の市場ゲート (検査時) で
    eBay Browse API 中央値が乖離 (例: $140 vs $115) → 判定が矛盾
  - check_csv が「CSV除外済」と表示しても **物理除外されない** バグあり
  - 人手で CSV から削除しないと NO-GO 行が入稿される事故

  本モジュール = 物理除外を機械化する応急対処. SSOT 化 (Phase C, branch
  feature/dual-gate-ssot) で根本解決するまでの安全弁.

stdout parse の対象パターン:
  check_csv.py L726 の出力:
    `  [N] Title... → ❌ NO-GO 出品X件 $XX 乖離XX% > 許容XX%`
  → 行 N (1-based) を NO-GO として認識.

使用例 (CLI):
    python excluder.py path/to/file.csv "[1] ... NO-GO ..."
  もしくは stdout を pipe:
    python check_csv.py file.csv | python excluder.py file.csv --stdin

control_panel から呼ぶ場合:
    excluder.exclude_from_check_csv_stdout(csv_path, captured_stdout)
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


# check_csv の NO-GO 行パターン (GATE 判定サマリー部のみ)
# 例: `  [5] PSA 10 Pokemon ... → ❌ NO-GO 出品2件 $115 乖離70% > 許容50%`
#
# 重要: `→` (arrow) を必須にして check_csv summary のみ matching する.
# psa_to_csv の intermediate log は `[N] #XXX Char: 出品X件 | 中央値$X | ❌ NO-GO ...`
# (パイプ + card_seq) で `→` 無し → このパターンに hit しない.
# 2026-04-29 fix: psa_to_csv の card_seq を CSV row として誤解釈し、無関係な CSV 行が
# 削除される事故を解消.
# 2026-06-20: 価格NO-GO廃止に伴い、新ラベル「🔵 高め / 価格高め」も検出(移行期は両対応)。
# 旧「❌ NO-GO」も引き続き検出(G-shock/Mercari 等 未移行 check_csv との互換)。
_NOGO_LINE_RE = re.compile(
    r"^\s*\[(\d+)\].*→\s*(?:❌\s*NO[-\s]?GO|🔵?\s*(?:価格)?高め)",
    re.IGNORECASE,
)

# GATE 判定サマリーの section 開始マーカー (二重の安全策)
_GATE_SECTION_MARKER = "GATE判定サマリー"


def parse_nogo_indices(stdout_text: str) -> List[int]:
    """check_csv stdout の GATE 判定サマリー section から NO-GO 行 index 抽出.

    安全策 (重要):
      1. `🏁 GATE判定サマリー` 以降の行のみ対象 (psa_to_csv 出力と切り分け)
      2. `→ ❌ NO-GO` arrow 必須 regex で check_csv summary のみマッチ
      3. (1) の section marker が見つからなければ regex のみ適用 (後方互換)

    Returns: [CSV 行 index (1-based, header を行 0 と見た data 行), ...]
    """
    lines = stdout_text.splitlines()
    in_summary = False
    has_marker = any(_GATE_SECTION_MARKER in ln for ln in lines)

    indices = []
    for line in lines:
        if has_marker:
            # marker を見つけてから parse 開始
            if not in_summary:
                if _GATE_SECTION_MARKER in line:
                    in_summary = True
                continue
            # summary section 終端 (次の section header らしき "===" 60+) で停止
            if line.strip().startswith("=") and len(line.strip()) >= 30:
                break
        m = _NOGO_LINE_RE.match(line)
        if m:
            try:
                indices.append(int(m.group(1)))
            except ValueError:
                pass
    return sorted(set(indices))


def exclude_rows_from_csv(csv_path: str, nogo_indices: List[int]) -> dict:
    """CSV から指定 row index (1-based) を物理除外、元ファイルは .bak で残す.

    Returns:
        {"removed": N, "kept": M, "backup_path": str, "csv_path": str}
    """
    if not nogo_indices:
        return {"removed": 0, "kept": 0, "backup_path": "", "csv_path": csv_path,
                "removed_titles": [], "removed_certs": []}

    # 元 CSV 読込
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {"removed": 0, "kept": 0, "backup_path": "", "csv_path": csv_path,
                "removed_titles": [], "removed_certs": []}

    header = rows[0]
    data = rows[1:]
    nogo_set = set(nogo_indices)

    # title 列の index (報告用)
    try:
        title_idx = header.index("*Title")
    except ValueError:
        title_idx = 2  # eBay FileExchange の標準位置

    # cert 列の index (= post_no_go_sentinel 用 NO-GO cert 収集。2026-06-12 追加)
    cert_idx = -1
    for _i, _h in enumerate(header):
        if "Certification Number" in _h:
            cert_idx = _i
            break

    removed_titles = []
    removed_certs = []
    kept_data = []
    for i, row in enumerate(data, start=1):  # 1-based
        if i in nogo_set:
            t = row[title_idx] if title_idx < len(row) else ""
            removed_titles.append(f"[{i}] {t[:60]}")
            if 0 <= cert_idx < len(row):
                _c = (row[cert_idx] or "").strip()
                if _c:
                    removed_certs.append(_c)
        else:
            kept_data.append(row)

    # バックアップ
    backup_path = csv_path + ".bak"
    shutil.copy2(csv_path, backup_path)

    # 上書き保存
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(header)
        writer.writerows(kept_data)

    return {
        "removed": len(removed_titles),
        "kept": len(kept_data),
        "backup_path": backup_path,
        "csv_path": csv_path,
        "removed_titles": removed_titles,
        "removed_certs": removed_certs,
    }


def peek_rows_from_csv(csv_path: str, indices: List[int]) -> dict:
    """指定 row index (1-based) の title/cert を **CSVを変更せず** 取得(read-only).

    2026-06-20 価格NO-GO廃止方針: 高め(旧NO-GO)は除外せず出品 + 既存メンテで追跡する。
    物理除外(exclude_rows_from_csv)の代わりに、高め行の title/cert だけ記録するため。
    Returns: {"high_count", "high_titles", "high_certs", "total"}.
    """
    if not indices:
        return {"high_count": 0, "high_titles": [], "high_certs": [], "total": 0}
    try:
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.reader(f))
    except Exception:
        return {"high_count": 0, "high_titles": [], "high_certs": [], "total": 0}
    if not rows:
        return {"high_count": 0, "high_titles": [], "high_certs": [], "total": 0}
    header, data = rows[0], rows[1:]
    idx_set = set(indices)
    try:
        title_idx = header.index("*Title")
    except ValueError:
        title_idx = 2
    cert_idx = next((i for i, h in enumerate(header) if "Certification Number" in h), -1)
    high_titles, high_certs = [], []
    for i, row in enumerate(data, start=1):
        if i in idx_set:
            t = row[title_idx] if title_idx < len(row) else ""
            high_titles.append(f"[{i}] {t[:60]}")
            if 0 <= cert_idx < len(row):
                c = (row[cert_idx] or "").strip()
                if c:
                    high_certs.append(c)
    return {"high_count": len(high_titles), "high_titles": high_titles,
            "high_certs": high_certs, "total": len(data)}


def exclude_from_check_csv_stdout(csv_path: str, stdout_text: str) -> dict:
    """check_csv の stdout text から 価格高め(旧NO-GO)を抽出 → **除外せず記録**(2026-06-20方針).

    価格NO-GO廃止: コストプラス(損なし)+無在庫+既存メンテ追跡 → 価格を理由に出品見送りしない。
    高め行は CSV に残して出品し、title/cert を記録して既存メンテ「高めレーン」で追跡する。
    Returns: {removed:0, high_count, high_titles, high_certs(=removed_certs後方互換), ...}.
    """
    indices = parse_nogo_indices(stdout_text)
    peek = peek_rows_from_csv(csv_path, indices)
    result = {
        "removed": 0,                                   # 物理除外しない
        "kept": peek["total"],
        "backup_path": "",
        "csv_path": csv_path,
        "high_count": peek["high_count"],
        "high_titles": peek["high_titles"],
        "high_certs": peek["high_certs"],
        # 後方互換: post_no_go_sentinel / sidecar が removed_certs を読む → 高め cert を渡す
        "removed_titles": [],
        "removed_certs": peek["high_certs"],
        "parsed_nogo_indices": indices,
    }
    # 高め cert を sidecar に保存 → post_no_go_sentinel が既存メンテ(スプシ K列)に追跡マーク。
    # 理由: post_no_go_sentinel は従来 `.csv.bak` 差分で NO-GO cert を求めていたが、
    # `.csv.bak` は後段 dedupe が同名で上書きするため、差分が「dedupe 除外 cert」に化けて
    # 価格 NO-GO cert を取りこぼしていた (2026-06-12 fix)。毎回上書き = 古い run の混入防止。
    try:
        import json as _json
        sidecar = csv_path + ".nogo_certs.json"
        with open(sidecar, "w", encoding="utf-8") as _f:
            _json.dump(result.get("removed_certs", []), _f, ensure_ascii=False)
    except Exception:
        pass
    return result


def render_report(result: dict) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("  🔵 価格高め(出品・既存メンテ追跡) report")
    lines.append("=" * 60)
    lines.append(f"  CSV          : {result.get('csv_path')}")
    indices = result.get("parsed_nogo_indices", [])
    if indices:
        lines.append(f"  高め検出行   : {indices}")
    high = result.get("high_count", 0)
    if high == 0:
        lines.append("  → 高め行なし(全件 市場内)")
    else:
        # 2026-06-20: 価格を理由に除外しない。高めは出品し既存メンテ「高めレーン」で追跡。
        lines.append(f"  🔵 価格高め {high} 行(**除外せず出品** + 既存メンテ追跡)/ 全 {result.get('kept', 0)} 行")
        lines.append("  高め内容(sell-through監視/再探索/価格revise 対象):")
        for t in result.get("high_titles", []):
            lines.append(f"    {t}")
    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================================
# CLI
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="check_csv NO-GO 行を CSV から物理除外")
    parser.add_argument("csv_path", help="対象 CSV ファイル")
    parser.add_argument("stdin_or_file", nargs="?", default=None,
                        help="check_csv の stdout (テキストまたはファイル). "
                             "省略時は stdin から読込.")
    parser.add_argument("--no-backup", action="store_true",
                        help=".bak バックアップ作成しない (危険、debug 用)")
    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"[excluder] CSV が見つかりません: {args.csv_path}", file=sys.stderr)
        sys.exit(1)

    # stdout text 取得
    if args.stdin_or_file is None:
        stdout_text = sys.stdin.read()
    elif os.path.exists(args.stdin_or_file):
        with open(args.stdin_or_file, encoding="utf-8", errors="replace") as f:
            stdout_text = f.read()
    else:
        stdout_text = args.stdin_or_file  # 直接テキスト

    result = exclude_from_check_csv_stdout(args.csv_path, stdout_text)
    print(render_report(result))

    # 終了コード: 除外があれば 0、なければ 0 (どちらも正常終了、除外件数で判別は呼出側)
    sys.exit(0)


if __name__ == "__main__":
    main()
