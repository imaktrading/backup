"""画像が空の行を「まだ取っていない」と「公式に絵が無い」に仕分ける (終端マーク).

依頼: requests/2026-08-24_hq_eb02_003_ch01_image_may_not_exist.md
回答: 同 _response.md ([IMPLEMENT-GO])

## 判定 (1丁目1番地): ①カタログのデータが誤り → catalog 側で直す

②は正しい (出品くんは product_id 完全一致でしか引かない)。誤りは、**取れないものを
「空欄」のまま置いた**こと。空欄が「まだ取っていない」と「原理的に無い」を兼ねるので、
HQ 側の自動依頼が同じカードを毎日投げ続ける (EB02-003_CH01 が 3走行連続)。

## 決めたこと

`specs.no_official_image = true` を終端マークにする。付いた行は
「公式が絵を出していない = 目視不能 = 出品しない」で確定し、再依頼の対象にしない。
併せて `no_official_image_reason` / `no_official_image_checked_at` /
`no_official_image_probe` (何を叩いて無いと言えるのか) を残す。

## マークは**その場の公式取得**でしか付けない

保存値や過去の判断を根拠にしない (CLAUDE.md 1丁目1番地の判定基準)。
本 script は行ごとに公式を叩いてから仕分ける:

  pokemon Classic (CLF/CLK/CLL)  公式特設 pokemon-card.com/ex/classic が **今** 出している
                                 deck-card 画像を数え、既に別の行に割り当てた分を引く。
                                 残りが基本エネルギー3枚だけなら、番号付きの空行に
                                 入る絵は公式に存在しない。
                                 ★deck 番号は弾コード順ではなく (CLK=deck3 / CLL=deck2)、
                                   画像の並び順も番号順ではない。**番号で対応付けない**。
  pokemon その他                 resultAPI.php (find_official_card) に image_url が有るか。
  pokemon cardID-*               公式の番号体系外 (cardID fallback) で pg 絞りができない。
                                 card-search の詳細ページを叩いて券面画像の有無を見る。
  one_piece                      onepiece-cardgame.com/images/cardlist/card/<pid>.png。
                                 clone 行でも **親の URL は絶対に叩かない** (clone_rows §3)。

取れた場合はマークせず「取れる」側に出す (画像投入は backfill_pokemon_images.py の仕事)。

使い方:
  python tools/no_official_image_audit.py              # 仕分けのみ (DB 書込なし)
  python tools/no_official_image_audit.py --commit     # 終端マークを付ける
  python tools/no_official_image_audit.py --offline    # 公式を叩かず現状の集計だけ
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

CATEGORIES = ("one_piece_tcg", "pokemon_tcg")
MARK_KEY = "no_official_image"

CLASSIC_INDEX = "https://www.pokemon-card.com/ex/classic/"
CLASSIC_BASE = "https://www.pokemon-card.com/ex/classic/assets/images/"
# 特設 30枚のうち **番号付きの行が存在しない** 3枚 (基本エネルギー)。
# 2026-08-24 に実際に落として券面を目視: 左下の番号が数字ではなく
#   deck-card-1-8 = CLF GRA(草) / deck-card-2-8 = CLL FIR(炎) / deck-card-3-8 = CLK WAT(水)。
# catalog の CLF/CLK/CLL は 001〜032 の連番で欠番が無い = この3枚に対応する行が無い。
CLASSIC_ENERGY = {
    CLASSIC_BASE + "deck-card-1-8.png",
    CLASSIC_BASE + "deck-card-2-8.png",
    CLASSIC_BASE + "deck-card-3-8.png",
}
OPCG_IMG = "https://www.onepiece-cardgame.com/images/cardlist/card/{pid}.png"
POKEMON_DETAIL = "https://www.pokemon-card.com/card-search/details.php/card/{cid}/"

_UA = {"User-Agent": "Mozilla/5.0"}


def _head_ok(url: str, timeout: int = 20) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers=_UA)
        return urllib.request.urlopen(req, timeout=timeout).status == 200
    except Exception:
        return False


def _get_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=_UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def classic_published() -> set:
    """公式特設が **今** 出している deck-card 画像の URL 集合 (2026-08-24 実測 30枚)."""
    try:
        html = _get_text(CLASSIC_INDEX)
    except Exception as e:
        raise RuntimeError(f"公式特設が取れない: {e}") from e
    return {CLASSIC_BASE + f for f in set(re.findall(r"(deck-card-\d+-\d+\.png)", html))}


def classic_assigned(con: sqlite3.Connection) -> set:
    """既に catalog の行に割り当てた特設画像の URL 集合."""
    used = set()
    for r in con.execute("SELECT images FROM products WHERE images LIKE ?",
                         (f"%{CLASSIC_BASE}%",)):
        try:
            used.update(json.loads(r[0] or "[]"))
        except Exception:
            pass
    return {u for u in used if u.startswith(CLASSIC_BASE)}


def classify_pokemon_classic(pid: str, spare: set) -> tuple[bool, str, str]:
    """CLF/CLK/CLL の1行 → (公式に絵が有るか, 理由, 叩いた先).

    番号での対応付けはしない (deck 番号は弾コード順でなく、並び順も番号順でない)。
    **未割当の絵が1枚も残っていない**ことだけを根拠にする。残っていれば fail-closed で
    マークせず、割り当て作業 (券面の目視) に回す。
    """
    if spare:
        return (True,
                f"公式特設に未割当の絵が {len(spare)}枚 残っている → 目視で割り当てるまで"
                f"終端マークは付けない",
                CLASSIC_INDEX)
    return (False,
            "公式特設 (pokemon-card.com/ex/classic) が出している 30枚は基本エネルギー3枚を"
            "除き全て別の行に割当済。番号付きの行に入る絵を公式が出していない",
            CLASSIC_INDEX)


def classify_pokemon_cardid(pid: str) -> tuple[bool, str, str]:
    cid = pid.split("-", 1)[1]
    url = POKEMON_DETAIL.format(cid=cid)
    try:
        html = _get_text(url)
    except Exception as e:
        return True, f"詳細ページが取れず判定不能 ({e}) → マークしない", url
    if re.search(r"/assets/images/card_images/[^\"']+\.jpg", html):
        return True, "公式詳細ページに券面画像が有る", url
    if "noimage/poke_ura.jpg" in html:
        return (False,
                "公式詳細ページが券面ではなくカード裏の placeholder "
                "(assets/images/noimage/poke_ura.jpg) を返す = 公式が絵を持っていない",
                url)
    return (False,
            "公式は cardID しか持たず券面画像を出していない (card-search 詳細に "
            "card_images が無い)",
            url)


def classify_pokemon_other(row: sqlite3.Row) -> tuple[bool, str, str]:
    from scrapers import pokemon_tcg as P  # 遅延 import (offline 時に読まない)
    pid = row["product_id"]
    m = re.match(r"^(.*)-(\d+)$", pid)
    if not m:
        return True, "product_id が番号体系外 → 判定しない", ""
    set_code, num = m.group(1), m.group(2)
    probe = f"resultAPI.php pg={set_code} keyword={row['name_jp']!r} no={num}"
    try:
        hit = P.find_official_card(set_code, name=row["name_jp"] or None, card_number=num)
    except Exception as e:
        return True, f"公式 API が引けず判定不能 ({e}) → マークしない", probe
    if hit and hit.get("image_url"):
        return True, "公式 resultAPI に image_url が有る", probe
    # ★「公式 API に無い ≠ 実在しない」。resultAPI は secret rare や未掲載の新 promo を
    #   返さない (backfill_pokemon_images.py の 2026-06-24 HQ 訂正)。行は消さない。
    return (False,
            "公式 resultAPI が該当を返さず券面画像も出ていない "
            "(未掲載の promo/secret rare。実在するので行は消さない)",
            probe)


def classify_one_piece(row: sqlite3.Row) -> tuple[bool, str, str]:
    pid = row["product_id"]
    probe = OPCG_IMG.format(pid=pid)
    if _head_ok(probe):
        return True, "公式 cardlist に自分の絵が有る", probe
    if clone_rows.is_clone(row["specs"], row["source"]):
        base = clone_rows.cloned_from(row["specs"], row["source"])
        return (False,
                f"公式 cardlist に {pid} の絵が無い。clone 行なので親 ({base}) の絵は "
                f"使わない (clone_rows §3: 別絵柄に親の絵を入れると目視照合が誤る)",
                probe)
    return False, f"公式 cardlist に {pid} の絵が無い", probe


def classify(row: sqlite3.Row, spare: set) -> tuple[bool, str, str]:
    pid = row["product_id"]
    if row["category"] == "pokemon_tcg":
        if re.match(r"^CL[FKL]-\d+$", pid):
            return classify_pokemon_classic(pid, spare)
        if pid.startswith("cardID-"):
            return classify_pokemon_cardid(pid)
        return classify_pokemon_other(row)
    return classify_one_piece(row)


def load_rows(con: sqlite3.Connection) -> list:
    ph = ",".join("?" for _ in CATEGORIES)
    return con.execute(
        f"SELECT id, category, product_id, name, name_jp, images, source, specs "
        f"FROM products WHERE category IN ({ph}) "
        f"AND IFNULL(images,'[]') IN ('[]','') ORDER BY category, product_id",
        list(CATEGORIES)).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="終端マークを DB に書く")
    ap.add_argument("--offline", action="store_true", help="公式を叩かず現状集計だけ")
    args = ap.parse_args()

    con = sqlite3.connect(str(api._DB_PATH))
    con.row_factory = sqlite3.Row
    rows = load_rows(con)
    marked = con.execute(
        f"SELECT COUNT(*) FROM products WHERE json_extract(specs,'$.{MARK_KEY}')=1").fetchone()[0]
    print(f"画像が空の行: {len(rows)} 件 / 終端マーク済: {marked} 件")
    if args.offline:
        con.close()
        return 0

    published = classic_published()
    assigned = classic_assigned(con)
    spare = published - assigned - CLASSIC_ENERGY
    print(f"公式特設 Classic: 公開 {len(published)}枚 / 割当済 {len(assigned)}枚 / "
          f"基本エネルギー {len(published & CLASSIC_ENERGY)}枚 → 未割当 {len(spare)}枚")
    for u in sorted(spare):
        print(f"  ⚠️ 未割当: {u} (券面を目視して行に割り当てること)")

    now = datetime.now().isoformat(timespec="seconds")
    obtainable, unobtainable = [], []
    for r in rows:
        ok, reason, probe = classify(r, spare)
        (obtainable if ok else unobtainable).append((r, reason, probe))

    print(f"\n=== 公式に絵が有る (終端マークを付けない) {len(obtainable)} 件 ===")
    for r, reason, probe in obtainable:
        print(f"  ・{r['product_id']:<24} {reason}  {probe}")

    print(f"\n=== 公式に絵が無い (終端マーク) {len(unobtainable)} 件 ===")
    agg: dict = {}
    for r, reason, _ in unobtainable:
        agg[reason] = agg.get(reason, 0) + 1
    for reason, n in sorted(agg.items(), key=lambda kv: -kv[1]):
        print(f"  ・{n:>3}行  {reason}")

    # 公式が後から絵を出したら終端マークを外す (マークを墓場にしない)。
    unmark = [r for r, _, _ in obtainable if json.loads(r["specs"] or "{}").get(MARK_KEY)]
    if unmark:
        print(f"\n=== 終端マークを外す (公式が絵を出した) {len(unmark)} 件 ===")
        for r in unmark:
            print(f"  ・{r['product_id']}")

    if not args.commit:
        print("\n(仕分けのみ — --commit で終端マークを付ける)")
        con.close()
        return 0

    for r, reason, probe in unobtainable:
        s = json.loads(r["specs"] or "{}")
        s[MARK_KEY] = True
        s[f"{MARK_KEY}_reason"] = reason
        s[f"{MARK_KEY}_checked_at"] = now
        s[f"{MARK_KEY}_probe"] = probe
        con.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                    (json.dumps(s, ensure_ascii=False), now, r["id"]))
    for r in unmark:
        s = json.loads(r["specs"] or "{}")
        for k in (MARK_KEY, f"{MARK_KEY}_reason", f"{MARK_KEY}_checked_at",
                  f"{MARK_KEY}_probe"):
            s.pop(k, None)
        con.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                    (json.dumps(s, ensure_ascii=False), now, r["id"]))
    con.commit()
    print(f"\n[OK] 終端マーク {len(unobtainable)} 行 / マーク解除 {len(unmark)} 行")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
