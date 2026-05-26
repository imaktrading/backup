"""vision_card_id - 商品画像 URL から TCG card_id を判定 (Anthropic Claude Vision API).

Phase 2 (mercari_seller 補強): メルカリ出品 title からは card_id が取れないケース
(= seller 独自表記、 別 TCG 混在 等) で、 画像 1 枚目 (= 基本カード表面) を Claude Haiku
4.5 に送信し、 ワンピース TCG `OP/ST/EB/P` 系の card_id を識別する。

設計原則:
  - 既存 `color_vision.py` の Vision API 呼出 pattern 踏襲 (= 流用率 90%+)
  - fail-closed: 確信できる card_id のみ返す、 判別不能 / 別 TCG / API エラー → 空文字
  - prompt で「OP/ST/EB/P 形式以外は NONE」 を明示 (= DON!! / GUNDAM / Disney Lorcana 等を弾く)
  - 出力は `extract_tcg_card_id` regex と同形式 (= `OP01-001` 大文字、 ハイフン正規化)
  - title × Vision 合議は呼出側 (= mercari_seller) で扱う、 本 module は単一画像 → card_id のみ

API key:
  - 既存 color_vision と同経路 (= `C:/dev/iMak_data/credentials/api_key.txt`、
    環境変数 `ANTHROPIC_API_KEY` 優先)

依存:
  - anthropic >= 0.40
"""
from __future__ import annotations

import os
import re
from typing import Optional

# 既存 color_vision の constants / helpers を再利用 (= 重複 init 避ける)
from scrapers.color_vision import (
    API_KEY_PATH,
    DEFAULT_TIMEOUT_SEC,
    MODEL_ID,
    _get_client,
    _load_api_key,
    reset_client_cache,
)

DEFAULT_MAX_TOKENS_CARD_ID = 16

# card_id 形式正規表現 (= extract_tcg_card_id と完全同期)
# OP/ST/EB の 2 桁-3 桁形式、 P-3 桁形式
CARD_ID_RE = re.compile(r"\b((?:OP|ST|EB)\d{2}-\d{3}|P-\d{3})\b", re.IGNORECASE)

# レスポンスから「NONE」 を意味する文字列のセット (大文字小文字無視)
NONE_MARKERS = (
    "NONE",
    "none",
    "なし",
    "不明",
    "判別不能",
    "判定不能",
    "わからない",
    "分からない",
)

# prompt (= 出力形式を厳格化、 OP/ST/EB/P 以外は NONE)
CARD_ID_PROMPT = """この画像はワンピース TCG (= トレーディングカードゲーム) の鑑定済みカードである可能性があります。
カード表面に印字されている card_id を読んでください。

【出力ルール (絶対遵守)】
- 形式は次のいずれか:
  - OP01-001 〜 OP99-999 (= ブースターパック)
  - ST01-001 〜 ST99-999 (= スターターデッキ)
  - EB01-001 〜 EB99-999 (= エクストラブースター)
  - P-001 〜 P-999 (= プロモーション)
- 上記形式の card_id が明確に読み取れる場合のみ、 その文字列 1 つだけ返してください
  (例: OP06-021、 ST16-001、 EB03-061、 P-018)
- ワンピース TCG **以外** のカード (= DON!! CARD / GUNDAM TCG / Disney Lorcana / Pokemon / 遊戯王 等) → NONE
- 読み取り不能 / 不鮮明 / カードでない / 判別不能 → NONE
- 出力は card_id か `NONE` の 1 単語のみ。 説明文・複数候補・記号・引用符・色サフィックス禁止"""


def parse_card_id_response(text: str) -> str:
    """Vision API レスポンステキストから card_id を抽出 + バリデーション.

    fail-closed 規則:
      - 空 → 空文字
      - 引用符 / 句読点除去
      - NONE / なし / 不明 / 判別不能 等のキーワード → 空文字
      - regex CARD_ID_RE 一致しなければ → 空文字
      - 一致した最初の card_id を大文字化して返す
    """
    if not text:
        return ""
    s = text.strip()
    # 引用符 / 句読点除去
    s = s.strip("「」『』\"'`，、,.。!！?？:：;；()（）[]【】 ")
    if not s:
        return ""

    # NONE markers (= 完全一致 or 部分一致で空文字)
    s_upper = s.upper()
    if any(m.upper() == s_upper for m in NONE_MARKERS):
        return ""
    if any(m in s for m in NONE_MARKERS if not m.isascii() or len(m) >= 4):
        # 「なし」「不明」 等 日本語 NONE marker は部分一致でも reject
        return ""

    # card_id regex 検索
    m = CARD_ID_RE.search(s)
    if not m:
        return ""
    return m.group(1).upper()


def judge_card_id_from_image_url(
    image_url: str,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    client=None,
) -> str:
    """画像 URL から card_id を判定 (fail-closed).

    Args:
        image_url:   公開アクセス可能な商品画像 URL (= 基本 listing 画像 1 枚目)
        timeout:     API タイムアウト秒
        client:      テスト用 mock client (None なら _get_client() を使用)

    Returns:
        ワンピース TCG card_id (例: `OP06-021`) または `""` (= NONE/エラー/判別不能)。
        以下のすべてのケースで空文字を返す:
          - 画像 URL 空 / API key 無し / anthropic SDK 未インストール
          - API timeout / network error / rate limit / その他例外
          - レスポンスが NONE / なし / 不明 / 判別不能 等
          - レスポンスが OP/ST/EB/P 形式 regex に一致しない
    """
    if not image_url:
        return ""

    cli = client if client is not None else _get_client()
    if cli is None:
        return ""

    try:
        msg = cli.messages.create(
            model=MODEL_ID,
            max_tokens=DEFAULT_MAX_TOKENS_CARD_ID,
            timeout=timeout,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "url", "url": image_url},
                        },
                        {"type": "text", "text": CARD_ID_PROMPT},
                    ],
                },
            ],
        )
    except Exception:
        return ""

    # レスポンス content から text を抽出
    try:
        text = ""
        for block in (msg.content or []):
            block_text = getattr(block, "text", None)
            if block_text:
                text = block_text
                break
        if not text:
            return ""
    except Exception:
        return ""

    return parse_card_id_response(text)


# ============================================================================
# 合議 logic (= title × Vision)
# ============================================================================
def reconcile_title_and_vision(title_card_id: str, vision_card_id: str) -> str:
    """title 抽出 vs Vision 抽出 の card_id を合議で確定 (= 依頼書 sec 3 B 表通り).

    | ケース                       | 採用 |
    |------------------------------|------|
    | title あり + Vision 一致      | title (= 確認済) |
    | title あり + Vision 不一致    | Vision (= カード本体印字優先) |
    | title なし + Vision あり      | Vision |
    | title あり + Vision なし      | title |
    | 両方なし                     | "" (= 単独 row、 aux skip) |
    """
    t = (title_card_id or "").strip().upper()
    v = (vision_card_id or "").strip().upper()
    if not t and not v:
        return ""
    if t and not v:
        return t
    if v and not t:
        return v
    # 両方ある → 一致なら t、 不一致なら v (= Vision 優先)
    if t == v:
        return t
    return v
