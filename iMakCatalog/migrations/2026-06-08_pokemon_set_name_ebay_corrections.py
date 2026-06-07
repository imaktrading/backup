"""set_name_ebay 修正分の適用: HQ確定 eBay facet 完全形(em-dash era接頭辞)に訂正 → verified昇格.

HQ確定文字列: requests/2026-06-08_..._round6_final_done_hq_facet_strings.md
接頭辞 convention = em-dash era prefix(承認済12,480件と統一)。HQ round略記は撤回、完全形が正。

JPセット名(set_name「」内core)キーに specs.set_name_ebay を完全形へ訂正し verified_manual 昇格。
- promo値の stray 行(real set下のpromo)は触らない(fail-closed)。
- 既verified行は対象外(unverified のみ訂正)。

実行: python iMakCatalog/migrations/2026-06-08_pokemon_set_name_ebay_corrections.py [--commit]
"""
from __future__ import annotations
import argparse, json, re, shutil, sqlite3, sys
from collections import Counter
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
SRC_TAG = "hq_confirmed_facet_20260608"
PROMO_VALUES = {"Promo", "XY Promo", "BW Promo", "Sword & Shield Promo", "Scarlet & Violet Promo"}

# JPセット「」内core -> 確定 eBay facet 完全形(このまま set)
FORCE = {
    "テラスタルフェスex": "Scarlet & Violet—Prismatic Evolutions",
    "GXウルトラシャイニー": "Sun & Moon—Hidden Fates",
    "湖の秘密": "Diamond & Pearl—Mysterious Treasures",
    "GXバトルブースト": "Sun & Moon—Ultra Prism",
    "ひかる闇": "Diamond & Pearl—Secret Wonders",
    "ミラクルツイン": "Sun & Moon—Unified Minds",
    "めざめる超王": "XY—Fates Collide",
    "ウルトラサン": "Sun & Moon—Ultra Prism",
    "ウルトラムーン": "Sun & Moon—Ultra Prism",
    "頂上大激突": "HeartGold & SoulSilver—Triumphant",
    "夜明けの疾走": "Diamond & Pearl—Majestic Dawn",
    "レッドコレクション": "Black & White—Noble Victories",
    "月光の追跡": "Diamond & Pearl—Great Encounters",
    "怒りの神殿": "Diamond & Pearl—Legends Awakened",
    "秘境の叫び": "Diamond & Pearl—Legends Awakened",
    "青い衝撃": "XY—BREAKthrough",
    "赤い閃光": "XY—BREAKthrough",
    "爆熱の闘士": "XY—Steam Siege",
    "冷酷の反逆者": "XY—Steam Siege",
    "闘う虹を見たか": "Sun & Moon—Burning Shadows",
    "光を喰らう闇": "Sun & Moon—Burning Shadows",
    "フリーズボルト": "Black & White—Boundaries Crossed",
    # 現値=目標一致(承認格上げ)。冪等にFORCEへ含める
    "プラズマゲイル": "Black & White—Plasma Storm",
    "コールドフレア": "Black & White—Boundaries Crossed",
    # UNCOVERED の確定分
    "超爆インパクト": "Sun & Moon—Lost Thunder",
    "破天の怒り": "XY—BREAKpoint",
}
_CORE_RE = re.compile(r"「(.+?)」")


def core_of(s):
    if not s:
        return None
    m = _CORE_RE.search(s)
    return m.group(1) if m else s


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute(
        "SELECT b.product_id_ref, p.set_name, p.specs FROM b_layer_status b "
        "JOIN products p ON p.id=b.product_id_ref "
        "WHERE b.field='set_name_ebay' AND b.status='unverified'"
    ).fetchall()

    apply = []  # (rid, old, new, newspecs)
    stray = Counter()
    per_set = Counter()
    for r in rows:
        core = core_of(r["set_name"])
        if core not in FORCE:
            continue
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            d = {}
        old = d.get("set_name_ebay")
        if old in PROMO_VALUES:        # real set 下の stray promo は触らない
            stray[core] += 1
            continue
        new = FORCE[core]
        d["set_name_ebay"] = new
        d["set_name_ebay_source"] = SRC_TAG
        apply.append((r["product_id_ref"], old, new, json.dumps(d, ensure_ascii=False)))
        per_set[(core, old, new)] += 1

    print(f"=== 訂正+昇格対象: {len(apply)} 件 / {len(per_set)} (set,old,new) ===")
    for (core, old, new), n in sorted(per_set.items(), key=lambda x: -x[1]):
        flag = " (現値=目標一致)" if old == new else ""
        print(f"   {n:4}  {core!r}: {old!r} -> {new!r}{flag}")
    if stray:
        print(f"\n  stray promo(触らない): {dict(stray)}")

    if not args.commit:
        print("\n  (DRY-RUN: --commit で適用)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_snecorr_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for rid, old, new, newspecs in apply:
        cur.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?", (newspecs, NOW, rid))
        cur.execute(
            "UPDATE b_layer_status SET status='verified_manual', oracle=?, checked_at=?, "
            "note=? WHERE product_id_ref=? AND field='set_name_ebay'",
            (SRC_TAG, NOW, f"corrected {old!r}->{new!r}", rid))
    con.commit()
    print(f"\n  ✅ 訂正 + verified_manual 昇格: {len(apply)} 件"); con.close()


if __name__ == "__main__":
    main()
