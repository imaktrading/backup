"""montbell_jacket - メルカリで拾う「モンベルのジャケット系」の判定 (純関数).

2026-09-05 新設 (user 依頼)。 user 確定:
  - **中古と新品の両方**を拾い、 状態は列で見分けられるようにする
    (既存の出品形式はタイトル末尾が `Pre-owned Japan` 固定 = 中古前提。 新品は出品側で選ぶ)
  - **型番 (7桁) の読み取りはしない**。 画像を見る作業は出品側の目視に任せる
    (補URL と同じ考え方。 機械が確定できない物をこちらで決めない)

対象は **アウター (ジャケット系)** だけ。 モンベルは寝袋・テント・靴・小物まで幅が広く、
それらは出品の形が別物なので採らない。
"""
from __future__ import annotations

import re

BRAND_RE = re.compile(r"モンベル|mont-?bell|モンベール", re.IGNORECASE)

# ジャケット系と分かる語 (どれかが要る)
JACKET_RE = re.compile(
    r"ジャケット|ジャケ|パーカ|アノラック|ウインドブレーカー|ウィンドブレーカー|"
    r"レインウェア|レインジャケット|マウンテンパーカ|シェル|ダウン|インナーダウン|"
    r"フリース|ブルゾン|コート|アウター|"
    r"ストームクルーザー|ウインドブラスト|ウィンドブラスト|サンダーパス|ライトシェル|"
    r"バーサライト|ノマド|クリマエア|クリマプラス|プラズマ|アルパインダウン|"
    r"シャミース|トレントフライヤー|レイントレッカー",
    re.IGNORECASE)

# 採らない物
NG_RE = re.compile(
    r"まとめ売り|まとめて|セット売り|\d+点セット|ジャンク|訳あり|穴|破れ|カビ|"
    r"キッズ|ジュニア|ベビー|子供|100cm|110cm|120cm|130cm|140cm|150cm|"
    r"寝袋|シュラフ|テント|ザック|リュック|バックパック|シューズ|靴|"
    r"パンツ|ズボン|タイツ|手袋|グローブ|帽子|キャップ|ハット|靴下|ソックス|"
    r"タオル|水筒|ボトル|ランタン|マット|カラビナ|ステッカー|"
    r"ビンテージ|ヴィンテージ|レプリカ|コピー|偽物",
    re.IGNORECASE)

NEW_CONDITION_RE = re.compile(r"新品[、,]?\s*未使用")


def is_montbell_jacket(title: str) -> bool:
    """モンベルのジャケット系か (タイトルだけで判定)."""
    t = title or ""
    if NG_RE.search(t):
        return False
    return bool(BRAND_RE.search(t) and JACKET_RE.search(t))


def condition_label(condition: str) -> str:
    """商品ページの「商品の状態」-> `新品` / `中古` (空なら空文字).

    出品側はタイトル末尾が `Pre-owned Japan` 固定なので、 **どちらかを列で見分けられる**
    ようにしておく (user 確定 2026-09-05)。
    """
    c = (condition or "").strip()
    if not c:
        return ""
    return "新品" if NEW_CONDITION_RE.search(c) else "中古"
