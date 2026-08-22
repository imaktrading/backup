"""tcg_scope — PSA→CSV pipeline の out-of-scope 判定 (純関数, SSOT・2026-07-30).

build_row (iMakTCG/psa_to_csv.py) と _route_none_to_catalog
(iMakHQ/tools/post_psa_review.py) の両方から呼ばれる **共通ヘルパ**。両者が同じ真理表で
「未収録カテゴリの cert を skip」する = missing_models.csv に SCG 対象外が毎日流れ、
Catalog に無駄な調査依頼が量産される事故 (2026-07-29 発覚) の根治。

対象外一覧 (2026-07-29 Advisor 確定):
- Yu-Gi-Oh! ................ catalog 日本版未収録
- SDBH = Super Dragon Ball Heroes .... アーケード=SCG対象外
- DIVERS = Dragon Ball Super Divers ... アーケード派生=SCG対象外 (brand 文字列で識別、
                                       franchise は "Dragon Ball" になる)
- ITAJAGA / イタジャガ .... 食玩プロモ、公式 TCG カタログ対象外
- Pokemon FAMILY POKEMON CARD GAME ... catalog 構造的未収録
- 非日本語 Pokemon ......... catalog の pokemon_tcg は日本語のみ (2026-08-19 実測 en 0件)
- ONE PIECE ウエハース ..... 2019年の菓子付録カード。OPTCG(2022年開始)とは別物
- Pokemon Web 期 ........... 2001年。catalog 0件
- Pokemon Neo 期 ........... 2000年。catalog 0件 (2026-08-21 psa_preflight から移設)

pokemon_out_of_scope (psa_to_csv.py) との関係:
本モジュールは pokemon_out_of_scope に依存しない (循環 import 回避)。真理表 (FAMILY のみ
skip、BLACK DECK KIT は skip しない) は同一。BLACK DECK KIT は 2026-07-26 以降 catalog
有無で判定 (skip しない=recall 損防止)。

依存: 標準ライブラリのみ (test-friendly)。
"""
from __future__ import annotations

import re

# `WEB` / `NEO` 等は語として見る (`WEBBED` / `NEON` を巻き込まない)
_WEB_RE = re.compile(r"\bWEB\b")
_NEO_RE = re.compile(r"\bNEO\b")
# SDBH の PSA 表記ゆれ (`... HEROES UGM5` / `... BIG BANG MISSION 12` 等)
_SDBH_RE = re.compile(r"HEROES|MISSION|HRS\.?UGM|SDBH")


def _tokens(brand: str) -> set:
    """brand を語に割る。`-` は区切り扱い (psa_to_csv.is_out_of_scope_language と同じ流儀)。"""
    return set((brand or "").upper().replace("-", " ").split())


def is_out_of_scope(franchise: str, brand: str, catalog_resolves=None) -> tuple[bool, str]:
    """PSA brand ✕ franchise → out-of-scope 判定 (純関数).

    Args:
        franchise: detect_game_info(brand) の3タプル目 ("One Piece" / "Dragon Ball" /
                   "Pokemon" / "Yu-Gi-Oh!" / "Dragon Ball Heroes" / "Itajaga" 等)。
        brand:     PSA cache の Brand 文字列 (大文字小文字混在)。
        catalog_resolves: 省略可の 0 引数 callable。**言語ゲートにだけ**効く逃がし口で、
                   True を返したら「日本語版 catalog に解決できた」= skip しない。
                   PSA が日本版 25th Anniversary Golden Box を
                   `POKEMON ASIA 25TH ANNIVERSARY` と誤ラベルする例 (cert142931332 =
                   S8a-G-005) があり、brand 文字列だけで撥ねると recall 損になる。
                   未解決が確定している呼び出し (post_psa_review の NONE 経路) は渡さない。

    Returns:
        (True, 理由文字列)  = skip すべき (build_row: return None / route: 書かない)
        (False, "")         = scope 内 (通常処理)
    """
    b = (brand or "").upper()
    if franchise == "Yu-Gi-Oh!":
        return True, "遊戯王は現在対象外(catalog日本版未収録)"
    if franchise == "Dragon Ball Heroes":
        return True, "SDBH=アーケード=SCG対象外"
    # ★2026-08-21: `DRAGON BALL SON GOKU HEROES UGM5` のように **HEROES が
    #   DRAGON BALL と離れて出る** PSA 表記は detect_franchise_from_brand が
    #   "Dragon Ball" を返すため上の枝に入らない。psa_preflight が持っていた規則を
    #   ここへ移設 (真理表を1本にする一環)。誤爆しないことは実測済:
    #   psa cache 1,144件でこの規則が当たるのは SDBH の9表記だけで、
    #   Fusion World は一件も当たらない。
    if ("DRAGON BALL" in b or "DRAGONBALL" in b) and _SDBH_RE.search(b):
        return True, "SDBH=アーケード=SCG対象外"
    if franchise == "Itajaga":
        return True, "ITAJAGA=食玩プロモ=公式TCGカタログ対象外"
    # DIVERS は detect_game_info が franchise="Dragon Ball" を返す (SCG 本編と同扱い)
    # → brand 文字列で識別。dragonball_scg に catalog 実体無しで missing_models 永久汚染
    # (2026-07-29 Advisor 確定)。DIVERS の全 vol (4/7/40th 等) を一括除外。
    if "DIVERS" in b:
        return True, "DIVERS=SCG対象外(catalog未収録)"
    # Pokemon FAMILY POKEMON CARD GAME (はじめての〜) は catalog 0件 (2026-07-01 実機確認)
    if franchise == "Pokemon" and "FAMILY POKEMON CARD GAME" in b:
        return True, "Pokemon FAMILY POKEMON CARD GAME (catalog構造的未収録)"
    # ★2026-08-19 追加 (回答書 2026-08-19_act_code_proposals_tcg_response.md の 2)。
    #   3件とも「post_psa_review._route_none_to_catalog が言語/商材のゲートを持たない」
    #   という**同じ穴**なので、ここ1本にまとめる。いずれも catalog が構造的に
    #   持っていない = fail-closed。出品数は変わらず、止まるのは誤ったカタログ依頼だけ。
    #
    #   (a) 非日本語 Pokemon: `pokemon_tcg` は 2026-08-19 実測で ja 21,889 / en **0件**。
    #       英語版スラブに日本語版レコードを当てると誤出品 (cert150639361 CROWN ZENITH
    #       #GG38 は catalog 0件、日本語版は `215/172` で番号体系そのものが別)。
    #       ★one_piece_tcg / dragonball_scg / gundam_tcg は en を持つので **Pokemon だけ**に適用。
    if franchise == "Pokemon" and "JAPANESE" not in _tokens(b):
        if not (catalog_resolves and catalog_resolves()):
            return True, "日本語版でない Pokemon (catalog の pokemon_tcg は language=ja のみ、en は0件)"
    #   (b) ONE PIECE ウエハース: 2019年の菓子付録カード。OPTCG は 2022年開始なので別物で、
    #       catalog の one_piece_tcg に WAFER/ウエハースは 0件。番号も `13` の通し番号で
    #       set_code 体系に乗らない。**`WAFER` 単独には一般化しない** (実データ1件では根拠不足)。
    if franchise == "One Piece" and ("WAFER" in b or "ウエハース" in (brand or "")):
        return True, "ONE PIECE ウエハース=食玩付録=公式TCGカタログ対象外(catalog 0件)"
    #   (c) Pokemon Web 期 (2001年): catalog の pokemon_tcg に 0件。Neo 期と同じ形。
    if franchise == "Pokemon" and _WEB_RE.search(b):
        return True, "Pokemon Web期(2001年)=catalog 0件(Neo期と同じく対象外)"
    #   (d) Pokemon Neo 期 (2000年): psa_preflight.out_of_scope_by_brand が別に持っていた
    #       真理表をここへ移設 (2026-08-21)。理由文は preflight の文言をそのまま使う。
    #       実測: `set_name_official / set_name に neo` = 0件。catalog 側も
    #       prune_missing_models.py で「Neo era」を対象外と宣言済。
    #       ★これを足さずに preflight を委譲すると、`157799487 POKEMON JAPANESE NEO` が
    #         静かに対象内へ戻る (回答書 2026-08-19_psa_preflight_scope_ssot_gap_response.md)。
    if franchise == "Pokemon" and _NEO_RE.search(b):
        return True, "Pokemon Neo 期 (2000年) — catalog に neo 期の set が 0件 (catalog も対象外と宣言済)"
    return False, ""


def detect_franchise_from_brand(brand: str) -> str:
    """brand 文字列だけから franchise を軽量判定 (純関数, psa_to_csv 非依存).

    _route_none_to_catalog から is_out_of_scope を呼ぶ前段 (post_psa_review は
    detect_game_info を持たない = psa_to_csv 重い import を避けるため軽量版を用意)。
    真理表は detect_game_info の franchise 判定と一致させる。

    Args:
        brand: PSA cache Brand (例 'DRAGON BALL SUPER DIVERS 4', 'ONE PIECE JAPANESE OP08-...')

    Returns:
        franchise 名 ("One Piece" / "Dragon Ball" / "Pokemon" / "Yu-Gi-Oh!" /
        "Dragon Ball Heroes" / "Itajaga" / "Gundam" 等)。判定不能は brand をそのまま。
    """
    b = (brand or "").upper()
    # 順序が意味を持つ: specific → 総称 (detect_game_info と同じ)
    if "DRAGON BALL HEROES" in b:
        return "Dragon Ball Heroes"
    if "ITAJAGA" in b or "イタジャガ" in (brand or ""):
        return "Itajaga"
    if "YU-GI-OH" in b or "YUGIOH" in b:
        return "Yu-Gi-Oh!"
    # Gundam 判定: DUAL IMPACT / NEWTYPE RISING / STEEL REQUIEM 等の specific set →
    # 総称 GUNDAM。detect_game_info と真理表を合わせる。
    for token in ("DUAL IMPACT", "NEWTYPE RISING", "STEEL REQUIEM", "HEROIC BEGINNINGS",
                  "WINGS OF ADVANCE", "ZEON", "SEED STRIKE", "IRON BLOOM", "GUNDAM"):
        if token in b:
            return "Gundam"
    if "ONE PIECE" in b:
        return "One Piece"
    if "DRAGON BALL" in b:
        return "Dragon Ball"
    if "POKEMON" in b:
        return "Pokemon"
    return brand or ""
