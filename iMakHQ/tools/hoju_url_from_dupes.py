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


def _norm(url):
    """URL の表記ゆれを吸収して突合キーにする (純関数)。

    dup_guard と同じ正規化を使う (「共有している」の判定が2か所でズレると意味がない)。
    読めない時は小文字化 + 末尾スラッシュ落としだけの素朴な正規化に落とす。
    """
    u = (url or "").strip()
    if not u:
        return ""
    try:
        import dup_guard
        return dup_guard.norm_url(u) or ""
    except Exception:                                          # noqa: BLE001
        return u.split("?")[0].rstrip("/").lower()


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
    # ★2026-09-06: **他の出品が既に使っている仕入元**は足さない。
    #   従来のガード (assigned) は *その走行の中だけ* で、既にシートに入っている分を
    #   見ていなかった。付ける先の行の中身しか照合しないので、日をまたぐと同じURLが
    #   2出品に付く。実害: m80392401851 が 820034256174 と 820034337348 の両方の
    #   補URLに入り、dup_guard が「★① 仕入元URL共有 = 両方売れたら履行不能」と検出。
    #   出品済(B非空)の行の A列 + 補URL列を、URL の持ち主として先に押さえる。
    owner_by_url = {}
    for i, r in enumerate(vals[1:], start=2):
        iid = _cell(r, B)
        if not iid:
            continue                      # 未出品の行は枠を押さえない (これから使う側)
        for u in [_cell(r, A)] + [_cell(r, AUX0 + k) for k in range(AUXN)]:
            n = _norm(u)
            if n:
                owner_by_url.setdefault(n, set()).add(iid)
    plan, warns, assigned = {}, [], set()
    for i, r in enumerate(vals[1:], start=2):
        iid, url, cert, key, sold = _cell(r, B), _cell(r, A), _cell(r, I), _cell(r, KEY), _cell(r, D)
        # 2枚目 = B空 + url/cert/KEY有。sold(D='○')の 2枚目 = 供給が死んでる → 補URLに入れない。
        if iid or sold or not url or not cert or not key or key.startswith(("item:", "shops:")):
            continue
        primaries = live_by_key.get(key, [])
        if not primaries:
            continue
        if url in assigned:
            continue          # 1本の仕入元を2出品に付けない (両方売れたら片方 履行不能)
        prow, pr = pick_primary(primaries, plan)
        # 既に **別の出品** が使っている仕入元なら足さない (走行をまたいだ共有を防ぐ)
        _own = owner_by_url.get(_norm(url), set()) - {_cell(pr, B)}
        if _own:
            warns.append(f"url={url} は既に他の出品 {sorted(_own)} が使用中 → 足さない "
                         f"(1本の仕入元を2出品に付けると両方売れた時に履行不能)")
            continue
        if len(primaries) > 1:
            warns.append(f"KEY={key} live出品 {len(primaries)}件 → row {prow} に付けた "
                         f"(渇いている順 / 2枚目 cert={cert})")
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
            assigned.add(url)
    return plan, warns


def pick_primary(primaries, plan):
    """同じカードの live 出品が複数ある時、**1つだけ**選ぶ (純関数)。

    ★2026-08-18: 以前は「どちらに付けるか決められない」として丸ごと skip していた。
      その結果、生きた仕入元を1本捨てていた (49種が該当)。
      **付けないより、渇いている方に付ける方が良い**。

    選ぶ順 (上から):
      1. 仕入元が死んでいる出品 (= 今まさに供給ゼロ)
      2. 予備の少ない出品
      3. 行番号の小さい方 (毎回同じ答えになるように)

    **全部には付けない**。1本の仕入元を2出品の予備にすると、両方売れた時に片方が
    履行不能になる (dup_guard が消して回っているのと同じ状態を自分で作ることになる)。
    """
    def rank(pr_):
        row, r = pr_
        n_aux = len(plan.get(row, {}).get("add", [])) + sum(
            1 for k in range(AUXN) if _cell(r, AUX0 + k))
        return (0 if _cell(r, D) else 1, n_aux, row)
    return min(primaries, key=rank)


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
        missing = verify_written(row_to_urls)
        if missing:
            # ★2026-08-18: 書込の戻り値を信じない。実測で「16行 完了」と出たのに
            #   1行分が入っていなかった (row 1341)。事後確認が無いので誰も気づけなかった。
            #   規約「送った後に実状態を verify し、漏れは同サイクル内で完結」に合わせる。
            print(f"⚠️ 書けていない行 {len(missing)}件 → もう一度書きます")
            sheet_io.write_aux_urls({row: row_to_urls[row] for row in missing})
            missing = verify_written({row: row_to_urls[row] for row in missing})
        print(f"=== 実書込 完了: {n} 行 (既存保持+新規追加)"
              + (f" / ⚠️**{len(missing)}行は書けていません (要対応)**" if missing else " / 全行 確認済")
              + " ===")
        for row in missing:
            print(f"  ⚠️ row {row}: {row_to_urls[row]}")
        _record(n, total_add, urgent, len(warns), unverified=len(missing))
    else:
        print("=== dry-run 終了(書込なし)。実書込は --write ===")


def diff_written(intended, actual):
    """書いたつもり vs 実際 → 入っていない行番号 (純関数)。

    ★2026-08-18: 「書込 完了 16行」と出たのに 1行分が実際には入っていなかった。
      戻り値は「API を呼んだ数」であって「入った数」ではない。実物を読んで確かめる。
    """
    out = []
    for row, urls in (intended or {}).items():
        have = set(actual.get(row) or [])
        if [u for u in urls if u and u not in have]:
            out.append(row)
    return sorted(out)


def verify_written(row_to_urls):
    """シートを読み直して、入っていない行を返す (I/O)。読めなければ空 (= 判定不能)。"""
    if not row_to_urls:
        return []
    try:
        vals = sheet_io._product_ws().get_all_values()
    except Exception:                                          # noqa: BLE001
        return []
    actual = {}
    for row in row_to_urls:
        r = vals[row - 1] if 0 < row <= len(vals) else []
        actual[row] = [u for u in (_cell(r, AUX0 + k) for k in range(AUXN)) if u]
    return diff_written(row_to_urls, actual)


def _record(rows, added, urgent, warns, unverified=0):
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
                       "urgent_supply_dead": urgent, "warns": warns,
                       "unverified": unverified}, f, ensure_ascii=False, indent=2)
    except Exception:                                          # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
