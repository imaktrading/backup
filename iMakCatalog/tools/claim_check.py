"""「直しました」と言う前に必ず走らせる検収 (2026-09-03 新設).

## なぜ要るか

2026-08-26〜09-02 の1週間で、**私 (Catalog Claude) が「完了」と言った後に
未完了が発覚したのが4回**あった。原因はいつも同じ形だった:

    1. 触った関数だけ確かめて、出品くんが通る入口 (resolver) を通していない  (8/28 DON)
    2. ポケモンだけ測って「全部やった」と書いた                              (9/01 Set)
    3. 空欄しか測らず、値が入っていれば中身が別セットでも通していた            (9/02 1セット2値)
    4. 取り込んだが出品に出る値を付けず、テストが落ちる状態で放置              (9/02 OP-17)

共通しているのは **主張が文章だったこと**。数字と再実行可能なコマンドが無いので、
読む側は信じるしかなく、間違っていても次の走行まで分からない。

このスクリプトは **その文章を置き換える**。カタログが守るべき不変条件を全部走らせて、
1画面の PASS/FAIL にする。**FAIL が1つでもあれば exit 1**。

## 使い方 (ユーザーも同じコマンドで検算できる)

    python tools/claim_check.py            # 全部
    python tools/claim_check.py --quick    # 公式への通信をしない (DB とコードだけ)

★ここに出ない主張は「確かめていない主張」。**完了と言う前にチェックを足す**のが手順。
★このスクリプト自身が間違う可能性がある。だから **各チェックは数字を必ず表示**する
  (「OK」だけ出すチェックは書かない)。2026-09-02 に、突合ツールの初版が 126枚を
  誤って「欠落」と出した。数字が出ていたから気づけた。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TCG = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")
LOG = Path("C:/dev/iMak_data/catalog/_claim_check_log.jsonl")
# 「この cert はこの KEY に解決する」= 直したと言った件の実物。増やしていく。
SPOT = ROOT / "tools" / "_claim_check_spots.json"


def _db():
    c = sqlite3.connect(str(api._DB_PATH))
    c.row_factory = sqlite3.Row
    return c


# ---------------------------------------------------------------- 個々のチェック
def check_set_empty(_):
    """Set が空の行 (TCG のみ)。セット名自体が無い行だけは空欄が正しい."""
    db = _db()
    try:
        bad = []
        for cat in TCG:
            n = db.execute(
                "SELECT COUNT(*) FROM products WHERE category=? "
                "AND IFNULL(json_extract(specs,'$.set_name_ebay'),'')='' "
                "AND IFNULL(set_name_official,'')<>''", (cat,)).fetchone()[0]
            if n:
                bad.append(f"{cat}={n}")
        return (not bad), ("空 0 行" if not bad else "空: " + " / ".join(bad))
    finally:
        db.close()


def check_one_set_one_value(_):
    """1つのセット名に Set の値は1つ (例外はプロモの刷りだけ)."""
    sys.path.insert(0, str(ROOT / "tests"))
    import test_one_set_one_value_20260902 as t  # noqa: E402
    bad = t._conflicts()
    detail = "食い違い 0 セット" if not bad else \
        f"{len(bad)} セット: " + ", ".join(f"{c}/{s[:18]}" for c, s, _ in bad[:3])
    return (not bad), detail


def check_type_key(_):
    """ポケモンの型は type_en の1つだけ (type という別名を作らない)."""
    db = _db()
    try:
        n = db.execute("SELECT COUNT(*) FROM products WHERE category='pokemon_tcg' "
                       "AND json_extract(specs,'$.type') IS NOT NULL").fetchone()[0]
        return n == 0, f"旧キー `type` を持つ行 {n}"
    finally:
        db.close()


def check_images(_):
    """画像が空の行は終端マーク付き (「まだ取っていない」と「公式に無い」を分ける)."""
    db = _db()
    try:
        n = db.execute(
            "SELECT COUNT(*) FROM products WHERE category IN ('one_piece_tcg','pokemon_tcg') "
            "AND IFNULL(images,'[]') IN ('[]','') "
            "AND json_extract(specs,'$.no_official_image') IS NULL").fetchone()[0]
        return n == 0, f"画像も理由も無い行 {n}"
    finally:
        db.close()


def _audit_counters(cat: str) -> dict:
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "set_name_integrity_audit.py"),
                          "--cat", cat], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    m = re.search(r"COMPLETE: (.+?) ===", out)
    return dict(p.split("=", 1) for p in m.group(1).split() if "=" in p) if m else {}


def check_audit(_):
    """監査を **出品する4カテゴリ**で走らせ、0 で維持する項目が 0 か見る.

    ★遊戯王は対象外 (2026-09-03 ユーザー確定: 出品していないので直さない)。
      数字は出すが赤にしない。CLAUDE.md「遊戯王は直しの対象外」。
    """
    kv = {}
    for cat in TCG:
        for k, v in _audit_counters(cat).items():
            kv[k] = str(int(kv.get(k, 0)) + int(v)) if v.isdigit() else v
    if not kv:
        return False, "監査が完走しなかった"
    watched = ("era", "code_value_mismatch", "stage_on_non_pokemon", "card_type_unknown",
               "const_violation", "card_number_mismatch", "type_forbidden",
               "rarity_raw_stamped", "rarity_map_drift", "rarity_unmapped", "not_a_rarity")
    ng = {k: kv.get(k) for k in watched if kv.get(k) not in ("0", None)}
    ygo = _audit_counters("yugioh_tcg").get("not_a_rarity", "?")
    tail = f" / 遊戯王 (対象外) not_a_rarity={ygo}"
    return (not ng), (("見張り項目 全 0" if not ng else f"0でない: {ng}") + tail)


def check_resolver(_):
    """直したと言った cert が、**出品くんが呼ぶ入口** で今も引けるか."""
    import resolver  # noqa: E402
    spots = json.loads(SPOT.read_text(encoding="utf-8")) if SPOT.exists() else []
    ng = []
    for s in spots:
        got = resolver.resolve({"category": s["category"],
                                "signals": {"brand": s["brand"], "card_no": s.get("card_no", ""),
                                            "subject": s.get("subject", "")}})
        if got != s["expect"]:
            ng.append(f"{s['label']}: {got!r} (期待 {s['expect']!r})")
    return (not ng), (f"{len(spots)} 件すべて期待どおり" if not ng
                      else f"{len(ng)}/{len(spots)} 件ズレ: " + " / ".join(ng[:3]))


def check_tests(_):
    """回帰テスト (pre-commit と同じもの)."""
    out = subprocess.run([sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stdout
    m = re.search(r"(\d+) passed", out)
    f = re.search(r"(\d+) failed", out)
    return (f is None), f"{m.group(1) if m else '?'} passed / {f.group(1) if f else 0} failed"


def check_official_drift(quick):
    """公式との突合が **どれだけ古いか**。走らせていない = 確かめていない."""
    state_p = Path("C:/dev/iMak_data/catalog/_official_drift_state.json")
    state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    if quick:
        return True, f"(--quick のため未実行) これまでに見た弾 {len(state)}"
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "official_drift_check.py"),
                          "--n", "2"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    m = re.search(r"突合 (\d+)枚 / 差分 (\d+)件", out)
    if not m:
        return False, "突合が完走しなかった"
    return m.group(2) == "0", f"{m.group(1)}枚 突合 / 差分 {m.group(2)}件 (累計で見た弾 {len(state)})"


def check_official_coverage(_):
    """**公式と1度も比べていないカテゴリを緑にしない** (2026-09-03 追加).

    ユーザー指摘:「監査としてそれでいいの?」— 良くない。
    突合が在るのは One Piece だけで、残り 3カテゴリ (30,116行 = 77%) は
    「カタログの中で辻褄が合っている」しか見ていない。それを緑と呼ぶのは、
    **測っていないから緑**と同じで、今週こちらが4回やった失敗そのもの。

    したがって: 突合の口が無いカテゴリが1つでも在れば **FAIL**。
    赤のままでよい。作るまでは「確かめていない」が正しい表示。
    """
    db = _db()
    try:
        rows = {c: n for c, n in db.execute(
            "SELECT category, COUNT(*) FROM products WHERE category IN "
            "('pokemon_tcg','one_piece_tcg','dragonball_scg','gundam_tcg') "
            "GROUP BY category")}
    finally:
        db.close()
    covered = {"one_piece_tcg"}                     # 突合の口が在るのは今ここだけ
    miss = {c: n for c, n in rows.items() if c not in covered}
    tot = sum(rows.values()) or 1
    pct = 100 * sum(n for c, n in rows.items() if c in covered) // tot
    detail = (f"公式と突合できるのは {pct}% ({'/'.join(sorted(covered))}) / "
              f"未突合 {sum(miss.values())}行: " + ", ".join(f"{c}={n}" for c, n in sorted(miss.items())))
    return (not miss), detail


CHECKS = [
    ("Set が空の行", check_set_empty),
    ("1セット1値", check_one_set_one_value),
    ("型のキー名", check_type_key),
    ("画像の終端マーク", check_images),
    ("監査 (出品4カテゴリ)", check_audit),
    ("cert → KEY (入口経由)", check_resolver),
    ("回帰テスト", check_tests),
    ("公式との突合", check_official_drift),
    ("公式突合のカバー範囲", check_official_coverage),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="公式への通信をしない")
    args = ap.parse_args()

    now = datetime.now().isoformat(timespec="seconds")
    print(f"=== 検収 {now} ===")
    results, ng = [], 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn(args.quick)
        except Exception as e:                       # 落ちたら PASS にしない
            ok, detail = False, f"チェック自体が落ちた: {e}"
        ng += (not ok)
        results.append({"name": name, "ok": ok, "detail": detail})
        print(f"  {'PASS' if ok else '★FAIL'}  {name:22s} {detail}")

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now, "ng": ng, "results": results}, ensure_ascii=False) + "\n")
    print("")
    print(f"{'すべて PASS' if ng == 0 else f'★FAIL {ng} 件'} — 記録: {LOG}")
    sys.exit(0 if ng == 0 else 1)


if __name__ == "__main__":
    main()
