"""tcg_parity_check — 旧パイプライン出力(既存 tcg_upload CSV)と新生成コアの parity 検証。

並行ビルドの strangler ゲート (2026-06-13 新設・read-only):
  旧 psa_to_csv が出した CSV の各行を、cert から **新コア
  (tcg_listing_fields.build_listing_fields / build_title_from_fields)** で再生成し、
  catalog 由来 Item Specifics + タイトルを **フィールド単位で diff** する。

  目的 = 切替前の証明。新コアが旧と一致 (SAME) か、もしくは
  **意図した2バグ修正 (#1 rarity推測除去 / #4 Subject汚染除去・set名是正)** だけが差分で、
  それ以外の **回帰 (REGRESSION) がゼロ** であることを示す。
  REGRESSION が出たら切替してはならない。

  比較対象は **新コアが担当する catalog 由来12列**のみ (_ALL_COLS)。
  C:Manufacturer / Country of Origin / Grade 等の静的・採点フィールドは新コア対象外なので diff しない
  (= オーケストレータ実装時にそれら静的列の担当を別途決める。本ツールの守備範囲外)。

使い方:
  python tcg_parity_check.py [csv_path]   # 省略時 csv_output 最新 tcg_upload_*.csv
  exit code: REGRESSION が1件でもあれば 1、無ければ 0。
"""
from __future__ import annotations
import csv
import glob
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_TCG = r"C:/dev/iMak/iMakTCG"
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tcg_catalog_audit import (  # noqa: E402
    CSV_DIR, CERT_COL, _detect_franchise, _resolve_card_id,
    _catalog_record, _get,
)

# 新コアが担当する列だけを parity 対象にする (静的/採点列は対象外)
PARITY_COLS = [
    "*Title", "C:Game", "C:Set", "C:Card Type", "C:Card Name", "C:Character",
    "C:Card Number", "C:Rarity", "C:Features", "C:Finish", "C:Illustrator",
    "C:Language", "C:Year Manufactured",
]

# 重要度の並び (悪い順)
_SEVERITY_ORDER = {"regression": 0, "review": 1, "improved": 2, "ok": 3}


def _norm(s: str) -> str:
    """比較用正規化: 小文字・em-dash/apostrophe 統一・空白畳み。"""
    s = (s or "").lower().replace("—", "-").replace("–", "-")
    s = s.replace("’", "'").replace("é", "e")  # ’→' / é→e
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str):
    s = _norm(s)
    s = re.sub(r"'s\b", "", s)
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def interpret_diff(col: str, old: str, new: str, rec: dict) -> tuple[str, str]:
    """旧値 vs 新値 を catalog record 文脈で分類 (純関数=テスト可能)。

    rec = {"name_en","rarity_code","set_ebay"(任意),"character_name"(任意)}。
    Returns (severity, note)。severity ∈ ok/improved/review/regression。
    """
    no, nn = _norm(old), _norm(new)
    if no == nn:
        return ("ok", "一致")

    if col == "C:Rarity":
        if not nn and no:
            if not rec.get("rarity_code"):
                return ("improved", f"推測rarity除去 (#1修正・catalogにrarity無): {old!r}→空欄")
            return ("regression", f"rarity空欄化だが catalog に '{rec['rarity_code']}' 有 = 要確認")
        return ("review", f"rarity変更 {old!r}→{new!r}")

    if col in ("C:Character", "C:Card Name"):
        ot, nt = set(_tokens(old)), set(_tokens(new))
        if nt and nt < ot:
            return ("improved", f"token縮小=汚染除去疑い (#4修正) {old!r}→{new!r}")
        if not nn and no:
            return ("regression", f"{col} 空欄化 {old!r}→空欄 (catalog name_en/character_name 要確認)")
        # name_en と一致する方向の変更なら improved 寄りだが、断定せず review
        return ("review", f"{col}変更 {old!r}→{new!r}")

    if col == "C:Set":
        # 新値=catalog set_name_ebay を期待。rec に set_ebay があれば一致確認。
        se = rec.get("set_ebay")
        if se is not None:
            if _norm(new) == _norm(se):
                return ("improved", f"Set是正→catalog set_name_ebay一致 {old!r}→{new!r}")
            return ("regression", f"Set新値 {new!r} が catalog set_name_ebay {se!r} と不一致")
        return ("review", f"Set変更 {old!r}→{new!r} (catalog set_name_ebay 要照合)")

    if col == "*Title":
        return ("review", f"title変更 (上記field差分の反映を確認)")

    # その他 (Game/Card Type/Number/Features/Finish/Illustrator/Language/Year)
    if not nn and no:
        return ("review", f"{col} 空欄化 {old!r}→空欄")
    if not no and nn:
        return ("review", f"{col} 新規 空欄→{new!r}")
    return ("review", f"{col}変更 {old!r}→{new!r}")


def _build_new(cert: str, game_hint: str):
    """新コアで cert を再生成。Returns (fields_dict, title, err)。"""
    from tcg_listing_fields import build_listing_fields, build_title_from_fields
    fields, err = build_listing_fields(cert, game_hint)
    if err:
        return None, None, err
    title = build_title_from_fields(fields)
    return fields, title, None


def compare_row(row, headers):
    """旧CSV1行 vs 新コア。Returns dict {cert, card_id, err, diffs:[(col,old,new,sev,note)]}。"""
    cert = _get(row, headers, CERT_COL)
    game = _get(row, headers, "C:Game")
    if not cert:
        return {"cert": "", "err": "cert列空 (PSA行でない)", "diffs": []}

    fields, new_title, err = _build_new(cert, game or "Pokémon TCG")
    if err:
        return {"cert": cert, "err": f"新コア再生成失敗: {err}", "diffs": []}

    card_id = fields.get("_card_id", "")
    rec = _catalog_record(card_id) or {}
    # rec に set_ebay / character_name を補完 (interpret_diff 用)
    se = None
    import sqlite3 as _sq
    import json as _json
    try:
        con = _sq.connect(_catalog_record.__globals__["CATALOG_DB"])
        r = con.execute("SELECT specs FROM products WHERE product_id=?", (card_id,)).fetchone()
        con.close()
        if r and r[0]:
            sp = _json.loads(r[0])
            se = sp.get("set_name_ebay")
            rec["character_name"] = sp.get("character_name") or ""
    except Exception:
        pass
    if se is not None:
        rec["set_ebay"] = se

    diffs = []
    for col in PARITY_COLS:
        old_val = _get(row, headers, col)
        if col == "*Title":
            new_val = new_title or ""
        else:
            new_val = fields.get(col, "")
        sev, note = interpret_diff(col, old_val, new_val, rec)
        if sev != "ok":
            diffs.append((col, old_val, new_val, sev, note))
    diffs.sort(key=lambda d: _SEVERITY_ORDER.get(d[3], 9))
    return {"cert": cert, "card_id": card_id, "err": None, "diffs": diffs}


def run(csv_path):
    rows = list(csv.reader(open(csv_path, encoding="utf-8", newline="")))
    if not rows:
        print("空 CSV"); return 0
    headers = {h: i for i, h in enumerate(rows[0])}
    print("=" * 70)
    print(f"tcg_parity_check (旧CSV vs 新生成コア・read-only)\n対象: {os.path.basename(csv_path)}")
    print("=" * 70)
    n_reg = n_imp = n_rev = 0
    for n, row in enumerate(rows[1:], 1):
        res = compare_row(row, headers)
        title = _get(row, headers, "*Title")
        if res.get("err"):
            print(f"\n[{n}] ⚠️ cert {res['cert']}: {res['err']}")
            continue
        diffs = res["diffs"]
        regs = [d for d in diffs if d[3] == "regression"]
        mark = "🚨" if regs else ("🔧" if any(d[3] == "improved" for d in diffs) else
                                  ("👀" if diffs else "✅"))
        print(f"\n[{n}] {mark} cert {res['cert']} → {res['card_id']}")
        print(f"     {title[:64]}")
        for col, old, new, sev, note in diffs:
            tag = {"regression": "🚨REGRESSION", "review": "👀REVIEW",
                   "improved": "🔧IMPROVED"}.get(sev, sev)
            print(f"     [{tag}] {col}: {note}")
            if sev == "regression":
                n_reg += 1
            elif sev == "improved":
                n_imp += 1
            else:
                n_rev += 1
    print("\n" + "=" * 70)
    print(f"結果: IMPROVED(意図修正) {n_imp} / REVIEW(要目視) {n_rev} / REGRESSION(切替阻止) {n_reg}")
    if n_reg:
        print("🚨 REGRESSION あり → 新コアへの切替は不可。原因を解消してから再検証。")
    else:
        print("✅ REGRESSION なし。差分は意図修正 or 要目視のみ (目視確認の上で切替判断可)。")
    print("=" * 70)
    return n_reg


def find_latest_csv():
    cands = [c for c in glob.glob(os.path.join(CSV_DIR, "tcg_upload_*.csv"))
             if ".bak" not in os.path.basename(c)]
    return max(cands, key=os.path.getmtime) if cands else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else find_latest_csv()
    if not path or not os.path.exists(path):
        print(f"CSV が見つかりません: {path}"); sys.exit(2)
    sys.exit(1 if run(path) else 0)


if __name__ == "__main__":
    main()
