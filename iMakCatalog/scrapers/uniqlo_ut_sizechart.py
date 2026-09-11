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
import gzip
import json
import re
import sqlite3
import sys
import time
import zlib
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

# ブランドで違うのは **ホストと category** だけ。中身 (モーダルの操作・見出しの読み方) は同じ。
#   ★列の並びは UNIQLO と GU で違うが、`_columns` が見出しから学ぶので分岐は要らない。
BRANDS = {
    "uniqlo": ("uniqlo_ut", "https://www.uniqlo.com/jp/ja/products/{pid}/00"),
    "gu": ("gu", "https://www.gu-global.com/jp/ja/products/{pid}/00"),
}
CATEGORY = "uniqlo_ut"
PDP = "https://www.uniqlo.com/jp/ja/products/{pid}/00"
KID_GENDERS = {"KIDS", "BABY"}
# ★同じブラウザで開き続けるとメモリが溜まる (2026-09-11 実測: 13件で 2GB)。
#   開き直しは1回15秒ほどなので、10件ごとでも遅くならない
RESTART_EVERY = 10
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
    # ★uc の `__del__` が終了処理でこけ、Windows で `OSError: [WinError 6]` を
    #   再帰的に投げて **走行ごと落ちる** (2026-09-09 実測: 836/1114 で死亡)。
    #   後始末は自分で `quit()` しているので、GC 側の後始末は黙らせる。
    uc.Chrome.__del__ = lambda self: None
    o = uc.ChromeOptions()
    o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--window-size=1500,2800")
    o.add_argument("--lang=ja-JP")
    # ★画像は読まない。実寸表は文字で、商品ページの画像が重い
    #   (2026-09-11 実測: 開いた直後で 1本 1.6〜2.3GB)
    o.add_argument("--blink-settings=imagesEnabled=false")
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


# 公式の見出し語 -> こちらのキー
_COL = {"身丈": "length", "肩幅": "shoulder", "身幅": "chest", "裄丈": "sleeve",
        "袖丈": "sleeve"}


def _columns(seg: str) -> list[str] | None:
    """見出しを読んで **列の並びを公式から学ぶ**。

    ★並びをコードに固定しない。UNIQLO は 身丈/肩幅/身幅/裄丈 だが、
      **GU は 身丈/裄丈/肩幅/身幅** で順番が違う (skill `apparel-tee-listing`)。
      固定すると列が1本ずれ、肩幅の欄に裄丈が入る
      (graniph で実際に起きた「前身丈/身丈 の部分一致で1本ずれた」事故と同じ形)。

    ★**列の数も固定しない**。オーバーサイズ/ドロップショルダーの型は
      **肩幅を測らない**ので 3列 (身丈/身幅/裄丈) で出る (2026-09-09 実測: 63件が該当)。
      4列前提だとこれが丸ごと落ちる。
    """
    head = seg[:200]
    cols, seen = [], set()
    for w in re.findall(r"身丈|肩幅|身幅|裄丈|袖丈", head):
        k = _COL[w]
        if k not in seen:
            seen.add(k)
            cols.append(k)
    return cols if 2 <= len(cols) <= 5 else None


def parse_table(body: str) -> list[dict] | None:
    """モーダルの本文 -> [{size, length, shoulder, chest, sleeve}].

    ★列の並び **と数** は 見出しから学ぶ (`_columns`)。コードに固定しない。
    ★見出しの数だけ数字が揃わない行は捨てる (欠けたまま入れない = fail-closed)。
    """
    i = body.find("サイズ 身丈")
    if i < 0:
        return None
    seg = body[i:i + 2000]
    cols = _columns(seg)
    if not cols:
        return None
    lines = [x.strip() for x in seg.split("\n") if x.strip()]
    rows, j = [], 0
    while j < len(lines):
        if lines[j].upper() in SIZE_LABELS:
            nums, k = [], j + 1
            while k < len(lines) and len(nums) < len(cols):
                if lines[k].upper() in SIZE_LABELS:
                    break
                if _NUM.fullmatch(lines[k]):
                    nums.append(lines[k])
                k += 1
            if len(nums) == len(cols):
                row = {"size": lines[j]}
                row.update(dict(zip(cols, nums)))
                rows.append(row)
            j = k
        else:
            j += 1
    return rows or None


def fetch_chart(d, pid: str) -> tuple[list[dict] | None, list[dict] | None, str, bool]:
    """(cm 表, inch 表, 生テキスト, 公式が消しているか)。

    ★**cm と inch の両方**を残す。cm が公式の生値 (小数)、inch は出品がそのまま使う形
      (`27 1/4` のような分数で出る)。片方だけにすると、もう片方が要った時に取り直しになる
      — 廃盤後は取り直せない。
    """
    d.get(PDP.format(pid=pid))
    time.sleep(6)
    # ★まず **button 要素**を直接押す。text 一致の総当たりだと、同じ文言の
    #   別要素を押してモーダルが開かないことがある (2026-09-09 実測: 14件が開かず、
    #   button を JS で押したら開いた)。
    btns = [e for e in d.find_elements("xpath", "//button")
            if "サイズを確認" in (e.text or "")]
    if btns:
        d.execute_script('arguments[0].scrollIntoView({block:"center"});', btns[0])
        time.sleep(1)
        d.execute_script("arguments[0].click();", btns[0])
    else:
        _click(d, "サイズを確認")
    time.sleep(5)
    opened = d.find_element("tag name", "body").text
    if "サイズ表" in opened and "仕上がり寸" not in opened:
        # ★モーダルは開いたが **公式が実寸表を消している** (2026-09-09 実測: 古い在庫なし
        #   商品 23件が該当)。「商品サイズの比較 / 身長別着丈ガイド」しか残っていない。
        #   取りこぼしではないので、呼び出し側で印を付けて次回から叩かない。
        return None, None, opened, True
    _click(d, "仕上がり寸", exact=True)
    time.sleep(3)
    body_cm = d.find_element("tag name", "body").text
    _click(d, "inch", exact=True)
    time.sleep(3)
    body_in = d.find_element("tag name", "body").text
    return (parse_table(body_cm), parse_table(body_in),
            body_cm + "\n===INCH===\n" + body_in, False)


def official_class(pid: str) -> str | None:
    """保管してある公式 detail の class (tops / accessories …)。生 JSON が無ければ None."""
    p = Path(f"C:/dev/iMak_data/catalog/_raw/{CATEGORY}/detail_{pid}.json.gz")
    if not p.exists():
        return None
    try:
        r = json.loads(gzip.open(p, "rt", encoding="utf-8").read())
    except Exception:
        return None
    r = r.get("result", r)
    return ((r.get("breadcrumbs") or {}).get("class") or {}).get("name") or ""


def targets(db, include_kids: bool) -> list[sqlite3.Row]:
    rows = db.execute("SELECT id, product_id, name, specs FROM products WHERE category=?",
                      (CATEGORY,)).fetchall()
    out, done, kids, gone = [], 0, 0, 0
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        if not include_kids and str(s.get("gender") or "").upper() in KID_GENDERS:
            kids += 1
            continue
        if s.get("is_collab_overview"):
            # ★商品でない行 (コラボの紹介記事)。実寸表は存在しない (2026-09-10)
            gone += 1
            continue
        if s.get("size_chart"):
            done += 1
            continue
        if s.get("size_chart_absent_at"):
            # 公式が寸法を消している (実測で確定済)。叩き直しても出てこない
            gone += 1
            continue
        if official_class(r["product_id"]) not in (None, "tops"):
            # ★手袋・ストール・肌着など UT でない物 (公式の class が tops でない)。
            #   公式が "ut graphic tees" に置いていても UT ではない (2026-09-11)
            gone += 1
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


def _shard_of(pid: str, n: int) -> int:
    """品番だけで決まる担当 (いつ数えても同じ行は同じ1本に当たる)."""
    return zlib.crc32(pid.encode("utf-8")) % n


def _start_driver():
    """ブラウザを起こす。並行で走らせると起動がぶつかることがあるので粘る."""
    for attempt in range(4):
        try:
            return new_driver()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))


def run(commit: bool, include_kids: bool, limit: int | None, brand: str = "uniqlo",
        shard: tuple[int, int] | None = None) -> None:
    global CATEGORY, PDP
    CATEGORY, PDP = BRANDS[brand]
    # ★他のセッション (回帰テスト等) が DB を掴んでいても待つ。
    #   待たないと `database is locked` で走行ごと落ちる (2026-09-09 実際に落ちた)。
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = targets(db, include_kids)
    if shard:
        # ★1件40秒かかる (2026-09-11 実測)。ブラウザを複数本立てて分担する。
        #   k/n = n 本のうち k 本目。**品番で**割り振る (並びの順番で割ると、
        #   起動のずれの間に他の1本が取った分だけ番号がずれ、誰も取らない行と
        #   2本が取る行ができる。2026-09-11 実測で 115行が取り残された)
        k, n = shard
        rows = [r for r in rows if _shard_of(r["product_id"], n) == k]
    if limit:
        rows = rows[:limit]
    print(f"=== {brand} 実寸表 ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(rows)}行 ===")
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
                d = _start_driver()
            pid = r["product_id"]
            try:
                cm, inch, body, absent = fetch_chart(d, pid)
            except Exception as e:
                stat[type(e).__name__] += 1
                continue
            if absent:
                # 公式が寸法を消している = 取りこぼしではない。印を付けて次回から叩かない
                stat["公式が実寸表を消している"] += 1
                if commit:
                    sp = json.loads(r["specs"] or "{}")
                    sp["size_chart_absent_at"] = now
                    sp["size_chart_absent_reason"] = (
                        "公式のサイズ表モーダルに 仕上がり寸/ヌード寸 が無い "
                        "(商品サイズの比較 と 身長別着丈ガイド だけ)。"
                        "古い在庫なし商品で公式が寸法を消したもの。取りこぼしではない。")
                    db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                               (json.dumps(sp, ensure_ascii=False), now, r["id"]))
                    db.commit()
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
                # ★DB が塞がっていても **走行を落とさない** (2026-09-09)。
                #   回帰テスト (3〜5分) が掴んでいる間は timeout でも足りず、
                #   2回とも走行ごと落ちた。待って、駄目なら次の商品へ進む
                #   (生テキストは倉庫に在るので、後から入れ直せる)。
                saved = False
                for attempt in range(6):
                    try:
                        db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                                   (json.dumps(s, ensure_ascii=False), now, r["id"]))
                        db.commit()          # ★1件ごとに保存 (1件15秒。取り直しが高い)
                        saved = True
                        break
                    except sqlite3.OperationalError as e:
                        if "locked" not in str(e):
                            raise
                        stat["DB が塞がって待った"] += 1
                        time.sleep(20)
                if saved:
                    ok += 1
                else:
                    stat["DB に入れられず (倉庫には在る)"] += 1
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
    ap.add_argument("--brand", choices=sorted(BRANDS), default="uniqlo")
    ap.add_argument("--shard", help="k/n — n 本で分担するうちの k 本目 (0 始まり)")
    a = ap.parse_args()
    shard = tuple(int(x) for x in a.shard.split("/")) if a.shard else None
    run(a.commit, a.include_kids, a.limit, a.brand, shard)


if __name__ == "__main__":
    main()
