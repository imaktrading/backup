#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スプシ集約の共有ヘルパ (2026-06-07)。eBayアップCSV以外はスプシに集約する方針。

各分析ボタン(需要・新規強化/再仕入れ/効果測定 等)は結果を「既存メンテ」スプシの
専用タブに書く。デスクトップCSVは廃止。
"""
import functools
import os

MAINT_SHEET_ID = "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4"   # 「既存メンテ」スプシ
MAINT_URL = f"https://docs.google.com/spreadsheets/d/{MAINT_SHEET_ID}/edit"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"

# 商品管理シート (出品マスタ。canonical KEY = AI列(idx34)、itemID = B列(idx1))。
# 既存メンテとは別スプシ。再仕入れ/需要マップが canonical KEY を引く血統元 (Step6, 2026-06-10)。
PRODUCT_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
PRODUCT_GID = 851100680
PRODUCT_COL_ITEMID = 1   # B
PRODUCT_COL_CERT = 8     # I (PSA cert#。psa_cache.json で CardImageUrl=現物PSA画像を引く)
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


class _ANWriteGuard:
    """商品管理シートの **AN列(仕入override)への書込を実行時に拒否**する薄い proxy (2026-07-27)。

    ★なぜ実行時ガードが要るか (2026-07-27 監査指摘):
    source 走査の test だけでは `ws.update_cell(row, 40, v)` の **数値列指定** や
    `chr(65 + idx0)` の **動的な列文字生成** を検知できず、しかもその2つは
    このリポジトリに既にある確立済みスタイル(sheet_io の write_aux_urls/write_keys 等)。
    = 「AN{row}」という文字列を書かなくても簡単に AN を触れてしまう。
    そこで **書込の出口(worksheet)を1点に絞って弾く**。列の指定方法に依らず止まる。

    AN が入った行は N=(M or F)−K の動的追随を無視して仕入値が凍結し、供給価格が上がっても
    値上げされず、誰も気づかないまま安売りが続く(実測: Boa Hancock P-066 が ¥29,999 凍結の
    まま実勢 ¥48,000 に対し $353.98 で出品)。AN は **人が手で入れる時だけ** の入口。
    """

    _WRITE_METHODS = ("batch_update", "update", "update_acell", "update_cell", "update_cells")
    _AN = PRODUCT_COL_COST_OVERRIDE          # 39 (0-indexed) = AN列

    def __init__(self, ws):
        object.__setattr__(self, "_ws", ws)

    def __getattr__(self, name):
        attr = getattr(object.__getattribute__(self, "_ws"), name)
        if name in _ANWriteGuard._WRITE_METHODS and callable(attr):
            return functools.partial(_ANWriteGuard._checked, self, name, attr)
        return attr

    @staticmethod
    def _deny(where):
        raise PermissionError(
            f"AN列(仕入override)への書込は禁止です [{where}]。"
            "AN を書くと N=(M or F)−K の動的追随が止まり仕入値が凍結します"
            "(実測: ¥29,999 凍結のまま実勢 ¥48,000 → 安売り)。"
            "cost を反映したいなら M列(現在価格)を seed してください。"
            "AN は人が手で入れる時だけの入口です。")

    def _checked(self, name, attr, *args, **kwargs):
        an = _ANWriteGuard._AN
        if name == "batch_update" and args:
            for req in (args[0] or []):
                if isinstance(req, dict) and range_touches_col(req.get("range"), an):
                    _ANWriteGuard._deny(f"batch_update range={req.get('range')}")
        elif name in ("update", "update_acell") and args:
            if isinstance(args[0], str) and range_touches_col(args[0], an):
                _ANWriteGuard._deny(f"{name} range={args[0]}")
        elif name == "update_cell" and len(args) >= 2:
            if args[1] == an + 1:                      # gspread は 1-indexed
                _ANWriteGuard._deny(f"update_cell col={args[1]}")
        elif name == "update_cells" and args:
            for c in (args[0] or []):
                if getattr(c, "col", None) == an + 1:
                    _ANWriteGuard._deny(f"update_cells col={getattr(c, 'col', None)}")
        return attr(*args, **kwargs)


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
    return _ANWriteGuard(ws)


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
