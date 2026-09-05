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
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io

A, B, C, D, CERT = 0, 1, 2, 3, sheet_io.PRODUCT_COL_CERT          # 0,1,2,3,8
CATEGORY = 17                                                      # R (カテゴリ。'TCG' が PSA)
LISTED_AT = 20                                                     # U (出品日時。新規優先の並べ替えキー)
KEY = sheet_io.PRODUCT_COL_KEY                                     # 34
AUX0, AUXN = sheet_io.PRODUCT_COL_AUX_START, sheet_io.PRODUCT_AUX_MAX  # 28, 5

# 「何本まで補があったら対象にするか」。★2026-09-05 に **探す側と目視側で分けた**。
#   探す側 (夜間) は 補0本 = 丸腰の出品を最優先で埋める。ここは従来どおり。
#   目視側 (③) は **満杯未満すべて**。従来は目視も 補0本 だけだったため、
#   補が1本でもある出品は目視に一度も出て来ず、9/5 に入れた「既存と見比べて安い順に
#   最大5本 持つ」が **通り道が無くて発火しなかった**。
#   実測 (2026-09-05): 補0本 45件 / 補≤1本 209件 / 満杯未満 409件。
#   = 364件が どのボタンにも出ないまま、高い仕入元を持ち続けていた。
SEARCH_MAX_BACKUPS = 1
CONFIRM_MAX_BACKUPS = AUXN          # 補<5 = 満杯未満
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


def _listed_sort_key(row):
    """出品日時(U列)の降順ソート用キー。空/不正は最古扱い(= 後回し)。

    形式は 'YYYY-MM-DD ...' / 'YYYY/MM/DD ...' の両方が実在するので区切りを正規化して
    文字列比較する (ISO 風なので辞書順 = 時系列順)。
    """
    v = _cell(row, LISTED_AT).replace("/", "-")
    return v if len(v) >= 10 and v[:4].isdigit() else ""


def select_backfill_targets(rows2d, max_backups=1):
    """HIGH rows2d(header含む) → 補<max_backups の live PSA 行リスト。純関数(test可)。

    max_backups=1 → 補 0本のみ(残1件でリフィル=定常の既定)。
    初期一括は呼び手が大きめ(例 5)を渡して「満杯未満すべて」を対象にできる。
    Returns: [{row(1-indexed), itemID, cert, key, card_no_title, n_backups, empty_slots}]

    ★2026-07-28: **新規出品を最優先**に並べ替える (出品日時 U列の降順)。
      理由: backlog が行順(=古い順)だと、1日あたりの処理件数が限られる運用では
      新規出品が最後尾に並び、**一番死にやすい出品直後の数日が無防備**になる。
      実測 (7/20-7/27 出品49件): 仕入元売切れ10件のうち **補URL 0本の8件が完全死**、
      補URLがあった2件は生存。= 補URLの有無が生死を分けており、付ける順番が効く。
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
            "listed_at": _listed_sort_key(r),
        })
    # 新規優先 (出品日時の降順)。同着は行番号昇順で安定させる。
    out.sort(key=lambda t: (t["listed_at"], -t["row"]), reverse=True)
    # ★2026-09-05: **補が少ない順**を上に置く (安定ソートなので同数の中は新規優先のまま)。
    #   目視の対象を満杯未満まで広げたので、これが無いと 補4本の出品が
    #   丸腰(補0本)より先に出てしまう。丸腰の方が死ぬ。
    out.sort(key=lambda t: t["n_backups"])
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
    """本体 (`mercari_psa_resource.card_no_from_key`) に委譲。

    ★2026-08-03: 実体をここから本体へ移した。二重定義にすると「KEY からの番号の作り方」が
    2箇所に散り、片方だけ直して食い違う (今回まさにそれが起きていた)。薄い別名だけ残す。
    """
    import mercari_psa_resource as _mp
    return _mp.card_no_from_key(key)


def build_search_query(target, mp):
    """1対象 → 検索クエリ(build_card_query + KEYフォールバック)。card_no 空なら kw も空(=探索不能)。

    build_card_query(gate共用)が title 由来 card_no を空で返したら KEY 由来番号で補い、kw を
    'PSA10 <name_jp> <card_no>' で再構成。snkrdunk も同じ card_no を使う。純ロジック(mp はDB引き用)。
    """
    # ★2026-08-03: KEY 優先は **build_card_query 本体**に入った (mercari_psa_resource)。
    #   ここに在った「後から card_no/name_jp/multi_variant を上書きする」パッチは全部不要になった。
    #   本体が KEY→set_no→title の順で番号を決めるので、呼び出し側は素直に渡すだけでよい。
    #   (同定を1箇所に寄せる = 同じ判定が2度出たら発生源を直す、の実行)
    q = mp.build_card_query(target.get("title", ""), "", target.get("key") or None)
    # 番号が KEY と食い違っていた事実は **見えるようにする** (出品者の誤記が何件あるかの計測)。
    _cn_key = _card_no_from_key(target.get("key"))
    _cn_title = mp._extract_card_no(target.get("title", ""), "", None)
    if _cn_key and _cn_title and _cn_key.upper() != _cn_title.upper():
        print(f"  ⚠️ 番号不一致: 仕入元タイトル='{_cn_title}' / KEY='{_cn_key}' → **KEY を採用** "
              f"(itemID={target.get('itemID')} / 出品者の表記ゆれ・誤記)", flush=True)
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


def _search_age_key(entry, today):
    """検索キューの並べ替え用: 「最後に探した日からの経過日数」(大きいほど先に探す)。

    未探索(entry 無し / date 無し / 解析不能) は最優先 (float('inf'))。
    """
    d = (entry or {}).get("date") if isinstance(entry, dict) else None
    if not d:
        return float("inf")
    try:
        import datetime
        return (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(d)).days
    except Exception:
        return float("inf")


# ---------------------------------------------------------------------------
# 空振りの記録 (2026-08-15)
# ---------------------------------------------------------------------------
# ★ユーザー指摘「全然減らない気がする」。実測で 8/09〜8/15 の7日間、補0本が 41〜46件で
#   横ばい。毎晩30件を叩いているのに埋まらない。ログを見ると同じカードが7日連続で並び、
#   毎晩「多変種で変種確証不可」または絵柄不一致で候補ゼロになっていた。
#   = **市場にその版が出ていない**カードを毎晩探し直し、30枠の半分以上を食っていた。
#   絵柄判定は正しく働いている (実測 same 514 / different 199、理由も具体的) ので、
#   判定を緩めてはいけない。**枠の使い方**を変える。
DRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hoju_dry_streak.json")
DRY_SKIP_AFTER = 3      # 何夜連続で候補ゼロなら毎晩の枠から外すか
DRY_RETRY_DAYS = 7      # 外した後、何日おきに再挑戦するか (供給は後から湧くので捨てない)


def load_dry(path=None):
    try:
        with open(path or DRY_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_dry(d, path=None):
    try:
        with open(path or DRY_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"  ⚠ 空振り台帳を書けず ({type(e).__name__})")


def _days_between(a, b):
    import datetime as _dt
    try:
        return (_dt.date.fromisoformat(b) - _dt.date.fromisoformat(a)).days
    except Exception:
        return 999


def should_skip_dry(entry, today, skip_after=DRY_SKIP_AFTER, retry_days=DRY_RETRY_DAYS):
    """空振り続きの対象を今夜の枠から外すか (純関数)。

    連続空振りが skip_after 以上、かつ最後の挑戦から retry_days 未満なら外す。
    **捨てるのではなく間隔を空けるだけ** — 供給は後から湧くので、週1では必ず戻る。
    """
    if not entry:
        return False
    if int(entry.get("streak") or 0) < skip_after:
        return False
    return _days_between(str(entry.get("last") or ""), today) < retry_days


def update_dry(dry, itemid, has_cand, today, card_no=""):
    """1件の結果を台帳に反映 (純関数)。候補が出たら streak を 0 に戻す。"""
    e = dict(dry.get(itemid) or {})
    e["streak"] = 0 if has_cand else int(e.get("streak") or 0) + 1
    e["last"] = today
    if card_no:
        e["card_no"] = card_no
    dry[itemid] = e
    return dry


def targets_needing_search(targets, cache, today):
    """当日まだ検索し切れてない対象を **探し直すべき順** で返す(純関数・レジューム耐性)。

    補URL自体がレジューム状態(埋まればクエリから外れる)だが、夜間検索の中断耐性のため
    「当日キャッシュ完了」も skip 条件にする(同夜の再実行で残りだけ叩く)。

    ★2026-08-01 並べ替えを追加 (これが無いと **一部が永久に探されない**)。
      入力 targets は select_backfill_targets が **出品日時の降順**(新規優先)で返す。
      夜間検索は `todo[:limit]` で先頭 limit 件しか叩かないため、対象数 > limit の間
      **古い出品はいつまでも順番が回ってこない**。実測 2026-08-01: 対象82件のうち
      14件が 7/25 の cache のまま(= 3日の鮮度窓を超えて確証UIにすら出ない)、22件が未探索。
      → 「最後に探した日が古い順」に並べ替え、全対象が必ず一巡するようにする。
      未探索(=新規出品も含む)が最優先なのは従来どおり。同着は新しい出品を先に。

    ★「市場に無い」対象を落とさないこと。候補ゼロでも entry は残るので経過日数で必ず戻ってくる。
      供給は後から湧くので、探し続けるのが正しい (打ち切ると二度と補URLが付かない)。
    """
    todo = [t for t in targets if not _entry_complete(cache.get(t.get("itemID")), today)]
    # 経過日数の降順のみで並べる。同着は **入力順(=出品日時の降順)がそのまま残る**
    # (Python の sort は安定) ので、「未探索の中では新規出品が先」は従来どおり保たれる。
    todo.sort(key=lambda t: -_search_age_key(cache.get(t.get("itemID")), today))
    return todo


def _entry_fresh(entry, today, max_age_days=3):
    """slice3 が消費してよい鮮度か(純関数)= mercari/snkrdunk 両方揃い + date が窓内。

    slice2 の same-day(_entry_complete)より緩い。**夜に検索→翌朝(=別日付)確認**の日跨ぎで
    キャッシュが失効しないため(供給は1-2日で消えないし、slice3 は人が現物と視覚照合する)。
    未来日付(0未満)や窓超過は False。日付欠落/解析不可も False(fail-closed)。
    """
    if not (isinstance(entry, dict) and "mercari" in entry and "snkrdunk" in entry):
        return False
    d = entry.get("date")
    if not d:
        return False
    try:
        import datetime
        age = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(d)).days
    except Exception:
        return False
    return 0 <= age <= max_age_days


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


# ---------------------------------------------------------------------------
# 候補の番号照合 (2026-07-28)。確証UI に「明らかに別カード」を出さないための足切り。
# ★除外しかしない (採用は必ず有人確証)。判定不能は残す = recall を落とさない fail-closed。
# ---------------------------------------------------------------------------
_SLASH_NO_RE = re.compile(r"(\d{1,3})\s*[/／]\s*(\d{1,3})")          # 093/187 (Pokemon 等)
_HYPHEN_NO_RE = re.compile(r"\b([A-Za-z]{1,5}\d{0,3}[A-Za-z]?)-(\d{1,3})\b")  # OP11-106 / P-041


def _target_card_number(card_no):
    """catalog の card_no → (set_code大文字, 番号int)。取れない要素は ''/None。純関数。

    'OP11-106' → ('OP11', 106) / 'SV8a-093' → ('SV8A', 93) / 'P-041' → ('P', 41)。
    """
    s = (card_no or "").strip()
    if not s:
        return "", None
    m = _HYPHEN_NO_RE.search(s)
    if m:
        return m.group(1).upper(), int(m.group(2))
    m = _SLASH_NO_RE.search(s)
    if m:
        return "", int(m.group(1))
    return "", None


def candidate_number_conflicts(name, card_no):
    """候補タイトルが **明らかに別番号** を名乗っているか (純関数)。

    True = 除外してよい。判定材料が無い/読めない場合は False (= 残して人に見せる)。
    - タイトルに 'xxx-nnn' 形式があり、どれも対象と一致しない → 衝突
    - タイトルに 'nnn/mmm' 形式があり、左辺のどれも対象番号と一致しない → 衝突
      (ゼロ埋め差は int 比較で吸収: '7/095' と '007' は一致)
    """
    tset, tnum = _target_card_number(card_no)
    if tnum is None:
        return False                      # 対象側が不明 = 判定しない
    t = (name or "").strip()
    if not t:
        return False                      # 候補名なし (snkrdunk 等) = 判定しない
    hyph = _HYPHEN_NO_RE.findall(t)
    if hyph:
        for sc, n in hyph:
            if int(n) == tnum and (not tset or sc.upper() == tset):
                return False              # 一致あり
        return True                       # 全部違う番号を名乗っている
    slash = _SLASH_NO_RE.findall(t)
    if slash:
        return all(int(a) != tnum for a, _ in slash)
    return False                          # 番号表記なし = 判定不能 → 残す


def _norm_url(u):
    """URL 比較用の正規化(純関数)。クエリ/フラグメント/末尾スラッシュ/大文字小文字の差を吸収。"""
    v = (u or "").strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return v.lower()


def filter_candidates_known_urls(cands, known_urls):
    """既に自分が使っている供給(主URL A列 / 既存補URL)を候補から除く。戻り: (残す, 落とした)。

    ★2026-07-28: 確証UIに **主URLと同じ出品** が出ていた(実測18件)。同一個体なので写真も cert も
    現物と同じになり「現物と候補が同じ cert」に見える = 目視が成立しない。補URLの目的は
    **別個体の確保**なので、主URLの再提示は意味がないどころか有害(同じURLを2枠が指すと、
    売れた時に両方が履行不能になる)。既存補URL との重複も目視の無駄なので同時に落とす。
    """
    known = {_norm_url(u) for u in (known_urls or []) if u}
    keep, drop = [], []
    for c in (cands or []):
        (drop if _norm_url(c.get("url")) in known else keep).append(c)
    return keep, drop


def filter_candidates_by_number(cands, card_no):
    """候補リストから明らかな別番号を除く。戻り: (残す, 落とした)。純関数(test可)。"""
    keep, drop = [], []
    for c in (cands or []):
        (drop if candidate_number_conflicts(c.get("name"), card_no) else keep).append(c)
    return keep, drop


def restock_targets(limit=None):
    """ファネルの RESTOCK∩PSA10 を「検索対象」の形に変換する (2026-07-28)。

    再仕入れ照合ボタン(psa_resource_gate)は押してから探すので待たされる。**同じ
    psa_research_cache を共有している**ので、夜のうちにここを温めておけば当日キャッシュが効き、
    ボタンは即座に候補を出せる(再スクレイプも減って BAN リスクも下がる)。

    KEY/cert は商品管理シートから itemID で join (gate の Step6 P1 と同じ血統)。
    itemID が取れない行は skip (キャッシュは itemID キーのため)。
    """
    import psa_resource_gate as gate
    rows, mp = gate._load_restock_psa10()
    if not rows:
        return []
    vals = _read_high()
    key_by, cert_by, title_by = {}, {}, {}
    for r in vals[1:]:
        iid = _cell(r, B)
        if iid:
            key_by[iid], cert_by[iid], title_by[iid] = _cell(r, KEY), _cell(r, CERT), _cell(r, C)
    out = []
    for r in rows:
        iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
        if not iid:
            continue
        out.append({"itemID": iid, "key": key_by.get(iid, ""), "cert": cert_by.get(iid, ""),
                    "title": r.get("title") or title_by.get(iid, "")})
    return out[:limit] if limit else out


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


def _clean_orphan_chrome():
    """★2026-07-28 廃止(no-op)。**他プロセスの driver を殺していた**ため。

    旧実装は run 開始時に `undetected_chromedriver` を **全部** kill していた(孤児掃除)。
    しかし深夜は 01:30 監視くん Cycle / 04:00 Backup / 04:30 リバイスくん が動いており、
    01:30 の cycle が長引いたまま 03:00 に本 run が始まると **監視くんの driver を殺す**。
    取下げ処理の途中で driver が消える = 状態同期が壊れる危険側の失敗。

    → ユーザー判断(2026-07-28): 他プロセスには触らず、**自分が起こした分だけ後片付けする**
      (_cleanup_own_drivers)。孤児蓄積の対策はそちらで達成する。
    互換のため関数は残すが何もしない。
    """
    return


def _own_driver_pids():
    """このプロセスが親の undetected_chromedriver PID と、その子 chrome PID を返す。

    他ジョブの driver を巻き込まないための「所有権」判定。親子関係で見るので、同時刻に
    別ジョブが driver を起こしていても取り違えない。Windows 以外/失敗は空(=何もしない)。
    """
    if sys.platform != "win32":
        return []
    import json as _json
    import subprocess
    ps = (
        f"$me={os.getpid()};"
        "$drv=Get-CimInstance Win32_Process -Filter \"Name='undetected_chromedriver.exe'\" |"
        " Where-Object {$_.ParentProcessId -eq $me};"
        "$ids=@($drv | ForEach-Object {$_.ProcessId});"
        "$kids=@();"
        "if($ids.Count -gt 0){$kids=Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" |"
        " Where-Object {$ids -contains $_.ParentProcessId} | ForEach-Object {$_.ProcessId}}"
        "; ConvertTo-Json @($ids + $kids)"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           timeout=30, capture_output=True, text=True)
        val = _json.loads((r.stdout or "").strip() or "[]")
        return [int(v) for v in (val if isinstance(val, list) else [val])]
    except Exception:
        return []


def _cleanup_own_drivers():
    """自分が起こした driver/chrome だけを終了する(他ジョブには触らない)。

    run 終了時に呼ぶ。途中 crash で残った分は次回 run では「自分の子」でなくなるため対象外だが、
    親を失った driver は Windows が概ね回収する。**他プロセスを巻き込まない**ことを優先する。
    """
    pids = _own_driver_pids()
    if not pids:
        return 0
    import subprocess
    ids = ",".join(str(p) for p in pids)
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Stop-Process -Id {ids} -Force -EA SilentlyContinue"],
                       timeout=30, capture_output=True)
    except Exception:
        return 0
    return len(pids)


class _KeepAwake:
    """実行中だけ Windows をスリープさせない(無人夜間runの早期死を防ぐ)。

    ★2026-07-25: 無人放置の search が毎回スリープで死んだ(chromedriver不達→初回コミット前に落ちる)。
    resilience(バッチ毎コミット)は「コミット済を守る」だけでスリープ死そのものは防げない。
    SetThreadExecutionState(ES_SYSTEM_REQUIRED) で run 中は system sleep を抑止し、終了で解除。
    Windows 以外/失敗は no-op(害なし)。ディスプレイは消えてよい(ES_DISPLAY_REQUIREDは付けない)。
    """
    _ES_CONTINUOUS = 0x80000000
    _ES_SYSTEM_REQUIRED = 0x00000001

    def __enter__(self):
        self._ok = False
        try:
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(
                    self._ES_CONTINUOUS | self._ES_SYSTEM_REQUIRED)
                self._ok = True
        except Exception:
            self._ok = False
        return self

    def __exit__(self, *exc):
        try:
            if self._ok:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(self._ES_CONTINUOUS)  # 抑止解除
        except Exception:
            pass
        return False


def run_night_search(max_backups=1, limit=None, fresh=False, snkr_sleep=1.0, commit_batch=8,
                     targets=None,
                     min_reviews=100):
    """夜間検索本体(impure)。HIGH→対象抽出→検索→**サブバッチ毎にcacheコミット**。補URL列は触らない。

    Args:
        max_backups: slice1 の閾値(既定1=補0本=初期 backlog)。
        limit: 今回叩く対象上限(None=全部。夜跨ぎ backlog を分割消化する用)。
        fresh: True で当日キャッシュも無視して全対象を再取得。
        snkr_sleep: SNKRDUNK 呼出間の待機秒(BAN 回避・nightly slow-and-steady)。
        commit_batch: この件数ごとに mercari+snkrdunk+cache保存(途中死の損失を≤1バッチに限定)。
        min_reviews: メルカリ補URL候補の個人セラー評価件数の下限(既定100)。送料込みも必須。
        targets: 対象を呼び手が渡す(None=HIGH から補URL薄い live PSA を自前抽出)。
                 再仕入れ候補の先読み(restock_targets)に同じ検索経路を使い回すための口。
    """
    import datetime
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mercari_psa_resource as mp
    import snkrdunk_psa_resource as sp

    today = datetime.date.today().isoformat()
    if targets is None:
        targets = select_backfill_targets(_read_high(), max_backups=max_backups)
        label = f"補<{max_backups}"
    else:
        label = "RESTOCK候補"       # 呼び手が対象を決めた(= 再仕入れ候補の先読み)
    cache = {} if fresh else _load_cache()
    todo = targets if fresh else targets_needing_search(targets, cache, today)
    total_targets = len(targets)
    skipped = total_targets - len(todo)
    # ★2026-08-15: 空振りが続く対象を今夜の枠から外す (limit を切る前に間引く)。
    #   毎晩30枠の半分以上を「市場にその版が無いカード」が食い、7日間 補0本が横ばいだった。
    #   捨てるのではなく間隔を空けるだけ (DRY_RETRY_DAYS ごとに必ず戻る)。
    dry = load_dry()
    _dry_out = [t for t in todo if should_skip_dry(dry.get(t.get("itemID")), today)]
    if _dry_out:
        _skip_ids = {t.get("itemID") for t in _dry_out}
        todo = [t for t in todo if t.get("itemID") not in _skip_ids]
        print(f"  ⏭ 空振り続き {len(_dry_out)}件を今夜は外す "
              f"({DRY_SKIP_AFTER}夜連続で候補ゼロ → {DRY_RETRY_DAYS}日おきに再挑戦)。"
              f"空いた枠は未探索の出品に回る")
    if limit is not None:
        todo = todo[:limit]
    print(f"夜間検索: 対象({label}) {total_targets}件 / 当日済skip {skipped}件 / 今回 {len(todo)}件"
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

    # --- サブバッチ処理(mercari→snkrdunk→**cacheコミット**を commit_batch 件ごと) ---
    # ★2026-07-25 resilience: 昨夜「mercari一括を全部やってから書込」中に途中死(マシンsleep)→
    #   snkrdunkループ未到達で40件全ロスト。→ サブバッチ毎に mercari+snkrdunk+save をまとめ、
    #   死んでも直前バッチまで残す(=再実行で当日済skipして続きから)。fresh driver/batch も
    #   長寿命driver劣化(昨夜の初回10件 HTTPConnectionPool 全滅)を避ける。
    print(f"▶ 補URLリサーチ {len(searchable)}件 (mercari+snkrdunk / {commit_batch}件ごとにcacheコミット)...", flush=True)
    # ★2026-07-28: 起動時の一括 kill は廃止(他ジョブの driver を殺していた)。
    # 代わりに **自分が起こした分だけ** run 終了時に片付ける(_cleanup_own_drivers)。
    m_hit = s_hit = done = 0
    with _KeepAwake():   # 実行中はマシンをスリープさせない(無人runの初回コミット前スリープ死を防ぐ)
        for start in range(0, len(searchable), commit_batch):
            grp = searchable[start:start + commit_batch]
            # メルカリ(このバッチだけ。fresh driver・内部 8s throttle)。startup失敗等はバッチごと隔離。
            mercari_res = {}
            try:
                cards = [{**queries[i], "ebay_item_id": todo[i]["itemID"]} for i in grp]
                # 補URL候補は「送料込み + 個人セラー評価件数≥min_reviews」に絞る(詳細訪問・opt-in)。
                scraped = mp.fetch_mercari_cheapest(cards, freeship_min_reviews=min_reviews)
                for j, i in enumerate(grp):
                    mercari_res[i] = scraped.get(j)
            except Exception as e:
                print(f"  ⚠ メルカリ batch skip ({type(e).__name__}: {str(e)[:40]}) — このバッチは SNKRDUNK のみ", flush=True)
            # SNKRDUNK(HTTP)+ マージ
            for i in grp:
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
                if snkr_sleep:
                    time.sleep(snkr_sleep)
            _save_cache(cache)            # ★バッチ完了ごとにコミット(途中死でもここまで残る)
            done += len(grp)
            print(f"   💾 {done}/{len(searchable)} コミット (mercari在庫{m_hit} / snkr在庫{s_hit})", flush=True)
    _n_killed = _cleanup_own_drivers()
    if _n_killed:
        print(f"   🧹 自分が起こした driver/chrome {_n_killed}個を終了(他ジョブには触らない)")
    print(f"✅ 補URLリサーチ完了: {len(searchable)}件 (mercari在庫あり{m_hit} / snkr在庫あり{s_hit}) "
          f"→ psa_research_cache.json 書込。補URL書込は slice3(昼確認)。")
    # ★2026-08-15: 今夜の結果を空振り台帳に反映する。候補が1件でも出れば streak を 0 に戻す。
    #   (候補が出たかどうかだけを見る。使えるかは slice3 の絵柄判定が決める)
    try:
        _c2 = _load_cache()
        _n_dry = 0
        for _i in searchable:
            _t = todo[_i]
            _iid = _t.get("itemID")
            _e = (_c2.get(_iid) or {})
            _mr = _e.get("mercari") or {}
            _has = bool(_mr.get("all_cands") or _mr.get("cands") or _mr.get("best")
                        or ((_e.get("snkrdunk") or {}).get("available")))
            update_dry(dry, _iid, _has, today, queries[_i].get("card_no") or "")
            _n_dry += 0 if _has else 1
        save_dry(dry)
        if _n_dry:
            print(f"  📉 今夜 候補ゼロ {_n_dry}件 を空振り台帳に記録 "
                  f"({DRY_SKIP_AFTER}夜連続で毎晩の枠から外れる)")
    except Exception as _e:                                       # noqa: BLE001
        print(f"  ⚠ 空振り台帳の更新に失敗 (非致命): {type(_e).__name__}")
    # ★現物画像URLを焼いておく = 朝、ボタンのラベルが API 無しで正確に出せる (2026-08-09)。
    try:
        prime_ref_images(targets or [])
    except Exception as _e:                                       # noqa: BLE001
        print(f"  ⚠ 現物画像URLの先読みに失敗 (非致命): {type(_e).__name__}")
    return {"searched": len(searchable), "mercari_hit": m_hit, "snkr_hit": s_hit,
            "skipped": skipped, "no_query": no_query}


# ---------------------------------------------------------------------------
# slice3: 昼の確認(有人)。キャッシュ済候補を視覚確証→補URL(AC-AG)へ冪等書込。
# ---------------------------------------------------------------------------
CONFIRM_SKIP_TAB = "補URL確証スキップ"
CONFIRM_SKIP_HEADER = ["itemID", "cert", "title", "理由", "日付", "その時の候補URL"]


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


# ★2026-09-05 ユーザー指示:
#   「せっかく見つけた訳だから、全ての補と見比べて、最安を最大5件持つべきでは？」
#
#   従来 (compute_backurl_additions) は **既存を必ず残して空き枠だけ**埋めていた。
#   そのため補が5本埋まっている出品では、その日 目視で確認した **もっと安い供給が
#   1本も入らなかった**。補URLは「売れた時にどこから買うか」なので、安い順に持つ方が
#   利益が出る (仕入値は N列 = 今の最安が正、という既存の考え方とも揃う)。
def rank_backurls(existing, new_urls, price_by_url=None, max_slots=None):
    """既存補URL + 今日 確定したURL を **安い順**に並べ直して最大 max_slots 本にする (純関数)。

    - 値段が分かる URL (= 今日の候補に出ている) を安い順に前へ
    - 値段が分からない URL (= 今日の候補に出ていない既存) はその後ろに元の順で置く
      → 5本ぶん もっと安いものが確定した時だけ押し出される。押し出す根拠が無いなら残る
    - 主URL(A列) はここでは扱わない (呼び手が別管理)

    Returns: (full, added, removed)
    """
    if max_slots is None:
        max_slots = AUXN
    prices = price_by_url or {}

    def _price(u):
        return prices.get(_norm_url(u))

    pool, seen = [], set()
    for u in list(existing or []) + list(new_urls or []):
        u = (u or "").strip()
        if not u:
            continue
        n = _norm_url(u)
        if n in seen:
            continue
        seen.add(n)
        pool.append(u)
    # 安定ソート: 値段が分かる方を先に、その中は安い順。分からない分は元の順のまま後ろへ
    ranked = sorted(pool, key=lambda u: (0, _price(u)) if _price(u) is not None else (1, 0))
    full = ranked[:max_slots]
    kept = {_norm_url(u) for u in full}
    before = {_norm_url(u) for u in (existing or []) if u}
    added = [u for u in full if _norm_url(u) not in before]
    removed = [u for u in (existing or []) if u and _norm_url(u) not in kept]
    return full, added, removed


# 確証スキップの cooldown (2026-07-29)。設計 (discussion/2026-07-24_..._design.md:65) は
# 「cooldown付き skip台帳で一定期間再表示しない … 数日後再挑戦」だったが、**実装は期限なし**で
# 一度でも外すと二度と補URLが付かなかった (= その出品は永久に丸腰)。
# 「違う」の主因の一つは **正変種が今その日に売られていない**ことなので、時間を置けば解決する。
#
# ★期間は **翌日** (ユーザー判断 2026-07-29「即対応していかないと生きていけない。翌日でいい」)。
#   ただし 2026-06-22 に「同じ3件が毎回出る」と指摘された経緯があるため、短縮だけだと
#   ノイズが再発する。**新供給が出た時だけ出す** (下の _has_new_supply) を併用して両立させる。
CONFIRM_SKIP_COOLDOWN_DAYS = {
    "違う": 1,
    "見送り": 1,
}
CONFIRM_SKIP_COOLDOWN_DEFAULT = 1


def _norm_urls(urls):
    """URL 集合を比較用に正規化(純関数)。空要素は落とす。"""
    return {_norm_url(u) for u in (urls or []) if (u or "").strip()}


# 候補単位の「違う」台帳 (2026-07-29)。
# それまで、確証UIで候補を個別に「違う」と外しても **その出品自体が確定した場合は
# 記録が残らず**、警告が1行出るだけだった (= 次回また同じ別カードが候補に並ぶ)。
# 「押した1クリックが必ずどこかの改善につながる」ようにするため、負例として貯めて
# 次回から出さない。出品単位の伏せ (CONFIRM_SKIP_TAB) とは別物 = 出品は伏せない。
NG_CAND_TAB = "補URL候補NG"
# ★2026-08-13: 「候補タイトル」「候補価格」を追加。従来は url しか残しておらず、
#   後から「この候補は何だったのか」を引く手段が無かった (= 捨てた候補を新規出品の種に
#   戻す時に、URL を1件ずつ開くしかない)。実測で 144件中 32件が復元不能だった。
#   旧5列の行はそのまま残る (末尾2列が空)。
NG_CAND_HEADER = ["itemID", "cert", "url", "title", "日付", "候補タイトル", "候補価格"]

# ★2026-08-09: 「ラベルの表記は違うが同じカードの可能性が濃厚」の受け皿。
#   PSA は同じカードに複数の印字書式を使うため (OP09-050 ナミの実例: 現物 "ONE PIECE JPN." /
#   候補 "ONE PIECE OP09 JP")、書式差だけで「違う」を押すと **使える仕入元を捨てる**。
#   かといって「仕入れる」に倒すと誤変種を掴む。目視を止めずに保留できる第3の受け皿を置く。
#   NG タブに入れない = 次回も候補に出る (調べる前に捨てない)。調べ終わったら行を消す。
PROBE_TAB = "補URL要調査"
PROBE_HEADER = ["itemID", "cert", "url", "title", "現物の番号", "現物の変種", "日付",
                "候補タイトル", "候補価格"]   # ★2026-08-13 候補側も残す (NG_CAND と同じ理由)


def cand_info_by_url(candidates):
    """候補 list → {正規化URL: (タイトル, 価格)} (純関数)。

    「違う」「要調査」を押した時に**候補側の情報も台帳に残す**ために使う。
    押した瞬間しかこの情報は手元に無い (次回は検索し直しになる)。
    """
    out = {}
    for c in (candidates or []):
        u = (c or {}).get("url") or ""
        if u:
            out[_norm_url(u)] = ((c.get("name") or "")[:60], c.get("price") or "")
    return out


def _ng_urls_by_iid(rows):
    """候補NG台帳 → {itemID: {正規化URL}} (純関数)。"""
    out = {}
    for r in (rows[1:] if rows and len(rows) > 1 else []):
        if not r or len(r) < 3:
            continue
        iid, url = (r[0] or "").strip(), (r[2] or "").strip()
        if iid and url:
            out.setdefault(iid, set()).add(_norm_url(url))
    return out


def filter_candidates_used_by_others(cands, used_by_others, self_iid):
    """**他の出品が既に使っている**仕入元URLを候補から外す。戻り: (残す, 落とした)。純関数。

    従来は書込時にだけ弾いていたため、**捨てる前提の候補を人に見せて判断させていた**
    (2026-07-30 ユーザー指摘「さっきやったカードが出てくる」)。同じカードの別出品が
    並ぶと候補集合がほぼ同じになり、同じ目視を何度も繰り返すことになる。
    同一URLを2出品が指すと両方売れた時に履行不能 → キャンセル → Defect なので
    **どのみち書けない。見せない方が正しい**。
    """
    keep, drop = [], []
    for c in (cands or []):
        owners = set(used_by_others.get(_norm_url(c.get("url")), ())) - {self_iid}
        (drop if owners else keep).append(c)
    return keep, drop


def filter_candidates_rejected(cands, ng_urls):
    """過去に「違う」と判定された候補を除く。戻り: (残す, 落とした)。純関数。

    人が一度「別カード」と判断した出品は、次に見せても同じ判断になる。
    再提示は目視の無駄で、押し間違いの元でもある。
    """
    ng = set(ng_urls or ())
    keep, drop = [], []
    for c in (cands or []):
        (drop if _norm_url(c.get("url")) in ng else keep).append(c)
    return keep, drop


def _merge_ng_rows(existing_rows, new_rows, header):
    """候補NG行をマージ(純関数)。(itemID, url) 重複は新規優先。"""
    def key(r):
        return ((r[0] or "").strip(), _norm_url(r[2] if len(r) > 2 else ""))
    new_keys = {key(r) for r in new_rows if r and (r[0] or "").strip()}
    kept = [r for r in (existing_rows[1:] if existing_rows else [])
            if r and len(r) > 2 and (r[0] or "").strip() and key(r) not in new_keys]
    return [header] + kept + list(new_rows)


def _has_new_supply(seen_urls, current_urls):
    """前回外した時に見せた候補と比べて **新しい出品が出ているか**(純関数)。

    True = 出す価値がある (前回は無かった供給が市場に出た)。
    前回の記録が無い (旧形式の台帳行) 場合は True = 出す。
    「同じ候補しか無いのに毎日出す」を防ぎつつ、「新しく出たのに1週間出さない」も防ぐ。
    """
    cur = _norm_urls(current_urls)
    if not cur:
        return False                      # 候補ゼロ = 見せるものが無い
    seen = _norm_urls(seen_urls)
    if not seen:
        return True                       # 記録なし(旧行) → 出す
    return bool(cur - seen)


def _skip_row_active(reason, date_str, today):
    """その台帳行がまだ「再表示しない」期間内か(純関数)。

    日付が読めない行は **True (skip 継続)**。判定材料が無いのに再表示すると、
    毎回同じものが出続けて目視が信用されなくなるため (安全側)。
    """
    days = CONFIRM_SKIP_COOLDOWN_DAYS.get((reason or "").strip(), CONFIRM_SKIP_COOLDOWN_DEFAULT)
    try:
        import datetime
        age = (datetime.date.fromisoformat((today or "").strip())
               - datetime.date.fromisoformat((date_str or "").strip())).days
    except Exception:
        return True
    if age < 0:
        return True          # 未来日付 = 壊れている → 触らない
    return age < days


def _seen_urls_by_iid(rows):
    """台帳 → {itemID: [その時に見せた候補URL]} (純関数)。旧形式(5列)の行は空リスト。"""
    out = {}
    for r in (rows[1:] if rows and len(rows) > 1 else []):
        iid = (r[0] or "").strip() if r else ""
        if not iid:
            continue
        cell = r[5] if len(r) > 5 else ""
        out[iid] = [u.strip() for u in (cell or "").split("|") if u.strip()]
    return out


def _cache_candidate_urls(entry):
    """キャッシュ1件 → 今出せる候補URL(純関数)。新供給の有無を安く判定するための素。

    メルカリの all_cands/cands のみ見る (SNKRDUNK 側の増減は拾わない = 保守的)。
    """
    m = (entry or {}).get("mercari") or {}
    if not isinstance(m, dict):
        return []
    # ★2026-08-01: 厳密一致が0件のときは **番号未確認(名前一致のみ)** の枠も候補として数える。
    #   ここで拾わないと「候補なし」として確証UIに出ないまま埋もれる (実測39件がこの状態だった)。
    #   番号未確認である事実は _build_visual_candidates が number_ok=False で持ち回り、UI が明示する。
    rows = m.get("all_cands") or m.get("cands") or m.get("loose_cands") or []
    return [t[1] for t in rows if t and len(t) > 1 and t[1]]


def _skip_iids_from_tab(rows, today=None):
    """補URL確証スキップ タブ → 「今は再表示しない」itemID集合(純関数)。

    today を渡すと **cooldown 判定**する (期間を過ぎた行は集合に入らない = 再表示される)。
    today 省略時は従来どおり全行を対象 (後方互換)。
    台帳の行は消さない: 「いつ・なぜ外したか」の履歴は残す (再表示は判定だけで制御する)。
    """
    if not rows or len(rows) < 2:
        return set()
    out = set()
    for r in rows[1:]:
        if not r or not (r[0] or "").strip():
            continue
        if today is not None:
            reason = r[3] if len(r) > 3 else ""
            date_str = r[4] if len(r) > 4 else ""
            if not _skip_row_active(reason, date_str, today):
                continue          # cooldown 満了 → 再表示する
        out.add((r[0] or "").strip())
    return out


def _merge_skip_rows(existing_rows, new_rows, header):
    """既存スキップ行 + 新規(itemID重複は新規優先)を純関数マージ。"""
    new_iids = {(r[0] or "").strip() for r in new_rows if r and (r[0] or "").strip()}
    kept = [r for r in (existing_rows[1:] if existing_rows else [])
            if r and (r[0] or "").strip() and (r[0] or "").strip() not in new_iids]
    return [header] + kept + new_rows


def _ebay_itm_url(itemid):
    return f"https://www.ebay.com/itm/{itemid}" if itemid else ""


def backfill_status(rows2d):
    """live PSA を補URL本数でセグメント(純関数)= 件数感/進捗ダッシュボード用(slice4 フック1の素)。

    Returns {live_psa, b0(補0), b1_4(補1-4), full(満杯5), by_count:{0..5}}。
    「補あり(≥1) vs 補なし(0)」がファネル成績セグメント(取下率/live日数)の軸になる。
    """
    allt = select_backfill_targets(rows2d, max_backups=AUXN + 1)   # 補<6 = 満杯含む全 live PSA
    by = {}
    for t in allt:
        by[t["n_backups"]] = by.get(t["n_backups"], 0) + 1
    return {"live_psa": len(allt), "b0": by.get(0, 0),
            "b1_4": sum(by.get(k, 0) for k in range(1, AUXN)),
            "full": by.get(AUXN, 0), "by_count": {k: by.get(k, 0) for k in range(AUXN + 1)}}


def run_status(max_backups=1):
    """補URL充填の件数感 + キャッシュ確証待ちを1画面で(read-only)。"""
    import datetime
    today = datetime.date.today().isoformat()
    vals = _read_high()
    st = backfill_status(vals)
    print(f"=== 補URL充填 現在地 (live PSA {st['live_psa']}件) ===")
    print(f"  補なし(0本)  : {st['b0']}件  ← 充填の主対象(丸腰=仕入元1本切れで即取下げ)")
    print(f"  補あり(1-4本): {st['b1_4']}件")
    print(f"  満杯(5本)    : {st['full']}件")
    print(f"  本数内訳: " + " / ".join(f"{k}本={st['by_count'][k]}" for k in range(AUXN + 1)))
    # 当日〜窓内キャッシュで確証可能(=slice3 confirm で今出せる)件数
    cache = _load_cache()
    targets = select_backfill_targets(vals, max_backups=max_backups)
    ready = sum(1 for t in targets if _entry_fresh(cache.get(t["itemID"]), today))
    need = sum(1 for t in targets if not _entry_fresh(cache.get(t["itemID"]), today))
    print(f"\n=== 丸腰(補<{max_backups}) {len(targets)}件 の内訳 ===")
    # ★2026-08-15: 「確証待ち(キャッシュ済) 35件」のような**安い母数**は出さない。
    #   実際に押して出る数と10倍ずれ、空振りさせていた。足切りを通した実数を、
    #   **「今すぐ手が打てる」/「市場にその版が無い(待ち)」** の2分類で出す。
    #   内部の理由名 (all_art / all_ng …) をそのまま出すと「ん?」となるので和名にする。
    try:
        w = count_workload(max_backups=max_backups, today=today)
        cf = w["confirm"]
        sp = split_blocked(cf["blocked"])
        print(f"  ■ 今すぐ手が打てる : {cf['ready'] + cf['unjudged'] + sp['act']}件")
        if cf["ready"]:
            print(f"      目視で埋まる       {cf['ready']}件  → `confirm` (🩹ボタン)")
        if cf["unjudged"]:
            print(f"      絵柄を判定すれば   {cf['unjudged']}件  → 押すと判定される")
        for name, n in sp["act_detail"]:
            print(f"      {name:<18}{n}件")
        print(f"  ■ 市場にその版が無い(待ち) : {sp['wait']}件")
        for name, n in sp["wait_detail"]:
            print(f"      {name:<18}{n}件")
        print("      ※ こちらの作業では動きません。供給が出れば毎晩の巡回が拾います")
    except Exception as e:                                        # noqa: BLE001
        print(f"  (内訳を出せず: {type(e).__name__}) キャッシュ有 {ready} / 未検索 {need}"
              f"  ※これは足切り前の母数。実数ではない")


def plan_aux_writeback(confirmed, item_targets, vals, owner_by_url, guard_ok, aux_max=None,
                       price_by_url=None):
    """確定URL → 補URL書込計画 {row: [URL×5]} を決める **純関数**(I/Oなし・test可)。

    - guard_ok=False (= URL共有ガードを組めなかった) なら **何も書かない**。
      ガード無効のまま書くと、他出品が使用中の仕入元URLを掴み、両方売れた時に片方が
      履行不能 → キャンセル → Defect。「判定不能は skip、破壊的動作に倒さない」に従う。
    - guard_ok=True なら 他出品所有のURLを落とした上で、**既存と新規を合わせて安い順**に
      並べ直し 最大5本にする (2026-09-05。従来は既存保持+空き枠のみだったので、
      補が埋まっている出品には もっと安い供給が1本も入らなかった)。
    price_by_url: {idx: {正規化URL: 価格}}。値段の分かるURLだけが安い順に前へ出る。
    戻り: (aux_writeback{row: [5要素]}, 追加URL総数,
           他出品所有で落としたURL [(url, [owner...])], 押し出した既存 [(itemID, url)])
    """
    aux_max = aux_max or AUXN
    if not guard_ok:
        return {}, 0, [], []
    import dup_guard as _dg
    aux_writeback, added_total, dropped_all, replaced_all = {}, 0, [], []
    for idx, urls in confirmed.items():
        t = item_targets[idx]
        row = t["row"]
        r = vals[row - 1] if 0 < row <= len(vals) else []
        urls, dropped = _dg.filter_urls_owned_by_others(urls, owner_by_url, _cell(r, B))
        dropped_all.extend(dropped)
        existing = [u for u in (_cell(r, AUX0 + k) for k in range(aux_max)) if u]
        full, added, removed = rank_backurls(existing, urls,
                                             (price_by_url or {}).get(idx), aux_max)
        # 並びが変わっただけでも書く (安い順に持ち直すのが目的なので)
        if added or removed or full != existing:
            aux_writeback[row] = full
            added_total += len(added)
            replaced_all.extend((t.get("itemID"), u) for u in removed)
    return aux_writeback, added_total, dropped_all, replaced_all


def build_confirm_context(vals, cache, today, verbose=False):
    """confirm の前提 (skip台帳 / 候補NG / 他出品が使用中のURL) を1回だけ作る。

    ★2026-08-09: **ラベルの件数と本番 confirm が同じ前提を見る**ための1本化。
      別々に数えていたせいで、パネルが「目視待ち32件」と出して実際に出るのは3件だった。
      件数は段取りを決めるために見るものなので、母数を件数として出してはいけない。
    """
    try:
        from sheet_io import read_tab
        _skip_rows = read_tab(CONFIRM_SKIP_TAB)
        skip_iids = _skip_iids_from_tab(_skip_rows, today=today)
        _all_skip = _skip_iids_from_tab(_skip_rows)
        _seen_urls = _seen_urls_by_iid(_skip_rows)
        revived = len(_all_skip) - len(skip_iids)
        # ★新供給が出ていれば cooldown 中でも出す (前回見せた候補に無いURLが在る)。
        newsupply = {i for i in skip_iids
                     if _has_new_supply(_seen_urls.get(i), _cache_candidate_urls(cache.get(i)))}
        skip_iids -= newsupply
    except Exception:
        skip_iids, revived, newsupply = set(), 0, set()
    try:
        from sheet_io import read_tab
        ng_by_iid = _ng_urls_by_iid(read_tab(NG_CAND_TAB))
    except Exception:
        ng_by_iid = {}
    # ★他の出品が既に使っているURLは、目視に出す前に外す (どのみち書けない・2026-07-30)。
    used_by_others, guard_ok = {}, True
    try:
        import dup_guard as _dg0
        for _r in vals[1:]:
            _iid0 = _cell(_r, B)
            if not (_iid0 and not _cell(_r, D)):      # live 出品のみ
                continue
            for _u0 in [_cell(_r, A)] + [_cell(_r, AUX0 + k) for k in range(AUXN)]:
                _n0 = _dg0.norm_url(_u0)
                if _n0:
                    used_by_others.setdefault(_n0, set()).add(_iid0)
    except Exception as _e0:
        if verbose:
            print(f"  ⚠ 使用中URLマップを作れず、表示前の除外はskip ({type(_e0).__name__})")
        used_by_others, guard_ok = {}, False
    if verbose:
        if revived:
            print(f"  ♻ cooldown 満了 {revived}件 → 再表示対象に復帰 (台帳の行は残す)")
        if newsupply:
            print(f"  🆕 新しい供給が出た {len(newsupply)}件 → cooldown 中だが再表示する")
    return {"skip_iids": skip_iids, "ng_by_iid": ng_by_iid, "used_by_others": used_by_others,
            "revived": revived, "newsupply": newsupply, "guard_ok": guard_ok}


# 足切りで止まった理由。**ラベル・status_now・confirm のログが同じ語彙を使う**。
STOP_REASONS = ("skip_ledger", "no_cache", "no_cand", "no_cardno",
                "all_known", "all_number", "all_ng", "all_used", "no_ref", "all_art")

# ★2026-08-15 ユーザー指示「そういう分類にしてくれないと、ん?ってなる」。
#   内部の理由名 (all_art / all_ng / no_cand …) をそのまま出していたので読めなかった。
#   1件ずつ画像で確かめた結果、これらの大半は **その版が市場に出ていない** という
#   同じ1つの事情だった (実証: ステューシー OP07-085 の候補3件は全部 OP11 の
#   SPECIAL ALTERNATE ART = 別カード。人の「違う」判断は正しかった)。
#   なので **「待ち」か「手が打てる」か** の2つに畳んで出す。
WAIT_REASONS = ("all_art", "all_ng", "no_cand", "all_known", "all_used")   # 市場にその版が無い
ACT_REASONS = ("no_cache", "all_number", "no_cardno", "skip_ledger")       # こちらで動かせる
_REASON_JA = {"all_art": "絵柄が別カード", "all_ng": "過去に別カードと確認済",
              "no_cand": "候補が出ない", "all_known": "候補が主URLと同じ",
              "all_used": "既に使用済", "no_cache": "未検索(今夜の巡回で解決)",
              "all_number": "番号違い", "no_cardno": "カード番号が取れない",
              "skip_ledger": "見送り中(翌日復活)", "no_ref": "現物画像が無い"}


def split_blocked(blocked):
    """止まっている理由を「市場待ち / 手が打てる」に畳む (純関数)。

    Returns: {"wait": n, "act": n, "wait_detail": [(和名, n)], "act_detail": [...]}
    """
    b = blocked or {}

    def _d(keys):
        return [(_REASON_JA.get(k, k), int(b.get(k) or 0)) for k in keys if b.get(k)]
    wd, ad = _d(WAIT_REASONS), _d(ACT_REASONS)
    return {"wait": sum(n for _, n in wd), "act": sum(n for _, n in ad),
            "wait_detail": sorted(wd, key=lambda x: -x[1]),
            "act_detail": sorted(ad, key=lambda x: -x[1])}


def confirm_survivors(t, vals, cache, ctx, today, *, ref_of, art_of, stats):
    """1件ぶんの足切りを通し (残った候補, ref, 止まった理由, 絵柄で落ちた候補) を返す。

    ref_of(t)->画像URL / art_of(ref, cands, t)->(keep, dropped) を差し替えられる:
      - 本番 confirm  = eBay GetItem + 絵柄判定(API)
      - 件数の計算    = ディスクキャッシュのみ (APIを呼ばない)
    どちらも **この関数を通る** ので、件数と実際に出る件数がずれない (2026-08-09)。
    """
    iid = t["itemID"]
    if iid in ctx["skip_iids"]:
        stats["skip_ledger"] += 1
        return [], "", "skip_ledger", []
    entry = cache.get(iid)
    if not _entry_fresh(entry, today):   # 夜検索→翌朝確認の日跨ぎOK(same-dayより緩い窓)
        stats["no_cache"] += 1
        return [], "", "no_cache", []
    mr = entry.get("mercari") or {}
    import psa_resource_gate as gate
    c = gate.combine(mr.get("best"), entry.get("snkrdunk"),
                     mercari_cands=mr.get("cands"), max_aux=AUXN)
    cands = gate._build_visual_candidates(mr, c)
    if not cands:
        stats["no_cand"] += 1
        return [], "", "no_cand", []
    # ★fail-closed: card_no が今取れない(探索不能)= stale cache の誤候補リスク(別カード/別ジャンル)
    import mercari_psa_resource as mp
    cn = build_search_query(t, mp).get("card_no") or ""
    if not cn:
        stats["no_cardno"] += 1
        return [], "", "no_cardno", []
    # ★既に自分が使っている供給(主URL/既存補URL)は出さない = 目視が成立しない
    _row0 = t.get("row")
    _rv0 = vals[_row0 - 1] if (_row0 and 0 < _row0 <= len(vals)) else []
    _known = [_cell(_rv0, A)] + [_cell(_rv0, AUX0 + k) for k in range(AUXN)]
    cands, dropped_known = filter_candidates_known_urls(cands, _known)
    stats["cand_known"] += len(dropped_known)
    if not cands:
        stats["all_known"] += 1
        return [], "", "all_known", []
    cands, dropped = filter_candidates_by_number(cands, cn)
    stats["cand_number"] += len(dropped)
    if not cands:
        stats["all_number"] += 1
        return [], "", "all_number", []
    # ★過去に人が「違う」と判定した候補は二度と出さない
    cands, dropped_ng = filter_candidates_rejected(cands, ctx["ng_by_iid"].get(iid))
    stats["cand_ng"] += len(dropped_ng)
    if not cands:
        stats["all_ng"] += 1
        return [], "", "all_ng", []
    if ctx["used_by_others"]:
        _keep, _drop = filter_candidates_used_by_others(cands, ctx["used_by_others"], iid)
        stats["cand_used"] += len(_drop)
        cands = _keep
        if not cands:
            stats["all_used"] += 1
            return [], "", "all_used", []
    ref = ref_of(t)
    if not ref:
        stats["no_ref"] += 1
        return [], "", "no_ref", []
    cands, dropped_art = art_of(ref, cands, t)
    stats["cand_art"] += len(dropped_art)
    if not cands:
        stats["all_art"] += 1
        return [], ref, "all_art", dropped_art
    return cands, ref, "", dropped_art


def prime_ref_images(targets, verbose=True):
    """対象の現物画像URLをディスクキャッシュに焼く (GetItem を1回ずつ)。

    ★これをやっておくと、あとは **API 無しで「目視できる件数」を正確に数えられる**。
      夜間検索の最後に回す = 朝ボタンを見た時点でラベルが正しい (2026-08-09)。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import psa_resource_confirm as prc
    todo = [t for t in targets if not prc.ref_image_known(t["itemID"])]
    if not todo:
        return 0
    if verbose:
        print(f"▶ 現物画像URLを {len(todo)}件 取得 (件数表示を正確にするため)", flush=True)
    got = 0
    for t in todo:
        if prc.ebay_listing_image(t["itemID"]):
            got += 1
    if verbose:
        print(f"  現物画像 {got}/{len(todo)}件 取得", flush=True)
    return got


def count_workload(max_backups=None, today=None, confirm_max_backups=None):
    """『押したら何件できるか』を **API/スクレイプ無し** で数える (SSOT)。

    パネルのボタンラベルと status_now が両方これを使う。返り値:
      {"targets", "search": {...}, "confirm": {...}}

    ★confirm 側は本番と同じ足切り (confirm_survivors) を通す。絵柄判定は
      **判定済みキャッシュだけ**読み、未判定は "unjudged" として別に数える
      (押すまで確定しないものを「できる件数」に混ぜない)。
    ★search 側は「探索不能(card番号が取れない)」を除く。ここを混ぜていたため
      「未探索10件」と出して実際に検索できたのは2件だった (2026-08-09 実測)。
    """
    import datetime
    import collections
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mercari_psa_resource as mp
    import psa_art_match as art
    import psa_resource_confirm as prc

    # ★2026-09-05: 探す側と目視側で対象の広さが違う (探す=丸腰優先 / 目視=満杯未満)。
    #   1本の targets で両方数えるとボタンのラベルが実際に出る件数と食い違う。
    max_backups = SEARCH_MAX_BACKUPS if max_backups is None else max_backups
    confirm_max_backups = (CONFIRM_MAX_BACKUPS if confirm_max_backups is None
                           else confirm_max_backups)
    today = today or datetime.date.today().isoformat()
    vals = _read_high()
    targets = select_backfill_targets(vals, max_backups=max_backups)
    c_targets = select_backfill_targets(vals, max_backups=confirm_max_backups)
    cache = _load_cache()
    live = len(select_backfill_targets(vals, max_backups=AUXN + 1))

    # --- 検索(slice2) 側 ---
    s_can = s_nocardno = s_done = 0
    for t in targets:
        if _entry_complete(cache.get(t["itemID"]), today):
            s_done += 1
        elif (build_search_query(t, mp).get("card_no") or ""):
            s_can += 1
        else:
            s_nocardno += 1

    # --- 目視(slice3) 側 ---
    ctx = build_confirm_context(vals, cache, today)
    acache = art.load_cache()
    stats = collections.Counter()

    unknown_ref = set()

    def _ref_of(t):
        """ディスクキャッシュのみ (API を叩かない)。

        まだ一度も取りに行っていない出品は、本番がどの画像を使うか分からない
        = 絵柄判定のキーも決まらないので **未判定扱い**にする (勝手に cert 画像で
        代用すると別のキーになり、判定済みでも「未判定」に見える)。
        """
        if not prc.ref_image_known(t["itemID"]):
            unknown_ref.add(t["itemID"])
        return (prc.ebay_listing_image(t["itemID"], allow_fetch=False)
                or prc.psa_image_for_cert(t.get("cert") or None))

    def _art_of(ref, cands, t):
        if t["itemID"] in unknown_ref:      # ref が未知 = 判定キーが決まらない
            return [dict(c, _art_unjudged=True) for c in cands], []
        keep, dropped = [], []
        for c in cands:
            hit = art.cached_verdict(ref, c.get("image") or c.get("url") or "",
                                     c.get("name") or "", acache)
            if hit is None:
                stats["cand_art_unjudged"] += 1
                c = dict(c, _art_unjudged=True)
                keep.append(c)
            elif art.drop_reason(hit):
                dropped.append(c)
            else:
                keep.append(c)
        return keep, dropped

    ready = unjudged = 0
    for t in c_targets:
        cands, _ref, _why, _ = confirm_survivors(
            t, vals, cache, ctx, today, ref_of=_ref_of, art_of=_art_of, stats=stats)
        if not cands:
            continue
        if any(c.get("_art_unjudged") for c in cands):
            unjudged += 1        # 判定待ちが混ざる = 押すまで出るか確定しない
        else:
            ready += 1
    return {"live_psa": live, "targets": len(targets),
            "confirm_targets": len(c_targets),
            "search": {"can": s_can, "no_cardno": s_nocardno, "done": s_done},
            "confirm": {"ready": ready, "unjudged": unjudged,
                        "blocked": {k: stats[k] for k in STOP_REASONS}}}


def run_daytime_confirm(max_backups=None, limit=None, dry_run=False):
    """昼の確認(impure)。slice2 が焼いた当日キャッシュから候補を出し、現物と視覚確証→
    確定URLを補URL(AC-AG)へ **安い順に最大5本** 書く(2026-09-05)。主URL(A)は触らない。

    - 対象 = 補<閾値 (既定 CONFIRM_MAX_BACKUPS = 満杯未満) の live PSA で、
      当日キャッシュに候補がある行(=slice2 で在庫確認済)。補が少ない行から出る。
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
    max_backups = CONFIRM_MAX_BACKUPS if max_backups is None else max_backups
    vals = _read_high()
    targets = select_backfill_targets(vals, max_backups=max_backups)
    cache = _load_cache()

    # ★前提(skip台帳 cooldown / 候補NG / 他出品が使用中のURL)は build_confirm_context に1本化。
    #   ラベルの件数計算も同じものを使う = 「32件と出て3件しか出ない」を構造的に防ぐ。
    import collections
    ctx = build_confirm_context(vals, cache, today, verbose=True)
    skip_iids = ctx["skip_iids"]
    stats = collections.Counter()

    # 当日キャッシュに候補がある対象だけを確証items化(idx=items内index→書込時に target へ戻す)
    items, item_targets = [], []
    art_all_dropped = 0
    art_dropped_log = []
    try:
        import psa_art_match as _art
        _art_cache = _art.load_cache() if _art._load_key() else None
        if _art_cache is None:
            print("  ⚠️ APIキーが無いため絵柄判定はスキップ (全候補を目視へ)")
    except Exception as _e_art:
        print(f"  ⚠️ 絵柄判定モジュール読込失敗 → skip ({type(_e_art).__name__})")
        _art, _art_cache = None, None
    # ★進捗を出す (2026-08-09)。ここは 1件ずつ eBay 画像取得 + 絵柄をAI照合するため
    #   対象が多いと **10分近く無言**になる。実際それを「ハングした」と誤診し、
    #   原因調査に時間を溶かした。動いていることが見えれば起きない誤解。
    print(f"▶ 目視候補を組み立て中… 対象 {len(targets)}件 "
          f"(1件ごとに 現物画像の取得 + 絵柄の照合。時間がかかります)", flush=True)
    def _ref_of(t):
        return (prc.ebay_listing_image(t["itemID"])
                or prc.psa_image_for_cert(t.get("cert") or None))

    def _art_of(ref, cands, t):
        """本番の絵柄判定 (API)。判定不能は全候補を目視へ = 捨てる方向に倒さない。"""
        if _art_cache is None:
            return cands, []
        # 現物の確定情報 (catalog/PSA) を渡す = モデルに推測させず「正」を与える
        try:
            _facts = dict(prc.psa_label_facts(t.get("cert"), t["_card_no"]))
            _facts["set_name"] = (mp.card_meta_for_key(t.get("key")) or {}).get("set") or ""
        except Exception:
            _facts = {}
        try:
            return _art.annotate_candidates(ref, cands, cache=_art_cache, ref_facts=_facts)
        except Exception as _e:
            print(f"  ⚠️ 絵柄判定 失敗(非致命・全候補を目視へ): {type(_e).__name__}: {_e}")
            return cands, []

    _scanned = 0
    for t in targets:
        _scanned += 1
        if _scanned % 10 == 0 or _scanned == len(targets):
            print(f"   … {_scanned}/{len(targets)}件 走査 "
                  f"(確証対象 {len(items)}件 / 除外 絵柄{stats['cand_art']}・"
                  f"既知{stats['cand_known']}・番号不一致{stats['cand_number']}・"
                  f"使用中{stats['cand_used']})", flush=True)
        iid = t["itemID"]
        # ★足切りは confirm_survivors に1本化 (2026-08-09)。ラベルの件数計算も同じ関数を通る
        #   ので、「目視待ち32件」と出して3件しか出ない、が構造的に起きない。
        t["_card_no"] = build_search_query(t, mp).get("card_no") or ""
        cands, ref, why, _dropped_art = confirm_survivors(
            t, vals, cache, ctx, today, ref_of=_ref_of, art_of=_art_of, stats=stats)
        for _c in _dropped_art:
            art_dropped_log.append((iid, _c.get("url", ""),
                                    _c.get("drop_why") or _c.get("art_reason", "")))
        if why == "all_art":
            art_all_dropped += 1
        if not cands:
            continue
        cn = t["_card_no"]
        idx = len(items)
        # 多変種(同番号で catalog に2変種以上=別アート/色/パラレル/Gold)か → UI に⚠️バッジ出す。
        # 単一変種は番号一致=正なので流し見でOK、多変種だけ絵柄を要確認(「違う」の主因はここ)。
        _mv = False
        try:
            # カテゴリで絞る(別作品の同番号を変種として数えない・2026-07-29)
            _mv = bool(mp._is_multi_variant(cn, mp.split_key(t.get("key"))[0])) if cn else False
        except Exception:
            _mv = False
        # 現在の仕入れ値(N=col13)+現在価格(M=col12)をカードに表示 → 候補価格と見比べて「今より安い供給か」が分かる。
        _row = t.get("row")
        _rv = vals[_row - 1] if (_row and 0 < _row <= len(vals)) else []
        _cost_now = (_cell(_rv, 13) or "")   # N=仕入れ値
        _price_now = (_cell(_rv, 12) or "")   # M=現在価格
        # ★同じカード(KEY)の別出品が対象に居ると、候補がほぼ同じで「さっきやった」に見える。
        #   別物であることを明示する (2026-07-30 ユーザー指摘)。
        _sib = [x["itemID"] for x in targets
                if x is not t and (x.get("key") or "") and x.get("key") == t.get("key")]
        # ★2026-08-02: 目視照合の「揺れない材料」(番号 / 変種名)を画面に出す。
        #   PSA の印字ラベルは同じカードでも書式が複数あり (例: "ONE PIECE JPN. / OP09-ALTERNATE ART"
        #   と "ONE PIECE OP09 JP / ALTERNATE ART" は同一カード)、ラベルの見た目が違うだけで
        #   人が「違う」を押してしまう = 使える仕入元を捨てる。
        try:
            _lab = prc.psa_label_facts(t.get("cert"), cn)
        except Exception:
            _lab = {}
        items.append({"idx": idx, "title": (t.get("title") or "")[:90], "card_no": cn,
                      "ebay_url": _ebay_itm_url(iid), "ref_image": ref, "candidates": cands,
                      "multi_variant": _mv, "cost_now": _cost_now, "price_now": _price_now,
                      "siblings": _sib, "psa_label": _lab})
        item_targets.append(t)

    no_cache, no_cand = stats["no_cache"], stats["no_cand"]
    no_cardno, no_ref = stats["no_cardno"], stats["no_ref"]
    no_cand_after_filter = (stats["all_known"] + stats["all_number"] + stats["all_ng"]
                            + stats["all_used"] + stats["all_art"])
    print(f"昼確認: 対象(補<{max_backups}) {len(targets)}件 / キャッシュ未取得skip {no_cache} / "
          f"候補なしskip {no_cand} / 探索不能skip {no_cardno} / 現物画像なしskip {no_ref} / "
          f"既知URL除外 {stats['cand_known']}候補 / 番号不一致で除外 {stats['cand_number']}候補 / "
          f"過去に「違う」除外 {stats['cand_ng']}候補 / "
          f"他出品が使用中で除外 {stats['cand_used']}候補 / "
          f"絵柄が明らかに別で除外 {stats['cand_art']}候補"
          f"(全滅skip {no_cand_after_filter}件) / "
          f"台帳skip {stats['skip_ledger']} → 確証対象 {len(items)}件")
    # ★省いた分は必ず表に出す (silent drop 禁止)。誤って捨てていないか人が検算できるようにする。
    if art_dropped_log:
        _tail = f" (うち全候補が別で {art_all_dropped}件は対象外)" if art_all_dropped else ""
        print(f"  🎨 絵柄が明らかに別で省いた {len(art_dropped_log)}候補{_tail}:")
        for _iid, _u, _r in art_dropped_log[:15]:
            print(f"     - {_iid} {_u} … {_r}")
        if len(art_dropped_log) > 15:
            print(f"     … 他 {len(art_dropped_log) - 15}候補")
    # same/unsure も含めて判定結果は保存 (同じ組を再問合せしない)
    if _art_cache is not None:
        _art.save_cache(_art_cache)
    # ★目視の残件を必ず出す (2026-08-09 ユーザー要望)。
    #   limit で切ると「今回出す分」しか見えず、**あと何件残っているか分からない**。
    #   45件残っているのに10件見て終わりだと、終わったつもりで放置される。
    _ready = len(items)
    if limit is not None:
        items, item_targets = items[:limit], item_targets[:limit]
        for n, it in enumerate(items):
            it["idx"] = n
        _rest = _ready - len(items)
        print(f"  (limit={limit} → 今回 {len(items)}件 / 目視対象 計 {_ready}件"
              + (f" / **残り {_rest}件は次回以降**" if _rest else " / 残りなし") + ")")
    else:
        _rest = 0
        print(f"  目視対象 計 {_ready}件 (limit 指定なし=全部出す)")

    # ★「目視残」を最後にまとめて出す (2026-08-09 ユーザー要望)。
    #   残は2種類あり、性質が違うので分けて書く:
    #     ① 目視すれば片づく残り  … 次回以降このコマンドを回せば消える
    #     ② 目視しても片づかない残 … 候補が1本も作れず**画面に出ない**ので、
    #        人が何回まわしても永久に残る。card番号が取れない(catalog/KEY 待ち)。
    #        ここを黙って落とすと「補URLゼロのまま放置」が見えなくなる。
    _stuck = no_cardno + no_cache + no_cand + no_cand_after_filter + no_ref
    print("──── 目視残 ────")
    print(f"  ① 目視で片づく残り      : {_rest}件"
          + (f"  (このコマンドをあと {-(-_rest // limit)}回で消化)" if (_rest and limit) else ""))
    print(f"  ② 目視しても出てこない残: {_stuck}件  ← 画面に出ないので何回まわしても減らない")
    if _stuck:
        print(f"       内訳: 探索不能(card番号取れず) {no_cardno} / キャッシュ未取得 {no_cache} / "
              f"候補なし {no_cand} / 絞り込みで全滅 {no_cand_after_filter} / 現物画像なし {no_ref}")
        if no_cardno:
            print(f"       ★探索不能 {no_cardno}件 は catalog/KEY の補完待ち。人手では解消しない")
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
    # ★ 他出品が既に使っている仕入元URLは書かない(2026-07-26)。同じURLを2出品が指すと
    #   両方売れた時に片方が履行不能 → キャンセル → Defect。補URL充填はこの事故の主な入口。
    # ★ ガードを組めなかった時は **書かない**(2026-07-26 監査指摘)。
    #   ガード無効のまま書込を続けると、他出品が使用中のURLを掴んで両売れ→履行不能→Defect。
    #   「判定不能は skip、破壊的動作に倒さない」(failclosed_must_skip_not_destructive) に従う。
    #   補URLは足せなくても出品は死なない(既存供給は残る)ので、skip の損失は小さい。
    _guard_ok, _owner_by_url = True, {}
    try:
        import dup_guard as _dg
        for _r in vals[1:]:
            if not (_cell(_r, B) and not _cell(_r, D)):
                continue
            for _u in [_cell(_r, A)] + [_cell(_r, AUX0 + k) for k in range(AUXN)]:
                _n = _dg.norm_url(_u)
                if _n:
                    _owner_by_url.setdefault(_n, set()).add(_cell(_r, B))
        _owner_by_url = {k: sorted(v) for k, v in _owner_by_url.items()}
    except Exception as _e_dg:
        print(f"⚠️要対応 URL共有ガードを組めず **補URL書込を中止**: {type(_e_dg).__name__}: {_e_dg}")
        _guard_ok = False

    # ★2026-09-05: 値段を渡す。既存と新規を **合わせて安い順**に持ち直すため
    #   (値段が分かるのは「今日の候補に出ている URL」だけ)。
    _price_by_idx = {}
    for _i in confirmed:
        _price_by_idx[_i] = {
            _u: _p for _u, (_n, _p) in
            cand_info_by_url((items[_i] or {}).get("candidates") if _i < len(items) else None).items()
            if isinstance(_p, int) and _p > 0
        }
    aux_writeback, added_total, dropped, replaced = plan_aux_writeback(
        confirmed, item_targets, vals, _owner_by_url, _guard_ok,
        price_by_url=_price_by_idx)
    for _u, _own in dropped:
        print(f"  ⛔ 補URL除外(他出品が使用中 {_own}): {_u[:70]}")
    for _iid, _u in replaced:
        print(f"  ♻ 補URL入替(もっと安いのが5本そろった) {_iid}: {_u[:70]}")
    written = 0
    if not _guard_ok:
        print("  (ガード不成立のため書込0行。確証結果は台帳に残るので再実行で復帰できます)")
    elif aux_writeback:
        try:
            from sheet_io import write_aux_urls
            written = write_aux_urls(aux_writeback)
            print(f"🔗 補URL(AC-AG) 書込: {written}行 / 追加URL {added_total}本 "
                  f"/ 入替 {len(replaced)}本 (安い順に最大{AUXN}本)")
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
            # ★その時に見せた候補URLを残す。次回「新しい供給が出たか」を判定する唯一の材料。
            # これが無いと cooldown 明けに同じ候補をまた見せることになる。
            _shown = " | ".join(c.get("url", "") for c in (items[idx].get("candidates") or [])
                                if c.get("url"))
            new_skip.append([t["itemID"], t.get("cert", ""), (t.get("title") or "")[:60],
                             reason, today, _shown])
        try:
            from sheet_io import read_tab, write_rows_to_tab
            merged = _merge_skip_rows(read_tab(CONFIRM_SKIP_TAB), new_skip, CONFIRM_SKIP_HEADER)
            write_rows_to_tab(CONFIRM_SKIP_TAB, merged)
            print(f"  📝 {CONFIRM_SKIP_TAB}: +{len(new_skip)}件 記録(次回は再表示しない・再検討は同タブ行削除)")
        except Exception as e:
            print(f"  ⚠ {CONFIRM_SKIP_TAB} 記録skip ({type(e).__name__}: {e})")
    # --- 候補単位の「違う」を負例として台帳へ (2026-07-29) ---
    # ここが無いと、出品自体が確定した場合に「違う」の1クリックが警告1行で消えていた
    # (次回また同じ別カードが候補に並ぶ)。押した判断は必ず次回に効かせる。
    _ng_new = []
    for d in (res.get("diffs") or []):
        _i, _u = d.get("idx"), (d.get("url") or "").strip()
        if _i is None or not _u or _i >= len(item_targets):
            continue
        _t = item_targets[_i]
        # ★候補側の情報も残す。押した瞬間しか手元に無い (2026-08-13)
        _ci = cand_info_by_url((items[_i] or {}).get("candidates")) if _i < len(items) else {}
        _ct, _cp = _ci.get(_norm_url(_u), ("", ""))
        _ng_new.append([_t["itemID"], _t.get("cert", ""), _u, (_t.get("title") or "")[:60],
                        today, _ct, _cp])
    if _ng_new:
        try:
            from sheet_io import read_tab, write_rows_to_tab
            write_rows_to_tab(NG_CAND_TAB,
                              _merge_ng_rows(read_tab(NG_CAND_TAB), _ng_new, NG_CAND_HEADER))
            print(f"  🚫 {NG_CAND_TAB}: +{len(_ng_new)}件 記録"
                  f"(この出品にこのURLは次回から出さない・復活は同タブ行削除)")
        except Exception as e:
            print(f"  ⚠ {NG_CAND_TAB} 記録skip ({type(e).__name__}: {e})")
    if diffs:
        print(f"🚨 「違う」{len(diffs)}件 = 検索が別カード/別変種を拾った精度事故。"
              "slice2 の検索(kw/variant_hint)を要修正(残存=精度事故の放置)。")

    # ★「ラベルの表記は違うが同じカードの可能性が濃厚」= 後で調べる印 (2026-08-09 ユーザー要望)。
    #   NG には落とさない。NG にすると次回から候補に出なくなり、**調べる前に捨てる**ことになる。
    #   見送りにも混ぜない (見送りは business 判断で、調査対象ではない)。専用タブに残す。
    _probe_new = []
    for _p in (res.get("probes") or []):
        _i = _p.get("idx")
        _u = (_p.get("url") or "").strip()
        if _i is None or _i >= len(item_targets) or not _u:
            continue
        _t = item_targets[_i]
        _lab = (_t.get("psa_label") or {}) if isinstance(_t.get("psa_label"), dict) else {}
        _ci = cand_info_by_url((items[_i] or {}).get("candidates")) if _i < len(items) else {}
        _ct, _cp = _ci.get(_norm_url(_u), ("", ""))
        _probe_new.append([_t["itemID"], _t.get("cert", ""), _u,
                           (_t.get("title") or "")[:60],
                           _lab.get("number", ""), _lab.get("variety", ""), today, _ct, _cp])
    if _probe_new:
        try:
            from sheet_io import read_tab, write_rows_to_tab
            _cur = read_tab(PROBE_TAB)
            _seen = {(r[0], r[2]) for r in (_cur[1:] if _cur else []) if len(r) > 2}
            _add = [r for r in _probe_new if (r[0], r[2]) not in _seen]
            if _add:
                write_rows_to_tab(PROBE_TAB, ([PROBE_HEADER] + (_cur[1:] if _cur else []) + _add))
            print(f"  🔎 {PROBE_TAB}: +{len(_add)}件 記録"
                  f"(ラベル表記は違うが同じかも。補URLには書いていない・調べたら行を消す)")
        except Exception as e:
            print(f"  ⚠ {PROBE_TAB} 記録skip ({type(e).__name__}: {e})")

    print(f"✅ 昼確認完了: 確証{len(confirmed)}件 → 補URL {written}行に {added_total}本追記。")
    return {"confirmed": len(confirmed), "written_rows": written, "added_urls": added_total}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # slice2: `search` で夜間検索。slice3: `confirm` で昼確認→補URL書込。無引数=slice1 件数レポート。
    if "search" in sys.argv:
        max_backups, limit, fresh, commit_batch, min_reviews = 1, None, False, 8, 100
        for a in sys.argv[1:]:
            if a.startswith("--max-backups="):
                max_backups = int(a.split("=", 1)[1])
            elif a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
            elif a.startswith("--commit-batch="):
                commit_batch = int(a.split("=", 1)[1])
            elif a.startswith("--min-reviews="):
                min_reviews = int(a.split("=", 1)[1])
            elif a == "--fresh":
                fresh = True
        run_night_search(max_backups=max_backups, limit=limit, fresh=fresh,
                         commit_batch=commit_batch, min_reviews=min_reviews)
        return
    if "search-restock" in sys.argv:
        # 再仕入れ候補(ファネル RESTOCK∩PSA10)の先読み。共有キャッシュを温めるだけで、
        # スプシにも補URL列にも書かない(判定は「🃏 PSA再仕入れ照合」ボタンの有人ゲートのまま)。
        limit = 20
        for a in sys.argv[1:]:
            if a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
        # --limit=0 = 全件。夜のうちに全部温めておけば、朝のボタンは探さずに出せる
        # (2026-09-03 ユーザー指示「全件やれば」)。当日済 skip と空振り台帳が効くので
        # 実際に叩く数はこれより少ない。
        limit = None if limit == 0 else limit
        tg = restock_targets()
        print(f"RESTOCK候補 {len(tg)}件 を先読み(limit={limit if limit else '全件'})")
        if tg:
            run_night_search(targets=tg, limit=limit)
        return
    if "confirm" in sys.argv:
        max_backups, limit, dry = CONFIRM_MAX_BACKUPS, None, "--dry-run" in sys.argv
        for a in sys.argv[1:]:
            if a.startswith("--max-backups="):
                max_backups = int(a.split("=", 1)[1])
            elif a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
        run_daytime_confirm(max_backups=max_backups, limit=limit, dry_run=dry)
        return
    if "workload" in sys.argv:
        # ボタンのラベル / status_now が使う件数を JSON で1行。**API/スクレイプ無し**。
        import json as _json
        print(_json.dumps(count_workload(), ensure_ascii=False))
        return
    if "status" in sys.argv:
        run_status()
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
