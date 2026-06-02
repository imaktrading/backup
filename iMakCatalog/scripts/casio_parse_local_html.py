r"""Casio 公式 view-source HTML (= サブPC が保存) を parse して catalog DB にマージ.

サブPC pipeline:
  casio_subpc/casio_autosave_viewsource.py が view-source HTML を ./saved_html に保存
  → OneDrive 同期で母艦へ → 本スクリプトで parse + DB merge.

出力スキーマは 6/1 の casio_official_union 100 件 detail と **完全一致** させる
(= listing/gshock_to_csv が読む canonical key: msrp_jpy / release_date / size /
 case_size / case_thickness / weight / water_resistance / material_band /
 material_case_bezel / band_material / shock_resistance / glass / battery)。
※ scrapers/gshock.py の _parse_official_spec は price_jpy_msrp/case_material 等の
  別スキーマで listing key に当たらないため、本スクリプトは独自パーサを持つ。

入力 (default 両方):
  - C:/Users/imax2/OneDrive/デスクトップ/casio_subpc/saved_html
  - C:/Users/imax2/OneDrive/デスクトップ/新しいフォルダー (2)/_imported

使い方 (母艦 = catalog worktree で):
  python iMakCatalog/scripts/casio_parse_local_html.py            # dry-run (DB 変更なし)
  python iMakCatalog/scripts/casio_parse_local_html.py --commit   # backup 取得 + 実投入
  python iMakCatalog/scripts/casio_parse_local_html.py --dir <path> [--dir <path>] ...
"""
from __future__ import annotations

import argparse
import html as _html_mod
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Allow `import api` (= scrapers/gshock.py と同じ書式)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api  # noqa: E402

CATEGORY = "gshock"
DB_PATH = Path("C:/dev/iMak_data/catalog/products.sqlite")

DEFAULT_DIRS = [
    Path(r"C:/Users/imax2/OneDrive/デスクトップ/casio_subpc/saved_html"),
    Path(r"C:/Users/imax2/OneDrive/デスクトップ/新しいフォルダー (2)/_imported"),
]

# ファイル名: view-source_https___www.casio.com_jp_watches_gshock_product.{PID}_.html
_FNAME_PID = re.compile(r"product\.([A-Z0-9][A-Z0-9-]+?)_?\.html$", re.IGNORECASE)

# 公式材質 JP → eBay 英語 (scrapers/gshock.py の _parse_official_spec と同基準)
_CASE_MAT = [("カーボン", "Carbon Fiber"), ("ステンレス", "Stainless Steel"),
             ("SUS", "Stainless Steel"), ("チタン", "Titanium"),
             ("セラミック", "Ceramic"), ("樹脂", "Resin")]
_BAND_MAT = [("ステンレス", "Stainless Steel"), ("SUS", "Stainless Steel"),
             ("チタン", "Titanium"), ("ナイロン", "Nylon"), ("クロス", "Nylon"),
             ("革", "Leather"), ("レザー", "Leather"), ("シリコン", "Silicone"),
             ("樹脂", "Resin"), ("ウレタン", "Resin")]


def _en_material(jp: str, table) -> str:
    for kw, en in table:
        if kw in jp:
            return en
    return ""


def parse_casio_html(html_text: str) -> dict:
    """view-source HTML → catalog canonical spec dict (取れた field のみ)."""
    d = _html_mod.unescape(html_text)
    out: dict = {}

    def grab(label_pat: str, maxlen: int = 100) -> str:
        # spec blob は `LABEL:VALUE;` 形式 (value に < や ; を含まない)
        m = re.search(label_pat + r"[:：]\s*([^;<]{1," + str(maxlen) + r"})(?=;|<)", d)
        return m.group(1).strip().rstrip(";,") if m else ""

    # --- spec blob 系 ---
    size_raw = grab(r"ケースサイズ（[^）]*）", 60)
    if size_raw:
        m = re.match(r"([\d.]+)\s*[×x]\s*([\d.]+)\s*[×x]\s*([\d.]+)\s*mm", size_raw)
        if m:
            out["size"] = f"{m.group(1)} × {m.group(2)} × {m.group(3)} mm"
            out["case_size"] = f"{m.group(2)} mm"       # 横
            out["case_thickness"] = f"{m.group(3)} mm"  # 厚さ
        else:
            out["size"] = size_raw

    w = grab(r"質量", 20)
    if w:
        mm = re.search(r"([\d.]+)\s*g", w)
        if mm:
            out["weight"] = f"{mm.group(1)} g"

    cb = grab(r"ケース・ベゼル材質", 80)
    if cb:
        out["material_case_bezel"] = cb
        en = _en_material(cb, _CASE_MAT)
        if en:
            out["case_material"] = en

    band = grab(r"(?<![ァ-ヶ])バンド", 80)
    if band:
        out["material_band"] = band
        en = _en_material(band, _BAND_MAT)
        if en:
            out["band_material"] = en

    st = grab(r"構造", 120)
    if st:
        out["shock_resistance"] = st

    wr = grab(r"防水性", 40)
    if wr:
        m = re.search(r"(\d+)\s*気圧", wr)
        if m:
            atm = int(m.group(1))
            out["water_resistance"] = f"{atm * 10} m ({atm} ATM)"
        elif "ISO" in wr or "ダイバー" in wr:
            out["water_resistance"] = "200 m (20 ATM) ISO Diver"

    glass = grab(r"ガラス", 40)
    if glass:
        out["glass"] = glass

    bat = grab(r"使用電源・電池寿命", 120) or grab(r"電池寿命", 120) or grab(r"駆動方式", 120)
    if bat:
        out["battery"] = bat

    # --- blob 外 (個別 regex) ---
    m = re.search(r"メーカー希望小売価格[^￥]*￥\s*([0-9,]+)", d)
    if m:
        out["msrp_jpy"] = "￥" + m.group(1)

    m = re.search(r"発売[^0-9]{0,8}(20[0-9]{2}年[0-9]{1,2}月)", d)
    if m:
        out["release_date"] = m.group(1)

    return out


def collect_files(dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        if not d.exists():
            print(f"  ⚠️ dir 不在 skip: {d}")
            continue
        # _failed/ は Akamai block (小サイズ) なので除外
        for f in d.glob("*.html"):
            if f.parent.name == "_failed":
                continue
            files.append(f)
    return files


def main():
    ap = argparse.ArgumentParser(description="Casio local HTML → catalog merge")
    ap.add_argument("--commit", action="store_true", help="DB に投入 (無印 = dry-run)")
    ap.add_argument("--dir", action="append", type=Path, help="入力 dir (複数可)")
    ap.add_argument("--min-bytes", type=int, default=500_000,
                    help="この byte 数未満は block/失敗とみなし skip (default 500KB)")
    args = ap.parse_args()

    dirs = args.dir if args.dir else DEFAULT_DIRS
    print(f"=== Casio local HTML parse {'(COMMIT)' if args.commit else '(DRY-RUN)'} ===")
    for d in dirs:
        print(f"  input: {d}")

    files = collect_files(dirs)
    print(f"  html files: {len(files)}")

    if args.commit:
        bak = DB_PATH.with_name(
            DB_PATH.name + ".pre_casio_local_merge_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(DB_PATH, bak)
        print(f"  ✅ backup: {bak}")

    seen: dict[str, dict] = {}     # pid -> parsed (dedup: 同 pid 複数 file は後勝ち)
    no_pid = 0
    too_small = 0
    parse_empty = 0

    for f in files:
        m = _FNAME_PID.search(f.name)
        if not m:
            no_pid += 1
            continue
        pid = m.group(1)
        if f.stat().st_size < args.min_bytes:
            too_small += 1
            continue
        spec = parse_casio_html(f.read_text(encoding="utf-8", errors="ignore"))
        if not spec or "msrp_jpy" not in spec and "size" not in spec:
            parse_empty += 1
            continue
        seen[pid] = spec

    print(f"\n  parse 済: {len(seen)} pid (no_pid={no_pid} too_small={too_small} empty={parse_empty})")

    in_db = 0
    not_in_db: list[str] = []
    updated = 0
    sample = []

    for pid, spec in sorted(seen.items()):
        rec = api.lookup(CATEGORY, pid)
        if not rec:
            not_in_db.append(pid)
            continue
        in_db += 1
        existing = dict(rec.get("specs") or {})
        before_msrp = existing.get("msrp_jpy")
        merged = dict(existing)
        merged.update(spec)              # 公式値で上書き (= official SSOT 優先)
        merged["official_spec_fetched"] = True
        merged["official_spec_source"] = "casio_official_local"
        if len(sample) < 8:
            sample.append((pid, before_msrp, spec.get("msrp_jpy"),
                           spec.get("size"), spec.get("release_date"),
                           spec.get("glass"), len(spec)))
        if args.commit:
            api.upsert(
                category=CATEGORY,
                product_id=pid,
                name=rec.get("name") or f"Casio G-SHOCK {pid}",
                specs=merged,
                images=rec.get("images") or [],
                source=rec.get("source"),
                source_url=rec.get("source_url"),
            )
        updated += 1

    print(f"\n  DB 照合: in_db={in_db}  not_in_db={len(not_in_db)}")
    print(f"  {'投入' if args.commit else '投入予定'}: {updated} 件")
    print(f"\n  --- sample (pid | before_msrp -> msrp | size | release | glass | field数) ---")
    for pid, bm, am, sz, rel, gl, n in sample:
        print(f"    {pid}: {bm!r} -> {am!r} | {sz} | {rel} | {gl} | {n}f")
    if not_in_db:
        print(f"\n  ⚠️ DB 未登録 pid (先頭15): {not_in_db[:15]}")

    if not args.commit:
        print("\n  (DRY-RUN: DB 変更なし。 確認後 --commit で投入)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
