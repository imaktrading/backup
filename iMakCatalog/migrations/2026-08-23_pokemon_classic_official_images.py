#!/usr/bin/env python3
"""ポケモンカードゲーム Classic (CLF/CLL/CLK) に公式特設の画像を入れる.

2026-08-23。回答書
`requests/2026-08-23_hq_go_cll_images_and_clone_hardening_response.md` §1 [IMPLEMENT-GO]。
発端は `PSA10-156684617` = `CLL-002 リザード` が画像なしで出品できなかったこと。

## 判定 (1丁目1番地): ①カタログのデータが誤り (画像の欠落) → catalog 側で直す

②は正しい。出品くんは product_id 完全一致でしか引かない。
CL* 96行は全行 images が空で、公式の取り込み経路 (resultAPI.php) に Classic が無い。

## 出所と、絵柄の確定のしかた (2026-08-23 に実取得)

  https://www.pokemon-card.com/ex/classic/index.html   200 / 35,886 bytes
  → assets/images/deck-card-{1..3}-{1..10}.png  = 30枚 (すべて 200)

alt が空なので **画像を落として券面の日本語カード名を目視して**割り当てた。
30枚のうち3枚は基本エネルギー (草/炎/水) で catalog に対応行が無い → 27行に入る。
残り 69行は公式が画像を出していないので **空のまま**が正しい (目視不能 = 出品しない)。

デッキ番号の対応も同ページの見出しで確認:
  deck1 = フシギバナ＆ルギアexデッキ = CLF
  deck2 = リザードン＆ホウオウexデッキ = CLL
  deck3 = カメックス＆スイクンexデッキ = CLK

★このページには「※このページの商品・カードの画像は、開発中のものです。」の注記がある。
  公式が出している唯一の券面画像なので採るが、**目視照合用**であって出品写真ではない。

## fail-closed

- 走らせるたびに公式ページを取り直し、**割り当てた slot が今もページに在ること**と
  見出しがデッキと合っていることを確かめる。合わなければその行は書かない。
- 画像URLは HEAD 200 を確かめてから書く。
- 既に images が入っている行には触らない。

実行:
  python migrations/2026-08-23_pokemon_classic_official_images.py           # dry-run
  python migrations/2026-08-23_pokemon_classic_official_images.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402
import clone_rows  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
CAT = "pokemon_tcg"
PAGE = "https://www.pokemon-card.com/ex/classic/index.html"
IMG_BASE = "https://www.pokemon-card.com/ex/classic/assets/images/"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
SRC_NOTE = "pokemon_official_classic_page_20260823"

# deck 番号 -> (catalog の set_code, 見出しに必ず入っている語)
DECKS = {1: ("CLF", "フシギバナ"), 2: ("CLL", "リザードン"), 3: ("CLK", "カメックス")}

# slot -> (product_id, 券面に印字されていた名前)。None = catalog に対応行が無い基本エネルギー。
# ★すべて画像を目視して確定 (2026-08-23)。推測で置いた行は無い。
MAPPING: dict[str, tuple[str | None, str]] = {
    "deck-card-1-1":  ("CLF-003", "フシギバナ"),
    "deck-card-1-2":  ("CLF-017", "ルギアex"),
    "deck-card-1-3":  ("CLF-015", "ラッキー"),
    "deck-card-1-4":  ("CLF-026", "オーキドはかせ"),
    "deck-card-1-5":  ("CLF-025", "太陽のタネ"),
    "deck-card-1-6":  ("CLF-010", "イワーク"),
    "deck-card-1-7":  ("CLF-028", "ポケモンナース"),
    "deck-card-1-8":  (None,      "基本草エネルギー (catalog に行が無い)"),
    "deck-card-1-9":  ("CLF-001", "フシギダネ"),
    "deck-card-1-10": ("CLF-002", "フシギソウ"),
    "deck-card-2-1":  ("CLL-003", "リザードン"),
    "deck-card-2-2":  ("CLL-007", "ホウオウex"),
    "deck-card-2-3":  ("CLL-008", "ピカチュウ"),
    "deck-card-2-4":  ("CLL-021", "パソコン通信"),
    "deck-card-2-5":  ("CLL-026", "灼熱のもくたん"),
    "deck-card-2-6":  ("CLL-013", "ピッピ"),
    "deck-card-2-7":  ("CLL-030", "マサキ"),
    "deck-card-2-8":  (None,      "基本炎エネルギー (catalog に行が無い)"),
    "deck-card-2-9":  ("CLL-001", "ヒトカゲ"),
    "deck-card-2-10": ("CLL-002", "リザード"),      # ← PSA10-156684617 の依頼そのもの
    "deck-card-3-1":  ("CLK-003", "カメックス"),
    "deck-card-3-2":  ("CLK-010", "スイクンex"),
    "deck-card-3-3":  ("CLK-014", "ミュウツー"),
    "deck-card-3-4":  ("CLK-025", "大海のしずく"),
    "deck-card-3-5":  ("CLK-031", "ロケット団の幹部"),
    "deck-card-3-6":  ("CLK-015", "マチスのコラッタ"),
    "deck-card-3-7":  ("CLK-021", "バトルサーチャー"),
    "deck-card-3-8":  (None,      "基本水エネルギー (catalog に行が無い)"),
    "deck-card-3-9":  ("CLK-001", "ゼニガメ"),
    "deck-card-3-10": ("CLK-002", "カメール"),
}


def image_url(slot: str) -> str:
    return IMG_BASE + slot + ".png"


def fetch(url: str) -> str:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "replace")


def head_200(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers=UA)
        return urllib.request.urlopen(req, timeout=20).status == 200
    except Exception:
        return False


def page_check(html: str) -> tuple[set[str], set[int]]:
    """ページに在る slot 名と、見出しがデッキと合っている deck 番号を返す."""
    slots = set(re.findall(r"(deck-card-\d+-\d+)\.png", html))
    ok_decks = set()
    heads = re.findall(r'class="box-deck-head ff-m">(.*?)</h3>', html, re.S)
    for i, raw in enumerate(heads, start=1):
        text = re.sub(r"<[^>]+>", "", raw)
        want = DECKS.get(i)
        if want and want[1] in text:
            ok_decks.add(i)
        else:
            print(f"   ! deck{i} の見出しが想定と違う: {text.strip()!r}")
    return slots, ok_decks


def process(commit: bool) -> int:
    print(f"=== Classic 画像 backfill ({'APPLY' if commit else 'DRY-RUN'}) ===")
    html = fetch(PAGE)
    print(f"公式ページ取得: {PAGE} ({len(html)} chars)")
    slots, ok_decks = page_check(html)
    print(f"ページ内の slot {len(slots)} 個 / 見出し一致 deck {sorted(ok_decks)}\n")

    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row
    updates, skipped = [], []

    for slot, (pid, label) in MAPPING.items():
        deck = int(slot.split("-")[2])
        if pid is None:
            skipped.append((slot, f"{label}"))
            continue
        if deck not in ok_decks:
            skipped.append((slot, f"{pid}: deck{deck} の見出しが合わない → 書かない")); continue
        if slot not in slots:
            skipped.append((slot, f"{pid}: 公式ページに slot が無い → 書かない")); continue
        r = db.execute("SELECT id, product_id, name_jp, images, specs, source FROM products "
                       "WHERE category=? AND product_id=?", (CAT, pid)).fetchone()
        if r is None:
            skipped.append((slot, f"{pid}: catalog に行が無い")); continue
        if clone_rows.is_clone(r["specs"], r["source"]):
            skipped.append((slot, f"{pid}: clone 行 → 画像補完の対象外")); continue
        if r["images"] and r["images"] not in ("[]", ""):
            skipped.append((slot, f"{pid}: 既に images が在る → 触らない")); continue
        if (r["name_jp"] or "") != label:
            skipped.append((slot, f"{pid}: 券面 {label!r} と catalog {r['name_jp']!r} が違う "
                                  f"→ 書かない (fail-closed)")); continue
        url = image_url(slot)
        if not head_200(url):
            skipped.append((slot, f"{pid}: {url} が 200 でない")); continue
        s = json.loads(r["specs"] or "{}")
        s["images_source"] = SRC_NOTE
        print(f"  + {pid:<9} {label:<12} <- {url}")
        updates.append((json.dumps([url], ensure_ascii=False),
                        json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print(f"\n入れる {len(updates)} 行 / 入れない {len(skipped)} 件")
    for slot, why in skipped:
        print(f"  - {slot:<16} {why}")

    empty_left = db.execute(
        "SELECT COUNT(*) FROM products WHERE category=? AND product_id LIKE 'CL%' "
        "AND (images IS NULL OR images IN ('','[]'))", (CAT,)).fetchone()[0]
    print(f"\n公式に画像が無く空のままになる CL* 行: {empty_left - len(updates)} 行 "
          f"(目視不能 = 出品しない が正しい扱い)")

    if commit and updates:
        db.executemany("UPDATE products SET images=?, specs=?, updated_at=? WHERE id=?", updates)
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
