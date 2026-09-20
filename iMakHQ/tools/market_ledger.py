"""市場で売れた実績の台帳 (Terapeak 抜き出しの CSV を1本に溜める)。

拡張 (iMakHQ/tools/terapeak_grab) が出した `terapeak_*.csv` を拾って、
`C:/dev/iMak_data/hq/market_sold/ledger.csv` に追記する。同じ出品は1行にしかならない。

    python iMakHQ/tools/market_ledger.py ingest          # ダウンロード等から取り込む
    python iMakHQ/tools/market_ledger.py archive         # 今の台帳を退避して空にする
    python iMakHQ/tools/market_ledger.py report          # 売れているカードと前回との差
    python iMakHQ/tools/market_ledger.py targets         # 探す先 (売れているのに出していない)
    python iMakHQ/tools/market_ledger.py cards           # 売れ筋 (出品済/未出品 の印つき・値段の差)
    python iMakHQ/tools/market_ledger.py html            # 売れ筋を HTML にして開く (画像つき)

★台帳に貯めるのは **出品ごとの行** (eBay が出した「期間中に何個売れたか」付き)。
  カード単位の集計は report の時に作る。集計を焼いて保存すると、後から数え直せなくなる。
"""

import csv
import glob
import json
import os
import re
import sys
import collections
import statistics
import datetime

LEDGER_DIR = r"C:/dev/iMak_data/hq/market_sold"
LEDGER = os.path.join(LEDGER_DIR, "ledger.csv")

# 拡張が出す CSV の置き場 (新しい順に見る)
SEARCH_DIRS = [
    os.path.join(os.path.expanduser("~"), "Downloads"),
    os.path.join(os.path.expanduser("~"), "OneDrive", "デスクトップ"),
    os.path.join(os.path.expanduser("~"), "Desktop"),
    LEDGER_DIR,
]

# 台帳の鍵: 同じ検索で同じ出品なら1行 (取り直したら新しい方で上書き)
KEY_COLS = ("種別", "検索語", "itemId", "期間")

# ---- 条件セット (ここが唯一の口。手打ちしない) ----
# 2026-09-18 ユーザー確定。変える時はここだけ変える。
#   共通: CCG Individual Cards / 即決+オファー承諾 (オークション除外) / 日本人セラー /
#         売れた数の多い順 / 1ページ50件。価格の下限は入れない ($40未満は実測で4%)
#   Game は URL の aspect に入る (aspect=Game:::One Piece CCG)。実機で確認済み
RESEARCH_BASE = "https://www.ebay.com/sh/research"
CATEGORY_CCG = "183454"

# ★2026-09-20: 一度「ゲームで絞らない」に変えたが、**戻した**。
#   ユーザー指摘「カタログに無いから自然に落ちるって、カタログ及び引き方の精度が低いのに、
#   よく言うわ」。そのとおりで、測ったら 落ちなかった:
#     正式値でない出品 267件 → カタログまで引けたのは **73件 (27%)** だけ。
#     残り194件は判別できないまま画面に出る (カードダス / 引けていない普通のポケカ /
#     何か分からない物 が混ざる)。
#   取りこぼす約10%より、判別できないゴミが267件入る方が害が大きい。
#   ★外すのは **カタログと引き方の精度が上がってから**。
# ★2026-09-20 eBay に直接聞いて確認した (Taxonomy API / category 183454 / 候補値168件)。
#   Game は **自由入力**なので、セラーは候補値を使わなくても出品できる。だから
#   絞り込みは候補値の分しか効かない (約10%が取りこぼし) = 構造的な天井。
#     Pok…        → "Pokémon TCG" の1つだけ
#     One Piece   → "One Piece CCG" の1つだけ
#     Dragon Ball → 4つある (CCG / GT TCG / Super Card Game / Z TCG)。
#                   うちが扱うのは Super Card Game (フュージョンワールド) だけ。
PRESETS = {
    "ポケモン": ["Pokémon TCG"],
    "ワンピース": ["One Piece CCG"],
    # ★2026-09-18: 市場側では Dragon Ball CCG にも66件出ていたが、CCG は 2000年代の
    #   別ゲーム (Score 社)。うちが扱う FB/DBS の弾は Super Card Game なので入れない
    #   (カタログ回答 2026-09-18_aspect_values_vs_ebay_list_response.md)。
    #   実データでも Dragon Ball CCG の中身は イタジャガ (シール) と
    #   ドラゴンボールヒーローズ で、フュージョンワールドではなかった (2026-09-20 確認)。
    "ドラゴンボール": ["Dragon Ball Super Card Game"],
}

DAY_RANGES = {
    "7日": 7, "30日": 30, "90日": 90, "6ヶ月": 180,
    "1年": 365, "2年": 730, "3年": 1095,
}
DEFAULT_DAYS = 90
# ★2026-09-18 ユーザー確定: `PSA10`。eBay の検索は `PSA 10` (間にスペース) も拾うので
#   取りこぼさない (実データで確認済み: "PSA 10 Red's Pikachu 270/SM-P" が入っていた)
KEYWORDS = "PSA10"


def build_url(preset, tab="SOLD", days=DEFAULT_DAYS, keywords=KEYWORDS, now=None):
    """条件セットから Research の URL を作る。

    tab は "SOLD" か "ACTIVE"。days は DAY_RANGES の値 (既定 90)。
    """
    import urllib.parse
    if preset not in PRESETS:
        raise KeyError(f"知らない条件セット: {preset}")
    tab = tab.upper()
    if tab not in ("SOLD", "ACTIVE"):
        raise ValueError(f"tab は SOLD か ACTIVE: {tab}")
    now = now or datetime.datetime.now()
    end = int(now.timestamp() * 1000)
    start = int((now - datetime.timedelta(days=days)).timestamp() * 1000)
    q = [
        ("marketplace", "EBAY-US"),
        ("keywords", keywords),
        ("dayRange", str(days)),
        ("endDate", str(end)),
        ("startDate", str(start)),
        ("categoryId", CATEGORY_CCG),
        ("format", "BEST_OFFER"),
        ("format", "FIXED_PRICE"),
    ]
    q += [("aspect", f"Game:::{g}") for g in PRESETS[preset]]   # 空 = 絞らない
    q += [
        # ★2026-09-20 ユーザー確定「セラーだけ日本にして、取り直しやな」。
        #   9/18 に取った分は **買い手の国 (buyerCountry=JP)** で絞られていた。
        #   買い手が日本人かどうかは どうでもよく、むしろ eBay の買い手は大半が米国なので
        #   市場の大部分を捨てていた。実害: 台帳1,612件に米国セラーの英語版が309件 混ざり、
        #   「英語版が多い」とユーザーに何度も指摘させた。
        #   絞るのは **売る側の国**。うちと同じ土俵の相場を見る。
        ("sellerCountry", "JP"),
        # 買い手の国では絶対に絞らない (ここに buyerCountry を足さないこと)
        ("offset", "0"),
        ("limit", "50"),
        ("tabName", tab),
        ("tz", "Asia/Tokyo"),
    ]
    if tab == "SOLD":
        q.append(("sorting", "-itemssold"))   # 売れた数の多い順 (ACTIVE には無い並び)
    return RESEARCH_BASE + "?" + urllib.parse.urlencode(q)


# ポケモンの形 (175/165 や 270/SM-P)
_CARD_NO = re.compile(r"\b(\d{1,3}\s*/\s*(?:\d{1,3}|[A-Z]{1,3}-?[A-Z]?))\b")
# ワンピース / ドラゴンボールの形 (OP03-057 / ST21-015 / P-001 / FB02-119 / SDV9-020 / MM2-074)
# ★2026-09-18: 斜線の形しか見ていなかったため、この2ゲームは1枚も読めていなかった
_CARD_NO_DASH = re.compile(r"\b([A-Z]{1,4}\d{0,2}-\d{2,3})\b")


def card_no(title):
    """タイトルからカード番号を取る。取れなければ None。

    ★eBay のタイトルは書き方がばらばらなので、番号だけを鍵にする。弾コードは
      セラーによって付いたり付かなかったりするので、鍵にすると取りこぼす。
    """
    if not title:
        return None
    t = title.upper().replace(" /", "/").replace("/ ", "/")
    m = _CARD_NO.search(t)
    if m:
        return m.group(1).replace(" ", "")
    m = _CARD_NO_DASH.search(t)
    if m:
        return m.group(1)
    # ★2026-09-20: eBay カタログが作った形 (斜線もハイフンも無い)
    code, num = ebay_catalog_no(title)
    return f"{code.upper()}-{num}" if code else None


# ★2026-09-20: eBay のカタログが作ったタイトルの形。番号が斜線でもハイフンでもなく
#   「<日本語名の英名> <番号> <レアリティ語> <年> Pokemon Japanese <弾>-<弾名> <和名>」と並ぶ。
#   実測: 番号が読めなかった858行のうち57行がこの形 (販売108個)。
_EBAY_SET = re.compile(r"JAPANESE\s+([A-Z]{1,3}[0-9]{1,2}[A-Z]?)-", re.I)
#   ★"PSA10" の 10 を番号と読まないこと (最初の実装で全部 -010 になった)
_EBAY_NUM = re.compile(r"(?<![0-9/])(\d{2,3})(?![0-9/])")


def ebay_catalog_no(title):
    """eBay カタログ形式のタイトル → (弾コード, 3桁番号)。読めなければ (None, None)。純関数。"""
    t = title or ""
    m = _EBAY_SET.search(t)
    if not m:
        return None, None
    clean = _EBAY_SET.sub(" ", re.sub(r"PSA\s*10", "", t, flags=re.I))
    for n in _EBAY_NUM.finditer(clean):
        v = int(n.group(1))
        if 1900 <= v <= 2100:              # 年は番号ではない
            continue
        return m.group(1), "%03d" % v
    return None, None


def lookup_by_set_and_no(code, num, title, conn):
    """弾コード+番号 → カタログの product_id (I/O)。当てられなければ None。

    ★カタログは `SV3a` `M2a` `SV11W` と **小文字混じり**で書く。こちらが大文字に潰して
      引いていたので当たらなかった (2026-09-20 / ②引き方の誤り。40件 → 54件)。
      `SV11` のように弾が2つに割れている時 (SV11W / SV11B) は **タイトルの和名**で決める。
      決められなければ None = 当てない (推測で当てると別のカードの値段を掴む)。
    """
    rows = conn.execute(
        "SELECT product_id, name_jp FROM products WHERE product_id LIKE ?",
        ("%s%%-%s" % (code, num),)).fetchall()
    ok = [r for r in rows if re.fullmatch(code + "[A-Za-z]?", r[0].split("-")[0], re.I)]
    if len(ok) == 1:
        return ok[0][0]
    for pid, jp in ok:
        if jp and jp in (title or ""):
            return pid
    return None


def _money(s):
    try:
        return float(str(s).replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_ledger():
    return _read(LEDGER) if os.path.exists(LEDGER) else []


def merge(kept, incoming, ingested_at=None):
    """台帳 kept に incoming を混ぜる。鍵が同じなら新しい方を残す。

    返り値は (混ぜた後の行, 足された数, 上書きした数)。
    """
    stamp = ingested_at or datetime.date.today().isoformat()
    index = {tuple(r.get(c, "") for c in KEY_COLS): i for i, r in enumerate(kept)}
    rows = list(kept)
    added = updated = 0
    for r in incoming:
        if not r.get("itemId"):
            continue
        r = dict(r)
        r.setdefault("取込日", stamp)
        k = tuple(r.get(c, "") for c in KEY_COLS)
        if k in index:
            r["取込日"] = rows[index[k]].get("取込日", stamp)  # 初めて見た日を残す
            rows[index[k]] = r
            updated += 1
        else:
            index[k] = len(rows)
            rows.append(r)
            added += 1
    return rows, added, updated


def save_ledger(rows):
    cols = []
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)
    os.makedirs(LEDGER_DIR, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def find_files(paths):
    out = []
    if paths:
        for p in paths:
            out += glob.glob(os.path.join(p, "terapeak_*.csv")) if os.path.isdir(p) else [p]
    else:
        for d in SEARCH_DIRS:
            out += glob.glob(os.path.join(d, "terapeak_*.csv"))
    # summary は 2026-09-18 に廃止。古いものが残っていても取り込まない
    out = sorted(set(p for p in out if "_summary_" not in os.path.basename(p)))
    # ★2026-09-20: **取り込んだファイルは二度と取り込まない**。
    #   Downloads に残ったままなので、取り込むたびに古い条件のデータが戻っていた
    #   (実害: 買い手の国で絞った 9/18 の469行が、退避したのに また入った)。
    done = _ingested()
    return [p for p in out if os.path.basename(p) not in done]


INGESTED = os.path.join(LEDGER_DIR, "ingested.json")


def _ingested():
    """もう取り込んだファイル名 (I/O)。読めなければ空。"""
    try:
        with open(INGESTED, encoding="utf-8") as f:
            v = json.load(f)
        return set(v) if isinstance(v, list) else set()
    except Exception:                                          # noqa: BLE001
        return set()


def _remember_ingested(names):
    """取り込んだファイル名を覚える (I/O)。書けなくても走行は止めない。"""
    try:
        os.makedirs(LEDGER_DIR, exist_ok=True)
        with open(INGESTED, "w", encoding="utf-8") as f:
            json.dump(sorted(_ingested() | set(names)), f, ensure_ascii=False)
    except Exception:                                          # noqa: BLE001
        pass


def cmd_ingest(paths):
    files = find_files(paths)
    if not files:
        print("取り込む CSV が見つかりません (terapeak_*.csv)")
        return 1
    rows = load_ledger()
    before = len(rows)
    for p in files:
        rows, added, updated = merge(rows, _read(p))
        print(f"  {os.path.basename(p):<32} 新規 {added:4} / 更新 {updated:4}")
    _remember_ingested([os.path.basename(p) for p in files])
    save_ledger(rows)
    print(f"\n台帳 {before} → {len(rows)}行  ({LEDGER})")
    warn = warn_if_wrong_filter(rows)
    if warn:
        print(warn)
    return 0


# ★2026-09-20 ユーザー報告「8は英語版」「77、78、79 英語版」「162〜165、173〜175 英語版」
#   「英語版が多いけど」。タイトルの文字だけでは 11件中4件しか見分けられなかった
#   ("Nami (Full Art) ST29-008 Starter Deck 29" のように 英語版と書いていない物が多い)。
#   → 今日 取った GetItem の **Language (相手が申告した値)** を使う。実測 1,271件に入っている
#     (日本語856 / 英語322 / 中国語55 / 韓国語7)。推測でなく申告値で分ける。
_LANG = {}


def lang_by_item():
    """{itemID: 言語} を GetItem の控えから作る (I/O・1回だけ)。無ければ空。"""
    if _LANG:
        return _LANG
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import market_getitem as _G
        for name in os.listdir(_G.OUT_DIR):
            iid = name.split(".")[0]
            try:
                sp = _G.specifics(_G.load_raw(iid))
            except Exception:                                  # noqa: BLE001
                continue
            v = (sp.get("Language") or [""])[0].strip()
            if v:
                _LANG[iid] = v
    except Exception:                                          # noqa: BLE001
        pass
    return _LANG


def is_japanese(row, lang=None):
    """その出品が **日本語版か** (純関数寄り)。分からない時は True = 落とさない。

    うちが売るのは日本語版だけ。英語版・中国語版の値段を混ぜると、別の商品の
    相場を見ることになる。
    """
    lang = lang if lang is not None else lang_by_item()
    v = (lang.get((row.get("itemId") or "").strip()) or "").strip().lower()
    if not v or v == "na":
        return True                       # 申告が無い = 判断材料なし → 落とさない
    return v.startswith("japan")


def by_card(rows, kind="Sold"):
    """カード番号ごとに 売れた数・出品本数・実売中央値 をまとめる。"""
    agg = collections.defaultdict(lambda: {"sold": 0, "listings": 0, "prices": [], "title": ""})
    unknown = 0
    lang = lang_by_item()
    for r in rows:
        if r.get("種別") != kind:
            continue
        if not is_japanese(r, lang):       # 英語版・中国語版は別の商品なので数えない
            continue
        try:
            n = int(r.get("売れた数") or 0)
        except ValueError:
            n = 0
        k = card_no(r.get("タイトル"))
        if not k:
            unknown += n
            continue
        a = agg[k]
        a["sold"] += n
        a["listings"] += 1
        p = _money(r.get("平均落札"))
        if p:
            a["prices"].append(p)
        if len(r.get("タイトル", "")) > len(a["title"]):
            a["title"] = r["タイトル"]
    return agg, unknown


# ---- 探す先に渡す一覧 (市場で売れているのに、うちが出していないカード) ----
# ★抽出くんの決まり (skill harvest-targeting ①-3): 語にしてよいのは「番号が取れた」か
#   「カタログを引けた」時だけ。訳さない・推測しない。だからここでは番号とカタログの和名しか出さない。
CATALOG_DB = r"C:/dev/iMak_data/catalog/products.sqlite"
TARGETS_CSV = os.path.join(LEDGER_DIR, "demand_market.csv")
# ★2026-09-20: 売れ筋の全体 (出品済/未出品 の印つき)。上の demand_market.csv は
#   抽出くんに渡す「うちが出していない分」だけなので、値段の比較には使えなかった。
CARDS_CSV = os.path.join(LEDGER_DIR, "market_cards.csv")

# タイトルの中の弾コード (SV2a / S12a / M2a / CLK / sv1a …)
_SET_CODE = re.compile(r"\b((?:SV|S|M|CLK|SM|XY|BW|DP)[0-9]{0,2}[A-Z]?)\b", re.I)


# ★2026-09-20 ユーザー指摘「カタログ未収録というか、引き方の問題じゃないの?」。
#   そのとおりだった (①カタログにデータは在る / ②こちらが使っていない)。
#   市場のタイトルは弾コードを書かず **英語のセット名**だけのことが多い
#   ("VSTAR Universe" / "Pokemon Card 151" / "VMAX Climax" / "Incandescent Arcana")。
#   カタログの `ebay_filter_map` が「S12a: Vstar Universe」の形で **コード付きの英語名**を
#   持っているので、そこから 名前→コード の表を作って引く。表は作らない (カタログが唯一の口)。
_SET_NAME_RE = re.compile(r"^([A-Za-z0-9-]{2,8}):\s*(.+)$")
_SET_BY_NAME = {}


def set_code_by_name(conn):
    """{英語のセット名(小文字): 弾コード} をカタログから作る (I/O・1回だけ)。"""
    if _SET_BY_NAME:
        return _SET_BY_NAME
    try:
        rows = conn.execute(
            "SELECT DISTINCT ebay_value FROM ebay_filter_map WHERE field LIKE 'set%'"
        ).fetchall()
    except Exception:                                          # noqa: BLE001
        return _SET_BY_NAME
    for (v,) in rows:
        m = _SET_NAME_RE.match((v or "").strip())
        if m:
            _SET_BY_NAME.setdefault(m.group(2).strip().lower(), m.group(1))
    return _SET_BY_NAME


def set_code_from_title(title, conn):
    """タイトルの中の英語セット名 → 弾コード。見つからなければ None。

    長い名前から先に当てる ("Pokemon Card 151" を "151" より先に見る)。
    """
    t = (title or "").lower()
    best = None
    for name, code in set_code_by_name(conn).items():
        if len(name) >= 4 and name in t:
            if best is None or len(name) > len(best[0]):
                best = (name, code)
    return best[1] if best else None


def product_id_candidates(key, title):
    """カード番号 (と市場タイトル) から、カタログの product_id の候補を作る。"""
    if "/" not in key:
        return [key.upper()]                      # OP03-057 / P-043 はそのまま
    num, suffix = key.split("/", 1)
    if not suffix.isdigit():                      # 020/M-P → M-P-020
        return [f"{suffix.upper()}-{num}"]
    out = []
    for m in _SET_CODE.finditer(title or ""):     # 175/165 は弾コードをタイトルから拾う
        code = m.group(1)
        if code.upper() in ("M", "S", "SV"):      # 単独の文字は弾ではない
            continue
        out.append(f"{code}-{num}")
    return out


def lookup_catalog(cands, conn, title=""):
    """product_id でカタログを引く。**完全一致だけ** (名前で探さない)。

    ★2026-09-20: 大文字小文字だけは問わない。カタログは `SV3a` `M2a` と小文字混じりで
      書くのに、こちらが大文字に潰して引いていて当たらなかった (②引き方の誤り)。
      綴りが同じで大小が違うだけの物は同じ物なので、これは「名前で探す」ことにはならない。
    ★弾が枝分かれしている物 (SV11 → SV11W / SV11B) は **タイトルの和名**で決める。
      決められなければ当てない。
    """
    for pid in cands:
        row = conn.execute(
            "SELECT product_id, name, name_jp, category, images FROM products "
            "WHERE product_id = ? COLLATE NOCASE", (pid,)).fetchone()
        if row:
            return row
    for pid in cands:
        m = re.fullmatch(r"([A-Za-z]{1,3}\d{1,2}[A-Za-z]?)-(\d{2,3})", pid or "")
        if not m:
            continue
        got = lookup_by_set_and_no(m.group(1), m.group(2), title, conn)
        if got:
            return conn.execute(
                "SELECT product_id, name, name_jp, category, images FROM products WHERE product_id=?",
                (got,)).fetchone()
    # ★最後に「英語のセット名」から弾コードを当てる (市場のタイトルはコードを書かないことが多い)
    num = ""
    for pid in cands:
        m = re.search(r"-(\d{2,3})$", pid or "")
        if m:
            num = m.group(1)
            break
    if not num:
        m = re.match(r"^(\d{1,3})/", (cands[0] if cands else "") or "")
        num = ("%03d" % int(m.group(1))) if m else ""
    if num:
        code = set_code_from_title(title, conn)
        if code:
            got = lookup_by_set_and_no(code, num, title, conn)
            if got:
                return conn.execute(
                    "SELECT product_id, name, name_jp, category, images "
                    "FROM products WHERE product_id=?", (got,)).fetchone()
    return None


def mine_index(live_keys):
    """うちが出しているカードの索引 (純関数)。戻り: (弾コード付きの集合, 番号→弾コード集合)。"""
    mine_dash, mine_num = set(), collections.defaultdict(set)
    for k in live_keys:
        # ★2026-09-20: 弾コードに `-` が入る物 (M-P-020 / SV-P-098 のプロモ) を拾えていなかった。
        #   末尾の数字より前を弾コードとして見る。
        suf = (k or "").split(":")[-1]
        m = re.match(r"^(.+)-(\d+)$", suf) or re.match(r"^([A-Za-z0-9]+)-(\d+)", suf)
        if m:
            mine_dash.add(f"{m.group(1).upper()}-{m.group(2)}")
            mine_num[m.group(2).lstrip("0")].add(m.group(1).upper())
    return mine_dash, mine_num


def is_mine(key, title, idx):
    """そのカードを うちが出しているか (純関数)。idx は mine_index の戻り。"""
    mine_dash, mine_num = idx
    if "/" in key:
        sets = mine_num.get(key.split("/")[0].lstrip("0"), set())
        t = re.sub(r"[^A-Z0-9]", "", (title or "").upper())
        # ★2026-09-20: 弾コード側も記号を落として比べる。`M-P` のままだと、記号を落とした
        #   タイトル (…020MP) に当たらず、プロモが全部「未出品」に見えていた。
        return any(re.sub(r"[^A-Z0-9]", "", s) in t for s in sets)
    return key.upper() in mine_dash


def cards_with_flag(rows, live_keys, min_sold=2):
    """市場で min_sold 以上売れたカードを **出品済/未出品 の印つき**で返す (純関数)。

    ★2026-09-20 ユーザー指示「売れ筋一覧に出品済、未出品のFLGがあれば、いいんだよね」。
      従来は「うちが出していない分」だけを出していた (抽出くんに渡す用) ので、
      **出している分の実売価格と自分の値段を比べられなかった**。同じ集計から両方出す。
    戻り: [(番号, 集計, 出品済か)] 売れた数の多い順。
    """
    agg, _ = by_card(rows)
    idx = mine_index(live_keys)
    out = [(k, v, is_mine(k, v["title"], idx))
           for k, v in agg.items() if v["sold"] >= min_sold]
    return sorted(out, key=lambda x: -x[1]["sold"])


def missing_cards(rows, live_keys, min_sold=2):
    """市場で min_sold 以上売れたのに、うちが出していないカード。"""
    return [(k, v) for k, v, have in cards_with_flag(rows, live_keys, min_sold) if not have]


# ---- 実売価格 → 上限の仕入れ値 (cost-plus の逆引き) ----
# ★式は持たない。出品と同じ pricing_engine を二分探索で逆に解くだけ。
#   ここに計算式を写すと、値付けを変えた時に2箇所になる (SSOT を割らない)。
PROFIT_CATEGORY = "TCG(PSA10)"


def max_cost_jpy(price_usd, category=PROFIT_CATEGORY, lo=100, hi=300000):
    """その値段で売るには、仕入れがいくらまでなら出せるか (円)。

    出品価格は仕入れ値に対して単調に増えるので、二分探索で解ける。
    解けない (安すぎて下限でも超える) 時は None。
    """
    if not price_usd or price_usd <= 0:
        return None
    sys.path.insert(0, r"C:/dev/iMak/iMakeBayAPI")
    from pricing_engine import compute_listing_price

    def price_of(cost):
        return compute_listing_price(cost, 0, category)["price"]

    try:
        if price_of(lo) > price_usd:
            return None                      # 一番安い仕入れでも、この値段では出せない
        for _ in range(40):
            mid = (lo + hi) / 2
            if price_of(mid) <= price_usd:
                lo = mid
            else:
                hi = mid
        return int(lo // 100 * 100)          # 100円単位で切り捨て (安全側)
    except Exception:                        # noqa: BLE001 価格が出せない時は付けない
        return None


def cmd_targets(argv):
    """探す先の一覧を作る (毎回作り直す。焼いた値は残さない)。"""
    import sqlite3
    rows = load_ledger()
    if not rows:
        print("台帳が空です。先に ingest してください")
        return 1
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import psa_hoju_fill as H
    live = H.select_backfill_targets(H._read_high(), max_backups=H.AUXN + 1)
    miss = missing_cards(rows, [t.get("key") for t in live])

    conn = sqlite3.connect(CATALOG_DB)
    out, hit = [], 0
    for k, v in miss:
        row = lookup_catalog(product_id_candidates(k, v["title"]), conn, v["title"])
        if row:
            hit += 1
        med = round(statistics.median(v["prices"]), 2) if v["prices"] else 0
        out.append({
            "番号": k,
            "product_id": row[0] if row else "",
            "和名": row[2] if row else "",
            "英名": row[1] if row else "",
            "画像": first_image(row[4]) if (row and len(row) > 4) else "",
            "ゲーム": row[3] if row else "",
            "売れた数": v["sold"],
            "出品本数": v["listings"],
            "実売中央値": med,
            "上限仕入れ値(円)": max_cost_jpy(med) if med else "",
            "市場のタイトル例": v["title"][:80],
        })
    cols = list(out[0].keys())
    with open(TARGETS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    print(f"市場で2個以上売れて、うちが出していない: {len(out)}種類 / 販売 "
          f"{sum(r['売れた数'] for r in out)}個")
    print(f"カタログを引けた: {hit}種類 ({hit / len(out):.0%})")
    print(f"→ {TARGETS_CSV}")
    return 0


FUNNEL_DIR = r"C:/dev/iMak/iMakHQ/funnel_output"


def _our_prices():
    """itemID → うちの eBay 出品価格 (USD)。一番新しいファネルCSVから (I/O)。

    ★商品管理シートの「商品価格」は **仕入元 (メルカリ) の円**なので使えない
      (2026-09-20 に取り違えた)。うちの売値が載っているのはファネルだけ。US のみ見る
      (UK/AU/CA は eBaymag のミラーで itemID が別物)。
    """
    files = sorted(glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv")))
    if not files:
        return {}
    out = {}
    with open(files[-1], encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("site") or "") != "US":
                continue
            p = _money(r.get("price"))
            if r.get("item_id") and p:
                out[r["item_id"].strip()] = (p, r.get("title") or "")
    return out


# ★2026-09-20: 番号だけで突き合わせると **別物の値段**を掴む (実測)。
#   シャンクス OP09-004: うち $272 に対して "Manga Alt Art comic parallel" が $19,447。
#   満身創痍 ST01-012: うち $186 に対して "1st Anniversary 尾田サイン入り" が $5,165。
#   ナミ OP08-106 は英語版、格闘戦 ST03-013 は中国語版だった。
#   同じ番号でも **刷り・言語・特別仕様が違えば別の商品**。印が食い違う行は値段に使わない。
_MARKERS = (
    ("英語版", ("ENGLISH", "ENG ")),
    ("中国語版", ("CHINESE", "CHN")),
    ("韓国語版", ("KOREAN",)),
    ("サイン", ("SIGNATURE", "SIGNED", "AUTOGRAPH", "SIGNATURE")),
    ("記念", ("ANNIVERSARY",)),
    # ★2026-09-20 訂正 (ユーザー「FB05-119とかも値上げできるのでは?」):
    #   「Alt Art」「Manga」は **同じカードの呼び名**で、別商品の印ではない。
    #   実例: 孫悟空 FB05-119 は そのカード自体が別イラストの SCR。市場側だけが
    #   "Alt Art" と書いていたために 別物と判定し、$730 の実売を捨てていた。
    #   番号が同じで 言語・サイン・大会賞品 が同じなら、同じ商品として比べてよい。
    ("パラレル", ("PARALLEL", "パラレル")),
    # ★大会の賞品は同じ番号でも別物 (実測: シャンクス OP09-004 の
    #   "SR final-T Best32 Promo Championship 2025" が $37,000。うちの通常版は $272)。
    ("大会賞品", ("CHAMPIONSHIP", "TOURNAMENT", "WINNER", "TOP 8", "BEST32", "BEST 32")),
    ("プロモ", ("PROMO",)),
)


def markers(title):
    """タイトルが名乗っている「別物の印」(純関数)。無ければ空集合。"""
    t = (title or "").upper()
    return {name for name, words in _MARKERS if any(w in t for w in words)}


def _rarity(title):
    """タイトルに明記されたレアリティ (SEC / SP / SR …)。補URL目視と同じ判定を使う。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # ★語で書かれた分も拾う (うちの eBay タイトルは "Super Rare" と綴る)。
    t = (title or "").upper()
    out = set()
    for word, tok in (("SECRET RARE", "SEC"), ("SUPER RARE", "SR"),
                      ("ULTRA RARE", "UR"), ("ART RARE", "AR"),
                      ("SPECIAL RARE", "SP"), ("TREASURE RARE", "TR")):
        if word in t:
            out.add(tok)
    try:
        import psa_hoju_fill as _H
        return out | _H._rarity_tokens(title)
    except Exception:                                          # noqa: BLE001
        return out


def same_product(our_title, market_title):
    """同じ商品として値段を比べてよいか (純関数寄り)。食い違えば比べない。

    ★2026-09-20: 印 (英語版/サイン/記念/パラレル 等) に加えて **レアリティ**も見る。
      OP05-119 ルフィは うち $150 に対し、市場の `SEC` / `SP` / `Alt Art` が $675〜$1,001
      だった。番号が同じでも SEC と通常は別の商品。
    """
    if markers(our_title) != markers(market_title):
        return False
    # ★値段を比べる用途なので **完全に同じレアリティ**でなければ比べない。
    #   OP05-119 は うちが SEC、市場が "Sec Sp" で、重なりを見る判定では通ってしまった。
    ro, rm = _rarity(our_title), _rarity(market_title)
    if ro and rm and ro != rm:
        return False
    return True


PRICE_CACHE = os.path.join(LEDGER_DIR, "our_prices.json")


def _price_from_ebay(item_ids):
    """ファネルに無い出品の値段を eBay に聞く (I/O)。

    ★2026-09-20 ユーザー報告「出品済で、うちの値段がないんだけど」。
      値段の出どころをファネルだけにしていたので、**出品したての物は必ず空**になっていた
      (実例: 9/14 出品の2件が 9/19 のファネルに載っていない。ファネルは表示回数が
      溜まってから載る)。足りない分だけ GetItem で補い、取れた分は残す。
    """
    import re as _re
    import requests
    try:
        cache = json.load(open(PRICE_CACHE, encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        cache = {}
    todo = [i for i in item_ids if i not in cache]
    if todo:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import market_getitem as _G
        for iid in todo[:60]:                 # 一度に取りすぎない
            body = ('<?xml version="1.0" encoding="utf-8"?>'
                    '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                    f"<ItemID>{iid}</ItemID></GetItemRequest>")
            try:
                r = requests.post(_G.EP, data=body.encode("utf-8"),
                                  headers=_G.headers("GetItem"), timeout=30)
                x = r.content.decode("utf-8", "replace")
                m = _re.search(r'<CurrentPrice currencyID="USD">([\d.]+)</CurrentPrice>', x)
                t = _re.search(r"<Title>(.*?)</Title>", x, _re.S)
                cache[iid] = [float(m.group(1)) if m else None,
                              t.group(1) if t else ""]
            except Exception:                                  # noqa: BLE001
                cache[iid] = [None, ""]
        try:
            os.makedirs(LEDGER_DIR, exist_ok=True)
            with open(PRICE_CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:                                      # noqa: BLE001
            pass
    return cache


def _live_rows():
    """出品中の行 → [(KEY, 出品価格USD, itemID, タイトル)] (I/O)。売り切れは除く。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sheet_io as _S
    usd = _our_prices()
    rows2d = _S._product_ws().get_all_values()[1:]
    live_ids = [(r[1].strip() if len(r) > 1 else "") for r in rows2d
                if (len(r) > 1 and r[1].strip()) and not (len(r) > 3 and r[3].strip())]
    # ファネルに無い分だけ eBay に聞く (出品したては必ずファネルに無い)
    extra = _price_from_ebay([i for i in live_ids if i and i not in usd])
    out = []
    for r in rows2d:
        g = lambda i: (r[i].strip() if len(r) > i else "")
        if not g(1) or g(3):                       # itemID 無 / 売り切れ
            continue
        # ★2026-09-20: 比べるのは **うちの eBay タイトル** (ファネル)。シートの C列は
        #   仕入元 (メルカリ) の日本語タイトルなので、市場の英語タイトルとは比べられない。
        p, t = usd.get(g(1)) or tuple(extra.get(g(1)) or (None, ""))
        out.append((g(34), p, g(1), t or g(2)))
    return out


def first_image(images_json):
    """カタログの images (JSON配列の文字列) → 先頭のURL (純関数)。無ければ空。

    ★2026-09-20 ユーザー「カード画像で見たいねん。テキストだけだとイメージがわかない。
      カタログ画像でいいよ。カタログになければ要補充もわかるし」。
    """
    try:
        v = json.loads(images_json) if isinstance(images_json, str) else images_json
    except Exception:                                          # noqa: BLE001
        return ""
    if isinstance(v, list) and v:
        return str(v[0])
    return str(v) if isinstance(v, str) else ""


def build_cards(min_sold=2):
    """売れ筋の一覧を作る (I/O)。戻り: (行, まとめ)。CSV も画面も同じものを使う。

    ★2026-09-20 ユーザー「よく売れているカードをHTMLで表示して欲しい。何のカードか、
      何枚売れたか、いくらで売れたか、内が出せているかどうか」。
    """
    import sqlite3
    rows = load_ledger()
    if not rows:
        return [], {"error": "台帳が空です。先に ingest してください"}
    live = _live_rows()
    _, unknown = by_card(rows)
    cards = cards_with_flag(rows, [k for k, _p, _i, _t in live], min_sold)

    ours = [(price, title, mine_index([key])) for key, price, _i, title in live if price]
    mine_of = collections.defaultdict(list)
    for k, v, have in cards:
        if not have:
            continue
        for price, title, one in ours:
            if is_mine(k, v["title"], one):
                mine_of[k].append((price, title))
    mine_pids = collections.defaultdict(list)
    for key, price, _iid, title in live:
        pid = (key or "").split(":")[-1].upper()
        if pid and price and "/" not in pid:
            mine_pids[pid].append((price, title))      # 鍵は大文字に揃えてある
            # ★2026-09-20 ユーザー「FB05-119とかも値上げできるのでは?」「OP05-119とか」。
            #   うちの鍵は変種の印が付く (`FB05-119_PARA` / `OP05-119_PRB01_1`) のに、
            #   市場側は番号だけ (`FB05-119`) なので照合できていなかった。
            #   **印の前の番号でも引けるようにする**。刷り違いは この後の
            #   same_product (言語・レアリティ・サイン・大会賞品) で落とす。
            base = pid.split("_", 1)[0]
            if base != pid:
                mine_pids[base].append((price, title))
    rows_of = collections.defaultdict(list)
    for r in rows:
        if r.get("種別") != "Sold":
            continue
        k = card_no(r.get("タイトル"))
        pr = _money(r.get("平均落札"))
        if k and pr:
            rows_of[k].append((pr, r.get("タイトル") or ""))

    conn = sqlite3.connect(CATALOG_DB)
    out, hit = [], 0
    for k, v, have in cards:
        row = lookup_catalog(product_id_candidates(k, v["title"]), conn, v["title"])
        if row:
            hit += 1
        med = round(statistics.median(v["prices"]), 2) if v["prices"] else 0
        mine = mine_of.get(k) or []
        low = min(p for p, _t in mine) if mine else ""
        fair = ""
        # ★2026-09-20 ユーザー報告「出品済で、うちの値段がないんだけど」。
        #   カタログは `SV2a-195` と小文字混じりで書くのに、こちらは大文字に潰した鍵で
        #   索引を作っていたので、照合できず値段が空になっていた (②引き方の誤り)。
        pid = (row[0] if row else "").upper()
        if pid and pid in mine_pids:
            our_title = min(mine_pids[pid])[1]
            ok = [pr for pr, t in rows_of.get(k, []) if same_product(our_title, t)]
            fair = round(statistics.median(ok), 2) if ok else ""
            low = min(p for p, _t in mine_pids[pid])
        out.append({
            "番号": k,
            "product_id": pid,
            "和名": row[2] if row else "",
            "英名": row[1] if row else "",
            "画像": first_image(row[4]) if (row and len(row) > 4) else "",
            "ゲーム": row[3] if row else "",
            "出品状況": "出品済" if have else "未出品",
            "売れた数": v["sold"],
            "出品本数": v["listings"],
            "実売中央値": med,
            "うちの値段": low,
            "比べてよい実売": fair,
            "差額": round(fair - low, 2) if (low and fair) else "",
            "上限仕入れ値(円)": max_cost_jpy(med) if med else "",
            "市場のタイトル例": v["title"][:90],
        })
    mine_n = sum(1 for r in out if r["出品状況"] == "出品済")
    cheap = [r for r in out if r["差額"] != "" and r["差額"] > 0]
    summary = {"カード": len(out), "出品済": mine_n, "未出品": len(out) - mine_n,
               "番号が読めなかった販売": unknown,
               "カタログを引けた": hit, "引けなかった": len(out) - hit,
               "実売より安い": len(cheap),
               "取り逃し合計": round(sum(r["差額"] for r in cheap), 2)}
    return out, summary


def cmd_cards(argv):
    """売れ筋の一覧を **出品済/未出品 の印つき**で出す (毎回作り直す)。"""
    out, summary = build_cards()
    if not out:
        print(summary.get("error") or "空です")
        return 1
    with open(CARDS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"売れ筋 {summary['カード']}種類 — 出品済 {summary['出品済']} / 未出品 {summary['未出品']}")
    print(f"特定できず: 番号が読めなかった販売 {summary['番号が読めなかった販売']}個 / "
          f"カタログを引けなかったカード {summary['引けなかった']}種類 "
          f"(引けた {summary['カタログを引けた']})")
    cheap = [r for r in out if r["差額"] != "" and r["差額"] > 0]
    if cheap:
        print(f"実売中央値より安く出している: {len(cheap)}件 / 差額の合計 ${summary['取り逃し合計']:,.2f}")
        for r in sorted(cheap, key=lambda x: -x["差額"])[:10]:
            print(f"  +${r['差額']:>7.2f}  今 ${r['うちの値段']:>7.2f} → 比べてよい実売 "
                  f"${r['比べてよい実売']:>7.2f} ({r['売れた数']}個)  {r['和名'] or r['番号']}")
    else:
        print("実売中央値より安く出している出品はありません")
    print("★この一覧は **候補まで**。値上げは1件ずつ人が確かめてから (自動で変えない)。")
    print(f"→ {CARDS_CSV}")
    return 0


CARDS_HTML = os.path.join(LEDGER_DIR, "market_cards.html")

_HTML_HEAD = """<!doctype html><html lang="ja"><meta charset="utf-8">
<title>よく売れているカード</title>
<style>
 :root{--bg:#14161a;--card:#1b1e24;--line:#2a2f38;--ink:#e8eaed;--ink2:#a9b0bb;--ink3:#767d88;
       --sunken:#20242b}
 /* ★2026-09-20 ユーザー「フィルタ以下がスクロールする感じで固定して欲しい」。
    見出しと絞り込みは動かさず、カードの並びだけスクロールさせる。 */
 html,body{height:100%}
 body{margin:0;background:var(--bg);color:var(--ink);height:100vh;
      display:flex;flex-direction:column;overflow:hidden;
      font:14px/1.6 "Yu Gothic UI","Segoe UI",system-ui,sans-serif}
 header{padding:18px 22px;border-bottom:1px solid var(--line);flex:none}
 h1{margin:0 0 4px;font-size:20px}
 .sum{color:var(--ink2);font-size:13px}
 .bar{display:flex;gap:6px;padding:12px 22px;flex-wrap:wrap;border-bottom:1px solid var(--line);
      background:var(--bg);flex:none}
 .chip{background:var(--card);border:1px solid var(--line);color:var(--ink2);border-radius:20px;
       padding:5px 14px;font-size:13px;cursor:pointer}
 .chip.on{background:#1e3a5f;color:#8ec8ff;border-color:#2f5d94}
 /* ★2026-09-20 ユーザー「カードをもう少し大きくしてほしいのと、ナンバリングして
    横に5枚くらい並べて」。表をやめて **5列のカード並び**にする。 */
 .grid{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;padding:16px 22px;
       overflow-y:auto;flex:1 1 auto;align-content:start}
 @media(max-width:1500px){.grid{grid-template-columns:repeat(4,1fr)}}
 @media(max-width:1200px){.grid{grid-template-columns:repeat(3,1fr)}}
 @media(max-width:880px){.grid{grid-template-columns:repeat(2,1fr)}}
 .it{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;
     position:relative}
 .rank{position:absolute;left:10px;top:10px;background:#1e3a5f;color:#8ec8ff;font-weight:700;
       font-size:12px;border-radius:14px;padding:2px 9px;z-index:1}
 .ph{display:flex;align-items:center;justify-content:center;height:280px;margin-bottom:10px}
 img.c{max-width:100%;max-height:280px;object-fit:contain;border-radius:6px}
 .none{width:190px;height:265px;display:flex;align-items:center;justify-content:center;
       border:2px dashed #a8703a;border-radius:6px;color:#ffc48e;font-size:13px;font-weight:700}
 .nm{font-weight:700;font-size:15px;margin-bottom:2px}
 .no{color:var(--ink3);font-size:12px;margin-bottom:8px}
 .kv{display:flex;justify-content:space-between;font-size:13px;padding:2px 0}
 .kv span:first-child{color:var(--ink2)}
 .kv b{font-variant-numeric:tabular-nums}
 .sub{color:var(--ink3);font-size:11px;margin-top:8px;line-height:1.4}
 .st{border-radius:20px;padding:2px 10px;font-size:11px;font-weight:700}
 .st.yes{background:#1e3a5f;color:#8ec8ff} .st.no{background:#5f3a1e;color:#ffc48e}
 .gain{color:#7ddc9a;font-weight:700}
 .foot{display:flex;justify-content:space-between;align-items:center;margin-top:10px}
</style>
"""


def cards_html(rows, summary):
    """売れ筋の一覧を1枚の HTML にする (純関数)。コンソールには埋めない。

    ★2026-09-20 ユーザー「よく売れているカードというボタンを作って、押したら別で HTML が
      立ち上がるようにして。コンソールが汚れるやろ」。
    """
    def esc(v):
        return (str(v) if v is not None else "").replace("&", "&amp;")             .replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def money(v):
        return "—" if v in ("", None) else "$%.2f" % float(v)

    body = []
    for n, r in enumerate(sorted(rows, key=lambda x: -x["売れた数"]), 1):
        img = (f"<img class='c' src='{esc(r['画像'])}' loading='lazy' alt=''>"
               if r.get("画像") else "<div class='none'>カタログ<br>要補充</div>")
        gain = ("<span class='gain'>+%.2f</span>" % r["差額"])             if (r["差額"] != "" and r["差額"] > 0) else ""
        st = ("<span class='st yes'>出品済</span>" if r["出品状況"] == "出品済"
              else "<span class='st no'>未出品</span>")
        body.append(
            f"<div class='it' data-st='{esc(r['出品状況'])}'"
            f" data-gain='{1 if gain else 0}' data-cat='{1 if r['product_id'] else 0}'>"
            f"<div class='rank'>{n}</div>"
            f"<div class='ph'>{img}</div>"
            f"<div class='nm'>{esc(r['和名'] or r['英名'] or '(カタログ未収録)')}</div>"
            f"<div class='no'>{esc(r['番号'])}</div>"
            f"<div class='kv'><span>売れた数</span><b>{r['売れた数']}個</b></div>"
            f"<div class='kv'><span>実売の中央値</span><b>{money(r['実売中央値'])}</b></div>"
            f"<div class='kv'><span>うちの値段</span><b>{money(r['うちの値段'])}</b></div>"
            f"<div class='foot'>{st}{gain}</div>"
            f"<div class='sub'>{esc(r['市場のタイトル例'])}</div></div>")
    sm = summary
    return (_HTML_HEAD +
            "<header><h1>よく売れているカード</h1><div class='sum'>"
            f"市場で2個以上売れた {sm['カード']}種類 — 出品済 {sm['出品済']} / "
            f"未出品 {sm['未出品']} · カタログを引けなかった {sm['引けなかった']}種類 · "
            f"番号が読めなかった販売 {sm['番号が読めなかった販売']}個</div></header>"
            "<div class='bar'>"
            "<button class='chip on' data-f='all'>全部</button>"
            "<button class='chip' data-f='no'>未出品だけ</button>"
            "<button class='chip' data-f='yes'>出品済だけ</button>"
            "<button class='chip' data-f='gain'>値上げできる</button>"
            "<button class='chip' data-f='nocat'>カタログ要補充</button></div>"
            "<div class='grid'>" + "".join(body) + "</div>"
            "<script>"
            "document.querySelectorAll('.chip').forEach(function(b){b.onclick=function(){"
            "document.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on')});"
            "b.classList.add('on');var f=b.dataset.f;"
            "document.querySelectorAll('.it').forEach(function(tr){var ok=true;"
            "if(f==='no')ok=tr.dataset.st==='未出品';"
            "if(f==='yes')ok=tr.dataset.st==='出品済';"
            "if(f==='gain')ok=tr.dataset.gain==='1';"
            "if(f==='nocat')ok=tr.dataset.cat==='0';"
            "tr.style.display=ok?'':'none';});};});"
            "</script></html>")


def cmd_html(_argv):
    """売れ筋の一覧を HTML にしてブラウザで開く。"""
    import webbrowser
    rows, summary = build_cards()
    if not rows:
        print(summary.get("error") or "空です")
        return 1
    with open(CARDS_HTML, "w", encoding="utf-8") as f:
        f.write(cards_html(rows, summary))
    print(f"売れ筋 {summary['カード']}種類 — 出品済 {summary['出品済']} / "
          f"未出品 {summary['未出品']} / カタログ要補充 {summary['引けなかった']}")
    print(f"→ {CARDS_HTML}")
    webbrowser.open("file:///" + CARDS_HTML.replace("\\", "/"))
    return 0


def cmd_archive(_argv):
    """今の台帳を日付つきで退避して、空にする。

    ★2026-09-20 ユーザー「セラーだけ日本にして、取り直しやな」。
      条件が変わったデータを混ぜると、前の条件で入った行が残り続ける
      (台帳は出品ごとに1行で、同じ出品は上書きしないため)。
    """
    import datetime as _dt
    import shutil
    if not os.path.exists(LEDGER):
        print("台帳がありません")
        return 1
    dst = LEDGER.replace(".csv", "_" + _dt.date.today().isoformat() + "_buyerCountryで取った分.csv")
    shutil.move(LEDGER, dst)
    print(f"退避しました → {dst}")
    print("次: リサーチを開いて取り直し → ingest")
    return 0


def warn_if_wrong_filter(rows):
    """取り込んだ行の検索条件を見て、**買い手の国で絞っていたら**知らせる (純関数)。

    ★9/18 の取り込みは buyerCountry=JP で絞られていて、米国セラーの英語版が309件 入った。
      同じことを黙って通さない。
    """
    bad = [r for r in (rows or [])
           if "buyerCountry" in ((r.get("条件") or "") + (r.get("検索語") or ""))]
    if bad:
        return ("⚠ 買い手の国 (buyerCountry) で絞った条件が混ざっています: "
                f"{len(bad)}行。絞るのは **売る側の国** (sellerCountry)。"
                "Research の画面で Seller location が日本になっているか見てください")
    return ""


def cmd_report(_):
    rows = load_ledger()
    if not rows:
        print("台帳が空です。先に ingest してください")
        return 1
    sold = [r for r in rows if r.get("種別") == "Sold"]
    days = sorted(set(r.get("取込日", "") for r in rows))
    print(f"台帳 {len(rows)}行 (Sold {len(sold)}) / 取込 {days[0]}〜{days[-1]}")
    agg, unknown = by_card(rows)
    total = sum(a["sold"] for a in agg.values()) + unknown
    print(f"販売 {total}個 / 番号が読めた {total - unknown}個 / カード {len(agg)}種類")
    multi = {k: a for k, a in agg.items() if a["sold"] >= 2}
    print(f"**2個以上売れたカード {len(multi)}種類**\n")
    print(f"{'個数':>4} {'中央値':>9}  {'番号':<12} カード")
    for k, a in sorted(agg.items(), key=lambda x: -x[1]["sold"])[:30]:
        med = statistics.median(a["prices"]) if a["prices"] else 0
        print(f"{a['sold']:>4} {med:>9.2f}  {k:<12} {a['title'][:52]}")
    if len(days) > 1:
        newest = days[-1]
        fresh = {k for k, a in by_card([r for r in rows if r.get("取込日") == newest])[0].items()}
        old = {k for k, a in by_card([r for r in rows if r.get("取込日") != newest])[0].items()}
        print(f"\n{newest} に初めて出てきたカード: {len(fresh - old)}種類")
    return 0


def main(argv):
    cmds = {"ingest": cmd_ingest, "report": cmd_report, "targets": cmd_targets,
            "cards": cmd_cards, "html": cmd_html,
            "archive": cmd_archive}
    if len(argv) < 2 or argv[1] not in cmds:
        print(__doc__)
        return 1
    return cmds[argv[1]](argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
