"""color_vision - 商品画像 URL から色を判定 (Anthropic Claude Vision API).

Mercari 等の商品画像 1 枚を Claude Haiku 4.5 に送信し、確信できる単一色のみ
返す fail-closed 設計の色判定モジュール。

設計原則 (Takaaki さん指示 2026-05-04):
  - 確信できる単一色のみ返す。複数色 / 判別不能 / API エラー → 空文字
  - スプシ S 列 (色) は空欄でも OK (HQ 側で AI fallback)
  - 詳細色名のまま保存 (ネイビー / 水色 / ベージュ 等)
    eBay 16 色への正規化は HQ 側 listing スクリプトに委ねる
  - キャッシュ性: harvest が append-only なので新規アイテムだけ AI 課金
  - cap 無し (自然制限のみ): scrape 対象件数が hard limit

API key:
  - 共通領域 C:/dev/iMak_data/credentials/api_key.txt から読込
  - 環境変数 ANTHROPIC_API_KEY が優先 (テスト/CI 用)
  - どちらも無ければ空文字を返す (graceful degradation)

依存:
  - anthropic >= 0.40 (image source url 対応版)
"""
from __future__ import annotations

import os
from typing import Optional

API_KEY_PATH = r"C:\dev\iMak_data\credentials\api_key.txt"
MODEL_ID = "claude-haiku-4-5-20251001"
DEFAULT_TIMEOUT_SEC = 15.0
DEFAULT_MAX_TOKENS = 20

# 不確実判定キーワード (含まれていれば空文字を返す)
UNCERTAIN_KEYWORDS = (
    "不明",
    "わからない",
    "判別不能",
    "分からない",
    "判定不能",
    "?",
    "？",
    "複数",
    "混在",
    "multiple",
    "unknown",
)

# 文章検出キーワード (色名にこれが含まれていたら "AI が説明文を返した" 判定で空欄)
# 助詞 / 文末表現 (色名そのものには通常含まれない)
SENTENCE_MARKERS = (
    "です",
    "ます",
    "だ。",
    "は",
    "が",
    "を",
    "に",
    "の商品",
    " is ",
    " a ",
)

# 色名以外の異常出力ガード上限文字数 (シャンパンゴールド = 9 字相当まで許容)
MAX_COLOR_LEN = 12

# プロンプト (出力フォーマットを厳格化)
COLOR_PROMPT = """この商品画像から、商品本体の主要な色を判定してください。

ルール:
- 確信できる単一色のみ答える (例: 黒、白、赤、青、緑、黄、グレー、ベージュ、茶、ピンク、紫、オレンジ、ネイビー、水色、アイボリー 等)
- 複数色が混在し主要色を1つに決められない場合: 「不明」
- 商品が判別できない / 画像不鮮明: 「不明」
- 出力は色名 1 単語のみ。説明文・複数候補・記号・引用符は禁止
- 「○○色」のような接尾辞も禁止 (× 「黒色」 → ○ 「黒」)"""


# anthropic クライアントは lazy 初期化 (anthropic 未インストール環境でも import エラー回避)
_CLIENT_CACHE: list = []


def _load_api_key() -> str:
    """API key を共通領域 or 環境変数から読込. 無ければ空文字."""
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key
    if os.path.exists(API_KEY_PATH):
        try:
            with open(API_KEY_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""
    return ""


def _get_client():
    """anthropic.Anthropic クライアントを返す. 初期化失敗時は None.

    None 返却時は caller 側で空文字判定 (fail-closed) すること。
    """
    if _CLIENT_CACHE:
        return _CLIENT_CACHE[0]
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        _CLIENT_CACHE.append(None)
        return None
    api_key = _load_api_key()
    if not api_key:
        _CLIENT_CACHE.append(None)
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
    except Exception:
        _CLIENT_CACHE.append(None)
        return None
    _CLIENT_CACHE.append(client)
    return client


def reset_client_cache() -> None:
    """テスト用: client cache をクリア."""
    _CLIENT_CACHE.clear()


def parse_color_response(text: str) -> str:
    """API レスポンステキストから色名を抽出 + バリデーション.

    fail-closed 規則:
      - 空 → 空文字
      - 引用符 / 句読点除去
      - 不確実キーワード (不明 / 複数 / unknown 等) を含む → 空文字
      - 文章マーカー (です/ます/は/が 等) を含む → 空文字
      - 複数語 (空白区切り 2 語以上) → 空文字
      - 文字数 > MAX_COLOR_LEN → 空文字
      - 接尾辞「色」「カラー」は剥がさず透過 (「水色」「ローズピンク」等を壊さない)
    """
    if not text:
        return ""
    s = text.strip()
    # 引用符 / 句読点除去
    s = s.strip("「」『』\"'`，、,.。!！?？:：;；()（）[]【】")
    if not s:
        return ""

    # 不確実判定 (大文字小文字を無視して部分一致)
    s_lower = s.lower()
    if any(kw.lower() in s_lower for kw in UNCERTAIN_KEYWORDS):
        return ""

    # 文章検出 (助詞・文末表現が含まれれば AI が説明文を返したと判定)
    if any(marker in s for marker in SENTENCE_MARKERS):
        return ""

    # 複数語チェック (空白で 2 単語以上 → 不明扱い)
    parts = s.split()
    if len(parts) > 1:
        return ""

    # 文字数制限
    if len(s) > MAX_COLOR_LEN:
        return ""

    return s.strip()


def judge_color_from_image_url(
    image_url: str,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    client=None,
) -> str:
    """画像 URL から商品の主要色を判定 (fail-closed).

    Args:
        image_url: 公開アクセス可能な商品画像 URL
        timeout:   API タイムアウト秒
        client:    テスト用 mock client (None なら _get_client() を使用)

    Returns:
        確信できる単一色名 (詳細色名のまま、例: 「ネイビー」「ベージュ」) または "" (空文字)。
        以下のすべてのケースで空文字を返す (上位は無条件で空欄として扱える):
          - 画像 URL 空 / API key 無し / anthropic SDK 未インストール
          - API timeout / network error / rate limit / その他例外
          - レスポンスが「不明」「複数色」「判別不能」等
          - レスポンスが複数語 / 過剰文字数 (異常出力)
    """
    if not image_url:
        return ""

    cli = client if client is not None else _get_client()
    if cli is None:
        return ""

    try:
        msg = cli.messages.create(
            model=MODEL_ID,
            max_tokens=DEFAULT_MAX_TOKENS,
            timeout=timeout,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "url", "url": image_url},
                        },
                        {"type": "text", "text": COLOR_PROMPT},
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

    return parse_color_response(text)


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="商品画像 URL から色を判定 (Claude Haiku Vision)")
    ap.add_argument("image_url", help="商品画像 URL (公開アクセス可能)")
    args = ap.parse_args()

    result = judge_color_from_image_url(args.image_url)
    if result:
        print(f"color: {result}")
    else:
        print("color: (空 / 判別不能 / API 利用不可)")
