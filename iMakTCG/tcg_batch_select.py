# -*- coding: utf-8 -*-
"""PSA 新規バッチの franchise 均等サンプリング + 目視済スキップ (純粋ロジック・テスト可能)。

psa_to_csv.main() が 92件等から 10件/回 を選ぶ際、従来は全体 random.shuffle → 先頭10 だった。
在庫は Pokemon が大半なので Pokemon ばかり選ばれ、One Piece / Dragon Ball が滞留していた
(2026-06-23 ユーザー要望: Pokemon / One Piece / Dragon Ball を均等に出品したい)。

選定時点では PSA cert を scrape していないため franchise は確定しないが、スプシ C列(日本語
タイトル)に明示フランチャイズ語 / OP系カード番号が入っており best-effort で分類できる
(実データ98件で誤判定ゼロを確認)。分類 → round-robin で均等に取る。在庫が偏っていても
各 franchise を満遍なく拾い、足りない franchise の分は他で埋める。
"""
import json
import re

_PRIMARY = ("Pokemon", "OnePiece", "DragonBall")

# 目視済(NONE/NG=識別不能)cert を一定期間 再出題しないためのスキップ台帳。
# post_psa_review が NONE/NG 判定時に追記、psa_to_csv.main() が選定プールから除外する。
# (2026-06-23 ユーザー要望: 一度目視したカードがちょいちょい再出現する → 再表示防止)
REVIEW_SKIP_PATH = r"C:/dev/iMak_data/dedupe/psa_review_skip.json"
REVIEW_SKIP_COOLDOWN_DAYS = 14   # この期間は再出題しない。経過後は再浮上(catalog修正済なら今度は出品可)


def load_review_skips(path=REVIEW_SKIP_PATH):
    """目視済スキップ台帳 {cert: {at, choice}} を読む。無ければ空 dict。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def active_review_skips(skip_data, now, cooldown_days=REVIEW_SKIP_COOLDOWN_DAYS):
    """cooldown 期間内に NONE/NG 目視された cert の set を返す(= 今回スキップ対象)。

    at(ISO日時)が cooldown 内 → スキップ。経過/不明 → スキップしない(永久hide回避 = 再浮上させる)。
    now は datetime(test 用に注入可)。
    """
    import datetime as _dt
    out = set()
    for cert, info in (skip_data or {}).items():
        at = info.get("at") if isinstance(info, dict) else None
        if not at:
            continue
        try:
            t = _dt.datetime.fromisoformat(at)
        except Exception:
            continue
        if (now - t).days < cooldown_days:
            out.add(str(cert))
    return out


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
