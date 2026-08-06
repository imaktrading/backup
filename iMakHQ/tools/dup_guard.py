# -*- coding: utf-8 -*-
"""dup_guard — 出品の重複ガード (2026-07-26)。

## なぜ要るか (2026-07-26 実測で判明した穴)
- 商品管理シートの KEY(AI列) が空の live 行が ACTIVE 386 中 80 あり、重複くん(dedupe)は
  「KEY空=判定不能」で **素通り**(fail-OPEN)していた。結果、同一カードが2枠 live に:
  ガンダム RP-028 (cert 154708661 / 154708662) が 7/06・7/07 に連続出品された。
- ただし実害の本体は「同一カード」ではない。**同じ仕入元URLを2出品が指す**と、両方売れた時に
  片方が履行不能 → キャンセル → Defect (無在庫の生命線)。同一カードでも仕入元が別なら健全。
  → 本モジュールは **URL共有=致命 / 同一カード=注意** の2段で見る。
- 同一カードは止めない (listing を勝手に絞らない原則)。検出→警告→台帳。
- ★2026-08-03 追加: **同一 cert (= 同じ現物) が既に出品済**の行だけは別格で、
  pre_upload が **物理除外**する。二度売れたら片方は必ず履行できないため
  (NO-GO 行を物理削除するのと同じ扱い)。同一カードの2枚目とは切り分ける。

## 提供するもの
- 純関数: card_token_from_title / norm_url / shared_supply_urls / live_card_index /
          dup_candidates / filter_urls_owned_by_others
- I/O   : audit()          … 全 ACTIVE を棚卸し(URL共有 + 同一カード) + live titles cache 更新
          pre_upload(csv)  … 入稿前 CSV を live と突合して警告 + 台帳
          fill_keys_from_titles(csv) … KEY空 & タイトルの #ID が catalog に完全一致する行に KEY を書く
                                       (dedupe resolver が解けない DON!! 等の救済。ID完全一致のみ=fail-closed)

CLI:
  python tools/dup_guard.py --audit
  python tools/dup_guard.py --pre-upload <csv>
  python tools/dup_guard.py --fill-keys <csv> [--dry]
"""
import csv
import json
import os
import re
import sys
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io

A, B, C, D = 0, 1, 2, 3
CERT = sheet_io.PRODUCT_COL_CERT                 # I(8)
KEY = sheet_io.PRODUCT_COL_KEY                   # AI(34)
COST_OVERRIDE = sheet_io.PRODUCT_COL_COST_OVERRIDE  # AN(39) 仕入override(人が手で入れる時だけ)
COST_NOW = 12                                    # M(現在価格=生きてる最安。N の追随元)
AUX0, AUXN = sheet_io.PRODUCT_COL_AUX_START, sheet_io.PRODUCT_AUX_MAX   # AC(28), 5

CATALOG_DB = r"C:\dev\iMak_data\catalog\products.sqlite"
DATA_DIR = r"C:\dev\iMak_data\hq"
LIVE_CACHE = os.path.join(DATA_DIR, "live_listings_cache.json")
LEDGER = os.path.join(DATA_DIR, "dup_guard_ledger.jsonl")

CSV_TITLE = "*Title"
CSV_LABEL = "CustomLabel"
CSV_CERT = "CDA:Certification Number - (ID: 27503)"


# ===================================================================
# 純関数
# ===================================================================
def card_token_from_title(title):
    """eBay タイトルの '#<カードID>' を返す(大文字化)。無ければ None。

    例: 'PSA 10 Gundam Japanese #RP-028 Resource 2026 Card' → 'RP-028'
        '... #DON-PRB02-018 DON!! Card 2025'                → 'DON-PRB02-018'
    ※ '#073/066' のような分数表記も token としてそのまま返す(set 違いの衝突は
      呼び出し側が KEY を優先することで回避する)。
    """
    if not title:
        return None
    m = re.search(r"#([A-Za-z0-9][A-Za-z0-9\-/_.]*)", str(title))
    return m.group(1).upper() if m else None


def parse_key(k):
    """KEY → (category|None, product_id)。新形式 `gundam_tcg:ST02-010` と旧形式 `ST02-010` 両対応。

    catalog の product_id は **カテゴリ内で一意**(schema は `UNIQUE(category, product_id)`)で、
    global 一意は元から保証されていない。One Piece と Gundam が同じ set-code 体系を使うため
    `ST02-010` は両方に実在する(実測 283件が重複)。KEY にカテゴリが無いと dedupe が
    別ゲームの同番号を同一商品と誤認する → **KEY 側にカテゴリを持たせる**(2026-07-27 Catalog 合意)。
    `:` は product_id が使わない文字(`[A-Za-z0-9_-]`)なので、最初の `:` で確実に分離できる。
    純関数。url-key(`item:` / `shops:`)は catalog-backed でないのでカテゴリ扱いしない。
    """
    k = (k or "").strip()
    if not k or k.startswith(("item:", "shops:")):
        return (None, k)
    if ":" in k:
        cat, _, pid = k.partition(":")
        return (cat, pid)
    return (None, k)


def group_key(k):
    """突合用のグループキー。カテゴリが判っていれば含める(別ゲーム同番号を分離する)。

    移行期は 旧形式(カテゴリ無)と新形式が併存するが、**両者は同一グループにしない**。
    = 誤って「重複」と判定して出品を落とす方向には倒さない(fail-closed は出品を守る側)。純関数。
    """
    cat, pid = parse_key(k)
    return f"{cat}:{pid}" if cat else pid


def norm_url(url):
    """仕入元URL の比較キー(query/fragment/末尾スラッシュ除去 + 小文字)。空は ''。"""
    if not url:
        return ""
    u = str(url).strip().split("?")[0].split("#")[0].rstrip("/")
    return u.lower()


def _cell(row, idx):
    return (row[idx] or "").strip() if len(row) > idx else ""


def _is_active(row):
    """出品中 & 取下げられていない行か (B有り + D空)。"""
    return bool(_cell(row, B)) and not _cell(row, D)


def shared_supply_urls(rows2d):
    """ACTIVE 行の 主URL(A)+補URL(AC-AG) を集計し、**2出品以上が指す URL** だけ返す。

    戻り: {正規化URL: [itemID,...(重複なし・昇順)]}。これが1件でもあれば
    「両方売れたら片方履行不能」= キャンセル→Defect の実リスク (fail-OPEN の本体)。
    純関数(rows2d は header 含む2次元配列)。
    """
    owner = {}
    for r in rows2d[1:]:
        if not _is_active(r):
            continue
        iid = _cell(r, B)
        urls = [_cell(r, A)] + [_cell(r, AUX0 + k) for k in range(AUXN)]
        for u in urls:
            n = norm_url(u)
            if n:
                owner.setdefault(n, set()).add(iid)
    return {u: sorted(v) for u, v in owner.items() if len(v) > 1}


def plan_shared_url_cleanup(rows2d):
    """共有された仕入元URLを **補URL側から外す**修正計画を作る (純関数)。

    ★なぜ必要か (2026-08-01 実害):
      `hoju_url_from_dupes` は「重複くんが弾いた2枚目の A列URL」を primary の補URLに足す。
      2枚目は書いた時点では **itemID 空 (未出品)** なので誰とも衝突していない。
      ところが **その2枚目が後日そのまま出品される**と、その行の主URLが他行の補URLと一致し、
      「両方売れたら片方が履行不能 → キャンセル → Defect」になる。
      = 入口ガードだけでは原理的に防げない。**危険化した時点で外す reconciliation が要る**。

    方針:
      - 外すのは **補URL(AC-AG) 側だけ**。主URL(A) は絶対に触らない (出品の供給そのもの)。
      - 対象は「その URL を **主URL として持つ ACTIVE 行が別に存在する**」補URLのみ。
        補URL どうしの重複は、実際に売れるまで履行不能にならないので触らない (過剰除去を避ける)。
      - 供給が減るだけで破壊的動作ではない (`failclosed_must_skip_not_destructive` の安全側)。

    戻り: {row(1-indexed): {'itemid', 'drop':[url,...], 'keep':[url,...], 'owner':{url:itemID}}}
    """
    primary_owner = {}
    for r in rows2d[1:]:
        if not _is_active(r):
            continue
        n = norm_url(_cell(r, A))
        if n:
            primary_owner.setdefault(n, _cell(r, B))
    plan = {}
    for i, r in enumerate(rows2d[1:], start=2):
        if not _is_active(r):
            continue
        me = _cell(r, B)
        aux = [_cell(r, AUX0 + k) for k in range(AUXN)]
        drop, keep, owner = [], [], {}
        for u in aux:
            if not u:
                continue
            n = norm_url(u)
            holder = primary_owner.get(n)
            if holder and holder != me:
                drop.append(u)
                owner[u] = holder
            else:
                keep.append(u)
        if drop:
            plan[i] = {"itemid": me, "drop": drop, "keep": keep, "owner": owner}
    return plan


def live_card_index(rows2d, titles_by_itemid=None, active_ids=None):
    """ACTIVE 行の カードキー → [itemID]。

    ★2026-08-04: `active_ids` (eBay ActiveList の itemID 集合) を渡すと、**そちらを真とする**。
    シートの D列は「**仕入元が**売り切れた」印であって「eBay 出品が終わった」印ではない。
    補URL で供給を繋いでいるので D='○' でも出品は生きている。実測 (2026-08-04):
    itemID を持つ 1,127行のうち D='○' が 749行、**そのうち 626行は eBay ActiveList に居る**。
    D列で live を判定すると live を 626件分 過小評価し、その相手には重複判定が効かない。
    実害: 8/03 OP07-109 / 8/04 OP05-098_P が **KEY 完全一致なのに素通り**して CSV に入った。

    カードキー優先順:
      1. KEY(AI列)      … catalog canonical id (最も確か)
      2. 't:' + タイトル token … KEY空の救済。titles_by_itemid={itemID: eBayタイトル} が要る
    KEY も token も無い行は index に入れない (= 判定不能。素通りでなく「不明」として
    呼び出し側が扱えるよう、別途 unkeyed で返す)。
    戻り: (index{key: [itemID]}, unkeyed[itemID])。純関数。
    """
    titles_by_itemid = titles_by_itemid or {}
    index, unkeyed = {}, []
    for r in rows2d[1:]:
        iid = _cell(r, B)
        alive = (iid in active_ids) if active_ids else _is_active(r)
        if not alive:
            continue
        k = _cell(r, KEY)
        if k and not k.startswith(("item:", "shops:")):
            index.setdefault(group_key(k), []).append(iid)
            continue
        tok = card_token_from_title(titles_by_itemid.get(iid, ""))
        if tok:
            index.setdefault("t:" + tok, []).append(iid)
        else:
            unkeyed.append(iid)
    return index, unkeyed


# SKU(CustomLabel) → cert の定義は sheet_io に1本化 (抽出段と入稿前で同じ判定にするため)
certs_from_skus = sheet_io.certs_from_skus


def same_cert_already_live(csv_rows, header, listed_cert_set):
    """CSV 行のうち **同一 cert が既に出品済** のものを返す (純関数)。

    ★これは「同じカードの2枚目」とは別物。**同じ現物**なので二度売れたら片方は必ず
    履行できない → キャンセル → Defect。よって警告ではなく **物理除外** する。
    2026-08-03 実害: cert 152687775 / 158452544 が既出品のまま CSV に入った。

    なぜ従来すり抜けたか: pre_upload は「自分自身(=同じcert)は除外して突合する」設計で、
    **同一 cert の live をわざと索引から外していた**。同一カード判定の自己一致を消す意図
    だったが、結果として最も重い「同一現物の二重出品」だけが常に無検出になっていた。
    """
    hi = {n: i for i, n in enumerate(header)}
    ci, li, ti = hi.get(CSV_CERT), hi.get(CSV_LABEL), hi.get(CSV_TITLE)
    out = []
    for n, r in enumerate(csv_rows):
        cert = (r[ci] or "").strip() if ci is not None and ci < len(r) else ""
        if cert and cert in (listed_cert_set or ()):
            out.append({"row": n,
                        "cert": cert,
                        "label": (r[li] or "").strip() if li is not None and li < len(r) else "",
                        "title": (r[ti] or "").strip() if ti is not None and ti < len(r) else ""})
    return out


def dup_candidates(csv_rows, header, index, cert_to_key=None):
    """入稿予定 CSV 行 × live index → 同一カードが既に live な行を返す。

    csv_rows/header: CSV の実データ。cert_to_key: {cert: KEY} (シート由来。あれば優先)。
    戻り: [{'label','cert','title','card_key','existing':[itemID]}]。純関数。
    """
    cert_to_key = cert_to_key or {}
    hi = {n: i for i, n in enumerate(header)}
    out = []
    for r in csv_rows:
        def col(name):
            i = hi.get(name)
            return (r[i] or "").strip() if i is not None and i < len(r) else ""
        cert, title = col(CSV_CERT), col(CSV_TITLE)
        key = cert_to_key.get(cert) or ""
        card_key = group_key(key) if key else ("t:" + (card_token_from_title(title) or ""))
        if card_key in ("", "t:"):
            continue
        existing = index.get(card_key) or []
        if existing:
            out.append({"label": col(CSV_LABEL), "cert": cert, "title": title,
                        "card_key": card_key, "existing": list(existing)})
    return out


def restock_collision(rows2d, titles_by_itemid=None):
    """live出品 と **取下げ中(D非空)** に同じカードが居る組を返す(=RESTOCK復活で2枠になる予備軍)。

    重複くん(dedupe)の母集団は「ACTIVE = itemID有り + D空」に絞られている。これは 7/13 に
    「弾いた=今 live 出品中」を構造保証するための意図的な設計で、**広げてはいけない**
    (補URL の live primary 保証が崩れ、取下げ中KEY との一致で新規を誤ブロックする)。
    しかしその結果、**取下げ中の在庫が母集団から消え**、同じカードをもう1枚出品でき、
    後で RESTOCK で復活すると2枠 live になる (EB03-053 / OP08-106 がこの形)。
    → 母集団は触らず、**独立の疑いフラグ**として人に見せる (Dedupe回答 2026-07-26 の推奨形)。
    **除外も DUP マークもしない**。純関数。
    戻り: [{'card_key','live':[itemID],'suspended':[itemID]}]
    """
    titles_by_itemid = titles_by_itemid or {}

    def _key(r):
        k = _cell(r, KEY)
        if k and not k.startswith(("item:", "shops:")):
            return group_key(k)
        tok = card_token_from_title(titles_by_itemid.get(_cell(r, B), ""))
        return "t:" + tok if tok else None

    live, susp = {}, {}
    for r in rows2d[1:]:
        iid = _cell(r, B)
        if not iid:
            continue
        k = _key(r)
        if not k:
            continue
        (live if not _cell(r, D) else susp).setdefault(k, []).append(iid)
    return [{"card_key": k, "live": v, "suspended": susp[k]}
            for k, v in sorted(live.items()) if k in susp]


def frozen_cost_rows(rows2d, gap_yen=0):
    """★**廃止した AN列に値が入っていないか**の tripwire (2026-07-27 に AN列を廃止)。

    経緯: AN(仕入override)は「人が仕入値を固定する」入口だったが、無在庫モデルでは
    仕入値=今の最安(M)が常に正しく、凍結は原理的に誤り。手元在庫の取得原価は F、
    ポイント控除は K が持つため **AN が担う残余ケースが無かった**(実績も人の書込ゼロ)。
    → N1 の ARRAYFORMULA から AN 分岐を除去し、AN を参照しない形にした
    (backup: iMak_data/hq/n_formula_backup_20260727.json)。

    以降 AN に値が入っても価格には効かないが、**入っていること自体が異常**(誰かが
    復活させようとしている / 旧コードが動いている)なので毎サイクル検出する。
    既定 gap_yen=0 = 値があれば全件報告。純関数。
    戻り: [{'row','itemID','an','m','gap','title'}]。
    """
    def _yen(v):
        # 全角￥/半角¥/カンマ が混在するので **数字だけ**取る(sheet_io._to_yen_int と同規約)。
        s = "".join(ch for ch in str(v or "") if ch.isdigit())
        return int(s) if s else 0

    out = []
    for n, r in enumerate(rows2d[1:], start=2):
        if len(r) <= COST_OVERRIDE or not _is_active(r):
            continue
        an = _yen(_cell(r, COST_OVERRIDE))
        if not an:
            continue
        m = _yen(_cell(r, COST_NOW))
        gap = m - an if m else 0
        if abs(gap) >= gap_yen:
            out.append({"row": n, "itemID": _cell(r, B), "an": an, "m": m, "gap": gap,
                        "title": _cell(r, C)[:40]})
    return sorted(out, key=lambda x: -x["gap"])


def filter_urls_owned_by_others(urls, owner_by_url, self_itemid):
    """補URL 書込前フィルタ: **他の出品が既に使っている URL** を落とす。

    urls: 追加しようとしている URL list / owner_by_url: {正規化URL: [itemID]}(全ACTIVE)
    self_itemid: 書込先の出品。自分が既に持っている URL は残す(冪等)。
    戻り: (通す urls, 落とした [(url, [owner...])])。純関数。
    """
    keep, dropped = [], []
    for u in urls:
        owners = [o for o in (owner_by_url.get(norm_url(u)) or []) if o != self_itemid]
        if owners:
            dropped.append((u, owners))
        else:
            keep.append(u)
    return keep, dropped


# ===================================================================
# I/O
# ===================================================================
def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return (rows[1:], rows[0]) if rows else ([], [])


def catalog_categories(product_ids):
    """product_id → [category,...] を catalog から引く(ID完全一致のみ・fallback無)。

    ★product_id は **カテゴリ内でのみ一意**(schema は `UNIQUE(category, product_id)`)。
    One Piece と Gundam が同じ set-code 体系を使うため `ST02-010` は両方に実在する(実測283件)。
    → カテゴリが2つ以上返る product_id は **どちらのカードか決められない**ので、
      呼び出し側は fail-closed で書かないこと。
    """
    ids = [i for i in set(product_ids) if i]
    if not ids or not os.path.exists(CATALOG_DB):
        return {}
    con = sqlite3.connect(CATALOG_DB)
    try:
        out = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            q = ("select product_id, category from products where product_id in ({})"
                 .format(",".join("?" * len(chunk))))
            for pid, cat in con.execute(q, chunk):
                out.setdefault(pid, []).append(cat)
        return out
    finally:
        con.close()


def catalog_has(product_ids):
    """catalog に **完全一致で存在する** product_id の集合を返す(ID-strict・fallback無)。"""
    return set(catalog_categories(product_ids))


def _ebay_active_titles():
    """eBay Active(US本体) の {itemID: title} を取得。失敗時は None (= 判定不能)。"""
    try:
        sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
        import dns_cache  # noqa: F401
        from fix_de_speedpak_shipping import refresh, token, post
    except Exception as e:
        print(f"  (live titles 取得不可: {type(e).__name__}: {e})")
        return None, None
    try:
        refresh()
        tok = token()
        out = {}
        skus = {}
        for n in range(1, 60):
            inner = ("<ActiveList><Include>true</Include><Pagination>"
                     f"<EntriesPerPage>200</EntriesPerPage><PageNumber>{n}</PageNumber>"
                     "</Pagination></ActiveList>")
            t = post("GetMyeBaySelling", inner, tok)
            al = t[t.find("<ActiveList>"):t.find("</ActiveList>")]
            chunk = re.findall(r"<Item>(.*?)</Item>", al, re.S)
            if not chunk:
                break
            for it in chunk:
                iid = re.search(r"<ItemID>(\d+)</ItemID>", it)
                ti = re.search(r"<Title>(.*?)</Title>", it)
                cur = re.search(r'<CurrentPrice currencyID="(\w+)"', it)
                # USD = US本体のみ。GBP/CAD/EUR は eBaymag ミラー(同SKUの複製=重複ではない)
                sk = re.search(r"<SKU>(.*?)</SKU>", it)
                if iid and ti and cur and cur.group(1) == "USD":
                    out[iid.group(1)] = ti.group(1)
                    if sk:                     # ★SKU = CustomLabel。PSA10-<cert> が入る
                        skus[iid.group(1)] = sk.group(1)
        return out, skus
    except Exception as e:
        print(f"  (live titles 取得失敗: {type(e).__name__}: {e})")
        return None, None


def _load_live_cache():
    try:
        with open(LIVE_CACHE, encoding="utf-8") as f:
            return json.load(f).get("titles") or {}
    except Exception:
        return {}


CACHE_MAX_AGE_H = 6      # これより古い live cache は「今 live か」の根拠にしない


def cache_age_hours(path=None, now=None):
    """live cache の古さ(時間)。無い/壊れている時は None (= 判定不能)。純関数寄り, test可。"""
    p = path or LIVE_CACHE
    try:
        with open(p, encoding="utf-8") as f:
            ts = json.load(f).get("generated_at")
        if not ts:
            return None
        gen = datetime.fromisoformat(ts)
    except Exception:                                          # noqa: BLE001
        return None
    return ((now or datetime.now()) - gen).total_seconds() / 3600.0


def ensure_fresh_live_cache(max_age_h=CACHE_MAX_AGE_H):
    """live cache が古ければ eBay から取り直す。戻り: (titles, skus, ok)。

    ★2026-08-07 発覚: この cache を **更新する担当が居なかった**。
    control_panel は `--audit --no-refresh` (シートだけで完結) で呼び、`--pre-upload` は
    `use_cache_only=True` で読むだけ。8/04-8/06 に cache が最新だったのは
    **人が手で叩いていたから**で、放っておけば古くなる。
    古い cache を「今 live」の根拠にすると、
      - 新しく出した listing が cache に無い → 重複を **見逃す** (今回直した事故の再来)
      - 終了した listing が cache に残る   → 真新規を **誤って落とす**
    どちらも黙って起きるので、**入稿の直前に自分で新鮮さを保証する**。
    """
    age = cache_age_hours()
    if age is not None and age <= max_age_h:
        return _load_live_cache(), _load_live_skus(), True
    print(f"  ↻ live cache が{'無い/壊れている' if age is None else f'{age:.1f}時間前と古い'}"
          f" → eBay から取り直します")
    titles, skus = _ebay_active_titles()
    if titles:
        _save_live_cache(titles, skus)
        return titles, skus or {}, True
    return _load_live_cache(), _load_live_skus(), False


def _load_live_skus():
    """live cache の {itemID: SKU}。旧形式(skus 無し)の cache でも壊れない。"""
    try:
        with open(LIVE_CACHE, encoding="utf-8") as f:
            return json.load(f).get("skus") or {}
    except Exception:
        return {}


def _strip_rows(csv_path, header, kept_rows):
    """CSV を kept_rows で書き直す (backup を残す)。NO-GO 行の物理除外と同じ扱い。"""
    bak = csv_path + ".bak_same_cert"
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            open(bak, "w", encoding="utf-8", newline="").write(f.read())
    except OSError:
        pass
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(header)
        w.writerows(kept_rows)
    print(f"       ✏️ CSV 上書き済 ({len(kept_rows)}行) / backup: {os.path.basename(bak)}")


def _save_live_cache(titles, skus=None):
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"), "titles": titles}
    if skus is not None:                       # ★SKU = 二重出品ガードの根拠 (cert が入っている)
        payload["skus"] = skus
    with open(LIVE_CACHE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _ledger(kind, payload):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                            "kind": kind, **payload}, ensure_ascii=False) + "\n")


def audit(refresh_titles=True):
    """全 ACTIVE 棚卸し: ①仕入元URL共有(致命) ②同一カード多重(注意)。戻り: stats dict。"""
    vals = sheet_io._product_ws().get_all_values()
    shared = shared_supply_urls(vals)
    titles, skus = _ebay_active_titles() if refresh_titles else (None, None)
    if titles:
        _save_live_cache(titles, skus)
    else:
        titles = _load_live_cache()
        if refresh_titles:
            print("  ⚠ live titles を更新できず cache を使用(同一カード判定は劣化)")
    index, unkeyed = live_card_index(vals, titles)
    dup_cards = {k: v for k, v in index.items() if len(v) > 1}

    n_act = sum(1 for r in vals[1:] if _is_active(r))
    print(f"■ dup_guard audit  ACTIVE {n_act}行 / live titles {len(titles)}件")
    print(f"★① 仕入元URL共有(=キャンセル risk): {len(shared)}件")
    for u, owners in list(shared.items())[:30]:
        print(f"    ⚠ {u[:70]}  →  {owners}")
    # ★2026-08-01: 検出して終わりにせず **その場で是正**する。
    #   共有の主因は hoju_url_from_dupes が足した「2枚目URL」で、書いた時点では未出品でも
    #   その2枚目が後日出品されると危険化する (入口ガードでは原理的に防げない)。
    #   外すのは補URL側だけ・主URLは不触なので供給が減るだけ = 安全側。
    _cleanup = plan_shared_url_cleanup(vals)
    if _cleanup:
        n_url = sum(len(v["drop"]) for v in _cleanup.values())
        print(f"    🔧 是正: 他出品の主URLと重なる補URL {n_url}本 を {len(_cleanup)}行から外します")
        for row, v in list(_cleanup.items())[:10]:
            for u in v["drop"]:
                print(f"       row{row}(itemID={v['itemid']}) ← {u[:58]} (主は {v['owner'][u]})")
        try:
            import sheet_io as _si
            _si.write_aux_urls({row: v["keep"] for row, v in _cleanup.items()})
            print(f"    ✅ 是正 完了 ({len(_cleanup)}行の補URLを書き換え)")
        except Exception as _e:      # noqa: BLE001
            print(f"    ⚠️要対応 是正の書込に失敗 (検出のみ): {type(_e).__name__}: {_e}")
    print(f"② 同一カード多重(注意・仕入元が別なら健全): {len(dup_cards)}組 "
          f"/ 判定不能(KEY無+token無) {len(unkeyed)}件")
    for k, v in list(dup_cards.items())[:30]:
        print(f"    - {k:22} {v}")
    frozen = frozen_cost_rows(vals)
    print(f"★③ 廃止したAN列(仕入override)に値がある行: {len(frozen)}件 ※常に0が正常")
    for f in frozen:
        print(f"    ⚠ row{f['row']:5} {f['itemID']} AN={f['an']:,} M={f['m']:,}  {f['title']}")
    coll = restock_collision(vals, titles)
    print(f"④ RESTOCK復活で2枠になりうる組(取下げ中に同じカードが居る): {len(coll)}組")
    for c in coll[:20]:
        print(f"    - {c['card_key']:22} live={c['live']} 取下げ中={c['suspended']}")
    _ledger("audit", {"shared_supply": {u: o for u, o in shared.items()},
                      "dup_cards": {k: v for k, v in dup_cards.items()},
                      "frozen_cost": frozen, "restock_collision": coll,
                      "unkeyed": len(unkeyed), "active": n_act})
    if shared:
        print("‼ URL共有あり = 両方売れたら履行不能。片方の補URL差替 or 取下げが必要。")
    if frozen:
        print("‼ AN列は 2026-07-27 に廃止済(N は参照しない)。値が入っているのは異常 → 空にしてください。")
    return {"active": n_act, "shared_supply": len(shared), "dup_cards": len(dup_cards),
            "frozen_cost": len(frozen), "restock_collision": len(coll),
            "unkeyed": len(unkeyed)}


def pre_upload(csv_path, use_cache_only=True):
    """入稿前 CSV を live と突合。

    2段:
      🔴 **同一cert が既に出品済** → 物理除外する (同じ現物。二度売れたら片方は履行不能)
      ⚠️ 同一カードの2枚目          → 警告のみ (仕入元が別なら健全。出品は止めない)
    """
    rows, header = _read_csv(csv_path)
    if not rows:
        print("  (dup_guard: CSV 空 skip)")
        return {"rows": 0, "dups": 0, "same_cert": 0}
    vals = sheet_io._product_ws().get_all_values()
    # ★2026-08-04: **ACTIVE 行に絞ってはいけない**。ここで引きたいのは
    #   「入稿しようとしている CSV 行自身の KEY」であり、その行は定義上まだ未出品
    #   (itemID 空 = _is_active False)。絞ると自分の KEY が引けず、タイトル token
    #   (`t:OP05-098`) にフォールバックして、live 側の `one_piece_tcg:OP05-098_P` と
    #   永久に一致しない。8/04 の OP05-098_P はこれで素通りした (KEY は完全一致していた)。
    cert_to_key = {}
    for r in vals[1:]:
        c, k = _cell(r, CERT), _cell(r, KEY)
        if c and k and not k.startswith(("item:", "shops:")):
            cert_to_key.setdefault(c, k)
    if use_cache_only:
        titles, skus, fresh = ensure_fresh_live_cache()
    else:
        titles, skus = _ebay_active_titles()
        titles, skus = titles or {}, skus or {}
        fresh = bool(titles)
        if titles:
            _save_live_cache(titles, skus)
    if not fresh:
        # ★判定不能を「重複なし」に倒さない。二重出品(→キャンセル→Defect)の方が
        #   出品が1日遅れることより遥かに重い。CSV は触らずに人へ返す。
        print("■ ⛔ live 情報が取得できず、cache も古い/無い → **重複判定を行いません**")
        print("     CSV は変更していません。ネット復旧後に再実行するか、目視で確認してください")
        return {"rows": len(rows), "dups": 0, "same_cert": 0, "same_key_stripped": 0,
                "blocked": True}

    # ---- 🔴 同一cert (= 同じ現物の二重出品) は物理除外する ----------------
    #   根拠は2つ union する。どちらか片方だけでは漏れる:
    #     - シート B列(itemID)  … 書き戻し漏れがある (実測 live PSA10 638件中 36件が空)
    #     - live SKU(CustomLabel) … eBay 側の事実。ただし `PSA10-<cert>` 形式の出品しか
    #       cert を持たない (実測 176/638) ので、36件のうち埋まるのは実測1件。残り35件は
    #       itemID 書き戻しのデータ修復が要る = **ここは完全ではない** (backlog)
    listed_cert = sheet_io.listed_certs(vals) | certs_from_skus(skus)
    severe = same_cert_already_live(rows, header, listed_cert)
    if severe:
        print(f"■ 🔴 dup_guard: **同一cert が既に出品済** {len(severe)}件 → CSV から物理除外します")
        for s in severe:
            print(f"    🚫 {s['label']:18} cert={s['cert']}  {s['title'][:60]}")
        print("       (同じ現物なので二度売れたら片方は必ず履行できない = キャンセル → Defect)")
        drop = {s["row"] for s in severe}
        kept = [r for i, r in enumerate(rows) if i not in drop]
        _strip_rows(csv_path, header, kept)
        _ledger("pre_upload_stripped",
                {"csv": os.path.basename(csv_path),
                 "same_cert": [{k: s[k] for k in ("label", "cert", "title")} for s in severe]})
        rows = kept
        if not rows:
            print("  (同一cert 除外の結果 CSV が空になりました)")
            return {"rows": 0, "dups": 0, "same_cert": len(severe)}

    # ★live の真は eBay ActiveList (シートの D列は「仕入元が売切」であって出品終了ではない)
    index, _unkeyed = live_card_index(vals, titles, active_ids=set(titles) or None)
    # 自分自身(=同じcert)は除外して突合する
    # ★ここで同一cert を index から外すのは **同一カード判定** の自己一致を消すためだけ。
    #   同一cert 自体は上で既に物理除外済 (2026-08-03 まで、この行のせいで
    #   最も重い「同一現物の二重出品」だけが常に無検出だった)。
    csv_certs = set()
    hi = {n: i for i, n in enumerate(header)}
    ci = hi.get(CSV_CERT)
    if ci is not None:
        csv_certs = {(r[ci] or "").strip() for r in rows if ci < len(r)}
    self_iids = {_cell(r, B) for r in vals[1:] if _cell(r, CERT) in csv_certs and _cell(r, B)}
    index = {k: [i for i in v if i not in self_iids] for k, v in index.items()}
    index = {k: v for k, v in index.items() if v}

    cands = dup_candidates(rows, header, index, cert_to_key)
    print(f"■ dup_guard 入稿前チェック: {len(rows)}行 → 同一カードが既に live: {len(cands)}件")
    for c in cands:
        print(f"    ⚠ {c['label']:18} {c['card_key']:20} 既存={c['existing']}")
        print(f"       {c['title'][:76]}")
    # ★2026-08-05: canonical KEY が **完全一致** した行は物理除外する。
    #   これは「勝手に絞る」ではなく、重複くん(dedupe_excluder)が元々やろうとしている
    #   ことと同じ (= 同KEYが live なら出さない)。重複くんは live を D列で判定するため
    #   626件を live と見なせず落とせないので、eBay ActiveList を根拠にこちらで落とす。
    #   タイトル token 一致 (`t:`) は精度が低いので **警告のまま** (別セットの同番号を
    #   巻き込むと出品対象を不当に減らす)。3日連続 (8/03 OP07-109 / 8/04 OP05-098_P /
    #   8/05 OP05-060) で人が手で外していたのを止める。
    exact = [c for c in cands if not str(c.get("card_key", "")).startswith("t:")]
    if exact:
        print(f"■ 🔴 canonical KEY 完全一致 {len(exact)}件 → CSV から物理除外します")
        for c in exact:
            print(f"    🚫 {c['label']:18} {c['card_key']:26} 既存={c['existing']}")
        drop_labels = {c["label"] for c in exact}
        li = hi.get(CSV_LABEL)
        kept = [r for r in rows
                if li is None or li >= len(r) or (r[li] or "").strip() not in drop_labels]
        _strip_rows(csv_path, header, kept)
        _ledger("pre_upload_stripped_samekey",
                {"csv": os.path.basename(csv_path),
                 "dups": [{k: c[k] for k in ("label", "cert", "card_key", "existing")}
                          for c in exact]})
        rows = kept
    weak = [c for c in cands if c not in exact]
    if weak:
        print("    ※上記のうちタイトル token 一致分は**残しています**(別セットの同番号を"
              "巻き込むため)。仕入元が別なら健全。入稿前に目視で判断すること。")
    if cands:
        _ledger("pre_upload", {"csv": os.path.basename(csv_path),
                               "dups": [{k: c[k] for k in ("label", "cert", "card_key", "existing")}
                                        for c in cands]})
    return {"rows": len(rows), "dups": len(cands), "same_cert": len(severe),
            "same_key_stripped": len(exact)}


def fill_keys_from_titles(csv_path, dry_run=False):
    """KEY空の live 行に、CSV タイトルの #ID が catalog に **完全一致** する時だけ KEY を書く。

    dedupe resolver が解けない DON!! カード等の救済 (catalog には DON-PRB02-018 が実在する)。
    ID完全一致のみ・推測なし (fail-closed)。cert でシート行を特定する。
    """
    rows, header = _read_csv(csv_path)
    if not rows:
        return {"written": 0, "unresolved": 0}
    hi = {n: i for i, n in enumerate(header)}

    def col(r, name):
        i = hi.get(name)
        return (r[i] or "").strip() if i is not None and i < len(r) else ""

    vals = sheet_io._product_ws().get_all_values()
    cert_row, cert_iid = {}, {}
    for n, r in enumerate(vals[1:], start=2):
        c = _cell(r, CERT)
        if c and not _cell(r, KEY) and _cell(r, B):
            cert_row[c], cert_iid[c] = n, _cell(r, B)

    want = {}
    for r in rows:
        cert = col(r, CSV_CERT)
        if cert not in cert_row:
            continue
        tok = card_token_from_title(col(r, CSV_TITLE))
        if tok:
            want[cert] = tok
    cats = catalog_categories(want.values())
    itemid_to_row, itemid_to_key, unresolved, ambiguous = {}, {}, [], []
    for cert, tok in want.items():
        c = sorted(set(cats.get(tok) or []))
        if len(c) == 1:
            # ★KEY は `{category}:{product_id}`(2026-07-27 3者合意)。別ゲームの同番号を分離する。
            iid = cert_iid[cert]
            itemid_to_row[iid] = cert_row[cert]
            itemid_to_key[iid] = f"{c[0]}:{tok}"
        elif len(c) > 1:
            # 同じ番号が複数カテゴリに実在 → どちらのカードか決められない → 書かない(fail-closed)
            ambiguous.append((cert, tok, c))
        else:
            unresolved.append((cert, tok))
    print(f"■ dup_guard KEY補完: 候補{len(want)} / catalog一致{len(itemid_to_key)} / "
          f"カテゴリ曖昧{len(ambiguous)} / 未解決{len(unresolved)}")
    for cert, tok, c in ambiguous:
        print(f"    - cert={cert} '{tok}' は {c} の複数カテゴリに実在 → 書かない(fail-closed)")
    for iid, k in itemid_to_key.items():
        print(f"    + {iid} row{itemid_to_row[iid]} → KEY='{k}'")
    for cert, tok in unresolved:
        print(f"    - cert={cert} token='{tok}' は catalog に無い → 書かない(fail-closed)")
    if dry_run or not itemid_to_key:
        return {"written": 0, "unresolved": len(unresolved), "ambiguous": len(ambiguous),
                "resolved": len(itemid_to_key)}
    written = sheet_io.write_keys(itemid_to_row, itemid_to_key)
    print(f"    ✔ AI列 書込: {written}行")
    _ledger("fill_keys", {"csv": os.path.basename(csv_path), "written": written,
                          "keys": itemid_to_key})
    return {"written": written, "unresolved": len(unresolved), "ambiguous": len(ambiguous),
            "resolved": len(itemid_to_key)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = sys.argv[1:]
    if "--audit" in args:
        audit(refresh_titles="--no-refresh" not in args)
    elif "--pre-upload" in args:
        # ★判定できなかった時は非ゼロで返す (走行ログに「続行」と出て人が気づける)
        if pre_upload(args[args.index("--pre-upload") + 1]).get("blocked"):
            return 2
    elif "--fill-keys" in args:
        fill_keys_from_titles(args[args.index("--fill-keys") + 1], dry_run="--dry" in args)
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
