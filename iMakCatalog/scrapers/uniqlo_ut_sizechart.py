# -*- coding: utf-8 -*-
"""UT の実寸表 (仕上がり寸) を公式から取って catalog に焼く (2026-09-09 新設).

## なぜ要るか

**実寸表は廃盤になると復元手段が無い。** 画像URLは CDN に生き残るが、寸法はどこにも残らない。
出品くん (skill `apparel-tee-listing`) は「サイズ実寸は推測せず全サイズ公式取得する」と
決めてあり、毎回 `iMakMercari/uniqlo_size_fetch.py` で公式を叩いている。
**現役のうちに catalog に持たないと、廃盤の瞬間に出せなくなる。**

## 取り方 (Selenium しかない)

公式 API に寸法は無く (`sizeInformation` は空)、`.../size/<l1id>_size.html` は
**bot に 403** を返す (2026-09-09 実測)。PDP のモーダルを開くしかない:

    サイズを確認する -> 仕上がり寸 -> inch

★列の並びは **公式そのまま**。並べ替えない (skill の指示):
    UNIQLO = 身丈 / 肩幅 / 身幅 / 裄丈 = Length / Shoulder / Chest / Sleeve

## 途中保存 (CLAUDE.md「長く走るものは必ず途中保存」)

  - **1件ごとに commit** (1件15秒かかる。落ちた時に取り直すのが高い)
  - 再実行は **DB を見て** 済み (`specs.size_chart` あり) を飛ばす。飛ばした件数を出す
  - モーダルの生テキストは `_raw/uniqlo_ut/` に残す (parse をやり直せるように)
  - Chrome は 40件ごとに開き直す (メモリと bot 判定対策)

実行:
    python scrapers/uniqlo_ut_sizechart.py --limit 3     # 動作確認
    python scrapers/uniqlo_ut_sizechart.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_CATALOG_ROOT / "scrapers"))
import _raw_store  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
PDP = "https://www.uniqlo.com/jp/ja/products/{pid}/00"
KID_GENDERS = {"KIDS", "BABY"}
RESTART_EVERY = 40
SIZE_LABELS = ("XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL",
               "SS", "MM", "LL", "3L", "4L")


def _chrome_major():
    """★version は固定しない (グローバル CLAUDE.md 2026-06-13)."""
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            k = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
            v, _ = winreg.QueryValueEx(k, "version")
            return int(v.split(".")[0])
        except Exception:
            pass
    return None


def new_driver():
    import undetected_chromedriver as uc
    o = uc.ChromeOptions()
    o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--window-size=1500,2800")
    o.add_argument("--lang=ja-JP")
    return uc.Chrome(options=o, version_main=_chrome_major())


def _click(d, txt, exact=False):
    xp = (f"//*[normalize-space(text())='{txt}']" if exact
          else f"//*[contains(text(),'{txt}')]")
    for e in d.find_elements("xpath", xp):
        try:
            d.execute_script('arguments[0].scrollIntoView({block:"center"});', e)
            try:
                e.click()
            except Exception:
                d.execute_script("arguments[0].click();", e)
            return True
        except Exception:
            pass
    return False


# 値の書き方: cm は `69` / `44.5`、inch は `27 1/4` / `19` (公式が分数で出す)
_NUM = re.compile(r"\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+")


def parse_table(body: str) -> list[dict] | None:
    """モーダルの本文 -> [{size, length, shoulder, chest, sleeve}].

    ★ラベルは公式の並び (身丈 / 肩幅 / 身幅 / 裄丈) をそのまま採る。並べ替えない
      (skill `apparel-tee-listing`: UNIQLO = Length / Shoulder / Chest / Sleeve)。
    ★4つ揃わない行は捨てる (欠けたまま入れない = fail-closed)。
    """
    i = body.find("サイズ 身丈")
    if i < 0:
        return None
    seg = body[i:i + 2000]
    lines = [x.strip() for x in seg.split("\n") if x.strip()]
    rows, j = [], 0
    while j < len(lines):
        if lines[j].upper() in SIZE_LABELS:
            nums, k = [], j + 1
            while k < len(lines) and len(nums) < 4:
                if lines[k].upper() in SIZE_LABELS:
                    break
                if _NUM.fullmatch(lines[k]):
                    nums.append(lines[k])
                k += 1
            if len(nums) == 4:
                rows.append({"size": lines[j], "length": nums[0], "shoulder": nums[1],
                             "chest": nums[2], "sleeve": nums[3]})
            j = k
        else:
            j += 1
    return rows or None


def fetch_chart(d, pid: str) -> tuple[list[dict] | None, list[dict] | None, str]:
    """(cm 表, inch 表, 生テキスト)。

    ★**cm と inch の両方**を残す。cm が公式の生値 (小数)、inch は出品がそのまま使う形
      (`27 1/4` のような分数で出る)。片方だけにすると、もう片方が要った時に取り直しになる
      — 廃盤後は取り直せない。
    """
    d.get(PDP.format(pid=pid))
    time.sleep(5)
    _click(d, "サイズを確認")
    time.sleep(4)
    _click(d, "仕上がり寸", exact=True)
    time.sleep(3)
    body_cm = d.find_element("tag name", "body").text
    _click(d, "inch", exact=True)
    time.sleep(3)
    body_in = d.find_element("tag name", "body").text
    return parse_table(body_cm), parse_table(body_in), body_cm + "\n===INCH===\n" + body_in


def targets(db, include_kids: bool) -> list[sqlite3.Row]:
    rows = db.execute("SELECT id, product_id, name, specs FROM products WHERE category=?",
                      (CATEGORY,)).fetchall()
    out, done, kids, gone = [], 0, 0, 0
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        if not include_kids and str(s.get("gender") or "").upper() in KID_GENDERS:
            kids += 1
            continue
        if s.get("size_chart"):
            done += 1
            continue
        if s.get("official_gone_at") or not s.get("enriched_at"):
            # 廃盤 = もう取れない / まだ生死を確かめていない行は先に uniqlo_ut_enrich.py
            # (1件15秒の Selenium を、消えている商品に使わない)
            gone += 1
            continue
        out.append(r)
    print(f"  取得済み {done}行 は飛ばす / キッズ・ベビー {kids}行 は対象外 / "
          f"廃盤・生死未確認 {gone}行 は対象外")
    return out


def run(commit: bool, include_kids: bool, limit: int | None) -> None:
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = targets(db, include_kids)
    if limit:
        rows = rows[:limit]
    print(f"=== UT 実寸表 ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(rows)}行 ===")
    if not rows:
        return

    now = datetime.now().isoformat(timespec="seconds")
    d, stat, ok = None, Counter(), 0
    try:
        for i, r in enumerate(rows, 1):
            if d is None or (i - 1) % RESTART_EVERY == 0:
                if d is not None:
                    try:
                        d.quit()
                    except Exception:
                        pass
                d = new_driver()
            pid = r["product_id"]
            try:
                cm, inch, body = fetch_chart(d, pid)
            except Exception as e:
                stat[type(e).__name__] += 1
                continue
            if not cm and not inch:
                stat["表が開かなかった"] += 1
                continue
            _raw_store.save(CATEGORY, f"size_{pid}", body, PDP.format(pid=pid), ext="txt")
            stat["取れた"] += 1
            if not inch:
                stat["inch が取れず cm のみ"] += 1
            if commit:
                s = json.loads(r["specs"] or "{}")
                s["size_chart"] = cm or inch
                s["size_chart_unit"] = "cm" if cm else "inch"
                if inch:
                    s["size_chart_inch"] = inch
                s["size_chart_at"] = now
                db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                           (json.dumps(s, ensure_ascii=False), now, r["id"]))
                db.commit()                  # ★1件ごとに保存 (1件15秒。取り直しが高い)
                ok += 1
            if i % 10 == 0:
                print(f"    ... {i}/{len(rows)} (取れた {stat['取れた']})", flush=True)
    finally:
        if d is not None:
            try:
                d.quit()
            except Exception:
                pass
        db.close()
    print("")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {ok}行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--include-kids", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    run(a.commit, a.include_kids, a.limit)


if __name__ == "__main__":
    main()
