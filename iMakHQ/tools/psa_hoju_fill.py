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
        return {"searched": 0, "mercari_hit": 0, "snkr_hit": 0, "skipped": skipped}

    # クエリ生成(build_card_query = kw/card_no/name_jp/hint/multi_variant/image)。
    queries = [mp.build_card_query(t.get("title", ""), "", t.get("key") or None) for t in todo]

    # --- メルカリ(一括 Selenium。内部で 8s throttle + driver 10件毎再起動 = BAN/クラッシュ耐性) ---
    print(f"▶ メルカリ最安取得 {len(todo)}件 (throttle 済)...", flush=True)
    mercari_res = {}
    try:
        cards = [{**queries[i], "ebay_item_id": todo[i]["itemID"]} for i in range(len(todo))]
        mercari_res = mp.fetch_mercari_cheapest(cards)
    except Exception as e:
        print(f"  ⚠ メルカリ一括 skip ({type(e).__name__}: {e}) — SNKRDUNK のみ書込", flush=True)

    # --- SNKRDUNK(HTTP-only)+ 増分キャッシュ書込 ---
    print("▶ SNKRDUNK PSA10 取得 + キャッシュ増分書込...", flush=True)
    m_hit = s_hit = 0
    for i, t in enumerate(todo):
        q = queries[i]
        iid = t["itemID"]
        cn = q.get("card_no")
        if cn:
            try:
                snkr = sp.check_by_keyword(cn, variant_hint=q.get("hint"),
                                           multi_variant=q.get("multi_variant"))
            except Exception as e:
                snkr = {"_error": str(e)[:40] or "error", "available": False, "psa10_price_jpy": None}
        else:
            snkr = None
        m = mercari_res.get(i)
        if isinstance(m, dict) and m.get("best"):
            m_hit += 1
        if isinstance(snkr, dict) and snkr.get("available"):
            s_hit += 1
        merge_search_result(cache, iid, m, snkr, today)
        if (i + 1) % 5 == 0:
            _save_cache(cache)          # 増分コミット(いつ落ちても残る)
            print(f"   {i+1}/{len(todo)} (mercari在庫{m_hit} / snkr在庫{s_hit})", flush=True)
        if cn and snkr_sleep:
            time.sleep(snkr_sleep)
    _save_cache(cache)
    print(f"✅ 夜間検索完了: {len(todo)}件検索 (mercari在庫あり{m_hit} / snkr在庫あり{s_hit}) "
          f"→ psa_research_cache.json 書込。補URL書込は slice3(昼確認)。")
    return {"searched": len(todo), "mercari_hit": m_hit, "snkr_hit": s_hit, "skipped": skipped}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # slice2: `search` で夜間検索。無引数は slice1 の件数レポート(read-only)。
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
