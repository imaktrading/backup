# -*- coding: utf-8 -*-
"""生きている出品で **KEY(AI列) が空** の行を、cert から埋める (2026-08-16)。

■ なぜ要るか
KEY を埋める処理は **その日のCSVに載っている行だけ**が対象だった (`dup_guard.backfill_keys`)。
出品時に取りこぼした行は、その後どこからも拾われず **永久に空のまま**残る。
KEY が空だと:
  - 補URL探索が「探索不能(card番号が取れない)」で毎晩スキップする
  - 重複チェック(同じカードの二重出品)が効かない
実測 (2026-08-16): 生きている TCG 出品で KEY 空が 13件。うち **12件は cert から引ける**。

■ 目視は要らない
ここで使う `canonical_pid_for_cert` は **出品時に人が目視で確定した値**。
シートに写していないだけなので、もう一度見ても同じ答えにしかならない。
引けない cert だけが本当の目視待ち。

■ fail-closed
- cert から確定値が引けない → 書かない
- product_id が複数カテゴリに実在する (OP と Gundam は同じ set-code 体系) → 書かない
- 既に KEY が入っている行は触らない (上書きしない)
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import dup_guard                                   # noqa: E402  (catalog_categories を再利用)
import sheet_io                                    # noqa: E402

B = sheet_io.PRODUCT_COL_ITEMID if hasattr(sheet_io, "PRODUCT_COL_ITEMID") else 1
SOLD = 3            # D 売り切れ
CERT = sheet_io.PRODUCT_COL_CERT
KEY = sheet_io.PRODUCT_COL_KEY
CAT = 17            # R カテゴリ ('TCG' が PSA)


def _cell(r, i):
    return ((r[i] if len(r) > i else "") or "").strip()


def find_targets(vals, category="TCG"):
    """KEY が空の live 行 → [{row, itemID, cert, title}] (純関数)。

    live = itemID あり かつ 売り切れ印なし。cert が無い行は cert から引けないので除く。
    """
    out = []
    for n, r in enumerate(vals[1:], start=2):
        if _cell(r, CAT) != category:
            continue
        if not _cell(r, B) or _cell(r, SOLD) or _cell(r, KEY):
            continue
        if not _cell(r, CERT):
            continue
        out.append({"row": n, "itemID": _cell(r, B), "cert": _cell(r, CERT),
                    "title": _cell(r, 2)})
    return out


def plan(targets, pid_of, categories_of):
    """cert → KEY の書込計画 (純関数)。戻り: (計画, 引けなかった, カテゴリ曖昧)。

    pid_of(cert) -> product_id / categories_of([pid]) -> {pid: [category,...]}
    """
    pids = {}
    unresolved = []
    for t in targets:
        pid = (pid_of(t["cert"]) or "").strip()
        if pid:
            pids[t["cert"]] = pid
        else:
            unresolved.append(t)
    cats = categories_of(list(pids.values())) if pids else {}
    ok, ambiguous = [], []
    for t in targets:
        pid = pids.get(t["cert"])
        if not pid:
            continue
        c = sorted(set(cats.get(pid) or []))
        if len(c) == 1:
            ok.append({**t, "key": f"{c[0]}:{pid}", "pid": pid})
        elif len(c) > 1:
            ambiguous.append({**t, "pid": pid, "categories": c})
        else:
            unresolved.append({**t, "pid": pid})       # catalog に無い = 決められない
    return ok, unresolved, ambiguous


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="書かずに件数だけ出す")
    ap.add_argument("--category", default="TCG")
    a = ap.parse_args()

    from listing_common import canonical_pid_for_cert

    vals = sheet_io._product_ws().get_all_values()
    targets = find_targets(vals, a.category)
    print(f"▶ KEY が空の live 出品: {len(targets)}件 ({a.category})")
    if not targets:
        return
    ok, unresolved, ambiguous = plan(targets, canonical_pid_for_cert,
                                     dup_guard.catalog_categories)
    for t in ok:
        print(f"  + row{t['row']} cert={t['cert']} → KEY='{t['key']}'  {t['title'][:34]}")
    for t in ambiguous:
        print(f"  ⚠ row{t['row']} cert={t['cert']} '{t['pid']}' は {t['categories']} "
              f"の複数カテゴリに実在 → 書かない")
    for t in unresolved:
        print(f"  ⏭ row{t['row']} cert={t['cert']} 確定値が引けない → **目視待ち**  "
              f"{t['title'][:34]}")
    if a.dry_run:
        print(f"🧪 DRY-RUN: 書込なし (書ける {len(ok)}件 / 目視待ち {len(unresolved)}件 / "
              f"曖昧 {len(ambiguous)}件)")
        return
    n = 0
    if ok:
        n = sheet_io.write_keys({t["itemID"]: t["row"] for t in ok},
                                {t["itemID"]: t["key"] for t in ok})
    print(f"✅ KEY 書込 {n}件 / 目視待ち {len(unresolved)}件 / 曖昧 {len(ambiguous)}件")
    if unresolved:
        print("   目視待ちは PSA再仕入れ照合 or カタログ登録で解消します")


if __name__ == "__main__":
    main()
