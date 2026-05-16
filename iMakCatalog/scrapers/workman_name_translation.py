"""Workman 商品名 (name_jp) → 英訳 name_en バッチ翻訳.

設計 (2026-05-16):
  - Workman は商品名 ja のみ、eBay 出品時は en title 必要
  - Pokemon の同様 pattern (pokemon_name_translation.py) と同設計
  - Claude Sonnet 4.6 batch、prompt cache 利用

実行:
  python iMakCatalog/scrapers/workman_name_translation.py --all
  python iMakCatalog/scrapers/workman_name_translation.py --smoke 10
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, sys, time
from pathlib import Path

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # noqa

CATEGORY = "workman"
MODEL_ID = "claude-sonnet-4-6"
BATCH_SIZE = 50

# 商標 / Workman 固有用語 canonical (HQ 確定でなくても英訳の一貫性のため固定)
TRADEMARK_CANONICAL = {
    "エアセンサー":       "Air Sensor",
    "ウィンドコア":       "WindCore",
    "イージス":           "Aegis",
    "エックスシェルター": "X-Shelter",
    "XShelter":           "X-Shelter",
    "リペアテック":       "Repair Tech",
    "サノラック":         "SanoRack",
    "ゼロステージ":       "Zero Stage",
    "ペルチェ":           "Peltier",
    "ファンウエア":       "Fan Wear",
    "和紙衣":             "Washi-Eco",
    "ドリブン":           "Driven",
    "エニタイム":         "Anytime",
    "We Move":            "We Move",
    "コットンキャンバス": "Cotton Canvas",
}

SYSTEM = """You are translating Japanese Workman clothing item names to natural English for eBay listings.

CONTEXT: These are Japanese Workman outdoor/work clothing product names. The English name will be used in eBay Title (max ~80 chars).

RULES:
1. Use trademark canonical names exactly as provided (例: ウィンドコア → WindCore, イージス → Aegis, エックスシェルター → X-Shelter, ペルチェ → Peltier).
2. Preserve product type (ジャケット → Jacket, パンツ → Pants, ベスト → Vest, シャツ → Shirt, T-shirt, パーカー → Hoodie, スラックス → Slacks, ジョガーパンツ → Jogger Pants).
3. For material descriptors (ストレッチ → Stretch, 速乾 → Quick-Dry, 接触冷感 → Cooling, 撥水 → Water-Repellent, 防水 → Waterproof, 防風 → Windproof, 透湿 → Breathable, 蓄熱 → Heat-Retention, ペルチェ → Peltier-Cooling, ハイブリッド → Hybrid).
4. Use Title Case (capitalize major words).
5. Keep names concise — eBay buyers should immediately understand the item.
6. Use canonical English Workman product names where they exist (e.g., "WindCore Ice x Heater Peltier Vest Pro 3").
7. NEVER include trademark symbols (®, ™) in the output.
8. Half-width characters only (no full-width Roman/numbers).

OUTPUT: JSON only, no markdown.
Format: {"japanese_name_1": "english_name_1", ...}"""


def translate_via_api(names: list[str]) -> dict[str, str]:
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        for p in (Path("C:/dev/iMak_data/credentials/api_key.txt"),
                  Path("C:/dev/iMak/iMakTCG/API key.txt")):
            if p.exists():
                api_key = p.read_text(encoding="utf-8").strip()
                break
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    out: dict[str, str] = {}
    total = len(names)
    print(f"=== Claude API 翻訳: {total} 件 (batch={BATCH_SIZE}) ===")
    # canonical reference を prompt に
    canonical_ref = "\n".join(f"  {jp} → {en}" for jp, en in TRADEMARK_CANONICAL.items())
    for i in range(0, total, BATCH_SIZE):
        batch = names[i:i + BATCH_SIZE]
        prompt = (
            f"Translate these {len(batch)} Japanese Workman product names to English (eBay-ready).\n\n"
            f"TRADEMARK / TERM CANONICAL:\n{canonical_ref}\n\n"
            f"Names:\n" + "\n".join(f"  - {n}" for n in batch) +
            f"\n\nReturn JSON only: {{name_jp: name_en, ...}}"
        )
        try:
            r = client.messages.create(
                model=MODEL_ID, max_tokens=4000, system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = r.content[0].text.strip()
            m = re.search(r"\{[\s\S]*\}", txt)
            if m:
                txt = m.group(0)
            d = json.loads(txt)
            for k, v in d.items():
                if isinstance(v, str) and v.strip():
                    out[k] = v.strip()
            print(f"  [{i+len(batch):>4d}/{total}] batch ok: {len(d)} translated")
        except Exception as e:
            print(f"  [{i+len(batch):>4d}/{total}] ERR: {type(e).__name__}: {str(e)[:120]}")
        time.sleep(0.3)
    return out


def run(smoke: int = 0, dry_run: bool = False) -> None:
    conn = sqlite3.connect(str(api._DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""SELECT product_id, name, name_jp FROM products
                   WHERE category=? AND (name_en IS NULL OR name_en='')""",
                (CATEGORY,))
    rows = cur.fetchall()
    print(f"対象: {len(rows)} 件 (name_en 未投入)")
    if smoke:
        rows = rows[:smoke]
        print(f"smoke 制限: {smoke} 件")

    # distinct name_jp 抽出
    distinct_names = sorted({(r['name_jp'] or r['name']).strip() for r in rows})
    print(f"distinct: {len(distinct_names)}")

    # API 翻訳
    name_map = translate_via_api(distinct_names)

    # DB 更新
    if dry_run:
        print(f"[dry-run] {len(name_map)} 件取得、DB 更新スキップ")
    else:
        updated = 0
        for r in rows:
            jp = (r['name_jp'] or r['name']).strip()
            en = name_map.get(jp)
            if not en:
                continue
            cur.execute("""UPDATE products SET name_en=?, name_en_source='claude_api'
                           WHERE category=? AND product_id=?""",
                        (en, CATEGORY, r['product_id']))
            updated += 1
        conn.commit()
        print(f"DB backfill: {updated} 件")
    conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", type=int, default=0)
    p.add_argument("--all", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    run(smoke=args.smoke, dry_run=args.dry_run)
