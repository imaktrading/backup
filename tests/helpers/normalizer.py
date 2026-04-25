#!/usr/bin/env python3
"""iMak Trading Japan - Golden Test 用 CSV 正規化エンジン.

CSV を「論理一致」レベルで比較するために、環境差で揺れる以下を吸収する:
  - 改行コード (CRLF / LF / CR)
  - セル前後の空白 (trim)
  - 数値表現 (1.0 vs 1, 1.10 vs 1.1)
  - 列順 (列名でソート)

使い方:
    from tests.helpers.normalizer import normalize_csv

    norm_a = normalize_csv(csv_string_a)
    norm_b = normalize_csv(csv_string_b)
    assert norm_a == norm_b   # 論理的に同じ内容なら True

設計方針:
  - 入力: CSV 文字列 (str) または file path (str/Path)
  - 出力: 正規化済 CSV 文字列 (LF区切り、列名ソート、セル trim、数値統一)
  - "論理一致" 用なので、列順を破壊する。byte-exact 比較は別レイヤで行う。
"""
from __future__ import annotations
import csv
import io
import re
from pathlib import Path
from typing import Iterable, List, Sequence, Union


_NUMERIC_RE = re.compile(r'^-?\d+(?:\.\d+)?$')


def _normalize_cell(value: str) -> str:
    """セル単位の正規化:
    - 前後空白を除去
    - 数値文字列 (例: "1.00", "1.0", "1") は float に変換し、末尾0除去で統一
      ※ 整数化はしない (1.0 と 1 を区別したい場面もあるため最小限の正規化)
    """
    if value is None:
        return ""
    s = str(value).strip()
    # 数値判定: 完全に数値文字列ならフォーマット統一
    if _NUMERIC_RE.match(s):
        try:
            f = float(s)
            # 整数値なら "5" / 小数なら末尾0を除去 ("1.10" -> "1.1")
            if f == int(f):
                return str(int(f))
            else:
                return f"{f:g}"  # %g: 必要桁のみ
        except (ValueError, OverflowError):
            return s
    return s


def _read_rows(source: Union[str, Path, Iterable[str]]) -> List[List[str]]:
    """CSV ソースを行リストに変換.

    Args:
        source: CSV 文字列 / ファイルパス / iterable of lines

    Returns:
        list of row (list of cells)
    """
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8")
        return list(csv.reader(io.StringIO(text)))
    if isinstance(source, str):
        # ファイルパスっぽいか CSV 文字列か判定
        if "\n" not in source and Path(source).is_file():
            text = Path(source).read_text(encoding="utf-8")
            return list(csv.reader(io.StringIO(text)))
        return list(csv.reader(io.StringIO(source)))
    # iterable of lines
    return list(csv.reader(source))


def normalize_csv(
    source: Union[str, Path, Iterable[str]],
    *,
    sort_columns: bool = True,
    sort_rows: bool = False,
) -> str:
    """CSV を論理一致用に正規化.

    Args:
        source: CSV 文字列 / Path / lines iterable
        sort_columns: True なら列名アルファベット順にソート (列順差異を吸収)
        sort_rows: True なら行を辞書順ソート (行順差異を吸収。eBay CSV では行順は意味があるので既定 False)

    Returns:
        正規化済 CSV 文字列 (LF 区切り、QUOTE_MINIMAL)
    """
    rows = _read_rows(source)
    if not rows:
        return ""

    header = rows[0]
    body = rows[1:]

    # 列インデックスのマッピング作成
    if sort_columns:
        # ヘッダ名をアルファベット順にソートして対応する列インデックスを取得
        sorted_indices: List[int] = sorted(range(len(header)), key=lambda i: header[i])
        new_header = [header[i] for i in sorted_indices]
        new_body = [[row[i] if i < len(row) else "" for i in sorted_indices] for row in body]
    else:
        new_header = list(header)
        new_body = [list(row) for row in body]

    # セル単位 normalize
    new_header = [_normalize_cell(c) for c in new_header]
    new_body = [[_normalize_cell(c) for c in row] for row in new_body]

    if sort_rows:
        new_body = sorted(new_body, key=lambda r: tuple(r))

    # 出力 (LF統一, QUOTE_MINIMAL = 必要な時だけクォート)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(new_header)
    writer.writerows(new_body)
    return buf.getvalue()


def assert_csv_logical_equal(
    actual: Union[str, Path],
    expected: Union[str, Path],
    **kwargs,
) -> None:
    """正規化後 byte 一致を assert. 失敗時は最初の差異行を提示.

    Raises:
        AssertionError: 不一致の場合
    """
    norm_a = normalize_csv(actual, **kwargs)
    norm_e = normalize_csv(expected, **kwargs)
    if norm_a == norm_e:
        return
    # 差分行を特定
    a_lines = norm_a.splitlines()
    e_lines = norm_e.splitlines()
    diff_idx = None
    for i, (a, e) in enumerate(zip(a_lines, e_lines)):
        if a != e:
            diff_idx = i
            break
    if diff_idx is None:
        diff_idx = min(len(a_lines), len(e_lines))
    msg_lines = [
        f"CSV logical mismatch at row {diff_idx}:",
        f"  expected: {e_lines[diff_idx] if diff_idx < len(e_lines) else '<missing>'}",
        f"  actual  : {a_lines[diff_idx] if diff_idx < len(a_lines) else '<missing>'}",
        f"  total rows: actual={len(a_lines)}, expected={len(e_lines)}",
    ]
    raise AssertionError("\n".join(msg_lines))
