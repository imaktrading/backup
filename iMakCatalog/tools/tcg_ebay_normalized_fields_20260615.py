#!/usr/bin/env python3
"""TCG specs に eBay 正規化フィールド *_ebay を追加 (2026-06-15 HQ BUILD).

元: 2026-06-15_tcg_ebay_normalized_fields.md。
generator(新コア tcg_listing_fields の _MULTI_SPEC_TO_COL)は catalog の *_ebay 値を copy するだけ。
正規化(日本語→eBay語彙)を catalog(SSOT)が持つ。fail-closed: マップ不能/source無は空欄(推測禁止)。

追加フィールド(各ゲームの既存 raw から):
  attack_power_ebay      ← power(OP,DB) / ap(Gundam)。DB '15000 / (裏)20000' は表'15000'。数値clean。
  defense_toughness_ebay ← hp(Gundam=防御値)。数値clean。
  color_ebay             ← color(OP,DB,Gundam)。JP/英→eBay語彙。複数色→Multi-Color。
                            Pokemon は color/type の raw が無い → 付与しない(fail-closed)。
  hp_ebay                ← hp(Pokemon)。数値clean。Gundam hp は防御なので hp_ebay に入れない。
  stage_ebay             ← stage(Pokemon)。たね→Basic/1進化→Stage 1/2進化→Stage 2/MEGA→Mega。
                            基本/VMAX/VSTAR は eBay Stage vocab に無 → 空欄(fail-closed)。

multi-color 方針(要相談項目): 複数色は eBay 単一値制約のため **Multi-Color**(eBay vocab内・事実正確・
  非推測)を採用。主色採用にしたい場合は COLOR の multi 分岐を変えるだけ(HQ 判断で切替可)。
"""
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DB_PATH = "C:/dev/iMak_data/catalog/products.sqlite"
BAK_PATH = Path("C:/dev/iMak_data/catalog/_bak/tcg_ebay_normalized_fields_before_20260615.json")

_JP_COLOR = {"赤": "Red", "青": "Blue", "緑": "Green", "黄": "Yellow",
             "黒": "Black", "紫": "Purple", "白": "White"}
_EN_COLOR_OK = {"Red", "Blue", "Green", "Yellow", "Black", "Purple", "White", "Colorless"}
# ★2026-08-23: 公式の進化段階の欄 (`<span class="type">`) から取り直したので、鍵を
#   公式の語彙に合わせた。実測 21,982枚に出る値は次の11種:
#     たね 9906 / (空) 5411 / 1進化 4750 / 2進化 1484 / V進化 276 /
#     レベルアップ 72 / BREAK進化 43 / 復元 14 / M進化 11 / 伝説 9 / V-UNION 6
#   旧鍵 'MEGA' は公式に存在せず、効果テキスト等の誤読 (98行中96行) だった → 'M進化' に。
#   ★残り (V進化/レベルアップ/BREAK進化/復元/伝説/V-UNION) は **意図的に空欄**。
#     eBay の Stage は FREE_TEXT で正解表が無く (2026-08-23 取得の 35 aspect で確認)、
#     英語表記をこちらで作ると推測になる。特に 'V進化' は VMAX / VSTAR / V-UNION の
#     どれかを区別できない。今も空欄なので、出さないことで失うものは無い。
_STAGE = {"たね": "Basic", "1進化": "Stage 1", "2進化": "Stage 2", "M進化": "Mega"}


def norm_color(raw):
    """色 raw → eBay Attribute/MTG:Color 語彙。複数色=Multi-Color。不明/無=空欄。"""
    if raw is None:
        return ""
    r = str(raw).strip()
    if not r or r in ("-", "無"):
        return ""              # 無色/非該当 = fail-closed 空欄
    if r.upper() == "ALL":
        return "Multi-Color"   # DB '全色'
    parts = [p.strip() for p in re.split(r"[/／]", r) if p.strip()]
    if len(parts) >= 2:
        return "Multi-Color"
    p = parts[0] if parts else ""
    if p in _JP_COLOR:
        return _JP_COLOR[p]
    t = p.title()              # BLUE→Blue / blue→Blue
    return t if t in _EN_COLOR_OK else ""   # 未知語 = fail-closed


def clean_num(raw):
    """数値文字列 clean。'15000 / (裏)20000' → 表'15000'。数字無→空欄。"""
    if raw is None:
        return ""
    head = re.split(r"[/／]", str(raw))[0]   # 表側のみ
    m = re.search(r"\d+", head)
    return m.group(0) if m else ""


def norm_stage(raw):
    """stage raw → eBay Stage 語彙。確証あるもののみ、不明は空欄(fail-closed)。"""
    if raw is None:
        return ""
    return _STAGE.get(str(raw).strip(), "")


# category → [(ebay_field, raw_field, normalizer), ...]
PLAN = {
    "one_piece_tcg": [("attack_power_ebay", "power", clean_num),
                      ("color_ebay", "color", norm_color)],
    "dragonball_scg": [("attack_power_ebay", "power", clean_num),
                       ("color_ebay", "color", norm_color)],
    "gundam_tcg": [("attack_power_ebay", "ap", clean_num),
                   ("defense_toughness_ebay", "hp", clean_num),
                   ("color_ebay", "color", norm_color)],
    "pokemon_tcg": [("hp_ebay", "hp", clean_num),
                    ("stage_ebay", "stage", norm_stage)],
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--apply" not in sys.argv
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    bak = {}
    stats = defaultdict(lambda: defaultdict(int))     # cat -> field -> set件数
    samples = defaultdict(list)
    now = datetime.now().isoformat(timespec="seconds")

    for cat, fields in PLAN.items():
        rows = conn.execute(
            "SELECT id, product_id, specs FROM products WHERE category=?", (cat,)
        ).fetchall()
        for r in rows:
            s = json.loads(r["specs"])
            changed = {}
            for ebay_f, raw_f, fn in fields:
                val = fn(s.get(raw_f))
                if val and s.get(ebay_f) != val:
                    changed[ebay_f] = (s.get(ebay_f), val)
                    s[ebay_f] = val
                    stats[cat][ebay_f] += 1
                    if len(samples[cat + ":" + ebay_f]) < 3:
                        samples[cat + ":" + ebay_f].append(
                            f"{r['product_id']}: {s.get(raw_f)!r}→{val!r}")
            if changed:
                bak[r["product_id"]] = {f: ov for f, (ov, nv) in changed.items()}
                if not dry:
                    conn.execute(
                        "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                        (json.dumps(s, ensure_ascii=False), now, r["id"]))

    print("=== 付与件数 (cat × field) ===")
    for cat in PLAN:
        for ebay_f, _, _ in PLAN[cat]:
            print(f"  {cat:16} {ebay_f:24} {stats[cat][ebay_f]:6} 件")
    print("\n=== サンプル ===")
    for k, v in samples.items():
        print(f"  {k}: {v}")

    if dry:
        print("\n[DRY-RUN] DB 未変更。投入は --apply。")
        conn.close()
        return

    BAK_PATH.parent.mkdir(parents=True, exist_ok=True)
    BAK_PATH.write_text(json.dumps(bak, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.commit()
    conn.close()
    print(f"\n✅ 完了。bak: {BAK_PATH} ({len(bak)} record touched)")


if __name__ == "__main__":
    main()
