"""[DEPRECATED 2026-06-07 — 再実行禁止] JP_TO_EN は誤りを含む (SNAD 発生源)。

  英語版の無い新弾JP set を無関係な旧ENセットに割当てる fail-closed 違反:
    インフェルノX→Burning Shadows / ムニキスゼロ→Ultra Prism / ニンジャスピナー→Steam Siege。
  live出品で SNAD 発生 (requests/2026-06-07_pokemon_mega_set_name_ebay_fix.md)。
  HQ裁定: set_name_ebay の SSOT は ebay_filter_map/pokemon.yaml に一本化。
  以後 set_name_ebay 修正は yaml 編集 + 再導出で行う。歴史的記録として残置 (削除しない)。

Pokemon set_name_ebay 投入 Step C: JP set_name → EN hardcode mapping (= 主要 80+ set).

依頼: 2026-05-30_phase_g2_pokemon_c_plus_b_go.md (= C + B GO 確定)

mapping: catalog の unique JP set_name (= 183 件) のうち主要 80+ 件 を hardcode。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = str(api._DB_PATH)
NOW = datetime.now().isoformat()

# JP set_name → EN set 名 (= pokemon.com US 公式準拠)
JP_TO_EN = {
    # === SV (Scarlet & Violet) 系 ===
    "拡張パック「スカーレットex」": "Scarlet & Violet—Scarlet ex",
    "拡張パック「バイオレットex」": "Scarlet & Violet—Violet ex",
    "拡張パック「トリプレットビート」": "Scarlet & Violet—Triplet Beat",
    "拡張パック「スノーハザード」": "Scarlet & Violet—Paldea Evolved",
    "拡張パック「クレイバースト」": "Scarlet & Violet—Paldea Evolved",
    "拡張パック「ポケモンカード151（イチゴーイチ）」": "Scarlet & Violet—151",
    "拡張パック「黒炎の支配者」": "Scarlet & Violet—Obsidian Flames",
    "拡張パック「レイジングサーフ」": "Scarlet & Violet—Paradox Rift",
    "拡張パック「古代の咆哮」": "Scarlet & Violet—Paradox Rift",
    "拡張パック「未来の一閃」": "Scarlet & Violet—Paradox Rift",
    "ハイクラスパック「シャイニートレジャーex」": "Scarlet & Violet—Paldean Fates",
    "拡張パック「ワイルドフォース」": "Scarlet & Violet—Temporal Forces",
    "拡張パック「サイバージャッジ」": "Scarlet & Violet—Temporal Forces",
    "拡張パック「クリムゾンヘイズ」": "Scarlet & Violet—Twilight Masquerade",
    "拡張パック「変幻の仮面」": "Scarlet & Violet—Twilight Masquerade",
    "拡張パック「ナイトワンダラー」": "Scarlet & Violet—Shrouded Fable",
    "拡張パック「ステラミラクル」": "Scarlet & Violet—Stellar Crown",
    "拡張パック「楽園ドラゴーナ」": "Scarlet & Violet—Surging Sparks",
    "拡張パック「超電ブレイカー」": "Scarlet & Violet—Surging Sparks",
    "ハイクラスパック「テラスタルフェスex」": "Scarlet & Violet—Surging Sparks",
    "拡張パック「バトルパートナーズ」": "Scarlet & Violet—Journey Together",
    "拡張パック「熱風のアリーナ」": "Scarlet & Violet—Destined Rivals",
    "拡張パック「ロケット団の栄光」": "Scarlet & Violet—Destined Rivals",
    "拡張パック「ブラックボルト」": "Scarlet & Violet—Black Bolt",
    "拡張パック「ホワイトフレア」": "Scarlet & Violet—White Flare",
    "拡張パック「メガブレイブ」": "Scarlet & Violet—Mega Brave",
    "拡張パック「メガシンフォニア」": "Scarlet & Violet—Mega Symphonia",
    "ハイクラスパック「MEGAドリームex」": "Mega Dimension",
    # === Sword & Shield 系 ===
    "拡張パック「ソード」": "Sword & Shield",
    "拡張パック「シールド」": "Sword & Shield",
    "拡張パック「反逆クラッシュ」": "Sword & Shield—Rebel Clash",
    "拡張パック「ムゲンゾーン」": "Sword & Shield—Darkness Ablaze",
    "拡張パック「伝説の鼓動」": "Sword & Shield—Vivid Voltage",
    "拡張パック「仰天のボルテッカー」": "Sword & Shield—Vivid Voltage",
    "ハイクラスパック「シャイニースターV」": "Sword & Shield—Shining Fates",
    "拡張パック「連撃マスター」": "Sword & Shield—Battle Styles",
    "拡張パック「一撃マスター」": "Sword & Shield—Battle Styles",
    "拡張パック「双璧のファイター」": "Sword & Shield—Battle Styles",
    "拡張パック「白銀のランス」": "Sword & Shield—Chilling Reign",
    "拡張パック「漆黒のガイスト」": "Sword & Shield—Chilling Reign",
    "拡張パック「イーブイヒーローズ」": "Sword & Shield—Evolving Skies",
    "拡張パック「蒼空ストリーム」": "Sword & Shield—Evolving Skies",
    "拡張パック「摩天パーフェクト」": "Sword & Shield—Evolving Skies",
    "拡張パック「フュージョンアーツ」": "Sword & Shield—Fusion Strike",
    "拡張パック「25th ANNIVERSARY COLLECTION」": "Celebrations",
    "ハイクラスパック「VMAXクライマックス」": "Sword & Shield—Brilliant Stars",
    "拡張パック「スターバース」": "Sword & Shield—Brilliant Stars",
    "拡張パック「バトルリージョン」": "Sword & Shield—Astral Radiance",
    "拡張パック「タイムゲイザー」": "Sword & Shield—Astral Radiance",
    "拡張パック「スペースジャグラー」": "Sword & Shield—Astral Radiance",
    "拡張パック「ダークファンタズマ」": "Sword & Shield—Lost Origin",
    "拡張パック「ロストアビス」": "Sword & Shield—Lost Origin",
    "拡張パック「白熱のアルカナ」": "Sword & Shield—Lost Origin",
    "拡張パック「Pokémon GO」": "Sword & Shield—Pokémon GO",
    "拡張パック「パラダイムトリガー」": "Sword & Shield—Silver Tempest",
    "ハイクラスパック 「VSTARユニバース」": "Sword & Shield—Crown Zenith",
    # === Sun & Moon 系 ===
    "拡張パック「コレクション サン」": "Sun & Moon",
    "拡張パック「コレクション ムーン」": "Sun & Moon",
    "拡張パック「アローラの月光」": "Sun & Moon—Guardians Rising",
    "拡張パック「アローラの太陽」": "Sun & Moon—Guardians Rising",
    "拡張パック「光を喰らう闇」": "Sun & Moon—Burning Shadows",
    "拡張パック「覚醒の勇者」": "Sun & Moon—Burning Shadows",
    "拡張パック「ひかる伝説」": "Sun & Moon—Shining Legends",
    "拡張パック「ウルトラサン」": "Sun & Moon—Crimson Invasion",
    "拡張パック「ウルトラムーン」": "Sun & Moon—Crimson Invasion",
    "拡張パック「ウルトラフォース」": "Sun & Moon—Ultra Prism",
    "拡張パック「ウルトラシャイニー」": "Sun & Moon—Forbidden Light",
    "拡張パック「禁断の光」": "Sun & Moon—Forbidden Light",
    "拡張パック「ドラゴンストーム」": "Sun & Moon—Forbidden Light",
    "拡張パック「雷鳴のスパーク」": "Sun & Moon—Celestial Storm",
    "拡張パック「裂空のカリスマ」": "Sun & Moon—Celestial Storm",
    "拡張パック「フェアリーライズ」": "Sun & Moon—Lost Thunder",
    "拡張パック「超爆インパクト」": "Sun & Moon—Lost Thunder",
    "拡張パック「ダークオーダー」": "Sun & Moon—Team Up",
    "ハイクラスパック「GXウルトラシャイニー」": "Sun & Moon—Lost Thunder",
    "拡張パック「タッグボルト」": "Sun & Moon—Team Up",
    "拡張パック「ナイトユニゾン」": "Sun & Moon—Team Up",
    "拡張パック「フルメタルウォール」": "Sun & Moon—Unbroken Bonds",
    "拡張パック「ダブルブレイズ」": "Sun & Moon—Unbroken Bonds",
    "拡張パック「スカイレジェンド」": "Sun & Moon—Cosmic Eclipse",
    "拡張パック「ジージーエンド」": "Sun & Moon—Cosmic Eclipse",
    "拡張パック「リミックスバウト」": "Sun & Moon—Cosmic Eclipse",
    "拡張パック「ドリームリーグ」": "Sun & Moon—Cosmic Eclipse",
    "拡張パック「オルタージェネシス」": "Sun & Moon—Cosmic Eclipse",
    "ハイクラスパック「TAG TEAM GX タッグオールスターズ」": "Sun & Moon—Cosmic Eclipse",
    # === XY 系 ===
    "拡張パック「コレクションX」": "XY",
    "拡張パック「コレクションY」": "XY",
    "拡張パック「ライジングフィスト」": "XY—Furious Fists",
    "拡張パック「ファントムゲート」": "XY—Phantom Forces",
    "拡張パック「タイダルストーム」": "XY—Primal Clash",
    "拡張パック「エメラルドブレイク」": "XY—Roaring Skies",
    "拡張パック「バンデットリング」": "XY—Ancient Origins",
    "拡張パック「めざめる超王」": "XY—BREAKpoint",
    "拡張パック「爆熱の闘士」": "XY—BREAKthrough",
    "拡張パック「青い衝撃」": "XY—Steam Siege",
    "拡張パック「赤い閃光」": "XY—Steam Siege",
    "拡張パック「ニンジャスピナー」": "XY—Steam Siege",
    "ハイクラスパック「THE BEST OF XY」": "XY—Evolutions",
    "拡張パック「ダブルクライシス」": "XY—Double Crisis",
    # === BW 系 ===
    "拡張パック「ブラックコレクション」": "Black & White",
    "拡張パック「ホワイトコレクション」": "Black & White",
    # === DP / DPs 系 ===
    "拡張パック「時空の創造 パールコレクション」": "Diamond & Pearl",
    # === ハイクラス / GX 系 ===
    "ハイクラスパック「GXバトルブースト」": "Sun & Moon—Burning Shadows",
    # === 拡張パック (Movie / Misc) ===
    "拡張パック「ひかる闇」": "Sun & Moon—Shining Legends",
    "拡張パック「インフェルノX」": "Sun & Moon—Burning Shadows",
    "拡張パック「ミラクルツイン」": "Sun & Moon—Forbidden Light",
    "拡張パック「アルセウス光臨」": "Sword & Shield—Astral Radiance",
    "拡張パック「破空の激闘」": "Sword & Shield—Vivid Voltage",
    "拡張パック「破天の怒り」": "Sword & Shield—Battle Styles",
    "拡張パック「時の果ての絆」": "Sword & Shield—Vivid Voltage",
    "拡張パック「ワイルドブレイズ」": "Scarlet & Violet—Stellar Crown",
    "拡張パック「ギンガの覇道」": "Sword & Shield—Astral Radiance",
    "拡張パック「湖の秘密」": "Sun & Moon—Lost Thunder",
    "拡張パック「ムニキスゼロ」": "Sun & Moon—Ultra Prism",
    "拡張パック「フロンティアの鼓動」": "Scarlet & Violet—Destined Rivals",
    "拡張パック「ロケット団の栄光」": "Scarlet & Violet—Destined Rivals",
    "拡張パック「ドラゴンセレクション」": "Scarlet & Violet—Stellar Crown",
    # === 案 2 追加 (= 5/30 Step B 失敗後、 主要漏れ TCG set 手動 mapping) ===
    "ハイクラスパック 「MEGAドリームex」": "Mega Dimension",
    "拡張パック「VMAXライジング」": "Sword & Shield—Brilliant Stars",
    "拡張パック「よみがえる伝説」": "Sword & Shield—Lost Origin",
    "拡張パック「ガイアボルケーノ」": "XY—Primal Clash",
    "拡張パック「キミを待つ島々」": "Sun & Moon—Guardians Rising",
    "拡張パック「コールドフレア」": "Black & White—Boundaries Crossed",
    "拡張パック「サイコドライブ」": "Black & White—Plasma Storm",
    "拡張パック「サン&ムーン」": "Sun & Moon",
    "拡張パック「サン＆ムーン」": "Sun & Moon",
    "拡張パック「ソウルシルバーコレクション」": "HeartGold & SoulSilver",
    "拡張パック「ダークラッシュ」": "Black & White—Dark Explorers",
    "拡張パック「チャンピオンロード」": "Black & White—Plasma Freeze",
    "拡張パック「ハートゴールドコレクション」": "HeartGold & SoulSilver",
    "拡張パック「フリーズボルト」": "Black & White—Plasma Freeze",
    "拡張パック「プラズマゲイル」": "Black & White—Plasma Storm",
    "拡張パック「ヘイルブリザード」": "Black & White—Plasma Blast",
    "拡張パック「メガロキャノン」": "XY—Primal Clash",
    "拡張パック「ライデンナックル」": "Black & White—Boundaries Crossed",
    "拡張パック「ラセンフォース」": "Black & White—Plasma Freeze",
    "拡張パック「リューズブラスト」": "Black & White—Dragons Exalted",
    "拡張パック「リューノブレード」": "Black & White—Dragons Exalted",
    "拡張パック「レッドコレクション」": "HeartGold & SoulSilver—Unleashed",
    "拡張パック「冷酷の反逆者」": "XY—BREAKpoint",
    "拡張パック「夜明けの疾走」": "Sun & Moon—Burning Shadows",
    "拡張パック「怒りの神殿」": "Black & White—Legendary Treasures",
    "拡張パック「新たなる試練の向こう」": "Sun & Moon—Guardians Rising",
    "拡張パック「時空の創造 ダイヤモンドコレクション」": "Diamond & Pearl",
    "拡張パック「月光の追跡」": "Sun & Moon—Lost Thunder",
    "拡張パック「爆炎ウォーカー」": "Sun & Moon—Burning Shadows",
    "拡張パック「秘境の叫び」": "XY—Ancient Origins",
    "拡張パック「超次元の暴獣」": "XY—Phantom Forces",
    "拡張パック「迅雷スパーク」": "Sun & Moon—Celestial Storm",
    "拡張パック「闘う虹を見たか」": "Black & White—Legendary Treasures",
    "拡張パック「頂上大激突」": "Platinum—Supreme Victors",
}


def process(dry_run: bool):
    print(f"=== Pokemon set_name_ebay JP→EN ({'DRY-RUN' if dry_run else 'APPLY'}) ===")
    print(f"  mappings defined: {len(JP_TO_EN)}")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rs = db.execute(
        "SELECT id, product_id, set_name, specs FROM products WHERE category='pokemon_tcg'"
    ).fetchall()
    n = len(rs)
    updated = 0
    skip_already = 0
    no_match = 0
    for r in rs:
        try:
            specs = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            specs = {}
        if specs.get("set_name_ebay"):
            skip_already += 1
            continue
        set_name_jp = r["set_name"] or ""
        en = JP_TO_EN.get(set_name_jp)
        if not en:
            no_match += 1
            continue
        specs["set_name_ebay"] = en
        updated += 1
        if not dry_run:
            db.execute(
                "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                (json.dumps(specs, ensure_ascii=False), NOW, r["id"]),
            )
    if not dry_run:
        db.commit()
    db.close()
    print(f"\n  total: {n:,}")
    print(f"  updated: {updated:,} ({updated/n*100:.1f}%)")
    print(f"  skip (= already set): {skip_already:,}")
    print(f"  no_match: {no_match:,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
