"""uniqlo_tee - メルカリで拾う「ユニクロ UT / GU のコラボT」の判定 (純関数).

2026-08-22 新設 (user 依頼「メルカリでユニクロのTシャツを抽出したい」)。
user 確定: **対象 = UT + GU のコラボT / 状態 = 新品・未使用のみ**。

なぜ絞るか:
  - 無地・エアリズム・ポケットTは海外で価格が付かない (指名買いされない)
  - 出品タイトルの末尾が `NWT` 固定 (skill `apparel-tee-listing`) なので、
    中古が混ざると既存の出品形式がそのまま使えない
"""
from __future__ import annotations

import re

# ブランド語 (どれかが要る)
BRAND_RE = re.compile(r"ユニクロ|UNIQLO|ユニ黒|\bUT\b|ジーユー|\bGU\b", re.IGNORECASE)
# Tシャツと分かる語 (どれかが要る)
TEE_RE = re.compile(r"Tシャツ|ティーシャツ|T-?shirt|グラフィックT|半袖|カットソー", re.IGNORECASE)

# コラボ/グラフィックの目印。 **これが無いものは採らない** (無地は価格が付かない)
COLLAB_RE = re.compile(
    r"UT\b|コラボ|グラフィック|アニメ|ワンピース|ONE PIECE|鬼滅|呪術|ドラゴンボール|"
    r"NARUTO|ナルト|ポケモン|POKEMON|ジブリ|スヌーピー|ディズニー|マリオ|ゼルダ|"
    r"KAWS|村上隆|ミッキー|セーラームーン|エヴァ|ガンダム|スパイファミリー|SPY|"
    r"チェンソーマン|進撃の巨人|ハイキュー|銀魂|コナン|ジョジョ|キン肉マン|"
    r"アンディ・ウォーホル|バスキア|MoMA|ピクサー|マーベル|MARVEL|スターウォーズ",
    re.IGNORECASE)

# 出品できない/採らない物
NG_RE = re.compile(
    r"まとめ売り|まとめて|セット売り|\d+枚セット|ジャンク|訳あり|汚れ|シミ|穴|破れ|"
    r"リメイク|自作|プリント加工|オーダー|受注|キッズ|ベビー|100cm|110cm|120cm|130cm",
    re.IGNORECASE)

# 「新品、未使用」だけ通す (メルカリの表記ゆれを吸収)
NEW_CONDITION_RE = re.compile(r"新品[、,]?\s*未使用")


# 服の「ワンピース」= 婦人服。 アニメの ONE PIECE と字面が同じなので分けて判定する
_DRESS_RE = re.compile(r"ワンピース")
_ONEPIECE_ANIME_RE = re.compile(
    r"ONE\s?PIECE|ルフィ|麦わら|ゾロ|ナミ|サンジ|チョッパー|エース|ロビン|ウソップ|尾田",
    re.IGNORECASE)


def is_dress(title: str) -> bool:
    """服のワンピース (婦人服) か。 アニメの ONE PIECE と取り違えないため.

    判定: 「ワンピース」があって、 ①ONE PIECE / キャラ名が無く、
    かつ ②「Tシャツ」とも書いていない → 服のワンピース。
    (`ユニクロ UT ワンピース Tシャツ` は アニメ。 `クルーネックTワンピース 半袖` は服)
    """
    t = title or ""
    if not _DRESS_RE.search(t):
        return False
    if _ONEPIECE_ANIME_RE.search(t):
        return False
    return "Tシャツ" not in t


def is_uniqlo_tee(title: str) -> bool:
    """ユニクロ/GU の T シャツか (タイトルだけで判定)."""
    t = title or ""
    if NG_RE.search(t) or is_dress(t):
        return False
    return bool(BRAND_RE.search(t) and TEE_RE.search(t))


def is_collab(title: str) -> bool:
    """コラボ/グラフィック物か。 無地は採らない."""
    return bool(COLLAB_RE.search(title or ""))


def is_target(title: str) -> bool:
    """収集対象か (ユニクロ/GU の T かつ コラボ物)."""
    return is_uniqlo_tee(title) and is_collab(title)


def is_new_condition(condition: str) -> bool:
    """商品ページの「商品の状態」が **新品、未使用** か."""
    return bool(NEW_CONDITION_RE.search(condition or ""))
