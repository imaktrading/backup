"""demand_keywords - 「需要が実証されたカード」から収集キーワードを作る.

2026-08-18 新設 (user 指摘「ファネル分析はそのための分析では？」)。

これまでの収集キーワードは弾コードの総当たり (`psa_search_terms`) で、
**市場にある物を舐めているだけで需要を見ていなかった**。
HQ の「ファネル分析」スプシには 在庫切れ × 需要実証済 (= RESTOCK バケツ) が
既に出ているので、そこからカード番号を取って検索語にする。

  RESTOCK の定義 (ファネル分析 Summary より):
    在庫=0 ∩ 需要>0 (生涯販売 + watch + 90日 impressions)

つまり **「売れる/見られているのに今 出せていないカード」**。ここを埋めるのが
一番 効率がよい。番号が取れない行 (キャラ名だけの出品等) は対象外にする
(推測で検索語を作ると別カードを拾うため = 出品の正確性原則)。
"""
from __future__ import annotations

import re

FUNNEL_SHEET_ID = "1UkaI4W6YCJgUbjgF7LLNN9_fHeVuz5qB4r9RqImElwg"
RESTOCK_TAB = "RESTOCK"
PREFIX = "PSA10"

# 需要マップ (HQ 「既存メンテ」スプシ) の キャラ軸。
# 「国内で在庫が切れていて需要がある キャラ」 が判定付きで出ている。
MAINTENANCE_SHEET_ID = "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4"
DEMAND_MAP_TAB = "需要マップ"
# 採用する判定。 🔴死筋 と 判定なし は採らない (= 判定が出ていない物を勝手に拾わない)
DEMAND_MAP_OK_MARKS = ("🔵", "🟢")

# カード番号 (例 OP08-106 / GD02-072 / SB02-001 / SV4a-123)。
# 弾コード = 英字2-4 + 数字2 (+ 英小文字1)、 通し番号 = 数字3。
# 境界は \b ではなく ASCII 英数字の有無で見る。 日本語タイトルでは \b が効かず
# 「ボア・ハンコック_ST17-004」「パラレルST30-001」 を取り逃がす (2026-08-18 実測)。
_CARD_NO_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2,4}\d{2}[A-Za-z]?)[-‐ ]?(\d{3})(?![0-9])")

# ゲームごとに番号表記が違うので受け皿を用意する (2026-08-18 実測: この2つで
# 「番号が取れない」52件のうち 29件が拾えた)。
#   ポケモン: "#077/071" "#232/S-P" "#196/SV-P" のような 分数表記
#   プロモ  : "P-053" "P-066"
_ALT_NO_RES = (
    re.compile(r"#(\d{2,3}/[A-Za-z0-9]{1,4}(?:-[A-Za-z0-9]{1,2})?)"),
    re.compile(r"\b(P-\d{3})\b", re.IGNORECASE),
)

# タイトルから ゲーム (= カタログの category) を当てる。 当たらない商材
# (Weiss Schwarz 等) は対象外にする = 別ゲームのカード名で誤変換しないため。
GAME_HINTS: dict[str, tuple[str, ...]] = {
    "one_piece_tcg": ("ONE PIECE", "ONEPIECE"),
    "pokemon_tcg": ("POKEMON", "POKÉMON"),
    "dragonball_scg": ("DRAGON BALL", "DRAGONBALL", "FUSION WORLD"),
    "gundam_tcg": ("GUNDAM",),
}

# 英名 → 和名 に変換する時の最短長。 短い語は別単語の一部に化ける
_MIN_NAME_LEN = 4

# PSA 出品だけを対象にする (同じ RESTOCK に PSA でない出品も入っている)
_PSA_RE = re.compile(r"\bPSA\s*10\b|\bPSA\b", re.IGNORECASE)


def extract_card_number(title: str) -> str:
    """出品タイトルからカード番号を取り出す (取れなければ "")."""
    up = (title or "").upper()
    m = _CARD_NO_RE.search(up)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    for pat in _ALT_NO_RES:
        m = pat.search(title or "")
        if m:
            return m.group(1).upper()
    return ""


def detect_game(title: str) -> str:
    """タイトルから カタログの category を当てる (当たらなければ "")."""
    up = (title or "").upper()
    for cat, hints in GAME_HINTS.items():
        if any(h in up for h in hints):
            return cat
    return ""


def resolve_japanese_name(title: str, name_map: dict) -> str:
    """カタログの 英名→和名 表を使って タイトル中のカード名を和名にする.

    name_map: {category: {英名(大文字): 和名}}
    - **単語境界で照合する**。 部分一致だと SIGNATURE の中の NATU を拾って
      別カード (ネイティ) に化ける (2026-08-18 実測)。
    - 複数当たったら **最長一致**を採る (より具体的な名前を優先)。
    - ゲームが判らないタイトルは変換しない (別ゲームのカード名で誤変換しないため)。
    """
    cat = detect_game(title)
    table = (name_map or {}).get(cat)
    if not table:
        return ""
    up = (title or "").upper()
    hits = [en for en in table
            if len(en) >= _MIN_NAME_LEN
            and re.search(rf"(?<![A-Z0-9]){re.escape(en)}(?![A-Z0-9])", up)]
    if not hits:
        return ""
    return table[max(hits, key=len)]


def demand_score(row: dict) -> float:
    """需要の強さ。 実売 > watch > 露出 の順に効かせる (並べ替え用の目安)."""
    def _num(key: str) -> float:
        try:
            return float(str(row.get(key) or "0").replace(",", ""))
        except ValueError:
            return 0.0

    return _num("sales90") * 100 + _num("watch") * 10 + _num("impr") / 1000.0


# カタログの category → 収集側のゲーム名 (`psa_search_terms.GAMES` と同じ綴り)
CATEGORY_TO_GAME = {
    "one_piece_tcg": "onepiece",
    "pokemon_tcg": "pokemon",
    "dragonball_scg": "dragonball",
    "gundam_tcg": "gundam",
}


def _game_of(title: str) -> str:
    return CATEGORY_TO_GAME.get(detect_game(title), "")


def build_keywords_from_rows(rows: list[dict], prefix: str = PREFIX,
                             limit: int = 0, name_map: dict | None = None,
                             games=None) -> list[str]:
    """RESTOCK 行から検索キーワードを作る (純関数).

    Args:
        rows: {"title","watch","impr","sales90",...} の dict 列 (ヘッダ行は含めない)
        limit: 上位何語まで (0 = 全部)
        name_map: {category: {英名: 和名}} を渡すと、 番号が取れない行を
                  **カタログ引き当ての和名**で拾う (推測ではなく lookup)
    Returns:
        需要の強い順・重複なしの検索キーワード (例 "PSA10 OP08-106" / "PSA10 ニコ・ロビン")
    """
    want = set(games) if games else None
    best: dict[str, float] = {}
    for r in rows:
        title = r.get("title") or ""
        if not _PSA_RE.search(title):
            continue
        if want is not None and _game_of(title) not in want:
            continue
        code = extract_card_number(title) or resolve_japanese_name(title, name_map or {})
        if not code:
            continue
        score = demand_score(r)
        if score > best.get(code, -1.0):
            best[code] = score
    ordered = sorted(best, key=lambda c: (-best[c], c))
    if limit:
        ordered = ordered[:limit]
    return [f"{prefix} {c}" for c in ordered]


def parse_demand_map(values: list[list[str]]) -> list[dict]:
    """需要マップ シートの 「属性別詳細」 表を dict 列にする (純関数).

    上に系統サマリー等が乗っているので、 `観点` 見出しの行を探して そこから読む。
    """
    head_i = next((i for i, r in enumerate(values) if r and r[0].strip() == "観点"), -1)
    if head_i < 0:
        return []
    header = [c.strip() for c in values[head_i]]
    return [dict(zip(header, r)) for r in values[head_i + 1:] if any(r)]


def _name_map_all(name_map: dict, games=None) -> dict:
    """{category: {英名: 和名}} を 1 枚に潰す。 和名が割れる英名は捨てる (fail-closed).

    games を渡すと そのゲームのカタログだけ使う。
    """
    want = set(games) if games else None
    seen: dict[str, set] = {}
    for cat, table in (name_map or {}).items():
        if want is not None and CATEGORY_TO_GAME.get(cat, cat) not in want:
            continue
        for en, jp in table.items():
            seen.setdefault(en, set()).add(jp)
    return {en: next(iter(jps)) for en, jps in seen.items() if len(jps) == 1}


def build_character_keywords(rows: list[dict], name_map: dict,
                             prefix: str = PREFIX, limit: int = 0,
                             games=None) -> list[str]:
    """需要マップの キャラ軸から検索キーワードを作る (純関数).

    - 判定が 🔵国内実需 / 🟢売れ筋 の行だけ採る (🔴死筋・判定なしは採らない)
    - 英名 → 和名 は **カタログの lookup のみ**。 表に無いキャラは語にしない
    - 国内OOS数 (= 在庫切れの本数) が多い順
    """
    table = _name_map_all(name_map, games=games)
    picked: dict[str, float] = {}
    for r in rows:
        if (r.get("観点") or "").strip() != "キャラ":
            continue
        verdict = (r.get("判定") or "").strip()
        if not verdict.startswith(DEMAND_MAP_OK_MARKS):
            continue
        jp = table.get((r.get("値") or "").strip().upper())
        if not jp:
            continue
        try:
            oos = float(str(r.get("国内OOS数") or 0).replace(",", ""))
        except ValueError:
            oos = 0.0
        if oos > picked.get(jp, -1.0):
            picked[jp] = oos
    ordered = sorted(picked, key=lambda j: (-picked[j], j))
    if limit:
        ordered = ordered[:limit]
    return [f"{prefix} {j}" for j in ordered]


def fetch_demand_map_rows(sheet_id: str = MAINTENANCE_SHEET_ID,
                          tab: str = DEMAND_MAP_TAB) -> list[dict]:
    """需要マップ タブを読む (通信あり)."""
    import sheet_writer  # noqa: PLC0415

    return parse_demand_map(sheet_writer.open_sheet_by_id(sheet_id).worksheet(tab).get_all_values())


def fetch_restock_rows(sheet_id: str = FUNNEL_SHEET_ID, tab: str = RESTOCK_TAB) -> list[dict]:
    """ファネル分析スプシの RESTOCK タブを読む (通信あり)."""
    import sheet_writer  # noqa: PLC0415

    ws = sheet_writer.open_sheet_by_id(sheet_id).worksheet(tab)
    values = ws.get_all_values()
    if len(values) < 2:
        return []
    header = values[0]
    return [dict(zip(header, r)) for r in values[1:] if any(r)]


CATALOG_DB = r"C:\dev\iMak_data\catalog\products.sqlite"


def load_name_map(db_path: str = CATALOG_DB,
                  categories=tuple(GAME_HINTS)) -> dict:
    """カタログから {category: {英名(大文字): 和名}} を読む (共有 DB の read only).

    英名は カタログが持っている値をそのまま使う (こちらで訳さない)。
    同じ英名に複数カードがぶら下がる場合は 先勝ち (和名は同じなので実害なし)。
    """
    import sqlite3  # noqa: PLC0415

    out: dict[str, dict[str, str]] = {c: {} for c in categories}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        q = ("select category, name_en, name, name_jp from products "
             f"where category in ({','.join('?' * len(categories))}) and name_jp != ''")
        for cat, name_en, name, name_jp in con.execute(q, tuple(categories)):
            en = (name_en or name or "").strip().upper()
            if len(en) >= _MIN_NAME_LEN:
                out[cat].setdefault(en, name_jp)
    finally:
        con.close()
    return out


def load_ja_names(db_path: str = CATALOG_DB, categories=tuple(GAME_HINTS)) -> dict:
    """カタログから {category: set(和名)} を読む (ゲーム判定用、 read only)."""
    import sqlite3  # noqa: PLC0415

    out: dict[str, set] = {c: set() for c in categories}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        q = ("select category, name_jp from products "
             f"where category in ({','.join('?' * len(categories))}) and name_jp != ''")
        for cat, name_jp in con.execute(q, tuple(categories)):
            out[cat].add(name_jp.strip())
    finally:
        con.close()
    return out


def build_demand_keywords(sheet_id: str = FUNNEL_SHEET_ID, prefix: str = PREFIX,
                          limit: int = 0, use_catalog: bool = True,
                          include_characters: bool = True, games=None) -> list[str]:
    """需要側の検索キーワードを作る (通信あり).

    ① ファネル分析 RESTOCK (在庫切れ ∩ 需要あり) のカード単位
    ② 需要マップ キャラ軸 (国内で在庫が切れていて需要があるキャラ)

    use_catalog=True なら 英名→和名 の変換にカタログを使う。
    カタログや需要マップが読めなければ、 取れた分だけで続行する (止めない)。
    """
    name_map: dict = {}
    if use_catalog:
        try:
            name_map = load_name_map()
        except Exception:  # noqa: BLE001 - カタログが無くても収集は続ける
            name_map = {}
    out = build_keywords_from_rows(fetch_restock_rows(sheet_id), prefix=prefix,
                                   limit=limit, name_map=name_map, games=games)
    if include_characters and name_map:
        try:
            chars = build_character_keywords(fetch_demand_map_rows(), name_map,
                                             prefix=prefix, games=games)
        except Exception:  # noqa: BLE001 - 需要マップが読めなくても収集は続ける
            chars = []
        out += [k for k in chars if k not in out]
    return out
