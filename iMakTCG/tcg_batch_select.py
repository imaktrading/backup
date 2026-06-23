# -*- coding: utf-8 -*-
"""PSA 新規バッチの franchise 均等サンプリング (純粋ロジック・テスト可能)。

psa_to_csv.main() が 92件等から 10件/回 を選ぶ際、従来は全体 random.shuffle → 先頭10 だった。
在庫は Pokemon が大半なので Pokemon ばかり選ばれ、One Piece / Dragon Ball が滞留していた
(2026-06-23 ユーザー要望: Pokemon / One Piece / Dragon Ball を均等に出品したい)。

選定時点では PSA cert を scrape していないため franchise は確定しないが、スプシ C列(日本語
タイトル)に明示フランチャイズ語 / OP系カード番号が入っており best-effort で分類できる
(実データ98件で誤判定ゼロを確認)。分類 → round-robin で均等に取る。在庫が偏っていても
各 franchise を満遍なく拾い、足りない franchise の分は他で埋める。
"""
import re

_PRIMARY = ("Pokemon", "OnePiece", "DragonBall")


def classify_franchise(title):
    """C列(日本語)タイトル → franchise ('Pokemon'|'OnePiece'|'DragonBall')。best-effort。

    明示フランチャイズ語を最優先、次に OP/DB 系カード番号、既定は Pokemon(在庫の大半)。
    Pokemon を OnePiece/DragonBall に誤分類しない方を優先(誤って少数派を水増ししないため)。
    """
    t = title or ""
    T = t.upper()
    # 明示フランチャイズ語 (最優先)
    if "ドラゴンボール" in t:
        return "DragonBall"
    if "ワンピース" in t:
        return "OnePiece"
    if "ポケモン" in t:
        return "Pokemon"
    # カード番号 (前に英字が無い境界 = "POP17" の "OP" 誤検出を防ぐ)
    if re.search(r"(?<![A-Z])(OP|ST|EB|PRB)\d{2}-\d{2,3}", T):
        return "OnePiece"
    if re.search(r"(?<![A-Z])(E\d{2}|FB\d{2}|FS\d{2})-?\d", T):
        return "DragonBall"
    if "エナジーマーカー" in t:        # Dragon Ball Energy Marker (E01系)
        return "DragonBall"
    return "Pokemon"                   # 既定 = 在庫の大半


def balanced_sample(certs, title_map, limit, shuffle=None):
    """franchise 均等に round-robin で limit 件選ぶ。

    各 franchise 内はシャッフル(上位行偏り防止)。巡回は Pokemon→OnePiece→DragonBall→その他。
    ある franchise が尽きたら飛ばして他で埋めるので、在庫が偏っていても「可能な限り均等」になる。
    shuffle: list を in-place シャッフルする関数 (既定 random.shuffle、test 用に注入可)。
    戻り: 選ばれた cert の list (順序も round-robin)。
    """
    if shuffle is None:
        import random
        shuffle = random.shuffle
    groups = {}
    for c in certs:
        groups.setdefault(classify_franchise((title_map or {}).get(c, "")), []).append(c)
    for g in groups.values():
        shuffle(g)
    order = [g for g in _PRIMARY if g in groups] + [g for g in groups if g not in _PRIMARY]
    picked, i = [], 0
    while len(picked) < limit and any(groups[g] for g in order):
        g = order[i % len(order)]
        if groups[g]:
            picked.append(groups[g].pop(0))
        i += 1
    return picked[:limit]
