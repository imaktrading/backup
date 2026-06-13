"""run_harvest_snkrdunk_op - スニダン ワンピPSA10 全件抽出 → 新タブ (Phase 2).

ゴール (2026-06-12 user): スニダンのワンピ PSA10・price<cap を全件、 中間スプシ新タブに抽出。
既存 iMakTCG 出品 (HIGH) と同カード = 補仕入扱い (Q列 FLG="補")、 それ以外 = 新規候補。

フロー:
  1. Selenium: トレカ singles 検索を頁送り → 候補 model_id 列挙
  2. HTTP   : 各 model の productNumber を見て One Piece (OP/ST/EB/PRB/P) のみ採用
  3. HTTP   : 各 One Piece model の PSA10 + 出品中 + price<cap を price 昇順抽出
  4. 書込   : 新タブ `snkrdunk_op_psa10` に 1 card 1 行 (最安 + 補仕入 URL を AC-AG)、 card_id dedup

使い方:
  python run_harvest_snkrdunk_op.py --dry-run --max-pages 3      # 小範囲テスト
  python run_harvest_snkrdunk_op.py --price-cap 100000           # 本番
  python run_harvest_snkrdunk_op.py --keywords "ワンピース,OP12,OP11"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from scrapers import snkrdunk_official as SO
from scrapers import snkrdunk_op_catalog as OP
from sheet_writer import COL_TITLE, HIGH_SHEET_ID, LISTINGS_GID
from sheet_writer_mercari_seller import (
    _col_to_letter,
    _get_template_header,
    open_seller_staging_sheet,
)
from sheet_writer_snkrdunk_aux import get_listings_worksheet, open_sheet_by_id

TAB_NAME = "snkrdunk_op_psa10"

# 商品管理シート 37列フォーマット (= sheet_writer_amazon と同じ列番号)
C_URL = 1     # A: 最安 PSA10 used URL
C_TITLE = 3   # C: カード名
C_PRICE = 6   # F: 最安 PSA10 価格 (JPY)
C_FLG = 17    # Q: "補" = 既存 HIGH 出品と同カード
C_AUX = 29    # AC: 補仕入 URL 1 (= AC-AG に最安 5 件)
C_KEY = 35    # AI: card_id (= productNumber)
NCOLS = 37
AUX_MAX = 5

OUT = Path(__file__).resolve().parent / "debug" / "snkrdunk_op_result.json"
CARDS_OUT = Path(__file__).resolve().parent / "debug" / "snkrdunk_op_cards.json"


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def load_existing_high_card_ids() -> set[str]:
    """HIGH スプシ iMakTCG listing の card_id 集合 (= 補仕入判定用)."""
    ids: set[str] = set()
    try:
        sh = open_sheet_by_id(HIGH_SHEET_ID)
        ws = get_listings_worksheet(sh, LISTINGS_GID)
        for row in ws.get_all_values()[1:]:
            title = row[COL_TITLE - 1] if len(row) >= COL_TITLE else ""
            cid = SO.extract_tcg_card_id(title)
            if cid:
                ids.add(cid.upper())
    except Exception as e:
        _log(f"WARN: HIGH card_id 取得失敗 (補仕入判定スキップ): {e!r}")
    return ids


def _get_or_create_clean_tab(sh):
    """TAB_NAME を取得、 無ければ NCOLS 幅のクリーンなタブを作成 (= template header のみコピー).

    template 全複製 (duplicate) は遠方列(CS等)のジャンクを引き継ぎ、 A列データ無しだと
    append/書込が誤った列に流れる (2026-06-13 事故)。 → add_worksheet で NCOLS 幅に限定。
    """
    try:
        return sh.worksheet(TAB_NAME)
    except Exception:
        ws = sh.add_worksheet(title=TAB_NAME, rows=2000, cols=NCOLS)
        header = (_get_template_header(sh) or [])[:NCOLS]
        if header:
            ws.update(range_name=f"A1:{_col_to_letter(len(header))}1",
                      values=[header], value_input_option="USER_ENTERED")
        return ws


def _build_row(card: dict, is_supplement: bool) -> list:
    row = [""] * NCOLS
    listings = card["psa10"]
    row[C_URL - 1] = listings[0]["url"]
    row[C_TITLE - 1] = card["name"]
    row[C_PRICE - 1] = listings[0]["price"]
    row[C_FLG - 1] = "補" if is_supplement else ""
    for i, lst in enumerate(listings[:AUX_MAX]):
        row[C_AUX - 1 + i] = lst["url"]
    row[C_KEY - 1] = card["card_id"]
    return row


def write_cards_to_tab(cards: list[dict], retries: int = 3) -> int:
    """cards を新タブに書込 (card_id dedup, A列起点 update, DNS 等の一過性失敗を retry)."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            sh = open_seller_staging_sheet()
            ws = _get_or_create_clean_tab(sh)
            existing_keys = {(r[C_KEY - 1].strip().upper())
                             for r in ws.get_all_values()[1:]
                             if len(r) >= C_KEY and r[C_KEY - 1].strip()}
            new_rows = [_build_row(c, c.get("is_supplement", False)) for c in cards
                        if c["card_id"].upper() not in existing_keys]
            if not new_rows:
                _log(f"新タブ書込: 0 行 (全 {len(cards)} 件が既存)")
                return 0
            # append_rows は遠方列ジャンクで誤列書込するため A列起点 update 強制 (fail-safe)。
            next_row = len(ws.col_values(C_URL)) + 1
            end_row = next_row + len(new_rows) - 1
            ws.update(range_name=f"A{next_row}:{_col_to_letter(NCOLS)}{end_row}",
                      values=new_rows, value_input_option="USER_ENTERED")
            _log(f"新タブ書込: {len(new_rows)} 行 (既存skip {len(cards)-len(new_rows)})")
            return len(new_rows)
        except Exception as e:
            last_err = e
            _log(f"sheet write 失敗 (attempt {attempt}/{retries}): {e!r}")
            time.sleep(5)
    _log(f"sheet write 最終失敗。 cards は {CARDS_OUT} に保存済 → "
         f"`python run_harvest_snkrdunk_op.py --write-from-json` で再書込可")
    raise last_err


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--price-cap", type=int, default=OP.DEFAULT_PRICE_CAP)
    ap.add_argument("--keywords", default="ワンピース",
                    help="カンマ区切り検索語 (= 完全性向上に弾コード OP12 等を足す)")
    ap.add_argument("--max-pages", type=int, default=20, help="keyword あたり最大頁")
    ap.add_argument("--max-models", type=int, default=0, help="検証用 model 上限 (0=無制限)")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--write-from-json", action="store_true",
                    help="スクレイプせず CARDS_OUT の保存済 cards を新タブに書込 (= 書込失敗の復旧)")
    args = ap.parse_args(argv)

    # 復旧モード: 保存済 cards から書込のみ (= scrape skip)
    if args.write_from_json:
        cards = json.loads(CARDS_OUT.read_text(encoding="utf-8"))
        _log(f"--write-from-json: {CARDS_OUT} から {len(cards)} 件 読込 → 書込")
        written = write_cards_to_tab(cards)
        _log(f"復旧書込 完了: {written} 行")
        return 0

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    # 1) 候補 model_id 列挙 (Selenium)
    _log(f"列挙開始: keywords={keywords} max_pages={args.max_pages}")
    driver = SO.create_driver(headless=args.headless)
    candidates: list[str] = []
    seen: set[str] = set()
    try:
        for kw in keywords:
            ids = OP.enumerate_candidate_model_ids(driver, kw, max_pages=args.max_pages)
            new = [i for i in ids if i not in seen]
            seen.update(new)
            candidates.extend(new)
            _log(f"  keyword={kw!r}: +{len(new)} (累計候補 {len(candidates)})")
    finally:
        driver.quit()
    if args.max_models:
        candidates = candidates[: args.max_models]
    _log(f"候補 model 総数: {len(candidates)}")

    # 2)+3) One Piece 判定 + PSA10<cap 抽出 (HTTP)
    session = OP.create_session()
    cards: list[dict] = []
    op_models = 0
    for idx, mid in enumerate(candidates, 1):
        if idx % 25 == 0:
            _log(f"  抽出 {idx}/{len(candidates)} (One Piece={op_models} PSA10カード={len(cards)})")
        det = OP.fetch_model_detail(session, mid)
        if not det:
            continue
        pn = (det.get("productNumber") or "").strip()
        if not OP.is_one_piece_pn(pn):
            continue
        op_models += 1
        psa10 = OP.extract_psa10_under(session, mid, args.price_cap)
        if not psa10:
            continue
        cards.append({"model_id": mid, "card_id": pn.upper(),
                      "name": (det.get("name") or "").strip(), "psa10": psa10})
        time.sleep(OP.RATE_SEC)
    _log(f"One Piece model={op_models} / PSA10<{args.price_cap}あり card={len(cards)} "
         f"/ 総PSA10出品={sum(len(c['psa10']) for c in cards)}")

    # 補仕入判定
    high_ids = load_existing_high_card_ids()
    for c in cards:
        c["is_supplement"] = c["card_id"] in high_ids
    n_sup = sum(1 for c in cards if c["is_supplement"])
    _log(f"既存HIGH一致(補仕入)={n_sup} / 新規候補={len(cards)-n_sup}")

    # 抽出結果を先に保存 (= sheet write が DNS 等で落ちても再スクレイプ不要、 --write-from-json で復旧)
    CARDS_OUT.parent.mkdir(parents=True, exist_ok=True)
    CARDS_OUT.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"cards 保存: {CARDS_OUT} ({len(cards)} 件)")

    # 4) 新タブ書込 (card_id dedup)
    written = 0
    if cards and not args.dry_run:
        written = write_cards_to_tab(cards)

    out = {
        "timestamp": datetime.now().isoformat(),
        "dry_run": args.dry_run, "price_cap": args.price_cap, "keywords": keywords,
        "candidates": len(candidates), "one_piece_models": op_models,
        "cards_with_psa10": len(cards),
        "total_psa10_listings": sum(len(c["psa10"]) for c in cards),
        "supplement": n_sup, "new_candidate": len(cards) - n_sup, "written": written,
        "cards": [{"card_id": c["card_id"], "name": c["name"],
                   "cheapest": c["psa10"][0]["price"] if c["psa10"] else None,
                   "n_listings": len(c["psa10"]), "supplement": c["is_supplement"]}
                  for c in cards],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"summary: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
