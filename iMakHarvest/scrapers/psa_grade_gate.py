"""psa_grade_gate - 「PSA10 のスラブか」を出品タイトル / ラベルで判定する.

2026-08-18 新設 (user 指摘「PSA9 や BGS9.5、ARS、CGC が混じっているね」)。

事故の形: cert が読めなかった出品を **グレードを見ずに** I列空欄で入れていたため、
PSA9・BGS・ARS・CGC・生カード (鑑定なし) まで中間スプシに並んでいた。
メルカリ検索は説明文にも当たるので、 タイトルに PSA10 が無い出品も普通に返ってくる。

方針は 出品の正確性原則どおり **fail-closed**:
  - 別の鑑定会社 (BGS / ARS / CGC / SGC / AGS) が書かれていたら通さない
  - ★"CCG" は鑑定会社ではない (Collectible Card Game の略)。 ガンダムの正規タイトル
    "Gundam CCG Edition Beta" に当たるので **除外語に入れてはいけない** (2026-08-19 是正)
  - "CGC10 PSA10相当" のように **PSA10 と併記した CGC 出品が多い**。 PSA10 表記があっても
    CGC が書かれていたら通さない (PSA のスラブではない)
  - PSA でもグレードが 10 でなければ通さない
  - **PSA10 と書かれている確証が無ければ通さない** (書いていない = 生カードの可能性)
"""
from __future__ import annotations

import re

# 別の鑑定会社。 これらが書かれていたら PSA10 ではない
# ★境界を \b で書くと "CGC10" "ARS10" のように数字が続いた時に立たず素通りする
# (2026-08-19 実測: CGC10 の出品 8件が中間スプシに入っていた)。
# 前後に英字が無いことだけ見る = 数字が続いても当たる。
# ★"CCG" は鑑定会社ではない (Collectible Card Game)。 ガンダムの正規タイトル
# "Gundam CCG Edition Beta" に当たるので入れない。
OTHER_GRADER_RE = re.compile(
    r"(?<![A-Za-z])(?:BGS|ARS|CGC|SGC|AGS|BECKETT)(?![A-Za-z])|ベッケット",
    re.IGNORECASE)

# PSA だが 10 でない (PSA9 / PSA 9.5 / PSA8 ...)
PSA_NOT_10_RE = re.compile(r"PSA\s*(?:鑑定)?\s*([0-9](?:\.5)?)(?![0-9])", re.IGNORECASE)

# PSA10 の表記ゆれ (PSA10 / PSA 10 / PSA-10 / 【PSA10】 / psa10)
PSA10_RE = re.compile(r"PSA[\s　\-]*10(?![0-9])", re.IGNORECASE)

# Vision が読んだラベルの grade 表記 (GEM MT 10 等)
LABEL_GRADE10_RE = re.compile(r"\bGEM\s*M[TN]\s*10\b|\bGEM\s*MINT\s*10\b|(?<![0-9])10(?![0-9])",
                              re.IGNORECASE)


def looks_like_psa10(title: str = "", label: str = "", grade: str = "") -> bool:
    """PSA10 のスラブと **確証が持てる** 時だけ True.

    grade は Vision がラベルから読んだ値 (例 "GEM MT 10")。 読めていればそれを優先する。
    """
    text = f"{title or ''} {label or ''}"
    if OTHER_GRADER_RE.search(text):
        return False
    for g in PSA_NOT_10_RE.findall(text):
        if g != "10":
            return False
    if grade:
        return bool(LABEL_GRADE10_RE.search(grade))
    return bool(PSA10_RE.search(text))


def contradicts_psa10(title: str = "", label: str = "") -> bool:
    """**PSA10 でないと明記されている** 時だけ True (2026-08-19 追加).

    `looks_like_psa10` は「確証が無ければ False」なので、 既に cert が読めている行
    (= Vision がスラブのラベルを読めた行) に使うと、 タイトルに PSA10 と書いていない
    だけの正当な行まで落ちる。 掃除にはこちらを使う。
    """
    text = f"{title or ''} {label or ''}"
    if OTHER_GRADER_RE.search(text):
        return True
    return any(g != "10" for g in PSA_NOT_10_RE.findall(text))
