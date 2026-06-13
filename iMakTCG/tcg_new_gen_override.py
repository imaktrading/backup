"""tcg_new_gen_override — 旧 psa_to_csv が組んだ行の catalog 由来フィールドを
新生成コア(tcg_listing_fields)の決定論値で上書きする strangler 切替 seam。

並行ビルドの最終段 (2026-06-13)。psa_to_csv 本体は main() ループで 1 行
`apply_new_gen_override(...)` を呼ぶだけ。**フラグ TCG_USE_NEW_GEN=1 の時のみ**有効で、
既定 (OFF) では一切呼ばれず本番は完全不変 (= 旧を残したまま切替可能)。

設計方針 (REGRESSION を出さない安全な切替):
  - 上書き対象は **catalog 由来の Item Specifics 12 列 + タイトル** のみ。
    静的/採点列 (Manufacturer/Country/Grade 等) は旧のまま (新コア対象外)。
  - 既定は **値があるときだけ上書き (blank_missing=False)**。新コアが空欄の列は旧値を残す
    → スターターデッキ等で set_name_ebay 未収録でも C:Set を空欄化しない = 情報欠落の回帰を防ぐ。
  - `TCG_NEW_GEN_STRICT=1` で blank_missing=True (fail-closed 厳格モード= rarity 推測も空欄化)。
  - 新コアが cert を解決できない時は **行を一切変更しない** (旧値を温存 = fail-safe)。

検証: parity (tcg_parity_check) で旧 CSV と同 cert の出力を比較し REGRESSION 0 を確認してから flag ON。
"""
from __future__ import annotations
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _col_idx(headers, name):
    """headers が dict(name→idx) でも list でも idx を返す。"""
    if isinstance(headers, dict):
        return headers.get(name)
    try:
        return headers.index(name)
    except ValueError:
        return None


def env_enabled():
    """本番フラグ: TCG_USE_NEW_GEN=1 の時だけ新生成を有効化。"""
    return os.environ.get("TCG_USE_NEW_GEN") == "1"


def apply_new_gen_override(row, headers, cert, *, blank_missing=None,
                           override_title=True, game_hint=""):
    """1 行を新コアの catalog 決定論値で上書きして返す (副作用なし=新 list を返す)。

    row: build_row が返した list / headers: 列名→idx の dict か 列名 list。
    解決不能や行が短い等で失敗したら **元 row をそのまま返す** (fail-safe)。
    """
    from tcg_listing_fields import build_listing_fields, build_title_from_fields

    if blank_missing is None:
        blank_missing = os.environ.get("TCG_NEW_GEN_STRICT") == "1"

    if not row:
        return row
    # C:Game が無い行 (PSA TCG 以外) は触らない
    gi = _col_idx(headers, "C:Game")
    game = game_hint or (row[gi] if gi is not None and gi < len(row) else "")

    fields, err = build_listing_fields(str(cert), game or "")
    if err or not fields:
        return row  # 解決不能 → 旧値温存 (fail-safe)

    new = list(row)
    for col, val in fields.items():
        if col.startswith("_"):          # _card_id 等の内部キーは除外
            continue
        idx = _col_idx(headers, col)
        if idx is None or idx >= len(new):
            continue
        val = (val or "").strip()
        if val:
            new[idx] = val
        elif blank_missing:
            new[idx] = ""               # 厳格モードのみ空欄化 (rarity 推測除去等)
        # 既定: 新コアが空 → 旧値を残す (回帰防止)

    if override_title:
        ti = _col_idx(headers, "*Title")
        if ti is not None and ti < len(new):
            # grade はタイトル先頭 "PSA 10" が旧に入っている前提で 10 固定
            title = build_title_from_fields(fields, grade="10")
            if title:
                new[ti] = title

    return new
