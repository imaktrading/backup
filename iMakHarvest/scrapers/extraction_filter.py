"""extraction_filter - 色/サイズ判定が不要な商品カテゴリを判定するフィルタ.

特定カテゴリ (TCG カード等) では色・サイズ抽出に意味がないので、AI コストと
遅延を削減するため抽出処理自体を skip する。

使い方:
    from scrapers.extraction_filter import should_skip_color_size
    if should_skip_color_size(title, description):
        size = ""
        color = ""
    else:
        size = _extract_size(driver)
        color = _judge_color(image_urls, title=title, description=description)

【追加方針】
Takaaki さんから「このカテゴリは色/サイズ要らない」と指示があったら、
SKIP_COLOR_SIZE_KEYWORDS に追加する。誤判定 (非該当商品の skip) を避けるため、
固有名詞 / 専門用語など他カテゴリで誤マッチしにくいキーワードを優先する。

【現在の対象】
- TCG カード全般 (グレーディング表記 PSA/BGS/CGC + 主要 TCG タイトル)
"""
from __future__ import annotations


# 色/サイズ判定が不要な商品の判定キーワード.
# 1 つでも title または description に含まれていれば skip 対象。
# 大文字小文字を区別せず判定する (lower() 後の文字列で照合)。
SKIP_COLOR_SIZE_KEYWORDS: tuple[str, ...] = (
    # ----- TCG グレーディング表記 (どの TCG でも該当) -----
    "psa10", "psa9", "psa8", "psa 10", "psa 9", "psa 8",
    "bgs 9.5", "bgs9.5", "bgs 10", "bgs10",
    "cgc 9.5", "cgc9.5", "cgc 10", "cgc10",
    # ----- 主要 TCG タイトル (固有名詞、誤判定低リスク) -----
    "ワンピースカード",
    "ポケモンカード",
    "ポケカ",
    "遊戯王",
    "デュエマ",
    "デュエル・マスターズ",
    "デュエルマスターズ",
    "ヴァイスシュヴァルツ",
    # ----- TCG レアリティ / カード種別表記 -----
    "リーダーパラレル",
    "lパラ",
    "公式イベント賞",
    # 注: "MTG" / "Magic: The Gathering" は MTG 商品が増えたら追加
    # 注: 今後 Takaaki さんから「○○も skip」指示があったらここに追加していく
)


def should_skip_color_size(title: str, description: str) -> bool:
    """この商品は color/size 抽出が不要 (TCG 等) かを判定.

    Args:
        title:       商品タイトル
        description: 商品説明文

    Returns:
        True  → color/size 抽出を skip (空欄でスプシに書込)
        False → 通常通り color (Vision AI) / size (構造化 field) を抽出
    """
    text = ((title or "") + " " + (description or "")).lower()
    if not text.strip():
        return False
    return any(kw.lower() in text for kw in SKIP_COLOR_SIZE_KEYWORDS)
