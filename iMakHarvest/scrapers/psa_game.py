"""psa_game - 収集した PSA10 出品が どのゲームのカードかを判定する.

2026-08-18 新設 (user 指示「中間スプシへは カード毎にシートを分けて」→ ゲーム毎4タブ)。

判定材料は 2 つだけ。 どちらも **その出品自体から取れた事実**で、推測はしない:
  ① スラブのラベル (Vision が読んだ英字。 例 "2025 ONE PIECE OP13 JP ...")
  ② 出品タイトル (日本語。 例 "PSA10 ワンピースカード ルフィ")

どちらでも判らなければ "other"。 捨てずに `_other` タブへ入れる
(黙って落とすと、 どこにも現れないまま消える)。
"""
from __future__ import annotations

import re

OTHER = "other"

# 弾コードらしき語 (OP08 / ST30 / EB02 / SV4a / GD02 ...)
_SET_CODE_TOKEN_RE = re.compile(r"[A-Z]{2,4}\d{1,3}[A-Za-z]?")

# ゲーム名 → 判定に使う語 (ラベル・タイトル 両方に効かせる)。 上から順に見る。
GAME_MARKERS: dict[str, tuple[str, ...]] = {
    "onepiece": ("ONE PIECE", "ONEPIECE", "ワンピース", "ワンピカード"),
    "pokemon": ("POKEMON", "POKÉMON", "ポケモン", "ポケカ"),
    "dragonball": ("DRAGON BALL", "DRAGONBALL", "FUSION WORLD",
                   "ドラゴンボール", "フュージョンワールド"),
    "gundam": ("GUNDAM", "ガンダム"),
}

# 弾コードの頭文字からも判る (ラベルに ゲーム名が出ない事があるため)。
SET_CODE_PREFIXES: dict[str, tuple[str, ...]] = {
    "onepiece": ("OP", "EB", "PRB", "ST", "SB"),
    "pokemon": ("SV", "SM", "SWSH"),
    "dragonball": ("FB", "FS"),
    "gundam": ("GD",),
}


# カタログの category → ここでのゲーム名
CATEGORY_TO_GAME = {
    "one_piece_tcg": "onepiece",
    "pokemon_tcg": "pokemon",
    "dragonball_scg": "dragonball",
    "gundam_tcg": "gundam",
}
# 和名でゲームを当てる時の最短長。 2文字の名前 (サボ 等) は別語に埋もれるので採らない
_MIN_JA_NAME_LEN = 3


def build_ja_name_games(name_map_ja: dict) -> dict:
    """{category: {和名: ...}} → {和名: game}。 ゲームが割れる和名は捨てる (fail-closed).

    name_map_ja は 「カタログの和名を key に持つ dict」 なら中身は何でもよい
    (`{cat: {和名: 英名}}` でも `{cat: set(和名)}` でも可)。
    """
    seen: dict[str, set] = {}
    for cat, names in (name_map_ja or {}).items():
        game = CATEGORY_TO_GAME.get(cat)
        if not game:
            continue
        for jp in names:
            if len(jp) >= _MIN_JA_NAME_LEN:
                seen.setdefault(jp, set()).add(game)
    return {jp: next(iter(g)) for jp, g in seen.items() if len(g) == 1}


def detect_item_game(title: str = "", label: str = "", card_number: str = "",
                     ja_name_games: dict | None = None) -> str:
    """出品タイトル / スラブのラベル / カード番号 から ゲームを判定する.

    ja_name_games: {和名: game} を渡すと、 ゲーム名も弾コードも無いタイトル
    (例 「【PSA10】カリファ SR パラレル」) を **カタログの和名 lookup** で判定する。

    Returns: "onepiece" | "pokemon" | "dragonball" | "gundam" | "other"
    """
    text = f"{label or ''} {title or ''}".upper()
    for game, markers in GAME_MARKERS.items():
        if any(m in text for m in markers):
            return game
    # ゲーム名が出ていない時は 弾コードで判る場合がある (例 "OP13-004")
    codes = [(card_number or "").upper().strip()] if card_number else []
    # ラベル/タイトル中の弾コードらしき語を **全部** 見る。 最初の 1 つで打ち切ると
    # "PSA10" を掴んで判定を諦める (2026-08-18 実測で 21 件が other に落ちた)。
    # 括弧や記号にくっついていても拾えるよう、 分割ではなく パターンで抜く
    # ("ナミ SR-P [OP08-106]" の "[OP08" を取り逃がしていた)。
    codes += _SET_CODE_TOKEN_RE.findall(text)
    for code in codes:
        for game, prefixes in SET_CODE_PREFIXES.items():
            for p in prefixes:
                if code.startswith(p) and code[len(p):len(p) + 1].isdigit():
                    return game
    # 最後に カタログの和名で当てる (キャラ名しか書かれていない出品が実際に多い)。
    # **最長一致を採る**。 短い名前は他の名前の一部に埋もれる
    # (「ハンコック」の中の「コック」が別ゲームのカード名に当たる)。
    if ja_name_games:
        hits = [(jp, g) for jp, g in ja_name_games.items() if jp in (title or "")]
        if hits:
            longest = max(len(jp) for jp, _ in hits)
            games = {g for jp, g in hits if len(jp) == longest}
            if len(games) == 1:
                return next(iter(games))
    return OTHER


def tab_label(base_label: str, game: str) -> str:
    """中間スプシの tab suffix を作る (= mercari_<base>_<game>)."""
    return f"{base_label}_{game or OTHER}"
