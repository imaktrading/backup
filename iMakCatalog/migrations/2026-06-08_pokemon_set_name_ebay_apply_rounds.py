"""set_name_ebay round1-6 反映: 承認(現値正)→verified_manual昇格.

HQ検証: requests/2026-06-08_set_name_ebay_jp_en_mapping_corrections{,_round2..6_final}.md
JPセット名(products.set_name の「」内core)をキーに HQ verdict を適用:

- APPROVE: 現値が正しい(HQが現値確認済) → 現値を保持して verified_manual 昇格【本migで適用】
- PROMO  : era-promo値(現値正) → verified_manual 昇格【本migで適用】
- CORRECT: 現値が誤り。HQ目標値は略記で eBay facet 正確文字列が要確認 → **本migでは触らない**
           (別途 HQ に正確文字列確認後、後続migで訂正昇格)
- FAILCLOSED: JP限定(英語版1対1なし) → unverified 据置(出品ゲートで弾く)【触らない】
- UNCOVERED : verdict未割当の set_name → unverified 据置 + 報告

⚠️ 出品正確性原則: CORRECT は eBay正規値が確証できるまで昇格しない(fail-closed)。

実行: python iMakCatalog/migrations/2026-06-08_pokemon_set_name_ebay_apply_rounds.py [--commit]
"""
from __future__ import annotations
import argparse, json, re, shutil, sqlite3, sys
from collections import Counter, defaultdict
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
SRC_TAG = "hq_confirmed_rounds_20260608"

PROMO_VALUES = {"Promo", "XY Promo", "BW Promo", "Sword & Shield Promo", "Scarlet & Violet Promo"}

# --- 承認(現値が正しい=HQ確認済 → 現値保持で昇格) : 「」内core ---
APPROVE_CORES = {
    # S&V 主弾/高級
    "黒炎の支配者", "変幻の仮面", "ステラミラクル", "ロケット団の栄光", "バトルパートナーズ",
    "ブラックボルト", "ホワイトフレア", "古代の咆哮", "未来の一閃", "ナイトワンダラー",
    "トリプレットビート", "スカーレットex", "バイオレットex", "メガブレイブ", "メガシンフォニア",
    "シャイニートレジャーex",
    # SwSh 主弾/高級
    "ロストアビス", "パラダイムトリガー", "フュージョンアーツ", "仰天のボルテッカー", "ムゲンゾーン",
    "反逆クラッシュ", "ソード", "シールド", "漆黒のガイスト", "白銀のランス", "双璧のファイター",
    "連撃マスター", "一撃マスター", "摩天パーフェクト", "Pokémon GO", "バトルリージョン",
    "タイムゲイザー", "スペースジャグラー", "シャイニースターV", "VMAXクライマックス", "VSTARユニバース",
    # XY 主弾
    "コレクションX", "コレクションY", "ワイルドブレイズ", "ライジングフィスト", "ファントムゲート",
    "ガイアボルケーノ", "タイダルストーム", "エメラルドブレイク", "バンデットリング",
    # SM 主弾
    "タッグボルト", "ダブルブレイズ", "禁断の光", "裂空のカリスマ", "ひかる伝説", "キミを待つ島々",
    "アローラの月光", "コレクション サン", "コレクション ムーン", "サン＆ムーン", "覚醒の勇者", "超次元の暴獣",
    "新たなる試練の向こう",
    # BW 主弾
    "ブラックコレクション", "ホワイトコレクション", "ダークラッシュ", "リューズブラスト", "リューノブレード",
    # DP/HGSS 基幹
    "時空の創造 ダイヤモンドコレクション", "時空の創造 パールコレクション",
    "ハートゴールドコレクション", "ソウルシルバーコレクション",
    # misc 確実
    "25th ANNIVERSARY COLLECTION", "ドラゴンセレクション",
}
# ポケモンカード151 は core に全角括弧の注記が付く → 部分一致で拾う
APPROVE_PREFIX = ("ポケモンカード151",)

# --- 修正(現値誤り。HQ目標値=略記。本migでは適用しない、報告のみ) ---
CORRECT_PENDING = {
    "湖の秘密": "Mysterious Treasures", "月光の追跡": "Great Encounters", "ひかる闇": "Secret Wonders",
    "夜明けの疾走": "Majestic Dawn", "GXウルトラシャイニー": "Hidden Fates", "GXバトルブースト": "Ultra Prism",
    "ミラクルツイン": "Unified Minds", "ウルトラサン": "Ultra Prism", "ウルトラムーン": "Ultra Prism",
    "テラスタルフェスex": "Prismatic Evolutions", "青い衝撃": "XY—BREAKthrough", "赤い閃光": "XY—BREAKthrough",
    "めざめる超王": "XY—Fates Collide", "爆熱の闘士": "XY—Steam Siege", "冷酷の反逆者": "XY—Steam Siege",
    "闘う虹を見たか": "Sun & Moon—Burning Shadows", "光を喰らう闇": "Sun & Moon—Burning Shadows",
    "フリーズボルト": "Black & White—Boundaries Crossed", "コールドフレア": "Black & White—Boundaries Crossed",
    "プラズマゲイル": "Black & White—Plasma Storm", "頂上大激突": "HS—Triumphant",
    "秘境の叫び": "Legends Awakened", "怒りの神殿": "Legends Awakened",
    "レッドコレクション": "Black & White—Noble Victories",
}
# --- JP限定(英語版1対1なし) → unverified据置(触らない) ---
FAILCLOSED_CORES = {
    "TAG TEAM GX タッグオールスターズ", "フルメタルウォール", "ナイトユニゾン", "ジージーエンド",
    "スカイレジェンド", "ドリームリーグ", "ダークオーダー", "ドラゴンストーム", "ウルトラフォース",
    "THE BEST OF XY",
}

_CORE_RE = re.compile(r"「(.+?)」")


def core_of(set_name):
    if not set_name:
        return None
    m = _CORE_RE.search(set_name)
    return m.group(1) if m else set_name


def classify(set_name, value):
    """Returns ('approve'|'promo'|'correct'|'failclosed'|'uncovered'|'skip', detail)."""
    core = core_of(set_name)
    if set_name is None or core is None:
        if value in PROMO_VALUES:
            return ("promo", value)
        return ("skip", "blank/voided")           # 空欄(void済) は触らない
    if core in FAILCLOSED_CORES:
        return ("failclosed", core)
    if core in CORRECT_PENDING:
        return ("correct", CORRECT_PENDING[core])  # 本migでは適用しない
    if core in APPROVE_CORES or any(core.startswith(p) for p in APPROVE_PREFIX):
        if value and value not in PROMO_VALUES:
            return ("approve", value)
        return ("skip", "stray-promo-or-blank-under-approved-set")
    return ("uncovered", core)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute(
        "SELECT b.product_id_ref, p.set_name, p.specs FROM b_layer_status b "
        "JOIN products p ON p.id=b.product_id_ref "
        "WHERE b.field='set_name_ebay' AND b.status='unverified'"
    ).fetchall()

    buckets = defaultdict(int)
    promote = []      # (rid, value)  ← approve + promo を verified_manual に
    correct_rep = Counter()
    failclosed_rep = Counter()
    uncovered_rep = Counter()
    for r in rows:
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            d = {}
        v = d.get("set_name_ebay")
        kind, detail = classify(r["set_name"], v)
        buckets[kind] += 1
        if kind in ("approve", "promo"):
            promote.append((r["product_id_ref"], v))
        elif kind == "correct":
            correct_rep[core_of(r["set_name"])] += 1
        elif kind == "failclosed":
            failclosed_rep[detail] += 1
        elif kind == "uncovered":
            uncovered_rep[detail] += 1

    print("=== 分類集計 ===")
    for k in ("approve", "promo", "correct", "failclosed", "skip", "uncovered"):
        print(f"  {k:12} {buckets.get(k,0)}")
    print(f"\n  → 本migで verified_manual 昇格(approve+promo): {len(promote)} 件")
    if correct_rep:
        print(f"\n=== CORRECT(本migは触らない・要HQ正確文字列) {sum(correct_rep.values())}件 ===")
        for core, n in correct_rep.most_common():
            print(f"   {n:4}  {core!r} -> HQ略記 {CORRECT_PENDING[core]!r}")
    if failclosed_rep:
        print(f"\n=== FAILCLOSED据置 {sum(failclosed_rep.values())}件 ===")
        for core, n in failclosed_rep.most_common():
            print(f"   {n:4}  {core!r}")
    if uncovered_rep:
        print(f"\n=== ⚠️ UNCOVERED(verdict未割当・要確認) {sum(uncovered_rep.values())}件 ===")
        for core, n in uncovered_rep.most_common():
            print(f"   {n:4}  {core!r}")

    if not args.commit:
        print("\n  (DRY-RUN: --commit で approve+promo を昇格)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_sneapply_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for rid, v in promote:
        cur.execute(
            "UPDATE b_layer_status SET status='verified_manual', oracle=?, checked_at=?, "
            "note=? WHERE product_id_ref=? AND field='set_name_ebay'",
            (SRC_TAG, NOW, f"hq_approved {v!r}", rid))
    con.commit()
    print(f"\n  ✅ verified_manual 昇格: {len(promote)} 件"); con.close()


if __name__ == "__main__":
    main()
