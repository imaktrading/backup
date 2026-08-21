#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tcg_set_rarity_maps.py — セット名/レアリティの言い換え表 (2026-08-21 に1本化)。

★なぜ分けたか: この6表は `psa_to_csv.py` と `psa_restock_csv.py` に
  **同じ内容で2本ずつ**あった。片方だけ直せば即ズレるので、
  set/rarity 絡みの依頼が3ヶ月で65本立った発生源のひとつだった
  (2026-08-21 ユーザー指摘で棚卸し)。

★ここは「出品くん側の言い換え」。カタログの `ebay_filter_map` とは役割が違う:
  - カタログ = 公式セット名 → eBay の Set 値 (カタログが正)
  - ここ     = タイトル生成や Features 補完に使う出品くん内の表
  レアリティは `api.derive_rarity_ebay()` へ寄せる作業が別途進行中
  (`2026-08-21_set_rarity_final_plan.md`)。
"""

_DRAGONBALL_SET_NAME_MAP = {
    # Booster Pack
    "BOOSTER PACK -AWAKENED PULSE- [FB01]": "Awakened Pulse",
    "BOOSTER PACK -BLAZING AURA- [FB02]":   "Blazing Aura",
    "BOOSTER PACK -RAGING ROAR- [FB03]":    "Raging Roar",
    "BOOSTER PACK -FUSION SURGE- [FB04]":   "Fusion Surge",
    "BOOSTER PACK -RISING SPARK- [FB05]":   "Rising Spark",
    "BOOSTER PACK -PERFECT COMBINATION- [FB06]": "Perfect Combination",
    "BOOSTER PACK -ULTRA LIMIT- [FB07]":    "Ultra Limit",
    "BOOSTER PACK -SECRET OF EVOLUTION- [FB08]": "Secret of Evolution",
    "BOOSTER PACK -DESTINED RIVALS- [FB09]": "Destined Rivals",
    # Manga Booster
    "MANGA BOOSTER 02 [SB02]":              "Manga Booster 02",
    "MANGA BOOSTER 01 [SB01]":              "Manga Booster 01",
    "MANGA BOOSTER -CRITICAL BLOW- [SB02]": "Critical Blow",
    # Starter Deck
    "STARTER DECK SAIYAN GENESIS [FS01]":   "Starter Deck Saiyan Genesis",
    "STARTER DECK BUDOKAI WARRIORS [FS02]": "Starter Deck Budokai Warriors",
    "STARTER DECK PERFECTION [FS03]":       "Starter Deck Perfection",
    "STARTER DECK FRIEZA [FS04]":           "Starter Deck Frieza",
    "STARTER DECK ANDROIDS [FS05]":         "Starter Deck Androids",
    "STARTER DECK PIRATES [FS06]":          "Starter Deck Pirates",
    "STARTER DECK ULTIMATE WARRIORS [FS07]": "Starter Deck Ultimate Warriors",
    "STARTER DECK MAJIN BUU [FS08]":        "Starter Deck Majin Buu",
    "STARTER DECK EX SHALLOT [FS09]":       "Starter Deck EX Shallot",
}

_RARITY_FULL_FOR_TITLE = {"AR": "Art Rare", "SR": "Super Rare", "SAR": "Special Art Rare"}

_RARITY_TO_FEATURES = {
    "AR": "Art Rare", "SR": "Super Rare", "SAR": "Special Art Rare",
    "UR": "Ultra Rare", "HR": "Hyper Rare", "MA": "Mega Attack Rare",
    "RR": "Double Rare", "RRR": "Triple Rare", "SSR": "Shiny Super Rare",
}

DRAGONBALL_SET_PREFIX = {
    "AWAKENED PULSE": "FB01",
    "BLAZING AURA": "FB02",
    "RAGING ROAR": "FB03",
    "FUSION SURGE": "FB04",
    "RISING SPARK": "FB05",
    # Manga Booster
    "MANGA BOOSTER": "SB01",
    "MANGA BOOSTER 02": "SB02",
    # Starter
    "STARTER DECK": "FS",
}

GUNDAM_SET_PREFIX = {
    # 2026-04-24 修正: DUAL IMPACT を GD01 → GD02 に訂正（Bandai TCG+ 実DB検証済）
    # GD02-069=Zeta Gundam, GD02-072=Hyaku-Shiki 等が Dual Impact 収録と判明。
    # 旧マッピングで GD01 に誤誘導された結果、PSA "DUAL IMPACT" のカードが
    # 別カード（Strike Rouge, Launcher Strike Gundam 等）の Item Specifics を引いていた（SNAD直結）。
    "NEWTYPE RISING": "GD01",
    "DUAL IMPACT":    "GD02",
    # 以下は未検証: 実DB突き合わせしていない推測マッピング（次セッション要検証）
    "STEEL REQUIEM":     "GD02",
    "HEROIC BEGINNINGS": "GD02",
    "WINGS OF ADVANCE":  "GD03",
    "SEED STRIKE":       "GD03",
    "IRON BLOOM":        "GD04",
}

POKEMON_SET_NAME_MAP = {
    "M2A-MEGA DREAM EX": "M2a: High Class Pack: Mega Dream Ex",
    "M2A": "M2a: High Class Pack: Mega Dream Ex",
    # 2026-05-01 18:46 観測: PSA brand "POKEMON GO JAPANESE" → fallback で "Go Japanese"
    # になり eBay 公式フィルタ値 "Pokémon GO" と乖離. dict 経由で正規化.
    "GO JAPANESE": "Pokémon GO",
    # 今後追加
}
