#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補URL 自動追記: 重複くんが弾く「同KEY既出品の2枚目」の A列URL(実在の別個体)を、
同KEー primary(出品中) の 補URL(AC-AG) に **既存を保ったまま冪等追加** する。

- 既存補URL(SNKRDUNK/Mercari 由来)は消さず、2枚目URLが未収載なら空き枠に足す(冪等)。
- primary = 同KEー AND B(itemID)非空 AND D(sold)空。複数live は曖昧 → skip(警告)。
- 満杯(5枠)時は溢れ警告のみ(= 売り切れ補URLの上書きは未実装。TODO: 監視くん per-URL 在庫確認と連携)。
- 実行: python -m tools.hoju_url_from_dupes [--write]   (iMakHQ 直下、既定=dry-run)
- 出品くん(control_panel)が write-keys の直後に --write で自動実行。

列(0-indexed): A0=url / B1=itemID / D3=sold / I8=cert / AC28..AG32=補URL / AI34=KEY
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools/
import sheet_io

A, B, D, I, KEY = 0, 1, 3, 8, sheet_io.PRODUCT_COL_KEY   # 34
AUX0, AUXN = sheet_io.PRODUCT_COL_AUX_START, sheet_io.PRODUCT_AUX_MAX  # 28, 5


def _cell(row, idx):
    return (row[idx].strip() if len(row) > idx else "")


def compute_additions(vals):
    """(pure) rows2d(header含む) → (plan, warns)。I/O 無しで test 可能。

    plan = {primary_row(1-indexed): {'itemid','existing','add','skip'}}。
    2枚目 = B空 AND url非空 AND cert非空 AND KEY非空 AND その KEY が live(B非空 D空)行を持つ。
    add = 2枚目URL が primary の既存補URL(AC-AG)に無く、空き枠がある時のみ。
    """
    live_by_key = {}
    for i, r in enumerate(vals[1:], start=2):
        iid, key, sold = _cell(r, B), _cell(r, KEY), _cell(r, D)
        if iid and key and not key.startswith(("item:", "shops:")) and not sold:
            live_by_key.setdefault(key, []).append((i, r))
    plan, warns = {}, []
    for i, r in enumerate(vals[1:], start=2):
        iid, url, cert, key, sold = _cell(r, B), _cell(r, A), _cell(r, I), _cell(r, KEY), _cell(r, D)
        # 2枚目 = B空 + url/cert/KEY有。sold(D='○')の 2枚目 = 供給が死んでる → 補URLに入れない。
        if iid or sold or not url or not cert or not key or key.startswith(("item:", "shops:")):
            continue
        primaries = live_by_key.get(key, [])
        if not primaries:
            continue
        if len(primaries) > 1:
            warns.append(f"KEY={key} live primary 複数({len(primaries)}) → 曖昧skip (2枚目 cert={cert})")
            continue
        prow, pr = primaries[0]
        existing = [u for u in (_cell(pr, AUX0 + k) for k in range(AUXN)) if u]
        d = plan.setdefault(prow, {"itemid": _cell(pr, B), "existing": existing, "add": [], "skip": []})
        if url in existing:
            d["skip"].append(url)
        elif len(existing) + len(d["add"]) >= AUXN:
            warns.append(f"row {prow}(itemID={_cell(pr,B)}) 補URL満杯(5) → url={url} 溢れ(売切上書きは未実装)")
        elif url not in d["add"]:
            d["add"].append(url)
    return plan, warns


def main():
    do_write = "--write" in sys.argv
    vals = sheet_io._product_ws().get_all_values()
    plan, warns = compute_additions(vals)
    mode = "実書込" if do_write else "dry-run"
    total_add = sum(len(v["add"]) for v in plan.values())
    print(f"=== 補URL 追記 [{mode}] (2枚目→primary補URL・既存保持+冪等) ===")
    print(f"シート行数 {len(vals)} / 追加対象primary {sum(1 for v in plan.values() if v['add'])}行 / 追加URL {total_add}")
    for row, v in sorted(plan.items()):
        if v["add"]:
            print(f"  row {row} (itemID={v['itemid']}): 既存{len(v['existing'])}件 → 追加 {v['add']}")
    for w in warns[:30]:
        print("  ⚠️", w)
    if do_write:
        row_to_urls = {row: (v["existing"] + v["add"])[:AUXN] for row, v in plan.items() if v["add"]}
        n = sheet_io.write_aux_urls(row_to_urls)
        print(f"=== 実書込 完了: {n} 行 (既存保持+新規追加) ===")
    else:
        print("=== dry-run 終了(書込なし)。実書込は --write ===")


if __name__ == "__main__":
    main()
