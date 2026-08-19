"""gacha_maker - ガチャポン出品のタイトルから メーカーを判定して 公式URL を返す.

2026-08-20 新設 (user 依頼: 「I列に公式のURLを入れれる?」)。

**楽天のタイトルにはメーカー名が決まった位置に入る**  (実測 93件中 81件):

    ... 全4種+ディスプレイ台紙セット <メーカー> ガチャポン ガチャガチャ コンプリート：<店名>

楽天の商品ページ側には メーカー欄が無く (実測 10/10件で `メーカー:` 表記なし)、
全文一致で探すと **同じ店の「おすすめ商品」欄の他商品**を拾ってしまう
(実測: 全16件が `Qualia` に一致したが、 本文ではなく lossleader ブロックだった)。
なので **タイトルのこのスロットだけ**を見る。 スロットが無い / 表に無いメーカーは
**空欄** (推測で URL を埋めない = fail-closed)。

メーカー一覧と公式URL は user 提供の15社 (2026-08-20) + 楽天の実データに多く出た4社
(ケイカンパニー / フクヤ / ケーツーステーション / ベネリック。 いずれも公式を実地確認)。
**ご当地本舗夢屋 (最多13件) は公式サイトが存在せず SNS のみ**なので空欄のまま。
"""
from __future__ import annotations

import re

# メーカー名 (正) -> 公式URL (公式サイト または カプセルトイ専用ページ)
MAKER_OFFICIAL: dict[str, str] = {
    "バンダイ": "https://gashapon.jp/",
    "タカラトミーアーツ": "https://www.takaratomy-arts.co.jp/items/gacha/",
    "ターリン・インターナショナル": "https://tarlin-capsule.jp/",
    "ケンエレファント": "https://kenelephant.co.jp/",
    "トイズスピリッツ": "http://www.toysp.co.jp/",
    "Jドリーム": "https://e-jdream.co.jp/",
    "トイズキャビン": "https://toyscabin.com/",
    "SO-TA": "https://www.so-ta.com/",
    "キタンクラブ": "https://kitan.jp/",
    "クオリア": "https://qualia-45.jp/",
    "スタンド・ストーンズ": "https://stasto.co.jp/",
    "アイピーフォー": "https://www.ip4.co.jp/",
    "ブシロードクリエイティブ": "https://bushiroad-creative.com/",
    "エール": "https://yell-world.jp/",
    "いきもん": "https://naturetechni.com/",
    # ↓ 楽天の実データに多く出るが user リスト外だったメーカー (2026-08-20 実地確認)
    "ケイカンパニー": "https://kcompany.co.jp/",
    "フクヤ": "https://www.fancy-fukuya.co.jp/topics/c/cat06/",
    "ケーツーステーション": "https://capsule.k2-st.co.jp/",
    "ベネリック": "https://benelic.com/capsuletoy/",
}

# 楽天タイトルに出てくる表記ゆれ -> 正のメーカー名
ALIASES: dict[str, str] = {
    "バンダイ": "バンダイ", "BANDAI": "バンダイ", "ガシャポン公式": "バンダイ",
    "タカラトミーアーツ": "タカラトミーアーツ", "T-ARTS": "タカラトミーアーツ",
    "タカラトミーA.R.T.S": "タカラトミーアーツ", "ユージン": "タカラトミーアーツ",
    "ターリン": "ターリン・インターナショナル", "ターリンインターナショナル": "ターリン・インターナショナル",
    "TARLIN": "ターリン・インターナショナル", "エポック社": "ターリン・インターナショナル",
    "ケンエレファント": "ケンエレファント", "ケンエレ": "ケンエレファント",
    "KENELEPHANT": "ケンエレファント",
    "トイズスピリッツ": "トイズスピリッツ", "TOYSSPIRITS": "トイズスピリッツ",
    "Jドリーム": "Jドリーム", "J.DREAM": "Jドリーム", "JDREAM": "Jドリーム",
    "ジェイドリーム": "Jドリーム",
    "トイズキャビン": "トイズキャビン", "TOYSCABIN": "トイズキャビン",
    "SO-TA": "SO-TA", "SOTA": "SO-TA", "ソータ": "SO-TA",
    "キタンクラブ": "キタンクラブ", "奇譚クラブ": "キタンクラブ", "KITANCLUB": "キタンクラブ",
    "クオリア": "クオリア", "QUALIA": "クオリア",
    "スタンドストーンズ": "スタンド・ストーンズ", "スタンド・ストーンズ": "スタンド・ストーンズ",
    "STASTO": "スタンド・ストーンズ", "スタスト": "スタンド・ストーンズ",
    "アイピーフォー": "アイピーフォー", "IP4": "アイピーフォー",
    "ブシロード": "ブシロードクリエイティブ", "ブシロードクリエイティブ": "ブシロードクリエイティブ",
    "エール": "エール",
    "いきもん": "いきもん", "ネイチャーテクニカラー": "いきもん", "NATURETECHNICOLOUR": "いきもん",
    "ケイカンパニー": "ケイカンパニー", "KCOMPANY": "ケイカンパニー",
    "フクヤ": "フクヤ", "FUKUYA": "フクヤ",
    "ケーツーステーション": "ケーツーステーション", "K2STATION": "ケーツーステーション",
    "ベネリック": "ベネリック", "BENELIC": "ベネリック",
}

# メーカー名が入るスロット: 「…セット <メーカー> ガチャポン…」
_SLOT_RE = re.compile(
    r"(?:セット|全\s*\d+\s*種[^\sガガ]*)\s+(.{1,24}?)\s+(?:ガチャポン|ガシャポン|ガチャガチャ)"
)


def _norm(s: str) -> str:
    """比較用に正規化 (空白・中黒・全角英数・大小の差を消す)."""
    s = (s or "").strip()
    s = s.translate({c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)})  # 全角英数 -> 半角
    return re.sub(r"[\s・､,、（）()【】\[\]]+", "", s).upper()


def extract_maker_text(title: str) -> str:
    """タイトルの メーカースロット をそのまま返す (無ければ空文字)."""
    m = _SLOT_RE.search(title or "")
    return m.group(1).strip() if m else ""


def resolve_maker(title: str) -> str:
    """タイトル -> 正のメーカー名. 判定できなければ空文字."""
    slot = _norm(extract_maker_text(title))
    if not slot:
        return ""
    for alias, maker in ALIASES.items():
        if _norm(alias) in slot:
            return maker
    return ""


def official_url(title: str) -> str:
    """タイトル -> メーカー公式URL. 判定できなければ空文字 (推測しない)."""
    return MAKER_OFFICIAL.get(resolve_maker(title), "")
