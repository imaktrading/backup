"""DON カード psa_subject_hint 投入 (= specs JSON 拡張) + lookup_don() 実装根拠.

依頼: 2026-05-27_don_card_psa_subject_lookup.md

設計判断:
- products schema には psa_subject_hint 列 追加せず、 specs JSON に格納 (= 既存 pattern)
- hint = PSA subject に substring 一致する想定 keyword list
- 例: DON-OP15-002 hint = ['OP-15', 'ALTERNATE ART', 'GOLD']
- 例: DON-KUMAMON-001 hint = ['KUMAMON', 'LUFFY']
- 例: DON-STORAGE-001 hint = ['STORAGE BOX', 'RED']

hint quality:
- 確定的な variant 名 (= Kumamon character / Storage color) は Vision OCR 観察ベース
- それ以外は set_code + variant index で一般化 (= 後日 PSA cert 実機マッチで精度上げ)

fail-closed:
- lookup_don() で subject に hint keyword 全件マッチしないなら None 返却
- 出品くん は None 受けたら handle (= AI 列空欄 or 手動補完)
"""
import sqlite3
import sys
import json
import re
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"
NOW = datetime.now().isoformat()


# === source_note (= 既存 specs.source_note) → variant keywords 抽出 ===
def derive_hint_keywords(set_code: str, position_in_set: int, source_note: str) -> list[str]:
    """set_code + position + 既存 source_note から psa_subject_hint keyword list 生成."""
    kws: list[str] = []

    # 1) set_code → PSA brand match keyword
    #    例: OP15 → 'OP-15', PRB01 → 'PRB-01' (PSA brand 内表記に合わせ hyphen 入り)
    if re.match(r"^OP\d+$", set_code):
        kws.append(f"OP-{set_code[2:]}")
    elif re.match(r"^EB\d+$", set_code):
        kws.append(f"EB-{set_code[2:]}")
    elif re.match(r"^PRB\d+$", set_code):
        kws.append(f"PRB-{set_code[3:]}")
    elif set_code == "ST10-13":
        kws.extend(["ST-10", "ST-13"])
    elif set_code == "OP-DAY-24":
        kws.append("ONE PIECE DAY 24")
    elif set_code == "OP-DAY-25":
        kws.append("ONE PIECE DAY 25")
    else:
        kws.append(set_code)  # 'STORAGE', 'EVENT', 'KUMAMON', etc.

    # 2) source_note 内の固有情報抽出
    # 2a) Kumamon character 名 = '(NICO ROBIN)' 等 括弧内英大文字
    m = re.search(r"\(([A-Z][A-Z &]+(?:[A-Z]+)?)\)", source_note)
    if m:
        kws.append(m.group(1).strip())

    # 2b) Storage color = '(= 赤)' / '(= 黄)' 等
    color_map = {
        "赤": "RED", "緑": "GREEN", "橙": "ORANGE", "黄": "YELLOW",
        "青": "BLUE", "紫": "PURPLE", "黒": "BLACK", "金": "GOLD",
        "teal": "TEAL",
    }
    for jp, en in color_map.items():
        if jp in source_note:
            kws.append(en)

    # 2c) 'variant' marker (= 投入時 set 内 2nd 以降の variant)
    if "variant" in source_note.lower() or position_in_set > 1:
        # OP15 等の booster set で position=2 は alt art variant 想定
        if re.match(r"^(OP|EB)\d+$", set_code) and position_in_set >= 2:
            kws.extend(["ALTERNATE ART", "GOLD"])

    # 2d) PRB 系は position 番号自体が KEY (= 89/90 variants の個別 PSA cert で区別)
    if set_code in ("PRB01", "PRB02"):
        kws.append(f"#{position_in_set:03d}")

    return kws


def main():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    rows = cur.execute(
        "SELECT id, product_id, specs FROM products "
        "WHERE category='one_piece_tcg' AND product_id LIKE 'DON-%' "
        "ORDER BY product_id"
    ).fetchall()

    print(f"対象 DON entries: {len(rows)}")

    updated = 0
    for r in rows:
        try:
            specs = json.loads(r["specs"])
        except Exception:
            specs = {}
        set_code = specs.get("set_code", "")
        position_in_set = specs.get("global_seq", 0)  # = set 内連番 ≠ global_seq だが代替
        source_note = specs.get("source_note", "")

        # set 内 position 推定: product_id の末尾 -NNN
        m = re.search(r"-(\d+)$", r["product_id"])
        position_in_set_actual = int(m.group(1)) if m else 1

        hint_kws = derive_hint_keywords(set_code, position_in_set_actual, source_note)
        specs["psa_subject_hint"] = hint_kws
        specs["catalog_internal_key_note"] = (
            "公式 card_number 不在; Catalog 内部 dedup KEY; "
            "eBay 'C:Card Number' 列には送信せず、 AI 列 (= dedup index) で利用"
        )

        cur.execute(
            "UPDATE products SET specs=?, updated_at=? WHERE id=?",
            (json.dumps(specs, ensure_ascii=False), NOW, r["id"]),
        )
        updated += 1

    db.commit()
    db.close()

    print(f"  UPDATE: {updated}")

    # sample 確認
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    print("\n=== sample hint 5 件 ===")
    for r in db.execute(
        "SELECT product_id, specs FROM products WHERE category='one_piece_tcg' AND "
        "product_id IN ('DON-OP15-001','DON-OP15-002','DON-KUMAMON-001','DON-KUMAMON-005','DON-STORAGE-001','DON-PRB01-042')"
    ).fetchall():
        specs = json.loads(r["specs"])
        print(f"  {r['product_id']:20s} hint={specs.get('psa_subject_hint')}")
    db.close()


if __name__ == "__main__":
    main()
