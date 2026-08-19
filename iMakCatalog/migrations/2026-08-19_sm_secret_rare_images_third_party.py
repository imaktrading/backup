"""SM 世代 secret rare 5件に第三者 source の画像を入れる (社内目視限定).

依頼/GO: requests/2026-08-19_pdca_catalog_queue_tcg_response_hq_go.md §3 [IMPLEMENT-GO]
  「対象5件。社内目視限定 / 出品の PicURL には使わない / 値は取らない・画像だけ /
    source に第三者印を残す」

なぜ第三者から取るのか (CLAUDE.md「画像の第三者 source 例外規約」の条件充足):
  1. 公式に無いことを実測済:
     - scrapers/pokemon_secret_rare_rescue.py --targets SM12-112 --window 250
       → 既知 cardID 範囲 [37065..37390] ±250 に一致なし (2026-08-19)
     - SM12 の公式 cardID は 096→037378 ... 108→037390 と連番で、109 以降は
       別セット (037394 = XY ヒトデマン 004/048) に飛ぶ。
       = 公式 DB の SM12 ブロックは 108 で終わっており HR 帯 (109-114) が存在しない
     - 同型: SM11 / SM12a / SM9a の HR/UR。S 世代の HR は 62/66 が公式画像を持つので
       系統的な穴ではなく SM 世代固有
  2. 画像内容が catalog の name / 収録番号 / rarity / セットと全項目一致することを
     取得元ページで確認済 (下表の note 参照、2026-08-19 実取得)
  3. 用途は社内目視限定 (eBay 出品画像は PSA スラブ実写)
  4. source に第三者印を残す (`+pokeca_images_confirmed_20260819`)

値 (name/rarity/specs) は一切触らない。images と source と目視用 note だけ。

実行:
  python migrations/2026-08-19_sm_secret_rare_images_third_party.py           # dry-run (URL 検証まで)
  python migrations/2026-08-19_sm_secret_rare_images_third_party.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = Path(api._DB_PATH)
NOW = datetime.now().isoformat()
MARK = "pokeca_images_confirmed_20260819"

NOTE = ("公式 (pokemon-card.com) に当該カードが存在しないため第三者 source から画像のみ取得 "
        "(CLAUDE.md「画像の第三者 source 例外規約」/ HQ GO 2026-08-19)。"
        "社内目視照合専用。eBay 出品の PicURL に使ってはいけない。")

# (product_id, 期待 name, 期待 card_number_text, 期待 rarity, 画像URL, 取得元ページ)
TARGETS = [
    ("SM12-112", "アルセウス＆ディアルガ＆パルキアGX", "112/095", "HR",
     "https://www.pokeca.net/data/pokeca/product/sm12b/112.jpg",
     "https://www.pokeca.net/product/9575"),
    ("SM11-112", "カイリューGX", "112/094", "HR",
     "https://www.pokeca.net/data/pokeca/product/sm11/112.jpg",
     "https://www.pokeca.net/product/9357"),
    ("SM12a-214", "ジラーチGX", "214/173", "HR",
     "https://www.pokeca.net/data/pokeca/product/sm12a2/214.jpg",
     "https://www.pokeca.net/product/9903"),
    ("SM12a-224", "ルカリオ&メルメタルGX", "224/173", "UR",
     "https://www.pokeca.net/data/pokeca/product/20191031_e16694.jpg",
     "https://www.pokeca.net/product/9913"),
    ("SM9a-067", "サーナイト&ニンフィアGX", "067/055", "HR",
     "https://www.pokeca.net/data/pokeca/product/sm9n/067.jpg",
     "https://www.pokeca.net/product/8705"),
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) iMakCatalog/1.0"}


def check_url(url: str) -> tuple[bool, str]:
    """画像 URL が実在し image/* を返すか (fail-closed: 取れなければ入れない)."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as res:
            ctype = res.headers.get("Content-Type", "")
            size = len(res.read(4096))
            ok = res.status == 200 and ctype.startswith("image/") and size > 0
            return ok, f"{res.status} {ctype}"
    except Exception as e:  # noqa: BLE001
        return False, f"ERROR {e}"


def norm(s: str) -> str:
    """全角/半角 & の揺れだけ吸収 (catalog と取得元で表記が割れるため)."""
    return (s or "").replace("＆", "&").replace(" ", "").strip()


def process(commit: bool) -> int:
    print(f"=== SM secret rare 画像 (第三者 source) ({'APPLY' if commit else 'DRY-RUN'}) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    updates = []

    for pid, exp_name, exp_num, exp_rar, img, src_page in TARGETS:
        r = db.execute(
            "SELECT id, product_id, name, source, images, specs FROM products "
            "WHERE category = 'pokemon_tcg' AND product_id = ?", (pid,)
        ).fetchone()
        if r is None:
            print(f"  ✗ {pid:<12} DB に居ない → skip (勝手に新規追加しない)")
            continue

        s = json.loads(r["specs"] or "{}")
        cur_imgs = json.loads(r["images"] or "[]")

        # --- fail-closed: catalog 側の値と期待値が1つでも違えば入れない ---
        checks = {
            "name": (norm(r["name"]), norm(exp_name)),
            "card_number_text": (norm(s.get("card_number_text")), norm(exp_num)),
            "rarity": (norm(s.get("rarity")), norm(exp_rar)),
        }
        bad = {k: v for k, v in checks.items() if v[0] != v[1]}
        if bad:
            print(f"  ✗ {pid:<12} catalog 値と不一致 → skip {bad}")
            continue
        if cur_imgs:
            print(f"  - {pid:<12} 既に画像あり ({len(cur_imgs)}枚) → skip")
            continue

        ok, detail = check_url(img)
        print(f"  {'✓' if ok else '✗'} {pid:<12} {detail:<28} {img}")
        if not ok:
            continue

        s["images_source_note"] = NOTE
        s["images_source_page"] = src_page
        s["images_internal_view_only"] = True
        src = (r["source"] or "") + ("+" if r["source"] else "") + MARK
        updates.append((json.dumps([img], ensure_ascii=False),
                        json.dumps(s, ensure_ascii=False), src, NOW, r["id"]))

    print(f"\n対象 {len(updates)} / {len(TARGETS)} 行")
    if commit and updates:
        db.executemany(
            "UPDATE products SET images = ?, specs = ?, source = ?, updated_at = ? WHERE id = ?",
            updates)
        db.commit()
        print("✅ 適用")
    elif not commit:
        print("(dry-run — --commit で適用)")
    db.close()
    return len(updates)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
