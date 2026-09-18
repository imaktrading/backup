"""psa_search_terms - PSA10 収集の検索キーワードを弾コードで刻む.

2026-08-17 実測 (debug/probe_psa10_volume.py / probe_psa10_keywords.py):
  - メルカリ検索は **1 キーワード 15 件前後で頭打ち**。 価格条件も送料条件も外したが
    増えなかったので、 フィルタではなく検索側の上限。
  - 一方 **語を増やせばほぼ線形に積み上がる**。 弾コード 10 語で 148 件 (重複はわずか 2 件)。
    10 語連続で回しても件数は落ちなかった (語間 8 秒)。
→ 件数を伸ばす唯一の手は「キーワードを増やす」。 弾コードは カード番号の頭なので
  出品タイトルに入りやすく、 語ごとの重なりも小さい。

ゲームを足す時はここに弾コードを足すだけでよい。
"""
from __future__ import annotations

PREFIX = "PSA10"

# ゲーム別の弾コード。 メルカリ出品タイトルに入る表記に合わせる。
# 収録は「現行で流通している弾」。 古い弾を足せばその分 語数 = 件数が増える。
SET_CODES: dict[str, list[str]] = {
    "onepiece": (
        [f"OP{i:02d}" for i in range(1, 15)]      # ブースター OP01-OP14
        + ["EB01", "EB02"]                        # エクストラブースター
        + ["PRB01"]                               # プレミアムブースター
        + [f"ST{i:02d}" for i in range(1, 31)]    # スタートデッキ
    ),
    "pokemon": [
        "SV1a", "SV2a", "SV3a", "SV4a", "SV5a", "SV6a", "SV7a", "SV8a",
        "SV1S", "SV1V", "SV2D", "SV2P", "SV3", "SV4K", "SV4M", "SV5K", "SV5M",
        "S12a", "S11a", "S10a", "S8b", "S4a",
    ],
    "dragonball": [f"FB{i:02d}" for i in range(1, 7)] + [f"FS{i:02d}" for i in range(1, 6)],
    "gundam": ["GD01", "GD02", "ST01", "ST02"],
}

# 弾コードだけだと拾いきれない分の受け皿 (キャラ名・一般語での取りこぼし回収)。
GENERIC: dict[str, list[str]] = {
    "onepiece": ["ワンピースカード", "ワンピース パラレル"],
    "pokemon": ["ポケモンカード", "ポケカ SAR"],
    "dragonball": ["ドラゴンボール フュージョンワールド"],
    "gundam": ["ガンダムカードゲーム"],
}

# 2026-09-17 user 提供: 海外eBay無在庫で取引ボリューム・PSA10相場が安定して高い
# キャラ (Aランク優先語)。 このプロジェクトの実測データではなく user の市場知見なので、
# ★型番までは信用せず キャラ名だけを検索語にする (型番はカタログ未照合)。
# build_demand_keywords (ファネル分析ベース) と別枠の静的リスト。 語は減らさず増やす方針
# (CLAUDE.md) のとおり、 既存の弾コード・需要ベース語と共存させ、 優先して先頭に置く。
POPULAR_CHARACTERS: dict[str, list[str]] = {
    "pokemon": [
        "リザードン", "ピカチュウ", "ブラッキー", "ナンジャモ", "リーリエ", "ミュウツー",
        "ゲンガー", "ミュウ", "ルギア", "マリィ", "ゲッコウガ", "ニンフィア",
        "レイ", "ルチア", "カビゴン", "レックウザ", "ミミッキュ", "キハダ",
        "サーナイト", "コイキング", "ポッチャマ",
    ],
    "onepiece": [
        "モンキー・D・ルフィ", "ロロノア・ゾロ", "ポートガス・D・エース", "シャンクス",
        "ボア・ハンコック", "トラファルガー・ロー", "ナミ", "ヤマト", "サボ", "サンジ",
        "ジュエリー・ボニー", "ウタ", "ニコ・ロビン", "キャベンディッシュ",
        "ゴール・D・ロジャー", "ペローナ", "シャーロット・カタクリ",
        "ドンキホーテ・ドフラミンゴ", "エドワード・ニューゲート", "レベッカ",
    ],
}

GAMES = tuple(SET_CODES)


def build_keywords(games=None, include_generic: bool = True,
                   include_popular: bool = True) -> list[str]:
    """収集用キーワード一覧を作る (純関数).

    Args:
        games: 対象ゲーム (既定 = 全部)。 未知の名前は無視する。
        include_generic: 弾コード以外の一般語も入れるか
        include_popular: POPULAR_CHARACTERS (Aランク優先語) を先頭に足すか
    Returns:
        重複を除いた検索キーワード。 ゲームごとに 優先キャラ → 弾コード → 一般語 の順。
        1 語あたり実測 15 件前後なので、 語数 × 15 が収集件数の目安。
    """
    names = list(games) if games else list(GAMES)
    out, seen = [], set()
    for g in names:
        codes = SET_CODES.get(g)
        if not codes:
            continue
        terms = []
        if include_popular:
            terms += [f"{PREFIX} {c}" for c in POPULAR_CHARACTERS.get(g, [])]
        terms += [f"{PREFIX} {c}" for c in codes]
        if include_generic:
            terms += [f"{PREFIX} {t}" for t in GENERIC.get(g, [])]
        for t in terms:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out
