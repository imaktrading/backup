# -*- coding: utf-8 -*-
"""PSA 補URL 能動充填 — Phase1 slice1(対象抽出) + slice2(夜間検索)。

設計: discussion/2026-07-24_psa_hoju_url_replenishment_design.md。
出品中で補URL が薄い PSA を拾い、夜間検索→昼確認で補URL を厚くする(live維持率↑)。

slice1 = 対象抽出(read-only)。
  select_backfill_targets: HIGH rows2d(header含む) → 補<閾値の live PSA 行 [{...}]。純関数(test可)。

slice2 = 夜間検索(無人・throttle・キャッシュ書込のみ。補URL書込は slice3=昼確認)。
  対象リストを検索プリミティブ(mercari_psa_resource / snkrdunk_psa_resource + combine 用素材)で叩き、
  候補+画像を psa_research_cache.json(itemIDキー・RESTOCK ゲートと共有)へ throttle 書込。
  = 昼の確認(slice3)と RESTOCK ゲートが同日キャッシュを即再利用できる(再スクレイプ/BAN 回避)。
  pure: targets_needing_search / merge_search_result(fail-closed mercari 除外)/ _entry_complete。
  impure: run_night_search(HIGH読込→対象抽出→検索→増分キャッシュ書込)。書込は補URL列に触れない。

対象条件(slice1):
  - B(itemID) 非空   = 出品中(listed)
  - D(売り切れ) 空   = live(取下げられてない)
  - I(cert#) 数値    = PSA(TCG)。※他カテゴリ(Tシャツ等)混入を弾く確実な signal
  - 補URL(AC-AG) 実数 < max_backups
  - KEY(AI) or cert あり = 供給検索の起点が要る
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io

A, B, C, D, CERT = 0, 1, 2, 3, sheet_io.PRODUCT_COL_CERT          # 0,1,2,3,8
CATEGORY = 17                                                      # R (カテゴリ。'TCG' が PSA)
KEY = sheet_io.PRODUCT_COL_KEY                                     # 34
AUX0, AUXN = sheet_io.PRODUCT_COL_AUX_START, sheet_io.PRODUCT_AUX_MAX  # 28, 5
HIGH_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
HIGH_GID = 851100680


def _cell(row, idx):
    return (row[idx].strip() if len(row) > idx else "")


def _is_cert(s):
    """PSA cert# = 数字のみ(TCG の確実 signal。他カテゴリ混入を弾く)。"""
    s = (s or "").strip()
    return bool(s) and s.isdigit()


def _backup_count(row):
    return sum(1 for k in range(AUXN) if _cell(row, AUX0 + k))


def select_backfill_targets(rows2d, max_backups=1):
    """HIGH rows2d(header含む) → 補<max_backups の live PSA 行リスト。純関数(test可)。

    max_backups=1 → 補 0本のみ(残1件でリフィル=定常の既定)。
    初期一括は呼び手が大きめ(例 5)を渡して「満杯未満すべて」を対象にできる。
    Returns: [{row(1-indexed), itemID, cert, key, card_no_title, n_backups, empty_slots}]
    """
    out = []
    for i, r in enumerate(rows2d[1:], start=2):
        iid = _cell(r, B)
        cert = _cell(r, CERT)
        if not iid:                     # 未出品 = 対象外(補は live 出品の延命策)
            continue
        if _cell(r, D):                 # 売り切れ(取下げ済) = 対象外
            continue
        if _cell(r, CATEGORY) != "TCG":  # R列=カテゴリ。PSA は 'TCG'(psa_to_csv と同じ絞り込み)
            continue
        if not _is_cert(cert):          # cert 数値でない = PSA でない = 対象外(二重ガード)
            continue
        nb = _backup_count(r)
        if nb >= max_backups:           # 既に閾値以上の補あり = 対象外
            continue
        key = _cell(r, KEY)
        if not key and not cert:        # 供給検索の起点なし = skip(fail-closed)
            continue
        out.append({
            "row": i, "itemID": iid, "cert": cert, "key": key,
            "title": _cell(r, C), "n_backups": nb, "empty_slots": AUXN - nb,
        })
    return out


def _read_high():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        sheet_io.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(HIGH_SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.id == HIGH_GID), None)
    return ws.get_all_values()


# ---------------------------------------------------------------------------
# slice2: 夜間検索(無人)。検索プリミティブで対象を叩き psa_research_cache へ書込。
# ---------------------------------------------------------------------------
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psa_research_cache.json")


def _card_no_from_key(key):
    """canonical KEY → 検索用 card番号(変種suffix除去)。gate `_key_card_number` と同一規約(純関数)。

    title に番号が出ない Pokemon 等(KEY=SV8a-093 / M2a-198)の供給源。url-key(item:/shops:)・
    数字を含まない値は "" (fail-closed)。build_card_query は title だけ見て空を返すため、slice2 は
    これで KEY を補い両チャネルを起動する(build_card_query 本体は gate 共用なので触らない)。
    """
    k = (key or "").strip()
    if not k or k.startswith(("item:", "shops:")):
        return ""
    base = k.split("_")[0].strip().upper()
    return base if any(ch.isdigit() for ch in base) else ""


def build_search_query(target, mp):
    """1対象 → 検索クエリ(build_card_query + KEYフォールバック)。card_no 空なら kw も空(=探索不能)。

    build_card_query(gate共用)が title 由来 card_no を空で返したら KEY 由来番号で補い、kw を
    'PSA10 <name_jp> <card_no>' で再構成。snkrdunk も同じ card_no を使う。純ロジック(mp はDB引き用)。
    """
    q = mp.build_card_query(target.get("title", ""), "", target.get("key") or None)
    if not q.get("card_no"):
        cn = _card_no_from_key(target.get("key"))
        if cn:
            q["card_no"] = cn
            nj = q.get("name_jp")
            q["kw"] = f"PSA10 {nj} {cn}" if nj else f"PSA10 {cn}"
    return q


def _mercari_errored(m):
    """メルカリ取得が「取れなかった(_error)」= 在庫確定でない(純関数)。

    gate と同じ fail-closed 判定。errored は「在庫なし」と区別し、キャッシュに焼き付けない
    (次夜に再取得。取れなかっただけを『無い』にしない)。
    """
    return isinstance(m, dict) and bool(m.get("_error"))


def _entry_complete(entry, today):
    """当日キャッシュ済で mercari/snkrdunk 両方揃ってるか(純関数)= 再検索不要判定。

    - date が今日でない → 未検索扱い(再取得)。
    - mercari 欠落(= errored で焼かれてない or 未検索) → 未完了(再取得)。
    - 両キー在れば value=None(在庫なし確定)でも完了扱い。
    """
    return (isinstance(entry, dict) and entry.get("date") == today
            and "mercari" in entry and "snkrdunk" in entry)


def targets_needing_search(targets, cache, today):
    """当日まだ検索し切れてない対象だけ返す(純関数・レジューム耐性)。

    補URL自体がレジューム状態(埋まればクエリから外れる)だが、夜間検索の中断耐性のため
    「当日キャッシュ完了」も skip 条件にする(同夜の再実行で残りだけ叩く)。
    """
    return [t for t in targets if not _entry_complete(cache.get(t.get("itemID")), today)]


def merge_search_result(cache, iid, mercari, snkrdunk, today):
    """検索結果を1件分キャッシュへマージ(純関数・fail-closed)。

    gate(psa_resource_gate)と同一規約: errored メルカリはキャッシュしない(mercari キー付けない)
    → 未完了のまま次夜に再取得。snkrdunk は card_not_found 含め設定値として保存(HTTP軽量・settled)。
    date は常に today に更新(部分成功でも当日再走で skip されず残りが埋まる)。itemID 無は no-op。
    """
    if not iid:
        return cache
    entry = dict(cache.get(iid) or {})
    entry["snkrdunk"] = snkrdunk
    entry["date"] = today
    if not _mercari_errored(mercari):
        entry["mercari"] = mercari      # 成功/在庫なし(確定)のみ。errored は付けない=次夜再取得。
    cache[iid] = entry
    return cache


def _load_cache(path=CACHE_PATH):
    import json
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache, path=CACHE_PATH):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def run_night_search(max_backups=1, limit=None, fresh=False, snkr_sleep=1.0):
    """夜間検索本体(impure)。HIGH→対象抽出→検索→増分キャッシュ書込。補URL列は触らない。

    Args:
        max_backups: slice1 の閾値(既定1=補0本=初期 backlog)。
        limit: 今回叩く対象上限(None=全部。夜跨ぎ backlog を分割消化する用)。
        fresh: True で当日キャッシュも無視して全対象を再取得。
        snkr_sleep: SNKRDUNK 呼出間の待機秒(BAN 回避・nightly slow-and-steady)。
    """
    import datetime
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mercari_psa_resource as mp
    import snkrdunk_psa_resource as sp

    today = datetime.date.today().isoformat()
    vals = _read_high()
    targets = select_backfill_targets(vals, max_backups=max_backups)
    cache = {} if fresh else _load_cache()
    todo = targets if fresh else targets_needing_search(targets, cache, today)
    total_targets = len(targets)
    skipped = total_targets - len(todo)
    if limit is not None:
        todo = todo[:limit]
    print(f"夜間検索: 対象(補<{max_backups}) {total_targets}件 / 当日済skip {skipped}件 / 今回 {len(todo)}件"
          + (f" (limit={limit})" if limit is not None else ""))
    if not todo:
        print("  対象なし(全て当日検索済 or 補が閾値以上)。終了。")
        return {"searched": 0, "mercari_hit": 0, "snkr_hit": 0, "skipped": skipped, "no_query": 0}

    # クエリ生成(build_card_query + KEYフォールバック)。card_no 空=探索不能 → 対象から除外し
    # **キャッシュに書かない**(mercari=None を焼くと RESTOCK ゲートが「在庫なし確定」と誤読=汚染)。
    queries = [build_search_query(t, mp) for t in todo]
    searchable = [i for i in range(len(todo)) if queries[i].get("card_no")]
    no_query = len(todo) - len(searchable)
    if no_query:
        print(f"  ⏭ 探索不能(title/KEYから card番号取れず) {no_query}件 = 検索せず・cache汚染しない(要 catalog/KEY補完)")
    if not searchable:
        print("  探索可能な対象なし。終了。")
        return {"searched": 0, "mercari_hit": 0, "snkr_hit": 0, "skipped": skipped, "no_query": no_query}

    # --- メルカリ(一括 Selenium。内部で 8s throttle + driver 10件毎再起動 = BAN/クラッシュ耐性) ---
    print(f"▶ メルカリ最安取得 {len(searchable)}件 (throttle 済)...", flush=True)
    mercari_res = {}   # todo-index → 結果
    try:
        cards = [{**queries[i], "ebay_item_id": todo[i]["itemID"]} for i in searchable]
        scraped = mp.fetch_mercari_cheapest(cards)
        for j, i in enumerate(searchable):
            mercari_res[i] = scraped.get(j)
    except Exception as e:
        print(f"  ⚠ メルカリ一括 skip ({type(e).__name__}: {e}) — SNKRDUNK のみ書込", flush=True)

    # --- SNKRDUNK(HTTP-only)+ 増分キャッシュ書込(探索可能な対象のみ) ---
    print("▶ SNKRDUNK PSA10 取得 + キャッシュ増分書込...", flush=True)
    m_hit = s_hit = 0
    for n, i in enumerate(searchable):
        t, q = todo[i], queries[i]
        iid, cn = t["itemID"], q.get("card_no")
        try:
            snkr = sp.check_by_keyword(cn, variant_hint=q.get("hint"),
                                       multi_variant=q.get("multi_variant"))
        except Exception as e:
            snkr = {"_error": str(e)[:40] or "error", "available": False, "psa10_price_jpy": None}
        m = mercari_res.get(i)
        if isinstance(m, dict) and m.get("best"):
            m_hit += 1
        if isinstance(snkr, dict) and snkr.get("available"):
            s_hit += 1
        merge_search_result(cache, iid, m, snkr, today)
        if (n + 1) % 5 == 0:
            _save_cache(cache)          # 増分コミット(いつ落ちても残る)
            print(f"   {n+1}/{len(searchable)} (mercari在庫{m_hit} / snkr在庫{s_hit})", flush=True)
        if snkr_sleep:
            time.sleep(snkr_sleep)
    _save_cache(cache)
    print(f"✅ 夜間検索完了: {len(searchable)}件検索 (mercari在庫あり{m_hit} / snkr在庫あり{s_hit}) "
          f"→ psa_research_cache.json 書込。補URL書込は slice3(昼確認)。")
    return {"searched": len(searchable), "mercari_hit": m_hit, "snkr_hit": s_hit,
            "skipped": skipped, "no_query": no_query}


# ---------------------------------------------------------------------------
# slice3: 昼の確認(有人)。キャッシュ済候補を視覚確証→補URL(AC-AG)へ冪等書込。
# ---------------------------------------------------------------------------
CONFIRM_SKIP_TAB = "補URL確証スキップ"
CONFIRM_SKIP_HEADER = ["itemID", "cert", "title", "理由", "日付"]


def compute_backurl_additions(existing, new_urls, max_slots=None):
    """既存補URL + 確定URL → (書込full_list, 追加分)。hoju と同規約の冪等追記(純関数)。

    既存を消さず、未収載の new_urls を空き枠にだけ足し、max_slots で頭打ち。空文字・重複は無視。
    Returns: (full[:max_slots], added)。added が空なら書込不要。
    """
    if max_slots is None:
        max_slots = AUXN
    full = [u for u in (existing or []) if u]      # 既存(空除去)
    added = []
    for u in (new_urls or []):
        u = (u or "").strip()
        if not u or u in full:
            continue
        if len(full) >= max_slots:
            break                                   # 満杯 → 溢れは書かない(売切上書きは監視くん Phase2)
        full.append(u)
        added.append(u)
    return full[:max_slots], added


def _skip_iids_from_tab(rows):
    """補URL確証スキップ タブ → itemID集合(純関数)。見送り/違うは再表示しない。"""
    if not rows or len(rows) < 2:
        return set()
    return {(r[0] or "").strip() for r in rows[1:] if r and (r[0] or "").strip()}


def _merge_skip_rows(existing_rows, new_rows, header):
    """既存スキップ行 + 新規(itemID重複は新規優先)を純関数マージ。"""
    new_iids = {(r[0] or "").strip() for r in new_rows if r and (r[0] or "").strip()}
    kept = [r for r in (existing_rows[1:] if existing_rows else [])
            if r and (r[0] or "").strip() and (r[0] or "").strip() not in new_iids]
    return [header] + kept + new_rows


def _ebay_itm_url(itemid):
    return f"https://www.ebay.com/itm/{itemid}" if itemid else ""


def run_daytime_confirm(max_backups=1, limit=None, dry_run=False):
    """昼の確認(impure)。slice2 が焼いた当日キャッシュから候補を出し、現物と視覚確証→
    確定URLを補URL(AC-AG)へ **既存保持+空き枠のみ** 冪等書込(hoju同規約)。主URL(A)は触らない。

    - 対象 = 補<閾値 live PSA で、当日キャッシュに候補がある行(=slice2 で在庫確認済)。
    - スキップ台帳(見送り/違う)にある itemID は再表示しない(前回判断の尊重)。
    - 補が閾値以上に増えた行は select_backfill_targets から自然に外れる(=補URL自体がレジューム状態)。
    - dry_run: 書込せず件数/内訳のみ(確証UIも出さない)。
    """
    import datetime
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mercari_psa_resource as mp
    import psa_resource_confirm as prc
    import psa_resource_gate as gate

    today = datetime.date.today().isoformat()
    vals = _read_high()
    targets = select_backfill_targets(vals, max_backups=max_backups)
    cache = _load_cache()

    # スキップ台帳(見送り/違う)= 再表示しない
    try:
        from sheet_io import read_tab
        skip_iids = _skip_iids_from_tab(read_tab(CONFIRM_SKIP_TAB))
    except Exception:
        skip_iids = set()

    # 当日キャッシュに候補がある対象だけを確証items化(idx=items内index→書込時に target へ戻す)
    items, item_targets = [], []
    no_cache = no_cand = 0
    for t in targets:
        iid = t["itemID"]
        if iid in skip_iids:
            continue
        entry = cache.get(iid)
        if not _entry_complete(entry, today):
            no_cache += 1
            continue
        mr = entry.get("mercari") or {}
        c = gate.combine(mr.get("best"), entry.get("snkrdunk"),
                         mercari_cands=mr.get("cands"), max_aux=AUXN)
        cands = gate._build_visual_candidates(mr, c)
        if not cands:
            no_cand += 1
            continue
        idx = len(items)
        cn = build_search_query(t, mp).get("card_no") or ""
        ref = prc.ebay_listing_image(iid) or prc.psa_image_for_cert(t.get("cert") or None)
        items.append({"idx": idx, "title": (t.get("title") or "")[:90], "card_no": cn,
                      "ebay_url": _ebay_itm_url(iid), "ref_image": ref, "candidates": cands})
        item_targets.append(t)

    print(f"昼確認: 対象(補<{max_backups}) {len(targets)}件 / キャッシュ未取得skip {no_cache} / "
          f"候補なしskip {no_cand} / 台帳skip {len(skip_iids)} → 確証対象 {len(items)}件")
    if limit is not None:
        items, item_targets = items[:limit], item_targets[:limit]
        for n, it in enumerate(items):
            it["idx"] = n
        print(f"  (limit={limit} → {len(items)}件)")
    if not items:
        print("  確証対象なし。終了。")
        return {"confirmed": 0, "written_rows": 0, "added_urls": 0}
    if dry_run:
        print("  (dry-run) 確証UI/書込なし。上記件数のみ。")
        return {"confirmed": 0, "written_rows": 0, "added_urls": 0, "candidates_ready": len(items)}

    print(f"▶ 補URL補強 視覚確証: {len(items)}件をブラウザ表示。① 現物 と 仕入候補を見比べ、"
          "**その出品に足す補URL(=正しい変種の在庫)だけチェックを残す**...")
    res = prc.restock_confirm(items)
    if res is None:
        print("⚠ 確証タイムアウト/未確定 — 補URL書込なし(再実行してください)。")
        return {"confirmed": 0, "written_rows": 0, "added_urls": 0}
    confirmed = {c["idx"]: c["urls"] for c in res["confirmed"]}

    # --- 確定URL → 補URL(AC-AG)へ冪等書込(既存保持・空き枠のみ) ---
    aux_writeback, added_total = {}, 0
    for idx, urls in confirmed.items():
        t = item_targets[idx]
        row = t["row"]
        r = vals[row - 1] if 0 < row <= len(vals) else []
        existing = [(_cell(r, AUX0 + k)) for k in range(AUXN)]
        existing = [u for u in existing if u]
        full, added = compute_backurl_additions(existing, urls, AUXN)
        if added:
            aux_writeback[row] = full
            added_total += len(added)
    written = 0
    if aux_writeback:
        try:
            from sheet_io import write_aux_urls
            written = write_aux_urls(aux_writeback)
            print(f"🔗 補URL(AC-AG) 冪等書込: {written}行 / 追加URL {added_total}本 (既存保持・空き枠のみ)")
        except Exception as e:
            print(f"⚠ 補URL書込失敗: {type(e).__name__}: {e}")
    else:
        print("  書込対象なし(全て既存収載 or 満杯 or 確定ゼロ)。")

    # --- 見送り/違う を台帳へ(次回再表示しない)+ 違う=検索精度事故アラート ---
    diffs = {d.get("idx") for d in (res.get("diffs") or []) if d.get("idx") is not None}
    shown = set(range(len(items)))
    not_confirmed = shown - set(confirmed.keys())
    if not_confirmed:
        new_skip = []
        for idx in sorted(not_confirmed):
            t = item_targets[idx]
            reason = "違う" if idx in diffs else "見送り"
            new_skip.append([t["itemID"], t.get("cert", ""), (t.get("title") or "")[:60], reason, today])
        try:
            from sheet_io import read_tab, write_rows_to_tab
            merged = _merge_skip_rows(read_tab(CONFIRM_SKIP_TAB), new_skip, CONFIRM_SKIP_HEADER)
            write_rows_to_tab(CONFIRM_SKIP_TAB, merged)
            print(f"  📝 {CONFIRM_SKIP_TAB}: +{len(new_skip)}件 記録(次回は再表示しない・再検討は同タブ行削除)")
        except Exception as e:
            print(f"  ⚠ {CONFIRM_SKIP_TAB} 記録skip ({type(e).__name__}: {e})")
    if diffs:
        print(f"🚨 「違う」{len(diffs)}件 = 検索が別カード/別変種を拾った精度事故。"
              "slice2 の検索(kw/variant_hint)を要修正(残存=精度事故の放置)。")

    print(f"✅ 昼確認完了: 確証{len(confirmed)}件 → 補URL {written}行に {added_total}本追記。")
    return {"confirmed": len(confirmed), "written_rows": written, "added_urls": added_total}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # slice2: `search` で夜間検索。slice3: `confirm` で昼確認→補URL書込。無引数=slice1 件数レポート。
    if "search" in sys.argv:
        max_backups, limit, fresh = 1, None, False
        for a in sys.argv[1:]:
            if a.startswith("--max-backups="):
                max_backups = int(a.split("=", 1)[1])
            elif a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
            elif a == "--fresh":
                fresh = True
        run_night_search(max_backups=max_backups, limit=limit, fresh=fresh)
        return
    if "confirm" in sys.argv:
        max_backups, limit, dry = 1, None, "--dry-run" in sys.argv
        for a in sys.argv[1:]:
            if a.startswith("--max-backups="):
                max_backups = int(a.split("=", 1)[1])
            elif a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
        run_daytime_confirm(max_backups=max_backups, limit=limit, dry_run=dry)
        return
    vals = _read_high()
    print(f"HIGH {len(vals)-1} 行")
    for th, label in [(1, "補0本(=初期対象)"), (2, "補≤1本"), (5, "補<5本(満杯未満=top-up含む)")]:
        tg = select_backfill_targets(vals, max_backups=th)
        print(f"  max_backups={th} ({label}): {len(tg)} 件")
    # 初期対象(補0本)のサンプル
    zero = select_backfill_targets(vals, max_backups=1)
    print("\n初期対象サンプル(補0本):")
    for t in zero[:5]:
        print(f"  row{t['row']} cert={t['cert']} KEY={t['key']!r} 補{t['n_backups']}本 | {t['title'][:34]}")


if __name__ == "__main__":
    main()
