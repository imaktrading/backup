#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pokemon name_en 自己整合監査 (read-only, 2026-06-07)。

Durant 型 (name_jp は同じなのに name_en が食い違う = pokeapi番号マッピング誤) を
**外部 Oracle 無し**で検出する。同一 name_jp グループ内で name_en が複数値に割れている
場合、多数決で「多数派=正の推定」「少数派=要確認(誤り疑い)」に分け、少数派を suspect 列挙。

設計意図 (Gemini提言②/差し戻しB-2 と整合):
  - Durant 事故の原因が pokeapi番号 → その pokeapi を単独 Oracle にして検証しても循環する。
  - カタログ内部の **多数決** は外部参照ゼロで「番号誤で1〜数件だけ別Pokemonに化けた」型を高精度に捕捉。
  - ※多数決の限界: ある name_jp の **全行が同じ誤り**(系統的誤り)は捕捉不可
    → それは外部の正(複数源 TCGPlayer/Bulbapedia/pokeapi-species 多数決)が要る別タスク(後段)。

read-only。修正はしない (Catalog領域)。--sheet でスプシにも書く。
"""
import collections
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = r"C:\dev\iMak_data\catalog\products.sqlite"
TARGET_SHEET_ID = "1U0P3gLMYzQMdxIrP2OE31XSGQOStdK0QPIfH2uC88vE"


def audit(con):
    rows = con.execute(
        """SELECT name_jp, name_en, name_en_source, product_id, set_name
           FROM products
           WHERE source LIKE 'pokemon%'
             AND name_jp IS NOT NULL AND name_jp<>''
             AND name_en IS NOT NULL AND name_en<>''"""
    ).fetchall()
    # name_jp -> {name_en -> [ (product_id, set_name, source), ... ]}
    groups = collections.defaultdict(lambda: collections.defaultdict(list))
    for jp, en, src, pid, setn in rows:
        groups[jp][en].append((pid, setn, src or "(空)"))

    suspects = []  # 1 row per suspect (minority) member
    conflict_groups = 0
    for jp, by_en in groups.items():
        if len(by_en) < 2:
            continue
        conflict_groups += 1
        # 多数派 = 件数最大の name_en
        ranked = sorted(by_en.items(), key=lambda kv: -len(kv[1]))
        majority_en, majority_members = ranked[0]
        maj_n = len(majority_members)
        total = sum(len(m) for _, m in ranked)
        for en, members in ranked[1:]:
            min_n = len(members)
            # 信頼度: 多数派が圧倒的なほど少数派は誤りの可能性大
            ratio = maj_n / total
            conf = "高" if (maj_n >= 5 and min_n <= 2) else ("中" if maj_n > min_n else "低(拮抗)")
            for pid, setn, src in members:
                suspects.append({
                    "name_jp": jp, "suspect_en": en, "majority_en": majority_en,
                    "suspect_n": min_n, "majority_n": maj_n, "total": total,
                    "ratio": round(ratio, 2), "conf": conf,
                    "product_id": pid, "set_name": setn or "", "src": src,
                })
    # 信頼度高い順・グループ規模大きい順
    conf_order = {"高": 0, "中": 1, "低(拮抗)": 2}
    suspects.sort(key=lambda s: (conf_order[s["conf"]], -s["majority_n"], s["name_jp"]))
    return conflict_groups, suspects


def main():
    to_sheet = "--sheet" in sys.argv
    con = sqlite3.connect(DB)
    conflict_groups, suspects = audit(con)

    n_high = sum(1 for s in suspects if s["conf"] == "高")
    n_mid = sum(1 for s in suspects if s["conf"] == "中")
    n_low = sum(1 for s in suspects if s["conf"].startswith("低"))
    print(f"name_en 自己整合監査 (pokemon, read-only)")
    print(f"  競合グループ(name_jp): {conflict_groups}")
    print(f"  suspect行(少数派): {len(suspects)}  [高{n_high} / 中{n_mid} / 低拮抗{n_low}]")
    print(f"\n  --- 高信頼 suspect (上位30) ---")
    for s in suspects[:30]:
        print(f"  [{s['conf']}] {s['name_jp']:12} 誤?{s['suspect_en']:18} "
              f"(正?{s['majority_en']:18} {s['majority_n']}/{s['total']}) "
              f"{s['product_id']:10} src={s['src']}")

    header = ["信頼度", "name_jp", "誤り疑い name_en", "正推定 name_en(多数派)",
              "少数派件数", "多数派件数", "総数", "多数派比",
              "product_id", "set_name", "name_en_source"]
    detail_rows = [header] + [[
        s["conf"], s["name_jp"], s["suspect_en"], s["majority_en"],
        s["suspect_n"], s["majority_n"], s["total"], s["ratio"],
        s["product_id"], s["set_name"], s["src"],
    ] for s in suspects]

    summary_rows = [
        ["Pokemon name_en 自己整合監査 — read-only / 2026-06-07", "", ""],
        ["方式", "同一 name_jp 内で name_en 割れ → 多数決(多数派=正推定/少数派=要確認)", ""],
        ["外部Oracle", "不使用(カタログ内部多数決のみ)。系統的全行誤りは別途 複数源Oracle が必要", ""],
        ["", "", ""],
        ["指標", "値", ""],
        ["競合グループ(name_jp)", conflict_groups, ""],
        ["suspect行(少数派合計)", len(suspects), ""],
        ["  うち 信頼度=高", n_high, "多数派>=5 かつ 少数派<=2"],
        ["  うち 信頼度=中", n_mid, "多数派>少数派"],
        ["  うち 信頼度=低(拮抗)", n_low, "多数派<=少数派 = 人判断必須"],
    ]

    if to_sheet:
        sys.path.insert(0, r"c:\dev\iMak\iMakHQ\tools")
        from sheet_io import write_rows_to_tab
        write_rows_to_tab("nameEn監査_サマリー", summary_rows, sheet_id=TARGET_SHEET_ID)
        write_rows_to_tab("nameEn監査_要確認", detail_rows, sheet_id=TARGET_SHEET_ID)
        print(f"\n✅ スプシ書込: nameEn監査_サマリー / nameEn監査_要確認")
        print(f"   https://docs.google.com/spreadsheets/d/{TARGET_SHEET_ID}/edit")


if __name__ == "__main__":
    main()
