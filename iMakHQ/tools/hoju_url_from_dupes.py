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


def compute_additions(vals, live_ids=None):
    """(pure) rows2d(header含む) → (plan, warns)。I/O 無しで test 可能。

    plan = {primary_row(1-indexed): {'itemid','existing','add','skip','supply_dead'}}。
    2枚目 = B空 AND url非空 AND cert非空 AND KEY非空 AND その KEY が出品中(B非空)行を持つ。
    add = 2枚目URL が primary の既存補URL(AC-AG)に無く、空き枠がある時のみ。

    ★2026-08-18: primary の条件から **D(売り切れ)が空** を外した。
      D は **仕入元** が売り切れた印であって、eBay の出品が終わった印ではない。
      外すまでは「eBay に出ているのに仕入元が死んでいる」出品にだけ新しい供給を
      足せなかった。**そこが一番足すべき相手**だった (売れたら仕入不能 →
      キャンセル → Defect Rate)。
      実測 2026-08-18: `pokemon_tcg:SMP2-014` (itemID 358738073108) と
      `pokemon_tcg:SV8a-203` (358683996599) はどちらも eBay live で D=○。
      同じカードの生きた仕入元をその日に見つけていたのに、この条件で捨てていた。
      2枚目側の D 判定はそのまま残す (死んだURLを足しても意味がない)。

    live_ids: eBay に live な itemID の集合 (dup_guard の live cache = SSOT)。
      渡された場合はこれで primary を絞る。None なら itemID のある行を primary とみなす
      (cache が無くても止めない。補URL を足す行為自体は無害なので fail-open で良い)。
    """
    live_by_key = {}
    for i, r in enumerate(vals[1:], start=2):
        iid, key = _cell(r, B), _cell(r, KEY)
        if not (iid and key) or key.startswith(("item:", "shops:")):
            continue
        if live_ids is not None and iid not in live_ids:
            continue                      # eBay に無い = 出品が終わっている → 足す先でない
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
        d = plan.setdefault(prow, {"itemid": _cell(pr, B), "existing": existing,
                                   "add": [], "skip": [],
                                   # primary の仕入元が死んでいる = 補充が最優先の行
                                   "supply_dead": bool(_cell(pr, D))})
        if url in existing:
            d["skip"].append(url)
        elif len(existing) + len(d["add"]) >= AUXN:
            warns.append(f"row {prow}(itemID={_cell(pr,B)}) 補URL満杯(5) → url={url} 溢れ(売切上書きは未実装)")
        elif url not in d["add"]:
            d["add"].append(url)
    return plan, warns


def load_live_ids():
    """eBay に live な itemID の集合。取れなければ None (= 絞り込まない)。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import dup_guard
        with open(dup_guard.LIVE_CACHE, encoding="utf-8") as f:
            import json
            return set((json.load(f).get("titles") or {}).keys()) or None
    except Exception:                                          # noqa: BLE001
        return None


def main():
    do_write = "--write" in sys.argv
    vals = sheet_io._product_ws().get_all_values()
    live_ids = load_live_ids()
    plan, warns = compute_additions(vals, live_ids)
    mode = "実書込" if do_write else "dry-run"
    total_add = sum(len(v["add"]) for v in plan.values())
    urgent = sum(len(v["add"]) for v in plan.values() if v["add"] and v.get("supply_dead"))
    print(f"=== 補URL 追記 [{mode}] (2枚目→primary補URL・既存保持+冪等) ===")
    print(f"シート行数 {len(vals)} / live判定 "
          f"{'eBay実在 ' + str(len(live_ids)) + '件' if live_ids else '(cache無し=itemIDのある行すべて)'}")
    print(f"追加対象primary {sum(1 for v in plan.values() if v['add'])}行 / 追加URL {total_add}"
          + (f" / うち **仕入元が死んでいる出品への補充 {urgent}本**" if urgent else ""))
    for row, v in sorted(plan.items()):
        if v["add"]:
            mark = " 🚨仕入元切れ" if v.get("supply_dead") else ""
            print(f"  row {row} (itemID={v['itemid']}){mark}: 既存{len(v['existing'])}件 → 追加 {v['add']}")
    for w in warns[:30]:
        print("  ⚠️", w)
    if do_write:
        row_to_urls = {row: (v["existing"] + v["add"])[:AUXN] for row, v in plan.items() if v["add"]}
        n = sheet_io.write_aux_urls(row_to_urls)
        print(f"=== 実書込 完了: {n} 行 (既存保持+新規追加) ===")
        _record(n, total_add, urgent, len(warns))
    else:
        print("=== dry-run 終了(書込なし)。実書込は --write ===")


def _record(rows, added, urgent, warns):
    """走行結果を1ファイルに残す (最新で上書き)。

    ★2026-08-18: この step は出品くんの画面にしか出ず、**走ったのか止まったのかを
      後から誰も確認できなかった**。実際 22本が溜まったまま気づかれていなかった。
      書けなくても本処理は成功しているので、失敗しても黙って続ける。
    """
    try:
        import json
        from datetime import datetime
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "review_logs", "hoju_from_dupes_last.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"at": datetime.now().isoformat(timespec="seconds"),
                       "rows": rows, "added": added,
                       "urgent_supply_dead": urgent, "warns": warns}, f,
                      ensure_ascii=False, indent=2)
    except Exception:                                          # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
