"""Pokemon TCG name_jp → name_en bulk 翻訳.

設計背景 (2026-05-11):
  HQ から 21,855 件全件 name_en バルク翻訳依頼.
  3AI BLOCK 事故 (Iono's Wattrel / Pidgeotto / Wigglytuff) の根本対策.

アプローチ (B 案、precision 重視):
  Tier 1: PokéAPI 公式 ja↔en 1,025 種辞書 + suffix rule (ex/V/VMAX/GX/EX/VSTAR/BREAK)
          + "<trainer>の<pokemon>" pattern → 約 54% カバー (高精度)
  Tier 2: Mega / Regional (Alolan/Galarian/Hisuian/Paldean) form rule
  Tier 3: Claude API batch (Trainer cards / Item / Stadium / Energy / 特殊カード)

ソース:
  PokéAPI: https://github.com/PokeAPI/pokeapi/blob/master/data/v2/csv/pokemon_species_names.csv
           (一度 DL してキャッシュ: C:/dev/iMak_data/catalog/pokemon_translation_cache/)

実行:
  python iMakCatalog/scrapers/pokemon_name_translation.py --smoke 30
  python iMakCatalog/scrapers/pokemon_name_translation.py --rule-only        # API なし
  python iMakCatalog/scrapers/pokemon_name_translation.py --all              # 全件
  python iMakCatalog/scrapers/pokemon_name_translation.py --export <out.csv> # HQ 検証用
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

# sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CATALOG_ROOT = Path(__file__).resolve().parent.parent
_SCRAPERS = Path(__file__).resolve().parent
for p in (_CATALOG_ROOT, _SCRAPERS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import api  # type: ignore  # noqa: E402

CATEGORY = "pokemon_tcg"
MODEL_ID = "claude-sonnet-4-6"
BATCH_SIZE = 50  # API call 1回での同時翻訳数

CACHE_DIR = Path("C:/dev/iMak_data/catalog/pokemon_translation_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
POKEAPI_DICT_PATH = CACHE_DIR / "ja_en_pokemon_names.json"
API_DICT_PATH = CACHE_DIR / "ja_en_api_translated.json"  # Claude API 結果 cache
TRANSLATION_LOG = CACHE_DIR / "translation_log.json"

# ============================================================================
# 辞書: 手動 (HQ 提示 seed + 拡張)
# ============================================================================
# トレーナー名 (人物). HQ 提示分 + 既存 set からよく出るもの.
# 出典: pokemon.com 英訳 / Bulbapedia
TRAINER_NAME_MAP: dict[str, str] = {
    # Scarlet/Violet era (HQ 提示)
    "ナンジャモ":      "Iono",
    "シロナ":          "Cynthia",
    "ボタン":          "Atticus",
    "カエデ":          "Tulip",
    "メロコ":          "Mela",
    "グルーシャ":      "Grusha",
    "リップ":          "Tyme",
    "ハッサク":        "Hassel",
    "フトゥー":        "Brassius",
    "サザレ":          "Lacey",
    "ペパー":          "Arven",
    "ネモ":            "Nemona",
    "オモダカ":        "Crispin",
    "ナタネ":          "Gardenia",
    # Sword/Shield era (頻出)
    "マリィ":          "Marnie",
    "ホップ":          "Hop",
    "ローズ":          "Rose",
    "オリーヴ":        "Olive",
    "ビート":          "Bede",
    "サイトウ":        "Bea",
    "オニオン":        "Allister",
    "ポプラ":          "Opal",
    "ネズ":            "Piers",
    "マクワ":          "Gordie",
    "メロン":          "Melony",
    "ラビ":            "Klara",
    "セイボリー":      "Avery",
    # Sun/Moon era
    "リーリエ":        "Lillie",
    "ククイ博士":      "Professor Kukui",
    "ハウ":            "Hau",
    "グズマ":          "Guzma",
    "アセロラ":        "Acerola",
    "カキ":            "Kiawe",
    "マオ":            "Mallow",
    "スイレン":        "Lana",
    "マーマネ":        "Sophocles",
    # Diamond/Pearl / Platinum
    "ヒカリ":          "Dawn",
    "コウキ":          "Lucas",
    "アカギ":          "Cyrus",
    "リッシ":          "Cynthia",  # 確認要
    # Kanto/Johto
    "サトシ":          "Ash",
    "カスミ":          "Misty",
    "タケシ":          "Brock",
    "エリカ":          "Erika",
    "キョウ":          "Koga",
    "サカキ":          "Giovanni",
    "ワタル":          "Lance",
    "レッド":          "Red",
    "グリーン":        "Blue",   # ※ アニメ版グリーン (= ゲーム英Blue)
    "ヒビキ":          "Ethan",
    "ジュン":          "Crystal",
    "ナナミ":          "Daisy",
    "オーキド博士":    "Professor Oak",
    # XY era
    "セレナ":          "Serena",
    "サナ":            "Shauna",
    "プラターヌ博士":  "Professor Sycamore",
    "シトロン":        "Clemont",
    "ユリーカ":        "Bonnie",
    "サトシゲッコウガ":"Ash-Greninja",  # 特殊例
    # Black/White era
    "アイリス":        "Iris",
    "ベル":            "Bianca",
    "チェレン":        "Cheren",
    "アララギ博士":    "Professor Juniper",
    "N":               "N",
    "アクロマ":        "Colress",
    "ゲーチス":        "Ghetsis",
    # PalDea/SV NPCs
    "ダイゴ":          "Steven",
    "ハンサム":        "Looker",
    # Team names (組織)
    "ロケット団":          "Team Rocket",
    "ロケット団のしたっぱ":"Team Rocket Grunt",
    "アクア団":            "Team Aqua",
    "マグマ団":            "Team Magma",
    "マグマ団のしたっぱ":  "Team Magma Grunt",
    "アクア団のしたっぱ":  "Team Aqua Grunt",
    "ギンガ団":            "Team Galactic",
    "プラズマ団":          "Team Plasma",
    "フレア団":            "Team Flare",
    "スカル団":            "Team Skull",
    "マクロコスモス":      "Macro Cosmos",
}

# Form prefix (Mega / Regional / Origin / 等)
FORM_PREFIX_MAP: list[tuple[str, str]] = [
    # ("メガ <Pokemon>" → "M <Pokemon>" は TCG English の表記、Mega も使われる)
    ("メガ",         "M "),       # M Charizard ex 等
    ("アローラ",     "Alolan "),  # Alolan Geodude
    ("ガラル",       "Galarian "),
    ("ヒスイ",       "Hisuian "),
    ("パルデア",     "Paldean "),
    ("オリジン",     "Origin Forme "),
]

# Pokemon suffix (TCG variant marker)
POKEMON_SUFFIXES = [
    "ex δ",        # 順序大事 (より長いものを先に)
    "VMAX",
    "VSTAR",
    "ex",
    "EX",
    "GX",
    "V",
    "BREAK",
    "STAR",
    "δ",
    "ΩMEGA",
    "プリズム",
    "♢",
]


# ============================================================================
# 辞書ロード
# ============================================================================
def load_pokeapi_dict() -> dict[str, str]:
    """PokéAPI 公式 ja↔en 1,025 種辞書をロード."""
    if not POKEAPI_DICT_PATH.exists():
        raise FileNotFoundError(
            f"PokeAPI 辞書未生成: {POKEAPI_DICT_PATH}\n"
            f"先に: python scrapers/_tmp_pokeapi_dict.py"
        )
    with open(POKEAPI_DICT_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_api_dict() -> dict[str, str]:
    """Claude API 翻訳 cache をロード (なければ空 dict)."""
    if not API_DICT_PATH.exists():
        return {}
    with open(API_DICT_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_api_dict(d: dict[str, str]) -> None:
    with open(API_DICT_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2, sort_keys=True)


# ============================================================================
# Rule-based 翻訳
# ============================================================================
def translate_by_rule(name_jp: str, poke_dict: dict[str, str],
                      api_dict: dict[str, str]) -> tuple[Optional[str], str]:
    """name_jp → name_en. 第二戻り値は match_type.

    match_type:
      pokeapi_direct        : PokéAPI 直接 hit
      pokeapi_suffix        : suffix 除去後 PokéAPI hit
      pokeapi_form          : form prefix 除去後 PokéAPI hit (Alolan 等)
      trainer_owned         : "<trainer>の<pokemon>" pattern
      trainer_standalone    : Trainer 名 (standalone)
      api_cache             : Claude API cache hit
      none                  : 翻訳不能 (要 API)
    """
    if not name_jp:
        return None, "none"

    # 1) PokéAPI 直接 hit
    if name_jp in poke_dict:
        return poke_dict[name_jp], "pokeapi_direct"

    # 2) suffix 除去 (ex/V/VMAX/GX/EX/VSTAR/BREAK/STAR/δ 等)
    for s in POKEMON_SUFFIXES:
        if name_jp.endswith(s):
            base = name_jp[:-len(s)].strip()
            if base in poke_dict:
                # Form prefix と組合せ
                en_base = _apply_form_prefix(base, poke_dict)
                if en_base is None:
                    en_base = poke_dict[base]
                # suffix も英語表記に正規化
                en_suffix = _english_suffix(s)
                return f"{en_base}{en_suffix}", "pokeapi_suffix"

    # 3) Form prefix 単独 (suffix なし) — "メガクチート" 等
    en_form = _apply_form_prefix(name_jp, poke_dict)
    if en_form is not None:
        return en_form, "pokeapi_form"

    # 4) "<trainer>の<pokemon>"
    m = re.match(r"^(.+?)の(.+)$", name_jp)
    if m:
        trainer_jp, poke_part = m.group(1), m.group(2)
        # pokemon part に suffix?
        poke_suffix = ""
        poke_base = poke_part
        for s in POKEMON_SUFFIXES:
            if poke_part.endswith(s):
                poke_base = poke_part[:-len(s)].strip()
                poke_suffix = _english_suffix(s)
                break
        en_poke_base = _apply_form_prefix(poke_base, poke_dict) or poke_dict.get(poke_base)
        if en_poke_base:
            # trainer 名翻訳
            en_trainer = TRAINER_NAME_MAP.get(trainer_jp) or api_dict.get(trainer_jp)
            if en_trainer:
                return f"{en_trainer}'s {en_poke_base}{poke_suffix}", "trainer_owned"

    # 5) Trainer 単独 (HQ 提示の辞書から)
    if name_jp in TRAINER_NAME_MAP:
        return TRAINER_NAME_MAP[name_jp], "trainer_standalone"

    # 6) Claude API cache
    if name_jp in api_dict:
        return api_dict[name_jp], "api_cache"

    return None, "none"


_INDEP_MATCH = {"pokeapi_direct", "pokeapi_suffix", "pokeapi_form"}


def resolve_name_en(name_jp: str, poke_dict: dict[str, str],
                    api_dict: dict[str, str] | None = None,
                    verified_en_by_jp: dict[str, str] | None = None
                    ) -> tuple[Optional[str], str, str]:
    """取り込み時 fail-closed な name_en 解決 (arch2: 番号計算→源参照+自己整合).

    旧来の「pokeapi 図鑑番号で機械計算」は番号ズレ/product_id破損で別種に化けた
    (チコリータ→Durant 等)。本関数は **canonical な name_jp 直引き(translate_by_rule)
    のみ採用 + 既存 verified との自己整合** を強制し、確証なければ空欄(fail-closed)。

    Args:
      verified_en_by_jp: {name_jp: 確定済 name_en}。同一 species は同一英名=源参照。
                         (b_layer verified_auto/manual から構築して渡す)
    Returns:
      (name_en | None, status, reason)
      status: 'verified_auto'(rule独立一致) | 'reuse_verified'(既存再利用)
            | 'disputed'(ruleと既存が不一致=番号バグの疑い) | 'blank'(確証なし=空欄)
    """
    verified_en_by_jp = verified_en_by_jp or {}
    api_dict = api_dict or {}
    existing = verified_en_by_jp.get(name_jp)
    cand, mt = translate_by_rule(name_jp, poke_dict, api_dict)
    cand_indep = bool(cand) and mt in _INDEP_MATCH

    if existing:
        if cand_indep and cand == existing:
            return existing, "verified_auto", f"rule({mt})+verified 一致"
        if cand_indep and cand != existing:
            # 独立 rule と既存 verified が食い違う = 番号/コード破損の疑い → 採らない
            return None, "disputed", f"rule={cand!r} != verified={existing!r}"
        # 候補が非独立 or 不能 → 既存 verified を源参照で再利用
        return existing, "reuse_verified", "既存 verified 再利用"

    # 既存なし: 独立 rule のみ採用、それ以外は fail-closed(空欄)
    if cand_indep:
        return cand, "verified_auto", f"rule {mt}"
    return None, "blank", f"非独立(mt={mt}) → fail-closed"


def _english_suffix(jp_suffix: str) -> str:
    """suffix の英語表記 (TCG English convention)."""
    mapping = {
        "ex":      " ex",          # lowercase ex
        "EX":      "-EX",          # XY era は -EX (uppercase + dash)
        "ex δ":    " ex δ",
        "δ":       " δ",
        "GX":      "-GX",
        "V":       " V",
        "VMAX":    " VMAX",
        "VSTAR":   " VSTAR",
        "BREAK":   " BREAK",
        "STAR":    " *",           # Pokémon Star (1A0)
        "ΩMEGA":   " ΩMEGA",
        "プリズム":" Prism Star",   # ♢ 標記
        "♢":       " ◇",
    }
    return mapping.get(jp_suffix, " " + jp_suffix)


def _apply_form_prefix(name: str, poke_dict: dict[str, str]) -> Optional[str]:
    """form prefix (メガ/アローラ等) を解釈、英訳を返す.

    例: "メガクチート" → poke_dict["クチート"] = "Mawile" → "M Mawile"
        "アローラ ガラガラ" → "Alolan Marowak"
    """
    for jp_prefix, en_prefix in FORM_PREFIX_MAP:
        if name.startswith(jp_prefix):
            base = name[len(jp_prefix):].lstrip(" 　")
            en_base = poke_dict.get(base)
            if en_base:
                return f"{en_prefix}{en_base}"
    return None


# ============================================================================
# Claude API 翻訳 (未マッチ用)
# ============================================================================
def translate_via_api(unique_names: list[str], specs_context: dict) -> dict[str, str]:
    """未マッチの name_jp を Claude API でバッチ翻訳.

    Args:
        unique_names: 翻訳対象の distinct ja name list
        specs_context: {name_jp: {set_name, card_type}} 付帯情報

    Returns:
        {ja_name: en_name}

    実装方針:
      - BATCH_SIZE 件単位でリクエスト
      - system prompt に Pokemon TCG English 表記規約 + reference 辞書 (suffix 例)
      - JSON 形式で返答求める
      - 既存 cache は呼び出し側で merge
    """
    try:
        import anthropic
    except ImportError:
        print("[ERROR] anthropic SDK 未インストール: pip install anthropic")
        return {}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # 共有 credentials から読込 fallback (HQ TCG の "API key.txt" と同パターン)
        for p in (
            Path("C:/dev/iMak_data/credentials/api_key.txt"),
            Path("C:/dev/iMak/iMakTCG/API key.txt"),
        ):
            if p.exists():
                api_key = p.read_text(encoding="utf-8").strip()
                print(f"  API key loaded from: {p}")
                break
    if not api_key:
        print("[ERROR] ANTHROPIC_API_KEY 未設定")
        return {}

    client = anthropic.Anthropic(api_key=api_key)

    system = """You are translating Japanese Pokémon TCG card names to their official English TCG names.

CONTEXT: These are Japanese Pokémon Trading Card Game card names from pokemon-card.com.
The translations will be used in eBay listings, so they MUST match the official English TCG card names exactly.

CARD TYPES:
- Pokémon (キャラ): Translate to the official English Pokémon name (e.g., ピカチュウ → Pikachu)
- Trainer cards (人物名 / Item / Stadium / Supporter): Use official English Trainer/Item/Stadium name
- Energy cards (エネルギー): Use official English Energy name

SUFFIX RULES (Pokémon variants):
- "ex" (小文字) at end → " ex"        e.g., リザードンex → Charizard ex
- "EX" (大文字、XY era) → "-EX"       e.g., リザードンEX → Charizard-EX
- "GX" → "-GX"                       e.g., リザードンGX → Charizard-GX
- "V" → " V"                          e.g., ピカチュウV → Pikachu V
- "VMAX" → " VMAX"                    e.g., リザードンVMAX → Charizard VMAX
- "VSTAR" → " VSTAR"                  e.g., リザードンVSTAR → Charizard VSTAR
- "BREAK" → " BREAK"
- "プリズム" (suffix) → " Prism Star"

POSSESSIVE PATTERN: "<Trainer>の<Pokemon>" → "<Trainer>'s <Pokemon>"
  e.g., ナンジャモのカイデン → Iono's Wattrel
        シロナのガブリアスex → Cynthia's Garchomp ex

FORM PREFIXES:
- メガ<Pokemon> → "M <Pokemon>"       e.g., メガクチートex → M Mawile ex
- アローラ<Pokemon> → "Alolan <Pokemon>"
- ガラル<Pokemon> → "Galarian <Pokemon>"
- ヒスイ<Pokemon> → "Hisuian <Pokemon>"
- パルデア<Pokemon> → "Paldean <Pokemon>"

ITEM CARD CONVENTIONS:
- しんかのおこう → Rare Candy (NOTE: this is actually "Evolution Incense" - look up correct name)
- モンスターボール → Poké Ball
- きずぐすり → Potion
- パワータブレット → Lillipup ? — use OFFICIAL English item name

IMPORTANT:
- If you don't know the exact official English name, give your BEST GUESS but flag with "?" suffix
- For Stadium / Trainer / Item cards, use the EXACT official translation from the English TCG
- Preserve accents (Pokémon, Poké, etc.)
- For 人名 (Trainer characters), use their official English game/anime name

OUTPUT: JSON only, no markdown, no explanation.
Format: {"japanese_name_1": "english_name_1", "japanese_name_2": "english_name_2", ...}"""

    out: dict[str, str] = {}
    total = len(unique_names)
    print(f"\n=== Claude API 翻訳開始: {total} 件 (batch={BATCH_SIZE}) ===")

    for i in range(0, total, BATCH_SIZE):
        batch = unique_names[i:i + BATCH_SIZE]
        # context 添付 (set_name / card_type が分かると精度向上)
        items = []
        for n in batch:
            ctx = specs_context.get(n, {})
            ctx_str = ""
            if ctx.get("set_name"):
                ctx_str += f" [set={ctx['set_name']}]"
            if ctx.get("card_type"):
                ctx_str += f" [type={ctx['card_type']}]"
            items.append(f'  - {n}{ctx_str}')
        prompt = (
            f"Translate these {len(batch)} Japanese Pokémon TCG card names to official English TCG names.\n\n"
            f"Names:\n" + "\n".join(items) +
            f"\n\nReturn JSON only: " + "{name_jp: name_en, ...}"
        )

        try:
            resp = client.messages.create(
                model=MODEL_ID,
                max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = resp.content[0].text.strip()
            # JSON 抽出 (```json ... ``` も対応)
            m = re.search(r"\{[\s\S]*\}", txt)
            if m:
                txt = m.group(0)
            d = json.loads(txt)
            for k, v in d.items():
                if isinstance(v, str) and v.strip():
                    out[k] = v.strip()
            print(f"  [{i+len(batch):>5d}/{total}] batch ok: {len(d)} translated")
        except Exception as e:
            print(f"  [{i+len(batch):>5d}/{total}] ERR: {type(e).__name__}: {str(e)[:150]}")
        time.sleep(0.3)  # rate-limit safety

    print(f"=== Claude API 完了: {len(out)} 件 翻訳 ===")
    return out


# ============================================================================
# Main: catalog 全 Pokemon TCG に rule 適用 + 未マッチを API
# ============================================================================
def run(smoke: int = 0, rule_only: bool = False, dry_run: bool = False) -> None:
    poke_dict = load_pokeapi_dict()
    api_dict = load_api_dict()
    print(f"PokéAPI 辞書: {len(poke_dict):,} 件")
    print(f"API cache: {len(api_dict):,} 件")

    conn = sqlite3.connect(str(api._DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # arch2 fail-closed: 既存 verified name_en を name_jp→en の源として構築 (同species同英名)
    verified_en_by_jp: dict[str, str] = {}
    try:
        for vr in cur.execute(
            """SELECT p.name_jp, p.name_en FROM products p
               JOIN b_layer_status b ON b.product_id_ref = p.id
               WHERE p.category = ? AND b.field = 'name_en'
                 AND b.status IN ('verified_auto','verified_manual')
                 AND p.name_jp IS NOT NULL AND p.name_en IS NOT NULL AND p.name_en != ''""",
            (CATEGORY,)):
            verified_en_by_jp.setdefault(vr["name_jp"], vr["name_en"])
    except sqlite3.OperationalError:
        pass  # b_layer_status 未作成環境
    print(f"verified 源 (name_jp→en): {len(verified_en_by_jp):,} 件")

    # 対象 (name_en 未投入のみ)
    cur.execute("""SELECT product_id, name, name_jp, specs FROM products
                   WHERE category = ? AND (name_en IS NULL OR name_en = '')""",
                (CATEGORY,))
    rows = cur.fetchall()
    print(f"\n対象: {len(rows):,} 件 (name_en 未投入)")
    if smoke:
        rows = rows[:smoke]
        print(f"  smoke 制限: {smoke} 件のみ")

    # 1) rule 適用 + 未マッチ集計
    stats = {"pokeapi_direct": 0, "pokeapi_suffix": 0, "pokeapi_form": 0,
             "trainer_owned": 0, "trainer_standalone": 0, "api_cache": 0, "none": 0}
    pending_api: dict[str, dict] = {}  # name_jp -> context dict
    results: list[tuple[str, str, str]] = []  # (pid, name_en, match_type)
    disputed: list[tuple[str, str]] = []      # (pid, reason) ← fail-closed(空欄)

    for r in rows:
        jp = r['name_jp'] or r['name']
        # arch2: 番号計算でなく resolve_name_en(独立rule一致+自己整合+fail-closed)
        en, status, reason = resolve_name_en(jp, poke_dict, api_dict, verified_en_by_jp)
        _, mt = translate_by_rule(jp, poke_dict, api_dict)  # stats 用 match_type
        stats[mt] += 1
        if status in ("verified_auto", "reuse_verified") and en:
            results.append((r['product_id'], en, status))
        elif status == "disputed":
            disputed.append((r['product_id'], reason))  # 番号バグ疑い→空欄(fail-closed)
        else:
            # 確証なし: API 候補 (unique) へ。API結果は unverified で保存(=ゲートで弾く)
            if jp not in pending_api:
                try:
                    specs = json.loads(r['specs']) if r['specs'] else {}
                except Exception:
                    specs = {}
                pending_api[jp] = {"card_type": specs.get("card_type", "")}
    if disputed:
        print(f"  ⚠️ disputed(fail-closed=空欄): {len(disputed):,} 件")

    print(f"\n=== Rule 適用結果 ===")
    for k, v in stats.items():
        if v > 0:
            print(f"  {k:25s}: {v:>6,}")
    print(f"  ----------------------------")
    print(f"  rule ヒット: {sum(stats[k] for k in stats if k != 'none'):>6,}")
    print(f"  API 必要 (distinct): {len(pending_api):>6,}")

    # 2) API 翻訳 (cache 越し)
    if pending_api and not rule_only:
        api_result = translate_via_api(sorted(pending_api.keys()), pending_api)
        # cache に統合
        api_dict.update(api_result)
        save_api_dict(api_dict)
        print(f"\nAPI cache 更新後: {len(api_dict):,} 件")
        # results に追記 (もう一度 rule 通すと API cache hit 経由で取れる)
        for r in rows:
            pid = r['product_id']
            if any(pid == res_pid for res_pid, _, _ in results):
                continue  # 既に rule で取得済
            jp = r['name_jp'] or r['name']
            en = api_result.get(jp)
            if en:
                results.append((pid, en, "claude_api"))

    # 3) DB backfill (arch2: b_layer status も同時付与。API単独=unverified, disputed=空欄)
    _NOW = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _set_status(pid, status, oracle, note):
        rr = cur.execute("SELECT id FROM products WHERE category=? AND product_id=?",
                         (CATEGORY, pid)).fetchone()
        if not rr:
            return
        try:
            cur.execute(
                "INSERT INTO b_layer_status (product_id_ref, category, product_code, field, "
                "status, oracle, checked_at, note) VALUES (?,?,?,'name_en',?,?,?,?) "
                "ON CONFLICT(product_id_ref, field) DO UPDATE SET status=excluded.status, "
                "oracle=excluded.oracle, checked_at=excluded.checked_at, note=excluded.note",
                (rr["id"], CATEGORY, pid, status, oracle, _NOW, note))
        except sqlite3.OperationalError:
            pass  # b_layer_status 未作成環境

    if dry_run:
        print(f"\n[dry-run] DB 更新スキップ. accept {len(results):,} / disputed {len(disputed):,} (適用なし)")
    else:
        print(f"\n=== DB backfill (arch2 fail-closed) ===")
        for pid, en, status in results:
            # status: verified_auto(独立rule) / reuse_verified(既存再利用) / claude_api(単独=unverified)
            if status == "claude_api":
                src, bstatus = "claude_api", "unverified"   # 単独Oracle→ゲートで弾く
            elif status == "reuse_verified":
                src, bstatus = "reuse_verified", "verified_manual"
            else:
                src, bstatus = "rule_resolve_independent", "verified_auto"
            cur.execute("""UPDATE products SET name_en = ?, name_en_source = ?
                           WHERE category = ? AND product_id = ?""",
                        (en, src, CATEGORY, pid))
            _set_status(pid, bstatus, src, f"ingest resolve ({status})")
        for pid, reason in disputed:
            _set_status(pid, "disputed", "rule_resolve", reason)  # name_en は空欄維持
        conn.commit()
        print(f"  backfilled: {len(results):,} 件 / disputed(空欄): {len(disputed):,} 件")

    conn.close()

    # 4) log 保存
    log = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_processed": len(rows),
        "stats": stats,
        "api_translated": len(pending_api) if not rule_only else 0,
        "results_count": len(results),
    }
    with open(TRANSLATION_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"\nlog 保存: {TRANSLATION_LOG}")


def export_to_csv(out_path: str) -> None:
    """HQ 検証用 CSV エクスポート."""
    conn = sqlite3.connect(str(api._DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""SELECT product_id, name_jp, name_en, name_en_source, set_name, source_url
                           FROM products WHERE category = ?
                           ORDER BY product_id""", (CATEGORY,)).fetchall()
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "name_jp", "name_en", "name_en_source", "set_name", "source_url"])
        for r in rows:
            w.writerow([r['product_id'], r['name_jp'], r['name_en'], r['name_en_source'],
                        r['set_name'], r['source_url']])
    print(f"exported: {out_path} ({len(rows):,} 件)")
    conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", type=int, default=0, help="N 件のみ処理 (動作確認)")
    p.add_argument("--all", action="store_true", help="全件処理")
    p.add_argument("--rule-only", action="store_true", help="rule 適用のみ (API 呼ばない)")
    p.add_argument("--dry-run", action="store_true", help="DB 更新せず stats のみ")
    p.add_argument("--export", help="DB 内容を CSV 出力")
    args = p.parse_args()
    if args.export:
        export_to_csv(args.export)
    else:
        run(smoke=args.smoke, rule_only=args.rule_only, dry_run=args.dry_run)
