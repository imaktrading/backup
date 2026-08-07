#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スプシ集約の共有ヘルパ (2026-06-07)。eBayアップCSV以外はスプシに集約する方針。

各分析ボタン(需要・新規強化/再仕入れ/効果測定 等)は結果を「既存メンテ」スプシの
専用タブに書く。デスクトップCSVは廃止。
"""
import functools
import os
import re as _re

MAINT_SHEET_ID = "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4"   # 「既存メンテ」スプシ
MAINT_URL = f"https://docs.google.com/spreadsheets/d/{MAINT_SHEET_ID}/edit"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"

# 商品管理シート (出品マスタ。canonical KEY = AI列(idx34)、itemID = B列(idx1))。
# 既存メンテとは別スプシ。再仕入れ/需要マップが canonical KEY を引く血統元 (Step6, 2026-06-10)。
PRODUCT_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
PRODUCT_GID = 851100680
PRODUCT_COL_ITEMID = 1   # B
PRODUCT_COL_CERT = 8     # I (PSA cert#。psa_cache.json で CardImageUrl=現物PSA画像を引く)
PRODUCT_COL_COST_M = 12  # M (現在価格・監視くん更新の最新観測値。書込 seed 可・regular 列)
PRODUCT_COL_COST = 13    # N (仕入れ価格（円）= live ARRAYFORMULA。**書込禁止**。読取専用)
PRODUCT_COL_COST_OVERRIDE = 39   # AN (仕入override) — ★2026-07-27 廃止。N の式はもう参照しない。
# 廃止理由: 無在庫モデルでは仕入値=今の最安(M)が常に正しく、凍結は原理的に誤り。
# 手元在庫の取得原価は F(商品価格)、ポイント控除は K が持つので AN の残余ケースが無かった
# (実績も人の書込ゼロ。入っていた4件は全て旧 RESTOCK コードの機械書込)。
# 定数は「この列に書かない」ことを示すためだけに残す(_ANWriteGuard が参照)。
                                 # N1 式が AN 優先で読む (AN空なら (M or F)−K)。2026-07-24 制定。
PRODUCT_COL_KEY = 34     # AI (canonical product_id)


def build_key_map(rows2d, itemid_col=PRODUCT_COL_ITEMID, key_col=PRODUCT_COL_KEY):
    """商品管理シート rows(2d, header含む) → {itemID(str): canonical_KEY(str)} (純関数, test可)。

    canonical KEY が空 / url-key(item:/shops:) の行は除外 (= catalog-backed の固有id のみ)。
    """
    out = {}
    for r in rows2d[1:]:
        if len(r) <= max(itemid_col, key_col):
            continue
        iid = (r[itemid_col] or "").strip()
        key = (r[key_col] or "").strip()
        if not iid or not key or key.startswith("item:") or key.startswith("shops:"):
            continue
        out[iid] = key
    return out


def listed_keys(rows2d, itemid_col=PRODUCT_COL_ITEMID, key_col=PRODUCT_COL_KEY):
    """商品管理シート rows → 「出品済」canonical KEY の集合 (純関数, test可)。

    出品済 = その KEY を持つ行のうち itemID(B列) 非空の行が1つ以上ある = 実際に eBay 出品された。
    用途: PSA 抽出で、出品済カードの2枚目(別cert・itemID空・同KEY)を抽出段階で除外し、
    viewer に毎回再表示されて目視労力を浪費するのを防ぐ(dedup は CSV 段階で消すが抽出は止めない)。
    url-key(item:/shops:) は catalog-backed でない固有idなので除外。
    """
    out = set()
    for r in rows2d[1:]:
        if len(r) <= max(itemid_col, key_col):
            continue
        iid = (r[itemid_col] or "").strip()
        key = (r[key_col] or "").strip()
        if iid and key and not key.startswith("item:") and not key.startswith("shops:"):
            out.add(key)
    return out


def normalize_key(key):
    """canonical KEY を **比較用**に正規化 (純関数)。

    ★2026-08-03: 同じ KEY が namespace prefix 付き/無しの両方で書かれており
    (`FB08-121_p1` と `dragonball_scg:FB08-121_p1`)、生文字列比較の dedup が
    すり抜けていた。**比較のときだけ** prefix を落とす。書込値は変えない。
    """
    k = (key or "").strip()
    if not k or k.startswith("item:") or k.startswith("shops:"):
        return ""
    return k.split(":", 1)[-1].strip().lower()


def listed_key_forms(rows2d, itemid_col=PRODUCT_COL_ITEMID, key_col=PRODUCT_COL_KEY):
    """出品済 KEY を **正規化した** 集合 (純関数)。`listed_keys` の比較用。"""
    return {n for n in (normalize_key(k) for k in listed_keys(rows2d, itemid_col, key_col)) if n}


PRODUCT_COL_CATEGORY = 17   # R (TCG / Tシャツ / 一番くじ / アウトドア・ジャケット 等が混在)


def listed_certs(rows2d, itemid_col=PRODUCT_COL_ITEMID, cert_col=PRODUCT_COL_CERT,
                 category_col=PRODUCT_COL_CATEGORY, categories=("TCG",)):
    """出品済 PSA cert の集合 (純関数, test可)。

    ★2026-08-03: **同じ cert = 同じ現物**。二度出品したら片方は必ず履行できない
    (無在庫以前の問題で、現物が1枚しかない)。KEY がどう揺れても cert は揺れないので、
    これが二重出品に対する**最も硬い**ガード。
    実害: 2026-08-03 の CSV に cert 152687775 / 158452544 が入り、どちらも
    itemID 358853881133 / 358794594782 で既に出品中だった。シート実測で同型 24件。

    ★カテゴリで絞るのが必須 (2026-08-03 の実機確認で判明)。I列は **PSA cert 専用ではなく**、
    montbell は同じ列に **型番** を入れている (`1103247` が3行で共有され、うち1行が出品済)。
    型番は「同じ現物」を意味しないので、カテゴリを見ないと **在庫のある別商品を誤って止める**。
    categories=None で全カテゴリ (テスト用)。
    """
    out = set()
    for r in rows2d[1:]:
        if len(r) <= max(itemid_col, cert_col):
            continue
        if categories is not None:
            cat = (r[category_col] or "").strip() if len(r) > category_col else ""
            if cat not in categories:
                continue
        iid = (r[itemid_col] or "").strip()
        cert = (r[cert_col] or "").strip()
        if iid and cert:
            out.add(cert)
    return out


LIVE_CACHE_PATH = r"C:\dev\iMak_data\hq\live_listings_cache.json"
_CERT_SKU_RE = _re.compile(r"^PSA10-(\d{6,})$", _re.I)


def certs_from_skus(sku_by_itemid):
    """live 出品の SKU(CustomLabel `PSA10-<cert>`) → 出品済 cert の集合 (純関数)。"""
    out = set()
    for sku in (sku_by_itemid or {}).values():
        m = _CERT_SKU_RE.match((sku or "").strip())
        if m:
            out.add(m.group(1))
    return out


def live_listed_certs(path=LIVE_CACHE_PATH):
    """live cache の SKU から出品済 cert を取る (eBay を叩かない・失敗は空集合)。

    シートの itemID 書き戻しは漏れるので (実測 2026-08-03: live PSA10 638件のうち
    **36件がシートに itemID を持たない**)、シート由来の cert 集合を SKU 側から補う。

    ★ただし **これで全部は埋まらない**。回収できるのは CustomLabel が `PSA10-<cert>`
    形式の出品だけ (実測 176/638)。古い出品は `005-PSA10` / `m73494307129` 等の
    別形式で **cert を持っていない** ため、36件のうち回収できたのは実測 **1件**。
    残り35件は「itemID をシートに書き戻す」データ修復でしか埋まらない (別途 backlog)。
    cache が古い/無い時は空集合 = シート側の判定に素直に戻るだけで、悪化はしない。
    """
    try:
        import json as _json
        with open(path, encoding="utf-8") as f:
            return certs_from_skus(_json.load(f).get("skus") or {})
    except Exception:
        return set()


def already_listed_reason(cert, key, listed_cert_set, listed_key_form_set):
    """この行を出品してはいけない理由を返す (無ければ "")。純関数, test可。

    - cert 一致 = **同一の現物**が既に出品中 → 絶対に出さない (KEY 不問)
    - KEY 一致 = 同じカードの2枚目 → 従来どおり抽出段で止める (正規化して比較)

    ★KEY が空でも cert で止まる。従来は `key and key in listed` の fail-OPEN だったため
    KEY 未記入の行が素通りしていた (シート実測 24件中 21件がこの経路)。
    """
    cert = (cert or "").strip()
    if cert and cert in (listed_cert_set or ()):
        return "cert"
    nk = normalize_key(key)
    if nk and nk in (listed_key_form_set or ()):
        return "key"
    return ""


PRODUCT_COL_AUX_START = 28   # AC (補URL1)。AC-AG = 補URL1-5 (idx28-32 / 1-indexed col 29-33)。
PRODUCT_AUX_MAX = 5


def _col_letters_to_idx0(letters):
    """列文字 → 0-indexed 列番号 ('A'→0 / 'AN'→39)。純関数。不正入力は None。"""
    letters = (letters or "").strip().upper()
    if not letters or not letters.isalpha():
        return None
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def range_touches_col(a1_range, col_idx0):
    """A1 レンジが指定列を含むか (純関数)。'AN5'/'AN2:AN9'/'A2:AN9'/'A:AN' すべて True。

    列指定のない開けたレンジ('2:5' や '' = シート全体)は **含む扱い**(安全側)。
    """
    if col_idx0 is None:
        return False
    s = str(a1_range or "").split("!")[-1].replace("$", "").strip().upper()
    if not s:
        return True
    parts = s.split(":")
    cols = []
    for p in parts:
        letters = "".join(ch for ch in p if ch.isalpha())
        cols.append(_col_letters_to_idx0(letters))
    if len(parts) == 1:
        return cols[0] == col_idx0 if cols[0] is not None else True
    lo, hi = cols[0], cols[1]
    if lo is None or hi is None:      # 行だけのレンジ = 全列を含む
        return True
    return min(lo, hi) <= col_idx0 <= max(lo, hi)


class _ColWriteGuard:
    """商品管理シートの **指定列への書込を実行時に拒否**する薄い proxy (2026-07-27 → 08-02 汎用化)。

    ★なぜ実行時ガードが要るか (2026-07-27 監査指摘):
    source 走査の test だけでは `ws.update_cell(row, 40, v)` の **数値列指定** や
    `chr(65 + idx0)` の **動的な列文字生成** を検知できず、しかもその2つは
    このリポジトリに既にある確立済みスタイル(sheet_io の write_aux_urls/write_keys 等)。
    = 「AN{row}」という文字列を書かなくても簡単に AN/N を触れてしまう。
    そこで **書込の出口(worksheet)を1点に絞って弾く**。列の指定方法に依らず止まる。

    ★2026-08-02 N列も同型ガード対象に追加 (BRAVO 依頼書 E 項):
    ichibankuji_restock が N列に cost を焼いていた事故 (7/27〜8/02 で N1=#REF! → 全空)
    の同型再発防止。N列は ARRAYFORMULA (M or F)−K の spill 列で、1セル書込むと spill が
    塞がり全 1415行が #REF!。値を反映したいなら M列(regular)を seed する運用。

    guarded_cols: {列idx0: (列名, deny メッセージ)} の dict。列ごとに違う理由メッセージ。
    """

    _WRITE_METHODS = ("batch_update", "update", "update_acell", "update_cell", "update_cells")

    def __init__(self, ws, guarded_cols=None):
        object.__setattr__(self, "_ws", ws)
        # guarded_cols 省略時は既定として AN 列のみ (2026-07-27 互換)。
        if guarded_cols is None:
            guarded_cols = {PRODUCT_COL_COST_OVERRIDE: ("AN", _AN_DENY_MSG)}
        object.__setattr__(self, "_guarded", dict(guarded_cols))

    def __getattr__(self, name):
        attr = getattr(object.__getattribute__(self, "_ws"), name)
        if name in _ColWriteGuard._WRITE_METHODS and callable(attr):
            return functools.partial(_ColWriteGuard._checked, self, name, attr)
        return attr

    def _deny(self, col_idx0, where):
        label, msg = self._guarded[col_idx0]
        raise PermissionError(f"{label}列への書込は禁止です [{where}]。{msg}")

    def _checked(self, name, attr, *args, **kwargs):
        guarded = object.__getattribute__(self, "_guarded")
        if name == "batch_update" and args:
            for req in (args[0] or []):
                if isinstance(req, dict):
                    rng = req.get("range")
                    for col in guarded:
                        if range_touches_col(rng, col):
                            self._deny(col, f"batch_update range={rng}")
        elif name in ("update", "update_acell") and args:
            if isinstance(args[0], str):
                for col in guarded:
                    if range_touches_col(args[0], col):
                        self._deny(col, f"{name} range={args[0]}")
        elif name == "update_cell" and len(args) >= 2:
            for col in guarded:
                if args[1] == col + 1:                # gspread は 1-indexed
                    self._deny(col, f"update_cell col={args[1]}")
        elif name == "update_cells" and args:
            for c in (args[0] or []):
                col1 = getattr(c, "col", None)
                if col1 is not None:
                    for col in guarded:
                        if col1 == col + 1:
                            self._deny(col, f"update_cells col={col1}")
        return attr(*args, **kwargs)


# 後方互換: 既存 test / 他 module が名前で参照している可能性に備え alias を残す。
_ANWriteGuard = _ColWriteGuard


_AN_DENY_MSG = ("AN を書くと N=(M or F)−K の動的追随が止まり仕入値が凍結します"
                "(実測: ¥29,999 凍結のまま実勢 ¥48,000 → 安売り)。"
                "cost を反映したいなら M列(現在価格)を seed してください。"
                "AN は人が手で入れる時だけの入口です。")
_N_DENY_MSG = ("N列は ARRAYFORMULA (M or F)−K の spill 出力です。1セル書込むと "
               "spill が塞がり N1=#REF! で全行が #REF! になります "
               "(2026-07-27〜08-02 ichibankuji_restock 事故で N109-N123 の 7 行を焼き、"
               "他 1400行 が #REF! で offer_calc の cost=0 表示 → 赤字承諾リスク)。"
               "cost を反映したいなら M列(現在価格)を seed してください。"
               "N はシートの数式が計算する唯一の出口で、コードから書く経路は無い。")

_PRODUCT_GUARDED_COLS = {
    PRODUCT_COL_COST_OVERRIDE: ("AN", _AN_DENY_MSG),
    PRODUCT_COL_COST:          ("N",  _N_DENY_MSG),
}


def _product_ws():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(PRODUCT_SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.id == PRODUCT_GID), None)
    if ws is None:
        raise RuntimeError(f"商品管理シート gid={PRODUCT_GID} が見つからない")
    return _ColWriteGuard(ws, _PRODUCT_GUARDED_COLS)


def product_key_map():
    """商品管理シートを読んで {itemID: canonical_KEY} を返す (I/O)。失敗は例外送出。"""
    return build_key_map(_product_ws().get_all_values())


def build_cert_map(rows2d, itemid_col=PRODUCT_COL_ITEMID, cert_col=PRODUCT_COL_CERT):
    """商品管理シート rows → {itemID(str): cert#(str)} (純関数, test可)。空itemID/空cert は除外。"""
    out = {}
    for r in rows2d[1:]:
        if len(r) <= max(itemid_col, cert_col):
            continue
        iid = (r[itemid_col] or "").strip()
        cert = (r[cert_col] or "").strip()
        if iid and cert:
            out[iid] = cert
    return out


def product_index():
    """商品管理シートを1回読んで (key_map, itemid_to_row, cert_map) を返す (I/O)。

    key_map = {itemID: canonical_KEY}、 itemid_to_row = {itemID: 1-indexed行番号}、
    cert_map = {itemID: PSA cert#}(再仕入れの目視確認で 現物PSA画像 を引くのに使う)。
    再仕入れゲートが KEY 解決 + 補URL書戻し + cert の全てに使う(sheet読みを1回に集約)。
    """
    vals = _product_ws().get_all_values()
    key_map = build_key_map(vals)
    cert_map = build_cert_map(vals)
    itemid_to_row = {}
    for i, r in enumerate(vals):
        if i == 0:
            continue
        if len(r) > PRODUCT_COL_ITEMID:
            iid = (r[PRODUCT_COL_ITEMID] or "").strip()
            if iid:
                itemid_to_row.setdefault(iid, i + 1)
    return key_map, itemid_to_row, cert_map


def write_aux_urls(row_to_urls):
    """{1-indexed行番号: [url,...]} を 商品管理シート 補URL列(AC-AG)に batch_update。

    各行 最大5URL、不足は空文字でクリア(古い補URLを残さない)。touch するのは AC-AG のみ。
    戻り: 書込んだ行数。row_to_urls 空なら 0。
    """
    if not row_to_urls:
        return 0
    ws = _product_ws()

    def _coln(idx0):
        return chr(65 + idx0) if idx0 < 26 else "A" + chr(65 + idx0 - 26)
    c0 = _coln(PRODUCT_COL_AUX_START)                      # AC
    c1 = _coln(PRODUCT_COL_AUX_START + PRODUCT_AUX_MAX - 1)  # AG
    reqs = []
    for row, urls in row_to_urls.items():
        vals5 = (list(urls)[:PRODUCT_AUX_MAX] + [""] * PRODUCT_AUX_MAX)[:PRODUCT_AUX_MAX]
        reqs.append({"range": f"{c0}{row}:{c1}{row}", "values": [vals5]})
    if reqs:
        ws.batch_update(reqs, value_input_option="RAW")
    return len(reqs)


def write_keys(itemid_to_row, itemid_to_key):
    """{itemID: canonical_KEY} を 商品管理シート AI列(canonical KEY) に書く (I/O)。

    PSA再仕入れ確認ゲートで目視確定した変種KEYを資産化(空欄補完/訂正)。itemid_to_row で
    行特定し AI列のみ touch。戻り=書込行数。row 不明な itemID は skip。
    """
    if not itemid_to_key:
        return 0
    ws = _product_ws()
    idx0 = PRODUCT_COL_KEY
    col = chr(65 + idx0) if idx0 < 26 else "A" + chr(65 + idx0 - 26)   # 34 → AI
    reqs = []
    for iid, key in itemid_to_key.items():
        row = itemid_to_row.get(iid)
        if row and key:
            reqs.append({"range": f"{col}{row}", "values": [[key]]})
    if reqs:
        ws.batch_update(reqs, value_input_option="RAW")
    return len(reqs)


def _to_yen_int(v):
    """'45000' / '¥45,000' / '21,500' → '45000' (純関数)。数字以外を除去。空/非数は ''。"""
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s


def restock_reactivate_master(itemid_to_row, itemid_to_url, itemid_to_cost=None):
    """RESTOCK で qty 復活させた出品の **商品管理シート master** を実状態に同期 (I/O)。

    - A列(URL=供給先)を最新の仕入URLに更新(売れたらここから買う)。
    - D列(売り切れ)をクリア(空)= 供給が戻った=売り切れ解除。
    - **M列(現在価格)を RESTOCK 確定の新仕入値(最安¥)で seed**。N=(M or F)−K がこれを拾い、以降は
      監視くんの M=min(生きてる最安:主+補) が毎cycle上書き = **cost が動的追随する**(2026-07-26)。
      ★AN列(仕入override=凍結)には書かない: AN は N式で最優先=固定 なので、書くと M-min 動的追随を
      上書きして「安い供給を見つけても値下げされない」出品を作る(2026-07-26 実測: RESTOCK 走行毎に
      AN凍結 4→14 に増殖し M-min を無効化していた)。凍結したい時だけ人が手で AN に入れる運用に戻す。
      M は formula でない regular 列なので直書き安全(N直書きの #REF! 事故は M seed では起きない)。
    在庫監視くんが D列「売り切れ」を見て、RESTOCK で復活させた出品を取り下げ直すのを防ぐ
    (状態同期の安全原則: 意図(復活) と 実状態(master) の乖離をゼロに)。touch は A/D/M列のみ(AN不可触)。
    戻り: 更新行数。row 不明な itemID は skip。
    """
    if not itemid_to_row:
        return 0
    ws = _product_ws()
    reqs = []
    n = 0
    for iid, row in itemid_to_row.items():
        if not row:
            continue
        url = (itemid_to_url or {}).get(iid, "")
        if url:
            reqs.append({"range": f"A{row}", "values": [[url]]})    # A列(idx0)=URL(供給先)
        reqs.append({"range": f"D{row}", "values": [[""]]})          # D列(idx3)=売り切れクリア
        cost = _to_yen_int((itemid_to_cost or {}).get(iid, ""))
        if cost:
            reqs.append({"range": f"M{row}", "values": [[cost]]})    # M列(idx12)=現在価格 seed → N=M-K で動的追随
        n += 1
    if reqs:
        ws.batch_update(reqs, value_input_option="RAW")
    return n


def read_tab(tab, sheet_id=MAINT_SHEET_ID):
    """スプシ tab を 2d list で返す (I/O)。タブが無ければ []。PDCA台帳の前回値読込に使う。"""
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    try:
        return sh.worksheet(tab).get_all_values()
    except gspread.WorksheetNotFound:
        return []


def write_rows_to_tab(tab, rows2d, sheet_id=MAINT_SHEET_ID):
    """rows2d ([[header...],[row...],...]) をスプシ tab に書く (clear+update, 無ければ作成)。

    タブは維持 (gid 安定)。戻り: 書込行数。失敗は例外送出 (呼出側で握る)。
    """
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    ncols = max((len(r) for r in rows2d), default=4)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
        # 既存タブの列数が不足だと update が grid limit で失敗する → 足りなければ拡張。
        if ws.col_count < ncols:
            ws.add_cols(ncols - ws.col_count)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=max(10, len(rows2d) + 5), cols=max(4, ncols))
    ws.update(range_name="A1", values=rows2d, value_input_option="RAW")
    return len(rows2d)
