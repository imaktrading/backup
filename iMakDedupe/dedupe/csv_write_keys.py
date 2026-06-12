"""Phase 1h: 入稿前 CSV から HIGH スプシに KEY1/KEY2 を事前書込.

依頼書 §3 仕様:
- 入力: psa_to_csv 生成 CSV (= `csv_output/tcg_upload_*.csv`)
- HIGH スプシ I 列 (= R 列 == "TCG" の場合 PSA cert 番号) で row 特定
- AI 列 (= KEY1) + AJ 列 (= KEY2) に書込
- 既存値あれば skip (= 手動補完尊重)
- fail-closed: cert 不一致 / card_id 取れず → skip + log

== なぜ lag 0? ==
cron 案 (= 入稿後 snapshot 経由) ではなく、 入稿前 chain hook で完結。
HIGH スプシは既に row 存在前提 (= 出品者が事前に I 列に cert 手動入力済)、
重複くんは CSV → HIGH row 特定 → AI/AJ 書込のみ。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# === eBay File Exchange CSV 列名 ===
CSV_COL_TITLE = "*Title"
CSV_COL_CARD_NUMBER = "C:Card Number"
CSV_COL_FEATURES = "C:Features"
CSV_COL_SPECIALITY = "C:Speciality"
CSV_COL_SET = "C:Set"
CSV_COL_CERT = "CDA:Certification Number - (ID: 27503)"
# Phase 1q (= 2026-05-28 体系再設計): CSV にリスティング無関係列を持たない方針
# 旧 C:PSA Brand / C:PSA Subject / INTERNAL:KEY1 / INTERNAL:KEY2 列は撤回.
# cert → iMakeBayAPI cache → brand/subject 経由に切替 (= SoC/SSOT/DRY 統一)
CSV_COL_PIC_URL = "PicURL"
CSV_COL_PIC_URL_STAR = "*PicURL"


def extract_cert_and_keys_from_csv_row(
    row: Dict[str, str],
    priority_extractor2: Callable,
    lookup_don_fn: Optional[Callable] = None,
    catalog_valid_pids: Optional[frozenset] = None,
    catalog_set_map: Optional[Dict] = None,
    lookup_yugioh_fn: Optional[Callable] = None,
    extract_variant_alias_fn: Optional[Callable] = None,
    get_variant_meta_fn: Optional[Callable] = None,
    get_category_fn: Optional[Callable] = None,
    get_catalog_variants_fn: Optional[Callable] = None,
    identify_variant_by_image_fn: Optional[Callable] = None,
) -> Tuple[str, Optional[str], str, str]:
    """CSV 1 row dict から (cert, key1, key1_type, key2) を抽出.

    cert: HIGH I 列との突合 key (= 9-10 桁数字、 PSA 認証番号)
    key1 / key2: Phase 1f 同型抽出 (title + C:Card Number fallback + variant aspect)

    Phase 1j (DON): title に 'DON' 含む + lookup_don_fn 指定 → product_id を key1 採用.
    Phase 1k (全 category): 通常 logic で取れない場合、 title / C:Card Number から
    catalog product_id token を抽出して valid_pids で完全一致 verify
    (= Pokemon SV1V-086 / G-shock DW-5600-1JF / Uniqlo E420005-000 等を統合 cover)。
    """
    from . import catalog_io  # 遅延 import

    cert = (row.get(CSV_COL_CERT) or "").strip()

    title = (row.get(CSV_COL_TITLE) or "").strip()
    card_num = (row.get(CSV_COL_CARD_NUMBER) or "").strip()
    features = (row.get(CSV_COL_FEATURES) or "").strip()
    speciality = (row.get(CSV_COL_SPECIALITY) or "").strip()
    extra = " ".join(s for s in (features, speciality) if s)
    # Phase 1q (= 2026-05-28 体系再設計): cert → iMakeBayAPI cache 経由で brand/subject 取得
    # 旧 C:PSA Brand/Subject 列読込撤回、 SoC/SSOT/DRY 観点で cache 経由統一.
    psa_brand = ""
    psa_subject = ""
    if cert:
        from . import iMakeBayAPI_psa_io as _psa_io
        psa_meta = _psa_io.get_cached_psa(cert)
        if psa_meta:
            psa_brand = (psa_meta.get("Brand") or "").strip()
            psa_subject = (psa_meta.get("Subject") or "").strip()

    # *Title 優先
    k1, t1, k2 = priority_extractor2(title, "", extra)
    if not k1 and card_num:
        # C:Card Number 完全形 fallback
        k1, t1, k2 = priority_extractor2(card_num, "", extra)

    # Phase 1k: catalog token verify fallback (全 category 統合)
    if not k1 and catalog_valid_pids:
        for source_text in (title, card_num):
            if not source_text:
                continue
            hit = catalog_io.find_product_id_in_text(source_text, catalog_valid_pids)
            if hit:
                k1 = hit[0]
                t1 = "card"  # catalog 由来 = product_id として確定
                break

    # Phase 1k 拡張 (= 2026-05-27): C:Card Number 連番 + C:Set 経由 reconstruct
    # 出品くんが C:Card Number に連番のみ書込 + C:Set に set 名 書込 ケース
    # → catalog で完全形 product_id (= 例 SV1V-086) に復元
    if not k1 and card_num and catalog_valid_pids and catalog_set_map:
        set_val = (row.get(CSV_COL_SET) or "").strip()
        cid, reason = catalog_io.reconstruct_card_id(
            card_num, set_val, catalog_set_map, catalog_valid_pids
        )
        if cid and "verified" in reason:
            k1 = cid
            t1 = "card"

    # Phase 1j + 1l: DON カード fallback
    # 5/27 修正後: C:PSA Brand / C:PSA Subject 列があれば優先 (= lookup_don 精度向上)
    # title-only fallback も keep (= 古い CSV 互換維持)
    don_in_text = "DON" in (psa_subject + title).upper()
    if not k1 and lookup_don_fn is not None and don_in_text:
        record = lookup_don_fn(
            brand=psa_brand or title,
            subject=psa_subject or title,
        )
        if record and record.get("product_id"):
            k1 = record["product_id"]
            t1 = "card"

    # Phase 1l (新規): YGO fallback (= PSA subject 経由 fuzzy match)
    # YGO catalog は Konami numeric ID format で title/Card Number 経由 verify 不能、
    # lookup_yugioh が唯一の path。 C:PSA Brand / C:PSA Subject 必須。
    if not k1 and lookup_yugioh_fn is not None and psa_brand and psa_subject:
        # YGO 関連 keyword で判定 (= 余計な fetch 回避)
        ygo_marker = any(k in (psa_brand + title).upper()
                          for k in ('YU-GI-OH', 'YUGIOH', 'YGO', '遊戯王'))
        if ygo_marker:
            record = lookup_yugioh_fn(
                brand=psa_brand,
                card_number=card_num,
                subject=psa_subject,
            )
            if record and record.get("product_id"):
                k1 = record["product_id"]
                t1 = "card"  # Konami numeric ID も card 系扱い

    # Phase 1n (= 2026-05-27 ① 連動): KEY2 catalog SSOT 化
    # k1 (= product_id) 確定済 + extract_variant_alias 関数あれば、
    # PSA Subject から variant_code を抽出して catalog 公式値を採用。
    # 既存 title parse 値 (k2) があっても、 catalog hit すれば上書き = SSOT 優先。
    # catalog 未投入カテゴリ / variant_meta None → 既存 k2 keep (= 後方互換).
    if k1 and extract_variant_alias_fn is not None:
        subject_for_alias = psa_subject or title
        catalog_variant = extract_variant_alias_fn(subject_for_alias)
        if catalog_variant and get_variant_meta_fn is not None and get_category_fn is not None:
            category = get_category_fn(k1)
            if category:
                meta = get_variant_meta_fn(k1, catalog_variant, category)
                if meta:
                    k2 = catalog_variant  # SSOT 公式値

    # Phase 1o (= 2026-05-28 ③ Phase C cycle 統合): 画像 hash 最終 fallback
    # 既存全 logic で k2 取れない + k1 確定済 + 画像 URL ありなら catalog image_phash 比較。
    # 全 variant の image_phash と hamming distance 計測、 閾値以下 unique なら採用 (= fail-closed).
    if k1 and not k2 and get_catalog_variants_fn is not None and identify_variant_by_image_fn is not None:
        image_url = (row.get(CSV_COL_PIC_URL_STAR) or row.get(CSV_COL_PIC_URL) or "").strip()
        if image_url and get_category_fn is not None:
            category = get_category_fn(k1)
            if category:
                catalog_variants = get_catalog_variants_fn(k1, category)
                if catalog_variants:
                    variant_code = identify_variant_by_image_fn(image_url, catalog_variants)
                    if variant_code:
                        k2 = variant_code  # 画像 hash 経由 SSOT 確定

    return cert, k1, t1, k2


def build_cert_to_row_index(
    ws_values: List[List[str]],
    category_col: int,
    cert_col: int,
    tcg_category_value: str = "TCG",
) -> Dict[str, int]:
    """HIGH スプシ全 row scan で {cert: row_idx_1based} を構築.

    R 列 (= category_col) == tcg_category_value の row のみ対象。
    重複 cert (= 同じ cert が複数 row にある) は最後の row_idx を保持
    (= 同じ cert で複数 row があるのは出品エラーだが、 重複くんは log 出力で済ます).
    """
    cert_map: Dict[str, int] = {}
    for offset, row in enumerate(ws_values[1:], start=1):
        cat = (row[category_col - 1] or "").strip() if len(row) >= category_col else ""
        if cat != tcg_category_value:
            continue
        cert = (row[cert_col - 1] or "").strip() if len(row) >= cert_col else ""
        if cert:
            cert_map[cert] = offset + 1  # 1-based row index
    return cert_map


def write_keys_to_high(
    ws,
    csv_path: Path,
    priority_extractor2: Callable,
    key1_col: int,
    key2_col: int,
    cert_col: int,
    category_col: int,
    tcg_category_value: str = "TCG",
    dry_run: bool = False,
    lookup_don_fn: Optional[Callable] = None,
    catalog_valid_pids: Optional[frozenset] = None,
    catalog_set_map: Optional[Dict] = None,
    lookup_yugioh_fn: Optional[Callable] = None,
    extract_variant_alias_fn: Optional[Callable] = None,
    get_variant_meta_fn: Optional[Callable] = None,
    get_category_fn: Optional[Callable] = None,
    get_catalog_variants_fn: Optional[Callable] = None,
    identify_variant_by_image_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """CSV を読込んで HIGH の R='TCG' row に KEY1/KEY2 事前書込.

    Returns:
        {
          "csv_rows": ..., "csv_with_cert": ...,
          "high_tcg_rows": ..., "matched": ...,
          "written_key1": ..., "written_key2": ...,
          "skipped_no_cert": ..., "skipped_cert_unmatched": ...,
          "skipped_no_key1": ...,
          "skipped_existing_key1": ..., "skipped_existing_key2": ...,
          "samples": [...],  # up to 10
        }
    """
    import gspread  # 遅延 (= test mock 容易)

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    # 1. HIGH 全 values 読込
    values = ws.get_all_values()
    cert_map = build_cert_to_row_index(
        values, category_col, cert_col, tcg_category_value
    )

    # 2. CSV 読込
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)

    result: Dict[str, Any] = {
        "csv_rows": len(csv_rows),
        "csv_with_cert": 0,
        "high_tcg_rows": sum(
            1
            for r in values[1:]
            if (r[category_col - 1] or "").strip() == tcg_category_value
            if len(r) >= category_col
        ),
        "matched": 0,
        "written_key1": 0,
        "written_key2": 0,
        "skipped_no_cert": 0,
        "skipped_cert_unmatched": 0,
        "skipped_no_key1": 0,
        "skipped_existing_key1": 0,
        "skipped_existing_key2": 0,
        "samples": [],
    }

    updates = []
    SAMPLE_MAX = 10

    for csv_row in csv_rows:
        cert, k1, t1, k2 = extract_cert_and_keys_from_csv_row(
            csv_row, priority_extractor2,
            lookup_don_fn=lookup_don_fn,
            catalog_valid_pids=catalog_valid_pids,
            catalog_set_map=catalog_set_map,
            lookup_yugioh_fn=lookup_yugioh_fn,
            extract_variant_alias_fn=extract_variant_alias_fn,
            get_variant_meta_fn=get_variant_meta_fn,
            get_category_fn=get_category_fn,
            get_catalog_variants_fn=get_catalog_variants_fn,
            identify_variant_by_image_fn=identify_variant_by_image_fn,
        )
        if not cert:
            result["skipped_no_cert"] += 1
            continue
        result["csv_with_cert"] += 1

        high_row_idx = cert_map.get(cert)
        if high_row_idx is None:
            result["skipped_cert_unmatched"] += 1
            continue
        result["matched"] += 1

        if not k1:
            result["skipped_no_key1"] += 1
            continue

        # 既存 KEY1 / KEY2 確認
        high_row = values[high_row_idx - 1]
        current_key1 = (
            (high_row[key1_col - 1] or "").strip()
            if len(high_row) >= key1_col
            else ""
        )
        current_key2 = (
            (high_row[key2_col - 1] or "").strip()
            if len(high_row) >= key2_col
            else ""
        )

        wrote_anything = False

        # KEY1: 自動 URL fallback 書込済なら card_id で上書き許容、
        # card/model は既存値尊重、 空なら書込
        if not current_key1:
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(high_row_idx, key1_col),
                    "values": [[k1]],
                }
            )
            result["written_key1"] += 1
            wrote_anything = True
        elif current_key1.startswith("item:") or current_key1.startswith("shops:"):
            # URL KEY → cert 経由で card_id 取れたなら upgrade
            if t1 in ("card", "model"):
                updates.append(
                    {
                        "range": gspread.utils.rowcol_to_a1(high_row_idx, key1_col),
                        "values": [[k1]],
                    }
                )
                result["written_key1"] += 1
                wrote_anything = True
            else:
                result["skipped_existing_key1"] += 1
        else:
            result["skipped_existing_key1"] += 1

        # KEY2: 既存値 skip、 空なら書込
        if not current_key2 and k2:
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(high_row_idx, key2_col),
                    "values": [[k2]],
                }
            )
            result["written_key2"] += 1
            wrote_anything = True
        elif current_key2:
            result["skipped_existing_key2"] += 1

        if wrote_anything and len(result["samples"]) < SAMPLE_MAX:
            title_preview = (csv_row.get(CSV_COL_TITLE) or "")[:50]
            result["samples"].append(
                f"HIGH row {high_row_idx}: cert={cert} → "
                f"KEY1={k1!r} KEY2={k2!r}  ({title_preview})"
            )

    if updates and not dry_run:
        CHUNK = 500
        for i in range(0, len(updates), CHUNK):
            ws.batch_update(updates[i : i + CHUNK], value_input_option="USER_ENTERED")

    return result


# ============================================================================
# Step 4 (= 2026-06-10): canonical KEY 単一化 API
# spec: iMak_data/KEY_REDESIGN_SPEC.md §2, §3
# resolver 経由で CSV row から canonical KEY 解決 → HIGH スプシ KEY 列に書込
# (= 旧 KEY1/KEY2 2 列書込 → 単一 KEY 列書込)
# ============================================================================

def write_canonical_key_to_high(
    ws,
    csv_path: Path,
    key_col: int,
    cert_col: int,
    category_col: int,
    tcg_category_value: str = "TCG",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """CSV を resolver 経由で canonical KEY 化 → HIGH の R='TCG' row に事前書込.

    spec §3, §4:
    - 各 CSV row を resolve() で canonical KEY 解決 (= 再 parse 禁止)
    - 解決不能 ("") row は skip + log
    - 既存 KEY が URL key の row は product_id で upgrade 許容
    - 既存 KEY が product_id の row は skip (= 手動補完尊重)

    Returns:
        {
          "csv_rows": ..., "csv_with_cert": ...,
          "high_tcg_rows": ..., "matched": ...,
          "written_key": ..., "upgraded_url_to_product_id": ...,
          "skipped_no_cert": ..., "skipped_cert_unmatched": ...,
          "skipped_no_resolution": ...,
          "skipped_existing_product_id": ...,
          "samples": [...],
        }
    """
    import gspread  # 遅延 (= test mock 容易)
    from . import resolver_io
    from .checker import (
        classify_canonical_key,
        KEY_TYPE_PRODUCT_ID,
        KEY_TYPE_URL_KEY,
    )

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    # 1. HIGH 全 values 読込 + cert → row index map 構築
    values = ws.get_all_values()
    cert_map = build_cert_to_row_index(
        values, category_col, cert_col, tcg_category_value
    )

    # 2. CSV 読込
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)

    result: Dict[str, Any] = {
        "csv_rows": len(csv_rows),
        "csv_with_cert": 0,
        "high_tcg_rows": sum(
            1
            for r in values[1:]
            if len(r) >= category_col
            and (r[category_col - 1] or "").strip() == tcg_category_value
        ),
        "matched": 0,
        "written_key": 0,
        "upgraded_url_to_product_id": 0,
        "skipped_no_cert": 0,
        "skipped_cert_unmatched": 0,
        "skipped_no_resolution": 0,
        "skipped_existing_product_id": 0,
        "samples": [],
    }

    updates = []
    SAMPLE_MAX = 10

    for csv_row in csv_rows:
        cert = (csv_row.get(CSV_COL_CERT) or "").strip()
        if not cert:
            result["skipped_no_cert"] += 1
            continue
        result["csv_with_cert"] += 1

        high_row_idx = cert_map.get(cert)
        if high_row_idx is None:
            result["skipped_cert_unmatched"] += 1
            continue
        result["matched"] += 1

        # === resolver 経由 canonical KEY 解決 (= 再 parse 禁止) ===
        canonical_key = resolver_io.resolve_csv_row(csv_row, purpose="listing")
        new_type = classify_canonical_key(canonical_key)

        if new_type != KEY_TYPE_PRODUCT_ID:
            # listing 用は product_id のみ採用 (= url key は HIGH 入稿前用途では使わない)
            result["skipped_no_resolution"] += 1
            continue

        # === 既存 KEY との突合 ===
        high_row = values[high_row_idx - 1]
        current_key = (
            (high_row[key_col - 1] or "").strip()
            if len(high_row) >= key_col
            else ""
        )

        wrote = False
        if not current_key:
            # 空 → 書込
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(high_row_idx, key_col),
                    "values": [[canonical_key]],
                }
            )
            result["written_key"] += 1
            wrote = True
        else:
            current_type = classify_canonical_key(current_key)
            if current_type == KEY_TYPE_URL_KEY:
                # url key → product_id upgrade
                updates.append(
                    {
                        "range": gspread.utils.rowcol_to_a1(high_row_idx, key_col),
                        "values": [[canonical_key]],
                    }
                )
                result["upgraded_url_to_product_id"] += 1
                wrote = True
            else:
                # 既に product_id (= 手動 or 自動補完済) → skip
                result["skipped_existing_product_id"] += 1

        if wrote and len(result["samples"]) < SAMPLE_MAX:
            title_preview = (csv_row.get(CSV_COL_TITLE) or "")[:50]
            result["samples"].append(
                f"HIGH row {high_row_idx}: cert={cert} → "
                f"KEY={canonical_key!r}  ({title_preview})"
            )

    if updates and not dry_run:
        CHUNK = 500
        for i in range(0, len(updates), CHUNK):
            ws.batch_update(updates[i : i + CHUNK], value_input_option="USER_ENTERED")

    return result
