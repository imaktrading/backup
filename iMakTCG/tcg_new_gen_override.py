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


# 切替時に上書きしない列 (現状なし)。
#   C:Features は 2026-06-14 に新コア側で eBay TCG facet 正規化済 (normalize_tcg_features)
#   = 'Art Card' 等の非facet生値は drop、'Alt Art'→'Alternative Art' 等のみ採用。value-only
#   override なので新コアが空(drop)なら旧値を残す=回帰なし。よって除外不要。
_NO_OVERRIDE = set()

# 新コアが空でも **必ず**新値で上書きする列 (= 既定 value-only の例外)。
#   C:Rarity: 旧コアは rarity 不明時に推測で 'Common' を埋める既知バグ (#1)。新コアは catalog
#   rarity_ebay 無→空欄が正。value-only だと旧 'Common' が温存され #1 が直らない (Gemini DISPUTE
#   2026-06-15) ため、rarity だけは新コアの判定 (空欄含む) を権威として常に反映する。
#   C:Features: 2026-08-22 契約で「catalog の features_ebay だけを出す」に変更。value-only だと
#     新コアが空の時に **旧コアがレアリティ語で埋めた値**が残り、8/22 の入稿で
#     C:Features='Art Rare' / 'Super Rare' が 4件 eBay に出た。空欄も権威として反映する。
#   C:Manufacturer / C:Country of Origin: 旧コアはハードコード。catalog が値を持つので空欄が正。
#
# ★2026-08-26: **列を1つずつ足すのはやめた**。事故のたびに 1列ずつ増えており
#   (Rarity=06-15 / Features・Manufacturer・Country=08-22)、まだ足していない列で
#   同じ事故が出続けていた (8/23〜8/26 の入稿 4本で C:Cost 21 / C:Attack/Power 18 /
#   C:Attribute 2 = 41セルが catalog に無い値)。
#   これ以降は **契約表 (_contract_aspects.yaml) で `source: specs.*` の項目に当たる列**を
#   まとめてカタログ権威 (空欄も反映) にする。下の集合は表が読めない時の退避値。
#   依頼書: hq/requests/2026-08-25_act_code_proposals_tcg.md 提案4
_ALWAYS_OVERWRITE_FALLBACK = {"C:Rarity", "C:Features", "C:Manufacturer", "C:Country of Origin"}

# 契約表の場所は監査くんと同じ 1 箇所 (aspect_contract.CONTRACT_PATH) を使う。
_HQ_TOOLS = os.path.join(os.path.dirname(_HERE), "iMakHQ", "tools")

_AUTH_COLS_CACHE = None


def contract_authoritative_cols(contract=None, cols=None):
    """カタログ権威の CSV 列 (= 新コアが空なら空欄化する列) を契約表から決める。

    表が読めない / 1列も当たらない時は `_ALWAYS_OVERWRITE_FALLBACK` を返す
    (= 従来挙動。表の一時的な不在で 8/22 に直した事故を再発させない)。純関数に近い
    (I/O は aspect_contract.load_contract 側)。
    """
    if cols is None:
        from tcg_listing_fields import _ALL_COLS
        cols = _ALL_COLS
    if contract is None:
        try:
            if _HQ_TOOLS not in sys.path:
                sys.path.insert(0, _HQ_TOOLS)
            from aspect_contract import load_contract
            contract = load_contract()
        except Exception:                       # noqa: BLE001
            contract = None
    if not contract:
        return set(_ALWAYS_OVERWRITE_FALLBACK)
    try:
        from aspect_contract import aspect_of
    except Exception:                           # noqa: BLE001
        return set(_ALWAYS_OVERWRITE_FALLBACK)
    out = set()
    for col in cols:
        rec = contract.get(aspect_of(col))
        if not rec or not rec.get("emit"):
            continue
        if str(rec.get("source") or "").startswith("specs."):
            out.add(col)
    return out or set(_ALWAYS_OVERWRITE_FALLBACK)


def always_overwrite_cols():
    """`contract_authoritative_cols` の結果を1走行ぶん cache して返す。"""
    global _AUTH_COLS_CACHE
    if _AUTH_COLS_CACHE is None:
        _AUTH_COLS_CACHE = contract_authoritative_cols()
        _log(f"カタログ権威の列 {len(_AUTH_COLS_CACHE)}: {sorted(_AUTH_COLS_CACHE)}")
    return _AUTH_COLS_CACHE


def _log(msg):
    """新コア override の動作を stderr に記録 (silent no-op 撲滅・運用観測性)。"""
    print(f"[new_gen] {msg}", file=sys.stderr)


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
                           override_title=True, game_hint="", forced_card_id=""):
    """1 行を新コアの catalog 決定論値で上書きして返す (副作用なし=新 list を返す)。

    row: build_row が返した list / headers: 列名→idx の dict か 列名 list。
    forced_card_id: 人が HTML 目視確認で確定/選び直した product_id。指定時は新コアが
      その card_id で決定論再生成 (= verify→build フロー / CHOSEN 補正)。
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

    fields, err = build_listing_fields(str(cert), game or "", forced_card_id=forced_card_id)
    if err or not fields:
        # 解決不能 → 旧値温存 (fail-safe)。但し **必ずログ** (silent no-op だと「新コアが
        # 効いてる風で実は未適用=defect 温存」を検知できない。Gemini DISPUTE 2026-06-15)。
        _log(f"cert={cert} override SKIP → 旧値温存: {err or 'fields空'}")
        return row

    new = list(row)
    _authoritative = always_overwrite_cols()
    for col, val in fields.items():
        if col.startswith("_"):          # _card_id 等の内部キーは除外
            continue
        if col in _NO_OVERRIDE:          # 非facet値で悪化する列は旧のまま
            continue
        idx = _col_idx(headers, col)
        if idx is None or idx >= len(new):
            continue
        val = (val or "").strip()
        if val:
            new[idx] = val
        elif blank_missing or col in _authoritative:
            new[idx] = ""               # 厳格モード or カタログ権威列 は空欄化 (catalog の空を写す)
        # 既定: 新コアが空 → 旧値を残す (回帰防止)

    if override_title:
        ti = _col_idx(headers, "*Title")
        if ti is not None and ti < len(new):
            # grade は行の C:Grade 列から取得 (旧は "10" ハードコード= PSA9 等で誤表示リスク・
            # Gemini DISPUTE 2026-06-15)。現状 build_row は C:Grade="10" 固定 (PSA10限定運用) なので
            # 実値は変わらないが、grade の SSOT を行に一本化してハードコード重複を除去。
            gri = _col_idx(headers, "C:Grade")
            grade = (new[gri].strip() if gri is not None and gri < len(new) and new[gri] else "") or "10"
            title = build_title_from_fields(fields, grade=grade)
            if title:
                new[ti] = title

    # 商品説明の Specifications ブロックを新コア値で作り直す
    # (旧コア build_row が入れた旧値の Specs を除去 → catalog 由来の新値で再挿入。
    #  = description と Item Specifics を一致させる。マーカー無しは fail-safe で不変)。
    di = _col_idx(headers, "*Description")
    if di is not None and di < len(new) and new[di]:
        from tcg_listing_fields import (build_tcg_specs_html, replace_tcg_specs,
                                        specs_pairs_from_fields)
        new[di] = replace_tcg_specs(new[di], build_tcg_specs_html(specs_pairs_from_fields(fields)))

    return new
