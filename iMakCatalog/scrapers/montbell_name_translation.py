"""Montbell 商品名 (name_jp) → 英語 (name_en) bulk 翻訳.

設計背景 (2026-05-04):
  HQ の montbell_listing.py が出品時に AI で毎回翻訳 → 不安定.
  catalog 側で事前に name_en を確定させ、HQ は lookup() で取るだけにする.

ソース優先順位 (HQ 確定):
  1. (検証で対象ゼロと確認) 海外モデル既英訳
  2. (検証で構造分離と確認) montbell.us 公式 crawl
  3. **辞書 + AI hybrid → ここに集約** ← 本ファイル

実装方針:
  - 全 ~2052 件を Claude API で bulk 翻訳
  - system prompt に
      (a) 表記ルール 4 項目 (ピリオド残す / ® ™ 省略 / 全角→半角 / 固定 30 個)
      (b) 既存 eBay 出品 csv から抽出した正解 11 cores (= reference dictionary)
      (c) 揺れ防止: Wind Blast (NOT Windblast) / Ultra Light (NOT Ultralight)
  - 100 件/batch で 21 batch、各 batch ~1500 token in / ~1500 token out
  - match_type 自動分類:
      claude_translation_with_existing_match  (出力が reference 11 cores の語幹と一致)
      claude_translation_partial_match        (語幹のみ既存に類似)
      claude_translation_no_reference         (既存 csv に類似例なし、要確認)

実行:
  python iMakCatalog/scrapers/montbell_name_translation.py --smoke 10
  python iMakCatalog/scrapers/montbell_name_translation.py --all
  python iMakCatalog/scrapers/montbell_name_translation.py --export <out.csv>  # HQ 検証用
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

# sys.path: api / 同 scrapers
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CATALOG_ROOT = Path(__file__).resolve().parent.parent
_SCRAPERS = Path(__file__).resolve().parent
for p in (_CATALOG_ROOT, _SCRAPERS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

CATEGORY = "montbell"
MODEL_ID = "claude-sonnet-4-6"
BATCH_SIZE = 100  # 1 API call で同時翻訳する件数 (50-100 が安定圏)


# ============================================================================
# 既存 eBay 出品 csv から正解 reference 11 cores
# (HQ 確定: 2026-05-04 / Wind Blast Parka, Ultra Light Shell Jacket 採用)
# ============================================================================
EXISTING_REFERENCE_CORES = [
    "Light Shell Parka",
    "U.L. Stretch Wind Jacket",
    "Wind Blast Parka",                # NOT "Windblast Parka"
    "Ultra Light Shell Jacket",        # NOT "Ultralight Shell Jacket"
    "Veil Down Parka",
    "EX Light Wind Parka",
    "Wind Blast Print Parka",
    "ThunderPass Jacket",
    "Light Shell Cycle Jacket",
    # 上記の派生・関連 (catalog name_jp との対応で含む):
    "Ultra Light Shell Parka",         # 1106686 ウルトラ ライトシェル パーカ
    "Ultra Light Shell Vest",          # 派生 (派生も Ultra Light 統一)
]

# 商標 / 素材語 canonical 表記 (HQ 確定 2026-05-05、Title Case 統一)
TRADEMARK_CANONICAL = {
    "ドライテック":          "Drytec",
    "スーパードライテック":  "Super Drytec",  # 1 単語連結
    "シャミース":            "Chameece",
    "クリマバリア":          "Climabarrier",
    "クリマプラス":          "Climaplus",
    "エクセロフト":          "Exceloft",
    "サーマラップ":          "Thermarap",
    "スペリオダウン":        "Superior Down",  # HQ 確定 2026-05-05: 公式 montbell.com/us/en で "Superior Down" 16/16
}

# DEPRECATED 表記 (既存出品にあったが今後採用しない、再翻訳時に検出)
DEPRECATED_PATTERNS = {
    "Ultralight": "Ultra Light",       # U.L. = Ultra Light の略 → 整合
    "Windblast": "Wind Blast",         # 多数派
    "Dry Tec": "Drytec",               # 1 単語が canonical
    "DRYTEC": "Drytec",                # eBay は Title Case
    "Chamice": "Chameece",             # スペル誤り
    "CHAMEECE": "Chameece",
    "CLIMABARRIER": "Climabarrier",
    "CLIMAPLUS": "Climaplus",
    "EXCELOFT": "Exceloft",
    "THERMARAP": "Thermarap",
    "Sperio Down": "Superior Down",    # 公式 = Superior、Sperio は DEPRECATED
    "Sperio": "Superior",
}


# ============================================================================
# 既知パーツ語辞書 (固定 30 個)
# ============================================================================
KNOWN_PARTS_JP_EN = {
    # 商品 type suffix
    "ジャケット": "Jacket",
    "パーカ": "Parka",
    "パーカー": "Parka",  # 表記揺れ
    "ベスト": "Vest",
    "コート": "Coat",
    "パンツ": "Pants",
    "アノラック": "Anorak",
    "プルオーバー": "Pullover",
    "シャツ": "Shirt",
    "Tシャツ": "T-Shirt",
    "ハット": "Hat",
    "キャップ": "Cap",
    "グローブ": "Glove",
    # 修飾語 (商品名に多い)
    "ストレッチ": "Stretch",
    "ウインド": "Wind",
    "ライト": "Light",
    "ダウン": "Down",
    "シェル": "Shell",
    "レイン": "Rain",
    "クール": "Cool",
    "サーマル": "Thermal",
    "フリース": "Fleece",
    "ソフト": "Soft",
    "ハード": "Hard",
    "プリント": "Print",
    "サイクル": "Cycle",
    "フィッシング": "Fishing",
    "アルパイン": "Alpine",
    "クライミング": "Climbing",
    "EX": "EX",  # 既英字、変換不要
    "U.L.": "U.L.",  # 既英字、変換不要 (Ultra Light の略)
    "O.D.": "O.D.",
}


# ============================================================================
# system prompt
# ============================================================================
def _build_system_prompt() -> str:
    """system prompt を組立 (reference dict + ルール + 揺れ防止を full embed)."""
    ref_lines = "\n".join(f"  - {c}" for c in EXISTING_REFERENCE_CORES)
    deprecated_lines = "\n".join(
        f"  - {old} (DEPRECATED) → {new} (CORRECT)"
        for old, new in DEPRECATED_PATTERNS.items()
    )
    parts_lines = "\n".join(f"  - {jp} → {en}" for jp, en in KNOWN_PARTS_JP_EN.items())
    trademark_lines = "\n".join(
        f"  - {jp} → {en} (Title Case 厳守)"
        for jp, en in TRADEMARK_CANONICAL.items()
    )

    return f"""あなたは Montbell (モンベル) 商品の name_jp (日本語名) を英語名 (name_en) に
翻訳する翻訳ボットです.

【表記ルール - 厳守】
1. "." (ピリオド) は省略しない (例: "U.L." はそのまま "U.L.", "O.D." はそのまま)
2. ® / ™ などの記号は省略
3. 全角スペース / 全角中点 (・) は半角スペースに置換
4. 半角英数字に統一

【既知パーツ語 (これに従って翻訳)】
{parts_lines}

【商標 / 素材語 canonical 表記 (HQ 確定、Title Case 厳守)】
これらは Montbell 公式商標. 必ず以下の表記で出力 (大文字・略語・分割禁止):
{trademark_lines}

【既存 eBay 出品で確定済の正解英訳 (= reference dictionary)】
これらと意味的に同じ商品が来た場合、必ずこの表記を使うこと:
{ref_lines}

【表記揺れ DEPRECATED (これは使わない、こちらが正解)】
{deprecated_lines}

【出力形式】
入力: JSON 配列 [{{"product_id": "1106551", "name_jp": "ウルトラ ライトシェルジャケット"}}, ...]
出力: JSON 配列 [{{"product_id": "1106551", "name_en": "Ultra Light Shell Jacket", "match_type": "with_existing_match"}}, ...]

match_type の判定基準:
  - "with_existing_match": 上記 reference dict のいずれかと完全一致 or ほぼ同じ
  - "partial_match":       語幹 (e.g. "Light Shell" 部分) は reference にあるが、
                           完全な商品名としては reference になし
  - "no_reference":        reference にも近い例なし。要 HQ 確認.

【重要】
- 推測しない. 不明なカタカナ固有名詞 (例: ヴェイル, アルチプラノ, パーマフロスト 等) は
  音写でローマ字化するが、既存 csv に実例がある場合はそれを最優先 (Veil, Altiplano, Permafrost 等).
- 商品ライン名は通常複合語 (Wind Blast = "Wind"+"Blast"). 直訳でなく音写または既存例採用.
- "US " 接頭は output からは除く (国内サイト固有の海外向けマーカー、英語名本体ではない).
  例: "US テンペスト ジャケット" → "Tempest Jacket" (US は除く)
- マークダウン code fence (```json) 不要. JSON のみ返す.
"""


# ============================================================================
# Anthropic API key 読込
# ============================================================================
def _load_anthropic_key() -> str:
    candidates = [
        _REPO_ROOT / "iMakMercari" / "API key.txt",
        _REPO_ROOT / "iMakG-shock" / "API key.txt",
        _REPO_ROOT / "iMakeBayAPI" / "API key.txt",
        Path(r"C:/dev/iMak/iMakMercari/API key.txt"),
        Path(r"C:/dev/iMak/iMakG-shock/API key.txt"),
        Path(r"C:/dev/iMak/iMakeBayAPI/API key.txt"),
    ]
    for cand in candidates:
        if cand.exists():
            return cand.read_text(encoding="utf-8").strip()
    raise RuntimeError("API key.txt が見つかりません")


# ============================================================================
# bulk 翻訳
# ============================================================================
def translate_batch(items: list) -> list:
    """1 batch (~100 件) を Claude API で翻訳.

    Args:
        items: list of {"product_id": ..., "name_jp": ...}

    Returns:
        list of {"product_id": ..., "name_en": ..., "match_type": ...}
    """
    import anthropic  # type: ignore

    client = anthropic.Anthropic(api_key=_load_anthropic_key())
    user_msg = "翻訳対象:\n" + json.dumps(items, ensure_ascii=False, indent=2)

    msg = client.messages.create(
        model=MODEL_ID,
        max_tokens=8000,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = msg.content[0].text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return json.loads(cleaned)


def get_pending_records() -> list:
    """name_en 未設定の montbell records を取得."""
    import sqlite3
    import api  # type: ignore

    conn = sqlite3.connect(str(api._DB_PATH))
    cur = conn.cursor()
    cur.execute(
        "SELECT product_id, name_jp FROM products "
        "WHERE category = ? AND (name_en IS NULL OR name_en = '') "
        "ORDER BY product_id",
        (CATEGORY,),
    )
    rows = [{"product_id": r[0], "name_jp": r[1]} for r in cur.fetchall()]
    conn.close()
    return rows


def get_records_by_keyword(keywords: list) -> list:
    """name_jp に keywords のいずれかを含む records を取得 (force re-translate 用)."""
    import sqlite3
    import api  # type: ignore

    if not keywords:
        return []
    conn = sqlite3.connect(str(api._DB_PATH))
    cur = conn.cursor()
    where_clause = " OR ".join(["name_jp LIKE ?"] * len(keywords))
    params = [CATEGORY] + [f"%{k}%" for k in keywords]
    cur.execute(
        f"SELECT product_id, name_jp FROM products WHERE category = ? "
        f"AND ({where_clause}) ORDER BY product_id",
        tuple(params),
    )
    rows = [{"product_id": r[0], "name_jp": r[1]} for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_translations(translations: list, existing_records: dict) -> int:
    """翻訳結果を catalog に upsert (既存 record の他フィールドは保持)."""
    import api  # type: ignore

    n = 0
    for t in translations:
        pid = t.get("product_id")
        name_en = (t.get("name_en") or "").strip()
        match_type = t.get("match_type", "no_reference")
        if not pid or not name_en:
            continue
        rec = existing_records.get(pid)
        if not rec:
            continue
        # 既存 record の name / name_jp / specs / images / source 等を維持
        api.upsert(
            category=CATEGORY,
            product_id=pid,
            name=rec["name"],
            name_jp=rec["name_jp"],
            name_en=name_en,
            name_en_source=f"claude_translation_{match_type}",
            specs=rec["specs"],
            images=rec["images"],
            source=rec["source"],
            source_url=rec["source_url"],
        )
        n += 1
    return n


def run_translation(limit: Optional[int] = None,
                    batch_size: int = BATCH_SIZE,
                    pacing_seconds: float = 1.0,
                    pending: Optional[list] = None) -> dict:
    """name_en 未設定の records を bulk 翻訳 + upsert.

    Args:
        limit: 上限 (smoke 用、None なら全件)
        batch_size: 1 API call の件数
        pacing_seconds: batch 間 sleep
        pending: 明示的に対象 record list を渡す (re-translation 用、name_en 上書き)

    Returns:
        {"total_pending": int, "translated": int, "upserted": int,
         "match_summary": {match_type: count, ...}, "errors": [...]}
    """
    import api  # type: ignore

    if pending is None:
        pending = get_pending_records()
    if limit:
        pending = pending[:limit]
    print(f"=== translation pending: {len(pending)} records ===")

    # 既存 record を product_id でロード (upsert 時に他フィールドを失わないため)
    existing_records = {}
    for p in pending:
        rec = api.lookup(CATEGORY, p["product_id"])
        if rec:
            existing_records[p["product_id"]] = rec

    translated_total = 0
    upserted_total = 0
    match_summary: dict = {}
    errors: list = []
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        b_idx = i // batch_size + 1
        b_total = (len(pending) + batch_size - 1) // batch_size
        print(f"  batch {b_idx}/{b_total} ({len(batch)} items)...", end="", flush=True)
        try:
            results = translate_batch(batch)
        except Exception as e:
            print(f" ⚠️ batch error: {type(e).__name__}: {str(e)[:120]}")
            errors.append({"batch": b_idx, "error": str(e)[:300]})
            time.sleep(pacing_seconds)
            continue
        translated_total += len(results)
        for r in results:
            mt = r.get("match_type", "no_reference")
            match_summary[mt] = match_summary.get(mt, 0) + 1
        n = upsert_translations(results, existing_records)
        upserted_total += n
        print(f" → translated={len(results)} upserted={n}")
        time.sleep(pacing_seconds)

    print()
    print(f"=== 完了: translated={translated_total} upserted={upserted_total} ===")
    print(f"  match_summary: {match_summary}")
    return {
        "total_pending": len(pending),
        "translated": translated_total,
        "upserted": upserted_total,
        "match_summary": match_summary,
        "errors": errors,
    }


# ============================================================================
# HQ 検証用 CSV エクスポート
# ============================================================================
def export_for_review(out_path: str, limit: Optional[int] = None) -> int:
    """全 montbell records の name_jp / name_en / source を CSV 出力 (HQ 検証用)."""
    import sqlite3
    import api  # type: ignore

    conn = sqlite3.connect(str(api._DB_PATH))
    cur = conn.cursor()
    sql = (
        "SELECT product_id, name_jp, name_en, name_en_source, source "
        "FROM products WHERE category = ? ORDER BY product_id"
    )
    if limit:
        sql += f" LIMIT {limit}"
    cur.execute(sql, (CATEGORY,))
    rows = cur.fetchall()
    conn.close()

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "name_jp", "name_en", "name_en_source", "source"])
        for r in rows:
            w.writerow(r)
    print(f"  → exported {len(rows)} rows to {out_path}")
    return len(rows)


# ============================================================================
# CLI
# ============================================================================
def _cli():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python iMakCatalog/scrapers/montbell_name_translation.py --smoke 10")
        print("  python iMakCatalog/scrapers/montbell_name_translation.py --all")
        print("  python iMakCatalog/scrapers/montbell_name_translation.py --export out.csv")
        sys.exit(1)

    if args[0] == "--smoke":
        n = int(args[1]) if len(args) > 1 else 10
        run_translation(limit=n)
    elif args[0] == "--all":
        run_translation()
    elif args[0] == "--retranslate-trademarks":
        # Step 1: 商標/素材語含む全 records を再翻訳 (name_en 上書き)
        keywords = list(TRADEMARK_CANONICAL.keys())
        targets = get_records_by_keyword(keywords)
        print(f"=== retranslate-trademarks 対象: {len(targets)} records ===")
        run_translation(pending=targets)
    elif args[0] == "--retranslate-by-keyword":
        # 任意 keyword で再翻訳
        kw = args[1].split(",")
        targets = get_records_by_keyword(kw)
        print(f"=== retranslate-by-keyword 対象 ({kw}): {len(targets)} records ===")
        run_translation(pending=targets)
    elif args[0] == "--export":
        out = args[1] if len(args) > 1 else "montbell_name_review.csv"
        export_for_review(out)
    else:
        print(f"⚠️ 不明な引数: {args}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
