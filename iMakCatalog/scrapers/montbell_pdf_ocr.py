"""Montbell カタログ PDF → 商品 spec 抽出 (Claude Vision OCR).

設計背景 (2026-05-04):
  公式 webshop.montbell.jp は active 商品しか持たず、廃盤は 404.
  Wayback も snapshot なし → 廃盤は構造的に空振り.
  ユーザー手元に Montbell 公式 PDF カタログ (allweather/alpine/insulation 等) があり、
  これは廃盤含む商品マスター → OCR 経由で catalog DB に取込む.

技術詳細:
  - PDF は印刷用 outline 化 (Adobe PDF Library 17.0) → pdftotext / PyMuPDF テキスト抽出 0
  - PyMuPDF で page を 200 DPI PNG に rasterize → Claude Sonnet 4.6 vision で構造化抽出
  - 既存 montbell.py の JP→EN 辞書 + 正規化推論を再利用 (重複実装なし、5fee51a 方針)

実行:
  python iMakCatalog/scrapers/montbell_pdf_ocr.py <pdf_path>            # 単 PDF 全 page
  python iMakCatalog/scrapers/montbell_pdf_ocr.py <pdf_path> --page 2   # 単 page (smoke)

依存:
  - PyMuPDF (fitz) — PDF rasterize
  - anthropic SDK — Claude Vision
  - existing montbell.py — JP→EN 辞書 / upsert
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

# sys.path: api / 同 scrapers (montbell.py 参照)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CATALOG_ROOT = Path(__file__).resolve().parent.parent
_SCRAPERS = Path(__file__).resolve().parent
for p in (_CATALOG_ROOT, _SCRAPERS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

CATEGORY = "montbell"
MODEL_ID = "claude-sonnet-4-6"
PDF_OCR_DPI = 180  # 解像度: 文字認識精度と画像 token のバランス


# ============================================================================
# Anthropic API key 読込
# ============================================================================
def _load_anthropic_key() -> str:
    """API key.txt を 既存リポジトリ内の数箇所から読み込み (montbell_listing と同じ流儀)."""
    for cand in [
        _REPO_ROOT / "iMakMercari" / "API key.txt",
        _REPO_ROOT / "iMakG-shock" / "API key.txt",
        _REPO_ROOT / "iMakeBayAPI" / "API key.txt",
    ]:
        if cand.exists():
            return cand.read_text(encoding="utf-8").strip()
    raise RuntimeError("API key.txt が見つかりません")


# ============================================================================
# PDF page → image rasterize
# ============================================================================
def _render_page_png(pdf_path: Path, page_num: int, dpi: int = PDF_OCR_DPI) -> bytes:
    """PDF の指定 page を PNG bytes に変換."""
    import fitz  # type: ignore
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def _pdf_page_count(pdf_path: Path) -> int:
    import fitz  # type: ignore
    doc = fitz.open(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


# ============================================================================
# Claude Vision で page から商品 list を抽出
# ============================================================================
_EXTRACTION_SYSTEM_PROMPT = """あなたは Montbell 公式カタログ PDF の page 画像から商品情報を抽出するアシスタントです.

各 page には 0〜複数の商品が掲載されている. 各商品について以下のフィールドを抽出する:

  - model_no:           7 桁の商品型番 (例: "1106645"). 通常 page 上に直接印字されている.
  - name_jp:            商品名 (日本語). 例: "ライトシェルパーカ"
  - department:         "Men's" / "Women's" / "Unisex" / null (商品名の末尾 / マーク等から判断)
  - outer_shell_jp:     表地 (素材表記の "表地:" 直後). 例: "ナイロン・タフタ"
  - lining_jp:          裏地 (素材表記の "裏地:" 直後). null 可.
  - insulation_jp:      中わた (素材表記の "中わた:" 直後). null 可 (アウター系では多くが null).
  - weight_g:           平均重量 (整数 g, 単位なし string). 例: "303". null 可.
  - price_jpy:          税込価格 (整数 string, 円記号なし). 例: "12430". null 可.
  - colors:             color list. each: {"suffix": "BK", "jp": "ブラック"}. 不明なら [].
  - sizes:              size list. 例: ["XS", "S", "M", "L", "XL"]. 不明なら [].
  - features_jp:        機能 list (日本語). 例: ["撥水", "軽量", "防風"]. 不明なら [].
  - description_jp:     商品説明テキスト (短く 1-2 文、page 上の説明文を要約). null 可.

ルール:
  - 推測しない. page 上に明示されていない情報は null / [] で残す (CLAUDE.md 大原則).
  - model_no は必ず 7 桁数字. 4-6 桁や英字混じりの番号は商品ではないので除外.
  - cover / 目次 / 広告 / lifestyle 写真のみの page は商品 0 件として {"products": []} 返却.
  - 商品が複数あれば list に並べる.

出力形式:
  必ず JSON のみ返す. マークダウン code fence (```json) 不要. 構造:
  {"products": [{...}, {...}], "page_note": "短い page 概要"}
"""


def extract_page_products(pdf_path: Path, page_num: int) -> dict:
    """1 page から商品 list を抽出 (Claude Vision OCR).

    Returns:
        {"products": [...], "page_note": "..."} or
        {"products": [], "error": "...エラーメッセージ..."} on 失敗
    """
    import anthropic  # type: ignore

    try:
        png_bytes = _render_page_png(pdf_path, page_num)
    except Exception as e:
        return {"products": [], "error": f"render failed: {e}"}

    img_b64 = base64.standard_b64encode(png_bytes).decode("utf-8")
    client = anthropic.Anthropic(api_key=_load_anthropic_key())

    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
        },
        {
            "type": "text",
            "text": "この page の商品情報を上記 schema で JSON 抽出してください.",
        },
    ]

    try:
        msg = client.messages.create(
            model=MODEL_ID,
            max_tokens=6000,  # 2026-05-04: 4000 → 6000 (alpine2024 p4 等の密ページ用)
            system=_EXTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        raw_text = msg.content[0].text.strip()
    except Exception as e:
        return {"products": [], "error": f"API call failed: {e}"}

    # JSON parse (code fence 念のため除去)
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {"products": [], "error": f"JSON parse failed: {e}", "raw": raw_text[:500]}

    if not isinstance(data, dict):
        return {"products": [], "error": "non-dict response"}
    if "products" not in data:
        data["products"] = []
    return data


# ============================================================================
# OCR 結果 → catalog product 形式に正規化 + DB upsert
# ============================================================================
def _normalize_ocr_product(p: dict, source_label: str) -> Optional[dict]:
    """OCR 出力 dict を montbell.py が upsert できる形に正規化.

    既存 montbell.py の JP→EN 辞書を import 再利用 (重複実装なし).
    None 返却 = 投入対象外 (model_no なし等).
    """
    import montbell as mb  # 同 scrapers/

    pid = (p.get("model_no") or "").strip()
    if not pid or not re.match(r"^\d{7}$", pid):
        return None  # 7 桁数字以外は除外

    name_jp = (p.get("name_jp") or "").strip()
    department_raw = (p.get("department") or "").strip()
    if "Men" in department_raw:
        department = "Men"
    elif "Women" in department_raw:
        department = "Women"
    elif "Unisex" in department_raw:
        department = "Unisex Adults"
    else:
        department = "Not Specified"

    outer = mb._translate_first_match(p.get("outer_shell_jp") or "", mb._MATERIAL_JP_EN, "Not Specified")
    lining = mb._translate_first_match(p.get("lining_jp") or "", mb._MATERIAL_JP_EN, "Not Specified")
    insulation = mb._translate_first_match(p.get("insulation_jp") or "", mb._MATERIAL_JP_EN, "Not Specified")

    activity = mb._derive_activity(name_jp + " " + (p.get("description_jp") or ""))
    type_, style = mb._derive_type_and_style(name_jp)

    # features: features_jp list → EN
    features_en = []
    for fj in (p.get("features_jp") or []):
        for jp_key, en_val in mb._FEATURE_JP_EN.items():
            if jp_key in fj and en_val not in features_en:
                features_en.append(en_val)

    # colors: list of {"suffix": ..., "jp": ...} → 既存 _COLOR_SUFFIX_EN マッピング
    color_variants = []
    for c in (p.get("colors") or []):
        sx = (c.get("suffix") or "").strip()
        jp = (c.get("jp") or "").strip()
        en = mb._COLOR_SUFFIX_EN.get(sx)
        if not en and jp:
            for jp_key, en_val in mb._COLOR_JP_EN.items():
                if jp_key in jp:
                    en = en_val
                    break
        color_variants.append({"suffix": sx, "jp": jp, "en": en or "Not Specified"})

    # weight / price 整数 string
    weight_g = ""
    if p.get("weight_g"):
        m = re.search(r"\d+", str(p["weight_g"]))
        weight_g = m.group(0) if m else ""
    price_jpy = ""
    if p.get("price_jpy"):
        m = re.search(r"\d+", str(p["price_jpy"]).replace(",", ""))
        price_jpy = m.group(0) if m else ""

    return {
        "product_id": pid,
        "name_jp": name_jp,
        "name_en": "",
        "description_jp": p.get("description_jp") or "",
        "specs": {
            "outer_shell_material": outer,
            "lining_material": lining,
            "insulation_material": insulation,
            "fabric_type": mb._derive_fabric_type(name_jp, {}),
            "features": features_en,
            "performance_activity": activity,
            "garment_care": "Not Specified",
            "jacket_coat_length": mb._derive_length(name_jp),
            "type": type_,
            "style": style,
            "department": department,
            "country_of_origin": "Not Specified",
            "weight_g": weight_g,
            "retail_price_jpy": price_jpy,
            "brand": "montbell",
            "size_type": "Regular",
            "theme": "Outdoor",
            "fit": "Regular",
            "accents": "Logo",
            "vintage": "No",
            "handmade": "No",
            "pattern": "Solid",
            "ocr_source": source_label,
        },
        "color_variants": color_variants,
        "size_variants": (p.get("sizes") or []),
        "image_urls": [],
    }


def _upsert_normalized(np: dict, source_label: str):
    """正規化済 dict を api.upsert へ."""
    import api  # type: ignore
    api.upsert(
        category=CATEGORY,
        product_id=np["product_id"],
        name=np.get("name_jp", ""),
        name_jp=np.get("name_jp", ""),
        specs={
            **np.get("specs", {}),
            "color_variants":   np.get("color_variants", []),
            "size_variants":    np.get("size_variants", []),
            "image_urls":       np.get("image_urls", []),
            "description_jp":   np.get("description_jp", ""),
        },
        images=[],
        source=f"catalog_pdf_ocr_{source_label}",
        source_url=f"local_pdf:{source_label}",
    )


# ============================================================================
# 公開 API
# ============================================================================
def extract_pdf(pdf_path: Path, max_pages: Optional[int] = None,
                page_pacing: float = 1.0) -> dict:
    """PDF 全 page から商品抽出 + DB upsert.

    Args:
        pdf_path: PDF file path
        max_pages: 上限 (smoke 用、None なら全 page)
        page_pacing: page 間 sleep (API rate limit 緩和)

    Returns:
        {"upserted": int, "pages_processed": int, "errors": [...], "skipped": int}
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {"upserted": 0, "pages_processed": 0, "errors": [f"file not found: {pdf_path}"]}

    source_label = pdf_path.stem  # e.g., 'allweather2023'
    n_pages = _pdf_page_count(pdf_path)
    if max_pages:
        n_pages = min(n_pages, max_pages)

    print(f"=== {pdf_path.name} ({n_pages} pages) ===")
    upserted = 0
    skipped = 0
    errors = []
    for i in range(n_pages):
        print(f"  page {i+1}/{n_pages}...", end="", flush=True)
        result = extract_page_products(pdf_path, i)
        if result.get("error"):
            print(f" ⚠️ {result['error'][:60]}")
            errors.append({"page": i + 1, "error": result["error"]})
            time.sleep(page_pacing)
            continue
        products = result.get("products") or []
        page_upserted = 0
        for p in products:
            np = _normalize_ocr_product(p, source_label)
            if np:
                _upsert_normalized(np, source_label)
                page_upserted += 1
            else:
                skipped += 1
        upserted += page_upserted
        note = result.get("page_note", "")
        print(f" → {page_upserted} products"
              + (f" / note={note[:40]}" if note else ""))
        time.sleep(page_pacing)

    print(f"\n=== 完了 {pdf_path.name}: upserted={upserted} skipped={skipped} errors={len(errors)} ===")
    return {"upserted": upserted, "pages_processed": n_pages,
            "skipped": skipped, "errors": errors}


# ============================================================================
# CLI
# ============================================================================
def _cli():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python iMakCatalog/scrapers/montbell_pdf_ocr.py <pdf_path>")
        print("  python iMakCatalog/scrapers/montbell_pdf_ocr.py <pdf_path> --page 2  # smoke 1 page")
        sys.exit(1)
    pdf_path = Path(args[0])

    if "--page" in args:
        idx = args.index("--page")
        page_num = int(args[idx + 1]) - 1  # 1-indexed → 0-indexed
        print(f"=== smoke: page {page_num + 1} of {pdf_path.name} ===")
        result = extract_page_products(pdf_path, page_num)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    extract_pdf(pdf_path)


if __name__ == "__main__":
    _cli()
