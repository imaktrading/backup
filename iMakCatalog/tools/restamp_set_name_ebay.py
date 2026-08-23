#!/usr/bin/env python3
"""products.specs.set_name_ebay を変換表から引き直す (焼き直し).

決定: hq/requests/2026-08-21_set_name_and_name_en_need_ebay_facet_response.md (窓口 Advisor)
      「手で置き換えるのではなく set_name_official から引き直す。適用前に dry-run で止める」

## なにをするか
`derive_set_name_ebay(category, set_name_official, product_id)` を全行で引き直し、
stored と違う行を新しい値に揃える。**手で値を書かない**。

  - derived が None の行は触らない (fail-closed。空欄のまま)
  - stored == derived の行は触らない
  - category を指定しなければ pokemon_tcg のみ (他は凍結)

## なぜ必要か
変換表を直しても products に焼いてある値は古いまま残る (契約 v1.2 §1-5 の restamp 方式)。
2026-08-21 に変換表を eBay の新マスタ (Game 別) へ合わせたので、その分を反映する。

実行:
  python tools/restamp_set_name_ebay.py                    # dry-run (既定)
  python tools/restamp_set_name_ebay.py --commit
  python tools/restamp_set_name_ebay.py --category all     # 全カテゴリ
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat()

MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")
GAME_OF = {"pokemon_tcg": "Pokémon TCG", "one_piece_tcg": "One Piece CCG",
           "dragonball_scg": "Dragon Ball Super Card Game"}
_EBAY_OK = {}


def _load_ebay_ok():
    """category -> eBay の Set 一覧 (Game 別)。格下げ禁止の判定に使う."""
    if _EBAY_OK:
        return
    node = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]["Set"]
    for cat, game in GAME_OF.items():
        _EBAY_OK[cat] = set(node["by_game"].get(game) or [])



SOURCE = "restamp_from_filter_map_20260821"

_BY_CODE = {}


def _own_code_values(category: str, product_id: str, specs: dict) -> set:
    """その商品の弾コードで始まる eBay 値 (監査 §0c と同じ引き方)."""
    sys.path.insert(0, str(ROOT / "tools"))
    import set_name_integrity_audit as _A  # noqa: E402
    if not _BY_CODE:
        for _cat, _vals in _EBAY_OK.items():
            d = {}
            for _v in _vals:
                m = _A._PREFIX_RE.match(_v)
                if m:
                    d.setdefault(_A._norm_code(m.group(1)), set()).add(_v)
            _BY_CODE[_cat] = d
    sc = _A._norm_code(_A.setcode_of(product_id, specs))
    return _BY_CODE.get(category, {}).get(sc, set())


def _is_other_set_value(category: str, product_id: str, specs: dict,
                        stored: str, derived: str) -> bool:
    """今の値が **別の弾のセット名** か (= 置き換えても格下げにならない).

    条件は監査 §0c と同じ: eBay に その弾自身の値が在るのに stored がそれでない。
    加えて derived が その弾の値であること (でなければ従来どおり守る)。
    ★stored がその弾自身の名前で始まる時は別商品なので対象外 (`S8a-P: …`)。
    """
    sys.path.insert(0, str(ROOT / "tools"))
    import set_name_integrity_audit as _A  # noqa: E402
    own = _own_code_values(category, product_id, specs)
    if not own or not derived:
        return False
    sc = _A.setcode_of(product_id, specs)
    if _A.names_own_setcode(stored, sc):
        return False
    return stored not in own and derived in own


def _abc_state(category: str, value) -> str:
    """契約 v1.2 §1-3 の 3 状態を返す (窓口 2026-08-21 の a/b/c と同じ)。

    (a) canonical … eBay master (Game 別) に在る値。code 形
    (b) free_text … master に無い。公式のセット名を自由文字列で維持
    (c) empty     … セット自体が不明 → 空 (derive が None = fail-closed)

    ★格下げ禁止・only-empty で触らなかった行も、行き先はこの3状態で数える。
      窓口が「a/b/c の内訳を出せ」と言っているのはこの分類 (2026-08-19_set_name_151_form_response.md)。
    """
    if not value:
        return "c"
    return "a" if value in _EBAY_OK.get(category, set()) else "b"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--only-empty", action="store_true",
                    help="今の値が空欄の行だけ埋める (既存値は一切上書きしない)")
    ap.add_argument("--category", default="pokemon_tcg",
                    help="'all' で全カテゴリ (既定: pokemon_tcg のみ。他は凍結)")
    args = ap.parse_args()

    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    if args.category == "all":
        rows = db.execute("SELECT id, category, product_id, set_name_official, specs FROM products "
                          "WHERE set_name_official IS NOT NULL")
    else:
        rows = db.execute("SELECT id, category, product_id, set_name_official, specs FROM products "
                          "WHERE category=? AND set_name_official IS NOT NULL", (args.category,))

    _load_ebay_ok()
    pairs, updates, skipped_none, kept = Counter(), [], 0, 0
    abc_now, abc_after = Counter(), Counter()   # 契約 v1.2 §1-3 の 3 状態 (窓口が要求した内訳)
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        stored = s.get("set_name_ebay") or ""
        derived = api.derive_set_name_ebay(r["category"], r["set_name_official"], r["product_id"])
        abc_now[_abc_state(r["category"], stored)] += 1
        # 既定の行き先は「触らない」= stored のまま。下で更新対象になった行だけ derived に替える。
        _final = stored
        if derived is not None and derived != stored:
            _demote = bool(stored) and stored in _EBAY_OK.get(r["category"], set())
            if not (_demote or (args.only_empty and stored)):
                _final = derived
        abc_after[_abc_state(r["category"], _final)] += 1
        if derived is None:
            skipped_none += 1
            continue
        if derived == stored:
            continue
        # ★格下げ禁止 (2026-08-22): 今の値が **既に eBay の一覧に在る** なら触らない。
        #   具体的なセット名を汎用のプロモ枠に落としても絞り込みは良くならず、情報だけ失う。
        #   例: SM-P-069 'Sm3h: to Have Seen the Battle Rainbow' (公式 拡張パック「闘う虹を見たか」)
        #       -> 'Sm-P: Sun & Moon Promos' は改悪。
        #   上書きしてよいのは 空欄 か 一覧外の値 のときだけ。
        #   ★例外 (2026-08-23): stored が **別の弾の値** なら格下げではない。
        #     `Sun & Moon - Team Up` は eBay の一覧に在るが英語版 SM9 の名前で、
        #     日本語版 SM9 (タッグボルト) の刷りには誤り (ルール③)。
        #     eBay に **その弾自身の値が在り**、derived がそれなら、置き換えは格上げ。
        #     判定は監査 §0c と同じ条件を使う (2つの面で条件がずれないように共有)。
        if stored and stored in _EBAY_OK.get(r["category"], set()) \
                and not _is_other_set_value(r["category"], r["product_id"], s,
                                            stored, derived):
            kept += 1
            continue
        # --only-empty: 空欄を埋めるだけ。既存値には触らない。
        #   ★変換表に推測 (REVIEW) 行が残っている間の安全弁。実例 (2026-08-22):
        #     set_code 'MC' -> 'Movie Promo' は誤りで、`スタートデッキ100 バトル
        #     コレクション` の 766行を塗り潰す。一覧外の値なので上の格下げ禁止では
        #     止まらない。
        if args.only_empty and stored:
            kept += 1
            continue
        pairs[(stored or "(空)", derived)] += 1
        s["set_name_ebay"] = derived
        s["set_name_ebay_source"] = SOURCE
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("=== set_name_ebay 焼き直し (%s / category=%s) ==="
          % ("APPLY" if args.commit else "DRY-RUN", args.category))
    print("変わる行 %d / %d 組   (derived が空で触らなかった行 %d)\n"
          % (len(updates), len(pairs), skipped_none))
    print("%-40s %-42s %s" % ("今の値", "引き直した値", "行数"))
    for (st, de), n in pairs.most_common(40):
        print("%-40s %-42s %d" % (st[:39], de[:41], n))
    if len(pairs) > 40:
        print("... 他 %d 組" % (len(pairs) - 40))

    # 契約 v1.2 §1-3 の 3 状態。窓口 2026-08-19_set_name_151_form_response.md が
    # 「a/b/c の内訳を出して一度止めろ」と指定した面。
    total = sum(abc_now.values())
    print("\n--- a/b/c 内訳 (%d 行) ---" % total)
    print("%-38s %8s %8s" % ("", "今", "引き直し後"))
    for k, label in (("a", "(a) canonical  eBay master に在る"),
                     ("b", "(b) 自由文字列 master に無い"),
                     ("c", "(c) 空         セット不明")):
        print("%-38s %8d %8d" % (label, abc_now[k], abc_after[k]))

    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("\n[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
