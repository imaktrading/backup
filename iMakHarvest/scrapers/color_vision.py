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

# プロンプト (出力フォーマットを厳格化、カタカナ強制)
# Phase 1d-2 改訂: HQ catalog の color_variants["jp"] がカタカナ統一されているため、
# 抽出くん出力もカタカナで揃える (漢字混在は HQ 側に正規化辞書を強要する負債になる)。
COLOR_PROMPT_NO_CONTEXT = """この商品画像から、商品本体の主要な色を判定してください。

【出力ルール (絶対遵守)】
- 色名は **必ずカタカナ表記** で答える (漢字での出力禁止)
  例: × 「赤」「緑」「青」「黄」「黒」「白」 → ○ 「レッド」「グリーン」「ブルー」「イエロー」「ブラック」「ホワイト」
- 複合色は丸めず詳細表記のまま答える
  例: ライトグリーン、ダークブルー、ペールピンク、ディープレッド 等は **そのまま**
- 確信できる単一色のみ答える
- 複数色が混在し主要色を 1 つに決められない / 商品判別不能: 「不明」
- 出力は色名 1 単語のみ。説明文・複数候補・記号・引用符・色サフィックス禁止
- 接尾辞「○○色」「○○カラー」も禁止 (× 「ブラック色」「レッドカラー」)"""

COLOR_PROMPT_WITH_CONTEXT_TEMPLATE = """この商品の主要な色を判定してください。
画像 + 出品者が記載した商品情報の両方を参考にします。

【商品情報】
タイトル: {title}
商品説明 (抜粋): {description}

【出力ルール (絶対遵守)】
- 色名は **必ずカタカナ表記** で答える (漢字での出力禁止)
  例: × 「赤」「緑」「青」「黄」 → ○ 「レッド」「グリーン」「ブルー」「イエロー」
- タイトル / 商品説明に色名 (カタカナ) が明記されていれば、その **原文表記をそのまま** 使う
  例: タイトルに「グリーン」 → 「グリーン」
  例: 説明文に「ライトグリーン」 → 「ライトグリーン」(「グリーン」に丸めない)
  例: 説明文に「ネイビー」 → 「ネイビー」(「ブルー」に丸めない)
- 商品情報になく画像のみで判断する場合もカタカナで答える
- 商品情報と画像で色が食い違う場合は **商品情報を優先**
- 複数色混在で主色不明 / 判別不能: 「不明」
- 出力は色名 1 単語のみ。説明文・複数候補・記号・引用符・色サフィックス禁止
- 接尾辞「○○色」「○○カラー」も禁止"""

# context あり版で含める description の最大文字数 (プロンプト肥大防止)
DESCRIPTION_CONTEXT_MAX_CHARS = 300

# ============================================================================
# カタカナ色名 whitelist (Phase 1d-2: HQ catalog/eBay enum マッピング前段)
# ============================================================================
# 役割: Harvest 側は出品者の原文表記 (カタカナ) を S 列に保存。
# catalog (color_variants["jp"]) との照合 + eBay 16 色 enum 正規化は HQ 側責務。
# Harvest は誤判定リスクを避けるため、確定的に抽出できるカタカナ色名のみ採用、
# 以外は AI Vision に任せる (AI もカタカナ強制プロンプト)。

# 基本 15 色 (eBay enum と同じ概念体系)
BASE_KATAKANA_COLORS = (
    "ブラック",
    "ホワイト",
    "レッド",
    "ブルー",
    "グリーン",
    "イエロー",
    "オレンジ",
    "ピンク",
    "パープル",
    "ブラウン",
    "グレー",
    "ベージュ",
    "シルバー",
    "ゴールド",
    "アイボリー",
)

# 追加 12 色 (メルカリ慣用、catalog の詳細色とのマッチング用)
EXTENDED_KATAKANA_COLORS = (
    "ネイビー",
    "カーキ",
    "マスタード",
    "ターコイズ",
    "ワインレッド",
    "ボルドー",
    "ガーネット",
    "チャコール",
    "モスグリーン",
    "オリーブ",
    "バーガンディ",
    "セージ",
)

# 複合色 prefix
COMPOUND_PREFIXES = ("ライト", "ダーク", "ペール", "ディープ")


def _build_color_whitelist() -> tuple[str, ...]:
    """全 katakana 色名 whitelist (longest-match-first sort).

    返り値:
      - 複合色 ("ライトグリーン", "ダークブルー" 等) を base 色より先に検出するため
        長い順に sort。
      - 重複除去 (set)。
    """
    base_all = BASE_KATAKANA_COLORS + EXTENDED_KATAKANA_COLORS
    compounds = tuple(
        f"{prefix}{base}"
        for prefix in COMPOUND_PREFIXES
        for base in base_all
    )
    all_colors = compounds + base_all
    # longest first (例: 「ライトグリーン」を「グリーン」より先に検出)
    return tuple(sorted(set(all_colors), key=len, reverse=True))


KATAKANA_COLOR_WHITELIST = _build_color_whitelist()


def extract_katakana_color_from_text(title: str, description: str) -> str:
    """title / description から最初に出現するカタカナ色名 (whitelist 一致) を抽出.

    検索優先順:
      1. title 内の whitelist 色名 (longest match first)
      2. description 内の whitelist 色名 (longest match first)
    どこにも該当なし → 空文字 (caller は AI fallback すべし)

    longest-match-first により「ライトグリーン」「ダークブルー」のような複合色を
    丸めずそのまま採用する (catalog の詳細色マッチング用)。
    """
    for source in (title or "", description or ""):
        if not source:
            continue
        for color in KATAKANA_COLOR_WHITELIST:
            if color in source:
                return color
    return ""


# 漢字 reject 用: Han ideograph (CJK Unified Ideographs) range
def _is_kanji_only(s: str) -> bool:
    """文字列が漢字のみ (末尾「色」suffix も含む) かを判定.

    True 例: "黒", "赤", "黒色", "深緑色"
    False 例: "レッド", "ライトグリーン", "ABC", "黒レッド" (混在)
    """
    if not s:
        return False
    core = s[:-1] if s.endswith("色") else s
    if not core:
        return False
    return all("一" <= c <= "鿿" for c in core)

# 後方互換: COLOR_PROMPT は context 無し版の alias として残す
COLOR_PROMPT = COLOR_PROMPT_NO_CONTEXT


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
      - **漢字のみの出力は reject** (Phase 1d-2: katakana 強制プロンプトに違反した
        AI 出力を排除。catalog 統一のため。例: "黒"/"赤色" → 空文字、"レッド" → OK)
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

    # 漢字 reject (Phase 1d-2: katakana 強制プロンプトに違反した AI 出力を排除)
    if _is_kanji_only(s):
        return ""

    return s.strip()


def _build_prompt(title: str, description: str) -> str:
    """title / description から AI 用 prompt を構築.

    - title と description の両方が空 → context 無し版の prompt
    - どちらか有り → context あり版 (出品者表記を優先するルール付き)
    description は MAX_CHARS で切り詰め (プロンプト肥大防止)。
    """
    title_clean = (title or "").strip()
    desc_clean = (description or "").strip()
    if not title_clean and not desc_clean:
        return COLOR_PROMPT_NO_CONTEXT
    desc_excerpt = desc_clean[:DESCRIPTION_CONTEXT_MAX_CHARS]
    if len(desc_clean) > DESCRIPTION_CONTEXT_MAX_CHARS:
        desc_excerpt += "..."
    return COLOR_PROMPT_WITH_CONTEXT_TEMPLATE.format(
        title=title_clean or "(なし)",
        description=desc_excerpt or "(なし)",
    )


def judge_color_from_image_url(
    image_url: str,
    title: str = "",
    description: str = "",
    timeout: float = DEFAULT_TIMEOUT_SEC,
    client=None,
) -> str:
    """画像 URL から商品の主要色を判定 (fail-closed).

    Args:
        image_url:   公開アクセス可能な商品画像 URL
        title:       商品タイトル (空なら使わない)
        description: 商品説明 (空なら使わない、長文は冒頭 N 字で切り詰め)
        timeout:     API タイムアウト秒
        client:      テスト用 mock client (None なら _get_client() を使用)

    title / description が与えられた場合、AI は画像 + テキスト両方を見て判定する。
    タイトル/説明文に色名 (「グリーン」「ネイビー」等) が明記されていれば、
    その **原文表記をそのまま** 採用 (HQ 側 listing スクリプトで eBay 16 色 enum に正規化)。

    Returns:
        確信できる単一色名 (詳細色名のまま、例: 「ネイビー」「ベージュ」「グリーン」) または ""。
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

    prompt = _build_prompt(title=title, description=description)

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
                        {"type": "text", "text": prompt},
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
