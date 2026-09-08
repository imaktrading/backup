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
F, M = 5, 12                      # F=商品価格 / M=現在価格 (2枚目行の値段)
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


# ★2026-09-08 (監視くん→HQ 2026-09-08_hoju_url_dead_on_arrival / ユーザーGO):
#   補URL に **書いた時点で既に死んでいる URL** が入っていた。従来のゲートは候補行の
#   D列(仕入元 売り切れ)しか見ておらず、この列は **監視くんの巡回でしか更新されない**。
#   23:30 の書込み時点で古ければ、死んだURLがそのまま入る。
#   補URLは「主が売れた時に買う先」なので、死んでいると意味がない。
#   → 2段で見る: ① 既に「買えない」と分かっている台帳で落とす (無料)
#                ② 残りは詳細ページをその場で開いて確かめる (--no-verify で無効化)
def drop_known_dead(urls):
    """「買えない」と分かっている URL を落とす (I/O。台帳が読めなければ素通し)。

    戻り: (残す, 落とした[(url, 理由)])
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import mercari_psa_resource as mp
        dead = mp.load_not_buyable() or {}
    except Exception:                                          # noqa: BLE001
        return list(urls or []), []
    keep, drop = [], []
    for u in (urls or []):
        hit = dead.get(u) or dead.get((u or "").strip())
        (drop.append((u, (hit or {}).get("why", "買えない台帳に在り")))
         if hit else keep.append(u))
    return keep, drop


def verify_alive(urls, verbose=True):
    """詳細ページを開いて **今そのまま買えるか**を確かめる (I/O)。

    戻り: (生きている, 死んでいる[(url, 理由)])。
    driver を起こせない / 例外は **落とさない** (fail-open。書込み自体は今までどおり)。
    買えないと分かったURLは台帳に覚えるので、次回は無料で落ちる。
    """
    urls = list(urls or [])
    if not urls:
        return [], []
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import mercari_psa_resource as mp
        drv = mp.new_scrape_driver()
    except Exception as e:                                     # noqa: BLE001
        if verbose:
            print(f"  ⚠ 在庫のその場確認は skip ({type(e).__name__}) — 今までどおり書きます")
        return urls, []
    alive, dead = [], []
    try:
        for u in urls:
            try:
                drv.get(u)
                import time as _t
                _t.sleep(3)
                ok = mp.buyable_from_detail(drv.page_source)
            except Exception as e:                             # noqa: BLE001
                if verbose:
                    print(f"  ⚠ {u[:50]} 開けず ({type(e).__name__}) → 落とさない")
                alive.append(u)
                continue
            if ok:
                alive.append(u)
            else:
                dead.append((u, "詳細ページで『買えない』(売切/オークション)"))
                mp.remember_not_buyable(u, "補URL書込み直前の確認で売切/オークション")
    finally:
        try:
            drv.quit()
        except Exception:                                      # noqa: BLE001
            pass
    return alive, dead


def price_by_url_from_cache():
    """{正規化URL: 価格} を 補URL探索キャッシュから作る (I/O。読めなければ空)。

    ★2026-09-07 ユーザー指示「満杯で捨てるのは徒労。修正して」。
      目視 (`psa_hoju_fill`) は既に **安い順に5本へ持ち直す**が、この自動追記は
      満杯なら新しい供給を捨てていた (実測: 1走行で23本 溢れ)。同じ考え方に揃える。
      値段は目視と同じキャッシュから取る (二重定義しない)。
    """
    out = {}
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import psa_hoju_fill as _H
        for entry in (_H._load_cache() or {}).values():
            m = (entry or {}).get("mercari") or {}
            if not isinstance(m, dict):
                continue
            for key in ("cands", "all_cands", "loose_cands"):
                for row in (m.get(key) or []):
                    if row and len(row) > 1 and row[1]:
                        n = _norm(row[1])
                        if n and n not in out:
                            try:
                                out[n] = float(row[0])
                            except (TypeError, ValueError):
                                pass
            # ★snkrdunk 側も入れる。既存の補URLは snkrdunk が多く、ここを見ないと
            #   「値段が比べられない」で入替が一度も起きない (2026-09-07 実測: 23本全部)。
            sd = (entry or {}).get("snkrdunk") or {}
            for lst in (sd.get("psa10_listings") or []):
                u = (lst or {}).get("url")
                if not u:
                    continue
                n = _norm(u)
                if n and n not in out:
                    try:
                        out[n] = float(lst.get("price"))
                    except (TypeError, ValueError):
                        pass
    except Exception:                                          # noqa: BLE001
        return {}
    return out


def row_price(r):
    """2枚目行の出品価格 (M=現在価格 → F=商品価格 の順)。取れなければ None (純関数)。

    ★N(仕入値)は使わない。既存枠の値段は **出品価格** なので、揃えないと比較にならない
      (N はポイント還元を引いた後の値)。
    """
    import re as _re
    for col in (M, F):
        v = _cell(r, col)
        d = _re.sub(r"[^0-9]", "", str(v or ""))
        if d:
            return float(d)
    return None


def plan_replacement(existing, url, prices, aux_max=None, new_price=None):
    """満杯の補URL枠に、**より安い**新URLを入れる時の並び (純関数, test可)。

    戻り: (full, removed) / 入れ替えない時は (None, [])。
    押し出してよいのは **値段が分かっていて、新URLより高い** 既存だけ。
      値段が分からない既存を押し出すと「もっと安いかもしれない供給」を根拠なく捨てる。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from psa_hoju_fill import rank_backurls, AUXN as _AUXN
    except Exception:                                          # noqa: BLE001
        return None, []
    aux_max = aux_max or _AUXN
    new_p = new_price if new_price is not None else (prices or {}).get(_norm(url))
    if new_p is None:
        return None, []                   # 新URLの値段が分からない = 比べられない
    prices = dict(prices or {})
    prices[_norm(url)] = new_p            # 行の値段を使う (キャッシュに無いことが多い)
    full, added, removed = rank_backurls(existing, [url], prices, aux_max)
    if not added or not removed:
        return None, []
    for u in removed:
        old_p = (prices or {}).get(_norm(u))
        if old_p is None or old_p <= new_p:
            return None, []               # 根拠なく押し出さない
    return full, removed


def compute_additions(vals, live_ids=None, prices=None):
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
            _cur = (d.get("full") or (existing + d["add"]))[:AUXN]
            _full, _removed = plan_replacement(_cur, url, prices, new_price=row_price(r))
            if _full:
                d["full"] = _full
                d["add"].append(url)
                d.setdefault("replaced", []).extend(_removed)
                assigned.add(url)
                warns.append(f"row {prow}(itemID={_cell(pr,B)}) 補URL満杯(5) → "
                             f"**より安いので入替** {_removed} を外して url={url} を入れた")
            else:
                _np = row_price(r) if row_price(r) is not None else (prices or {}).get(_norm(url))
                _known = [(prices or {}).get(_norm(u)) for u in _cur]
                if _np is None:
                    _why = "新しい方の値段が分からない"
                elif all(x is not None for x in _known):
                    _why = f"既存5本の方が安い (新 ¥{int(_np):,} / 既存 最高 ¥{int(max(_known)):,})"
                else:
                    _why = "既存に値段の分からない枠がある (根拠なく押し出さない)"
                warns.append(f"row {prow}(itemID={_cell(pr,B)}) 補URL満杯(5) → url={url} "
                             f"入れず ({_why})")
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
    prices = price_by_url_from_cache()
    plan, warns = compute_additions(vals, live_ids, prices)
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
    # ★2026-09-08: 書く直前に「今 買えるか」を確かめる (死んだURLを補URLに入れない)。
    #   ① 台帳で無料で落とす → ② 残りを詳細ページで確認 (--no-verify で②を無効化)
    if do_write and plan:
        _cands = sorted({u for v in plan.values() for u in v["add"]})
        _keep, _known = drop_known_dead(_cands)
        _dead = list(_known)
        if "--no-verify" not in sys.argv:
            _keep, _live_dead = verify_alive(_keep)
            _dead += _live_dead
        if _dead:
            print(f"  🚫 死んでいる仕入元を {len(_dead)}本 落としました (補URLに入れない)")
            for u, why in _dead[:10]:
                print(f"     - {u[:60]} … {why}")
        _alive = set(_keep)
        for v in plan.values():
            v["add"] = [u for u in v["add"] if u in _alive]
            if v.get("full"):
                v["full"] = [u for u in v["full"] if u in _alive or u in v["existing"]]
    if do_write:
        row_to_urls = {row: (v.get("full") or (v["existing"] + v["add"]))[:AUXN]
                       for row, v in plan.items() if v["add"]}
        # ★2026-09-08 ユーザー指示「勝手に補に追加するルートは閉じて、必ず目視を通る様にして」。
        #   この経路は **KEY が一致する行**から URL を配るが、元の行の KEY が誤っていれば
        #   誤った版を配る (KEY 取り違えは 2026-09-07 に実在。同じ番号の別版は商品名で
        #   見分けが付かない)。実害3件はすべて買い手の問い合わせで発覚した。
        #   → シートには書かず、目視待ちに積む。AUX_AUTO_WRITE=1 で従来動作に戻せる。
        if os.environ.get("AUX_AUTO_WRITE") != "1":
            import aux_pending
            item_of = {row: v.get("itemid", "") for row, v in plan.items()}
            existing_by_row = {row: v.get("existing") or [] for row, v in plan.items()}
            n_q = aux_pending.queue({row: [u for u in v["add"]] for row, v in plan.items()
                                     if v["add"]},
                                    source="2枚目の自動追記",
                                    existing_by_row=existing_by_row, item_of=item_of)
            print(f"=== 書込は行いません (2026-09-08 ユーザー指示)。"
                  f"目視待ちに {n_q}本 積みました ===")
            print("   人が採否を決めます: python aux_pending.py で中身を確認")
            _record(0, total_add, urgent, len(warns), unverified=0)
            return
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
