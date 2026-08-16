"""psa_restock - 売れた PSA10 カードの「別個体」をメルカリで探すための変換ロジック.

2026-08-17 新設 (user 依頼「売れた商品の補充」、 PSA10 から着手)。

PSA10 は 1 点もの。 売れた **同じ現物** はもう買えないので、 補充とは
「同じカードの **別個体** を仕入れて出し直す」 こと。 そのために要るのは:

  ① 売れたのが どのカードか      → eBay の Item Specifics が持っている (ebay_sold)
  ② メルカリで それをどう探すか  → build_keywords
  ③ 見つけた物が 同じカードか    → to_match_info + psa_cert.match_signals

★②の肝: eBay の Item Specifics は英語、 メルカリは日本語なので **カード名では引けない**
("Portgas D. Ace" では出てこない)。 **カード番号は言語に依存しない** (OP10-019 / 310/190)
ので、 番号を軸に検索する。 実測でもメルカリ出品タイトルには番号が入っている
(例「【PSA10】神避 パラレル OP10-019」)。

★③の肝: Vision がスラブラベルから読むのは **英字** なので、 eBay の Item Specifics
(こちらも英字) と直接突合できる。 日本語タイトルとの言語差の問題が出ない。
"""
from __future__ import annotations

import re

# Item Specifics の Game → メルカリ検索で使う日本語。 番号だけで足りない時の補助語。
# 載っていないゲームは日本語語を足さない (推測で間違った語を足すより、 番号だけで引く)。
GAME_JA = {
    "one piece card game": "ワンピース",
    "pokémon tcg": "ポケモンカード",
    "pokemon tcg": "ポケモンカード",
    "dragon ball super card game": "ドラゴンボール",
    "gundam card game": "ガンダム",
}

GRADE_PSA10 = "10"


def _first_num_group(card_number: str) -> str:
    """ポケモンの "310/190" のような表記から検索に使う側 (= 310) を取る.

    ワンピース系の "OP10-019" は "/" を含まないのでそのまま。
    """
    s = (card_number or "").strip()
    return s.split("/")[0].strip() if "/" in s else s


def is_psa10_card(specifics: dict) -> bool:
    """PSA10 の TCG カードか (= 再出品の対象か).

    fail-closed: Grade が読めない / 10 でない / カード番号が無い → False。
    (番号が無いと メルカリで引きようが無く、 同一カードの確認もできない)
    """
    if (specifics.get("Grade") or "").strip() != GRADE_PSA10:
        return False
    if not (specifics.get("Card Number") or "").strip():
        return False
    return bool((specifics.get("Game") or "").strip())


def to_card_identity(specifics: dict, title: str = "") -> dict:
    """Item Specifics を 扱いやすい形に整える (純関数)."""
    return {
        "card_name": (specifics.get("Card Name") or "").strip(),
        "card_number": (specifics.get("Card Number") or "").strip(),
        "set_name": (specifics.get("Set") or "").strip(),
        "game": (specifics.get("Game") or "").strip(),
        "year": (specifics.get("Year Manufactured") or "").strip(),
        "rarity": (specifics.get("Rarity") or "").strip(),
        "ebay_title": title or "",
    }


def build_keywords(identity: dict) -> list[str]:
    """メルカリ検索キーワードを組む (純関数).

    番号を軸にして 1〜2 本返す。 広い順ではなく **狭い順** (番号 + PSA10 が本命)。
    カード番号が無ければ空リスト (= 探しに行かない。 名前だけで引くと別カードを拾う)。
    """
    num = _first_num_group(identity.get("card_number") or "")
    if not num:
        return []
    kws = [f"PSA10 {num}"]
    ja = GAME_JA.get((identity.get("game") or "").strip().lower())
    if ja:
        kws.append(f"PSA10 {ja} {num}")
    return kws


def to_match_info(identity: dict) -> dict:
    """psa_cert.match_signals が食える形に変換 (純関数).

    match_signals は PSA 公式ページの項目名 (subject/brand/card_number/year) を前提に
    作ってあるので、 eBay 由来でも同じ鍵に詰め替えれば そのまま使い回せる。
    """
    return {
        "subject": identity.get("card_name") or "",
        "brand": " ".join(x for x in (identity.get("game"),
                                      identity.get("set_name")) if x),
        "card_number": _first_num_group(identity.get("card_number") or ""),
        "year": identity.get("year") or "",
    }


_CERT_RE = re.compile(r"^\d{8,9}$")


def is_same_individual(sold_cert: str, found_cert: str) -> bool:
    """売れた現物そのものか (= cert 一致).

    PSA10 は 1 点ものなので、 cert が一致する出品は **同じ現物**。 既に売れた個体が
    まだメルカリに出ているように見えるのは、 出品削除漏れ等の可能性が高く、 仕入れられない。
    → 再出品候補から外す。
    """
    if not _CERT_RE.match(sold_cert or "") or not _CERT_RE.match(found_cert or ""):
        return False
    return sold_cert == found_cert
