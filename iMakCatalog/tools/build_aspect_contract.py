#!/usr/bin/env python3
"""eBay 35項目の「決定表」を作る (2026-08-22 新設).

## なぜ作るか
変換表が Set と Rarity の2項目しか無く、残り33項目は **その都度どちらかが判断** していた。
判断の余地があるから判断を間違え、訂正が往復する。実例 (2026-08-22 の1日で4件):
  - Leader の cost (5月の判断が誤り) / Card Type は自由入力 (こちらの回答が誤り)
  - Features の Holo (HQ の前提が誤り) / rarity の集計範囲 (HQ の数字が別スコープ)

**この表を唯一の口にする。** 出品くんは表に書いてある項目を読むだけ、
カタログは表に書いてある項目を埋めるだけ、監査は表と突き合わせるだけ。
変えるときは表の1行を、証拠と日付を付けて変える。

## 列の意味
  source     : 値の出どころ。`specs.<key>` / `column.<name>` / `psa_cert` / `fixed:<値>` / null
  emit       : eBay に出すか
  owner      : 値を決める責任者 (catalog / listing)
  reason     : 出さない・埋まらない理由 (天井の根拠)
  decided    : 決めた日と根拠

実行:
  python tools/build_aspect_contract.py            # 生成 (既存は上書き)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")
OUT = ROOT / "ebay_filter_map" / "_contract_aspects.yaml"
# ★共有領域にも同じものを置く (2026-08-22 HQ 依頼)。
#   worktree 分離のルールで他セッションはこちらの worktree を読めないため、
#   出品くん・監査くんはこのコピーを読む。**書き手はカタログだけ**。
SHARED = Path(r"C:/dev/iMak_data/catalog/_contract_aspects.yaml")
NL = chr(10)
CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg", "yugioh_tcg")

# ★ここが人の決定。ここ以外に判断を置かない
D = {
    "Game":               ("specs.game_ebay", True, "catalog", "category ごとに1値の定数。監査 §11 で見張る", "2026-08-25"),
    "Card Name":          ("column.name_en", True, "catalog", "", "2026-08-22 綴りを eBay に合わせた"),
    "Set":                ("specs.set_name_ebay", True, "catalog", "", "2026-08-21 HQ 裁定 (コード形)"),
    "Character":          ("specs.character_name", True, "catalog", "", "2026-05-30 日本語混入禁止"),
    "Manufacturer":       ("specs.manufacturer_ebay", True, "catalog", "category ごとに1値の定数。監査 §11 で見張る", "2026-08-25"),
    "Card Type":          ("specs.card_type_ebay", True, "catalog", "公式の種別見出し (<h2>グッズ</h2>) から取る。語彙7つが eBay の Pokémon TCG 11値と1対1。監査 §10 で見張る", "2026-08-25 名前からの推定を廃止 (5,561行)"),
    "Rarity":             ("specs.rarity_ebay", True, "catalog", "空欄8,515行は公式にレアリティ表示が無い=天井", "2026-08-22 実取得で確認"),
    "Creature/Monster Type": ("specs.creature_type_ebay", True, "catalog", "遊戯王のみ 31,937行。当社は遊戯王を1枚も出していないので実質使わない。ポケモンのタイプはここではない", "2026-08-25 閉じた"),
    "Attribute/MTG:Color": ("specs.color_ebay", True, "catalog", "ポケモンのタイプはここ (取得中)", "2026-08-22"),
    "Features":           ("specs.features_ebay", True, "catalog", "Holo/Reverse Holo は Features に無い (Finish の値)。値は必ずリストで持つ。使用4値は eBay の39値内 (リスト外0行)", "2026-08-25 カタログ側は完了。HQ の区切り文字 (, -> |) 確認待ち"),
    "Speciality":         ("specs.speciality_ebay", True, "catalog", "ポケモンだけ (EX/V/GX/VMAX/BREAK)。他ゲームに相当する概念が無い", "2026-08-25 閉じた"),
    "Card Number":        ("specs.card_number_text", True, "catalog", "券面の番号。書式はゲームで違う (ポケモン 001/083 / ワンピ EB02-003) ので数字部分で突合。空欄はすべて cardID-* で公式に番号が刷られていない", "2026-08-25 §12 で見張る (食い違い0)"),
    "Language":           ("specs.language", True, "catalog", "現物が何語で刷られているか。日本語版4カテゴリは Japanese の定数。遊戯王は English。監査 §11 で見張る", "2026-08-25 空欄2,859行を穴埋め"),
    "Card Size":          ("specs.card_size_ebay", True, "catalog", "Standard の1値のみ。特大カードの区別はしない (元データに大きさの項目が無い)。監査 §11 で見張る", "2026-08-25 空欄2,859行を穴埋め"),
    "Illustrator":        ("specs.illustrator", True, "catalog", "取れるカテゴリだけ。ポケモン 21,140/22,111 / ワンピは元データに項目が無く 0", "2026-08-25 閉じた"),
    # ★2026-08-22 変更: 出どころは **PSA の鑑定ラベルの年**。現物に打たれた年で、
    #   cert がある出品では 100% 取れる (catalog の release_year は弾単位の推定で欠けがある)。
    #   catalog の release_year は社内用に残すが eBay には出さない。
    "Year Manufactured":  ("psa_cert", True, "listing", "PSA ラベルの年 (現物に打たれた年)", "2026-08-22 HQ Q2 で確定"),
    "Stage":              ("specs.stage_ebay", True, "catalog", "公式の欄 (span.type) から取る。eBay の9値のうちポケモン向けは Basic/Stage 1/Stage 2/Mega の4つで全部使用済。V進化/レベルアップ/BREAK進化/復元/伝説/V-UNION は**対応する値が無い**ので空欄が正 (Champion/Rookie 等はデジモンの段階)", "2026-08-25 §9/§13 で見張る"),
    "HP":                 ("specs.hp_ebay", True, "catalog", "ポケモンだけ。Trainer/Energy は持たない (化石の効果文 HP60 を拾っていた 43行を是正)。監査 §13 で見張る", "2026-08-25"),
    "Attack/Power":       ("specs.attack_power_ebay", True, "catalog", "種別が持たない組み合わせは §13 で見張る。「一部だけ持つ」は正常なこともある (ガンダムの Pilot 等)", "2026-08-25"),
    "Defense/Toughness":  ("specs.defense_toughness_ebay", True, "catalog", "ガンダムのみ。監査 §13 で見張る", "2026-08-25"),
    # --- 出さないと決めたもの (監査で 0% と出ても穴ではない) ---
    "Finish":             (None, False, "catalog", "現物を見ないと決まらない。公式データに foil/holo の項目が無い", "2026-08-22 ユーザー確定"),
    "Age Level":          (None, False, "catalog", "CPSC (米国消費者製品安全委員会) の関係", "2026-08-22 ユーザー確定"),
    "Autographed":        (None, False, "catalog", "サイン入りの取り扱いが無い", "2026-08-22 ユーザー確定"),
    "Signed By":          (None, False, "catalog", "同上", "2026-08-22"),
    "Autograph Authentication": (None, False, "catalog", "同上", "2026-08-22"),
    "Autograph Format":   (None, False, "catalog", "同上", "2026-08-22"),
    "Autograph Authentication Number": (None, False, "catalog", "同上", "2026-08-22"),
    "Customized":         (None, False, "catalog", "扱いが無い。固定値で出さない (出品側の固定出力を止める)", "2026-08-22 HQ Q4"),
    "Material":           (None, False, "catalog", "根拠が無い。固定値で出さない (出品側の固定出力を止める)", "2026-08-22 HQ Q4"),
    "Vintage":            (None, False, "catalog", "定義が曖昧。固定値で出さない (出品側の固定出力を止める)", "2026-08-22 HQ Q4"),
    "Convention/Event":   (None, False, "catalog", "扱いが無い", "2026-08-22"),
    "Franchise":          (None, False, "catalog", "eBay の37値は Disney Lorcana の作品名だけ。TCG に該当が無い (実取得で確認)", "2026-08-22 HQ Q4"),
    "Country of Origin":  ("specs.country_of_origin_ebay", True, "catalog", "", "2026-08-22 HQ Q4 で確定 (language=Japanese の行に Japan)"),
    "California Prop 65 Warning": (None, False, "listing", "出品側の運用", "2026-08-22"),
    # ★2026-08-22 変更: 自由入力で、カタログに事実の値がある (Leader は life に移したので空)。
    "Cost":               ("specs.cost", True, "catalog", "", "2026-08-22 HQ Q3 で確定 (出す)"),
    # --- 出品側が持つもの (カタログは関与しない) ---
    "Graded":             ("fixed:Yes", True, "listing", "PSA10 運用の固定値", "2026-08-22"),
    "Grade":              ("psa_cert", True, "listing", "cert から取る", "2026-08-22"),
    "Professional Grader": ("fixed:PSA", True, "listing", "PSA10 運用の固定値", "2026-08-22"),
    "Certification Number": ("psa_cert", True, "listing", "cert から取る", "2026-08-22"),
    "Card Condition":     ("fixed:Near Mint or Better", True, "listing", "PSA10 運用の固定値", "2026-08-22"),
}


def main():
    aspects = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]
    db = api._connect()
    fill = {}
    for asp, (src, *_rest) in D.items():
        if not src or not src.startswith(("specs.", "column.")):
            continue
        key = src.split(".", 1)[1]
        n = t = 0
        for r in db.execute("SELECT name_en, specs FROM products WHERE category IN (%s)"
                            % ",".join("?" * len(CATS)), CATS):
            t += 1
            v = r["name_en"] if src.startswith("column.") else json.loads(r["specs"] or "{}").get(key)
            if str(v or "").strip():
                n += 1
        fill[asp] = (n, t)

    lines = [
        "# eBay 35項目の決定表 (2026-08-22 制定) — **ここが唯一の口**",
        "#",
        "# 出品くん: emit=true の項目を source から読むだけ。自前で書き換えない",
        "# カタログ: owner=catalog の項目を埋める。出す/出さないを都度判断しない",
        "# 監査:     emit=false は穴として起票しない (reason が天井の根拠)",
        "#",
        "# 変えるときは この表の1行を、証拠 (実取得の出力) と日付を付けて変える。",
        "# 生成: tools/build_aspect_contract.py",
        "",
        "aspects:",
    ]
    # ★2026-08-23: eBay の 35項目に無いが **CSV には実際に出している** 列も表に載せる
    #   (PSA の cert 由来と PSA10 運用の固定値)。載せないと監査くんが毎回
    #   「表に無い項目」と言い続ける (HQ 指摘 2026-08-22)。
    extra = [a for a in D if a not in aspects]
    for asp in list(aspects) + extra:
        src, emit, owner, reason, decided = D.get(asp, (None, False, "catalog", "未決定", ""))
        n, t = fill.get(asp, (0, 0))
        lines += [
            f'  - ebay_aspect: "{asp}"',
            f'    source: {src if src else "null"}',
            f'    emit: {"true" if emit else "false"}',
            f'    owner: {owner}',
            f'    mode: {aspects[asp]["constraint"].get("mode") if asp in aspects else "N/A (eBay の aspect 一覧に無い列)"}',
            f'    ebay_values: {len(aspects[asp]["all"]) if asp in aspects else 0}',
        ]
        if t:
            lines.append(f'    filled: {n}/{t}')
        if reason:
            lines.append(f'    reason: "{reason}"')
        if decided:
            lines.append(f'    decided: "{decided}"')
    body = NL.join(lines) + NL
    OUT.write_text(body, encoding="utf-8")
    SHARED.write_text(body, encoding="utf-8")
    OUT.write_text(body, encoding="utf-8")
    SHARED.write_text(body, encoding="utf-8")
    miss = [a for a in aspects if a not in D]
    print(f"決定表を書きました: {OUT}")
    print(f"                    {SHARED} (共有コピー)")
    print(f"  35項目中 決定済 {len(aspects) - len(miss)} / 未決定 {len(miss)} {miss}")
    print(f"  出す {sum(1 for a in aspects if D.get(a, (0, False))[1])} / 出さない "
          f"{sum(1 for a in aspects if not D.get(a, (0, False))[1])}")


if __name__ == "__main__":
    main()
