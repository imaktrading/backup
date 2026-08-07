"""CSV 入稿前 自動物理除外 (Phase 1g).

eBay File Exchange 形式 CSV を読込み、 各 row から (KEY1, KEY2) tuple を抽出し、
既存出品スプシの (KEY1, KEY2) set と完全一致したら物理除外する。
元 CSV は `.bak` 拡張子で backup (= csv_postprocess/excluder.py と同型)。

依頼書 §6 仕様:
- 入力: eBay File Exchange 形式 CSV (= 出品くん生成)
- bak 保存 + 上書き保存
- console: 重複除外件数 / 残存件数 / KEY1 取れず件数 出力
- dry_run=True: 物理除外せず判定のみ print
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# === eBay File Exchange 列名 (= グローバル CLAUDE.md 規約) ===
COL_TITLE = "*Title"
COL_CARD_NUMBER = "C:Card Number"
COL_FEATURES = "C:Features"
COL_SPECIALITY = "C:Speciality"
COL_SET = "C:Set"
# Phase 1q (= 2026-05-28 体系再設計): リスティング無関係列を CSV に持たない方針.
# 旧 C:PSA Brand / C:PSA Subject / INTERNAL:KEY1 / INTERNAL:KEY2 列は撤回。
# cert → iMakeBayAPI cache → brand/subject 経由に切替 (= SoC/SSOT/DRY 統一)
COL_PIC_URL = "PicURL"
COL_PIC_URL_STAR = "*PicURL"
COL_CERT = "CDA:Certification Number - (ID: 27503)"


def extract_keys_from_csv_row(
    row: Dict[str, str],
    priority_extractor2: Callable,
    catalog_valid_pids: Optional[frozenset] = None,
    catalog_set_map: Optional[Dict] = None,
    lookup_yugioh_fn: Optional[Callable] = None,
    lookup_don_fn: Optional[Callable] = None,
    extract_variant_alias_fn: Optional[Callable] = None,
    get_variant_meta_fn: Optional[Callable] = None,
    get_category_fn: Optional[Callable] = None,
    get_catalog_variants_fn: Optional[Callable] = None,
    identify_variant_by_image_fn: Optional[Callable] = None,
) -> Tuple[Optional[str], str, str]:
    """CSV 1 row dict から (key1, key1_type, key2) を抽出.

    優先順 (= 出品くん仕様改善後を見越して C:Card Number 完全形を最優先):
    1. C:Card Number aspect が完全形 → key1 として採用
    2. *Title regex (= fallback)
    3. Phase 1k: catalog valid_pids 経由で title/card_num token 完全一致 verify
       (= Pokemon SV1V-086 / G-shock / Uniqlo 等 統合 cover)

    variant 抽出 source: *Title + C:Features / C:Speciality aspect。
    """
    from . import catalog_io  # 遅延 import

    title = (row.get(COL_TITLE) or "").strip()
    card_num = (row.get(COL_CARD_NUMBER) or "").strip()
    features = (row.get(COL_FEATURES) or "").strip()
    speciality = (row.get(COL_SPECIALITY) or "").strip()
    # Phase 1q (= 2026-05-28 体系再設計): cert → iMakeBayAPI cache → brand/subject
    # 旧 C:PSA Brand/Subject 列読込撤回、 SoC/SSOT/DRY 観点で cache 経由統一。
    cert = (row.get(COL_CERT) or "").strip()
    psa_brand = ""
    psa_subject = ""
    if cert:
        from . import iMakeBayAPI_psa_io as _psa_io
        psa_meta = _psa_io.get_cached_psa(cert)
        if psa_meta:
            psa_brand = (psa_meta.get("Brand") or "").strip()
            psa_subject = (psa_meta.get("Subject") or "").strip()

    extra_text = " ".join(s for s in (features, speciality) if s)

    def _apply_variant_meta_ssot(k1_val: str, k2_val: str) -> str:
        """Phase 1n: catalog 経由 KEY2 SSOT 化 (= title parse 値を catalog 公式値で上書き).

        Phase 1o (= 5/28): 画像 hash 最終 fallback も同 helper 内で適用。
        """
        if not k1_val:
            return k2_val
        # Phase 1n: catalog Subject alias 経由
        if extract_variant_alias_fn and get_variant_meta_fn and get_category_fn:
            subject_for_alias = psa_subject or title
            catalog_variant = extract_variant_alias_fn(subject_for_alias)
            if catalog_variant:
                category_phase_n = get_category_fn(k1_val)
                if category_phase_n:
                    meta = get_variant_meta_fn(k1_val, catalog_variant, category_phase_n)
                    if meta:
                        return catalog_variant  # SSOT 上書き
        # Phase 1o: 画像 hash 最終 fallback (= k2 まだ取れない場合のみ)
        if not k2_val and get_catalog_variants_fn and identify_variant_by_image_fn and get_category_fn:
            image_url = (row.get(COL_PIC_URL_STAR) or row.get(COL_PIC_URL) or "").strip()
            if image_url:
                category_phase_o = get_category_fn(k1_val)
                if category_phase_o:
                    variants = get_catalog_variants_fn(k1_val, category_phase_o)
                    if variants:
                        v = identify_variant_by_image_fn(image_url, variants)
                        if v:
                            return v
        return k2_val

    # *Title 優先で抽出
    k1, t1, k2 = priority_extractor2(title, "", extra_text)
    if k1:
        k2 = _apply_variant_meta_ssot(k1, k2)
        return k1, t1, k2

    # title hit せず + C:Card Number に値あれば key1 代替試行
    if card_num:
        k1, t1, k2 = priority_extractor2(card_num, "", extra_text)
        if k1:
            k2 = _apply_variant_meta_ssot(k1, k2)
            return k1, t1, k2

    # Phase 1k: catalog token verify fallback
    if catalog_valid_pids:
        for source_text in (title, card_num):
            if not source_text:
                continue
            hit = catalog_io.find_product_id_in_text(source_text, catalog_valid_pids)
            if hit:
                k2_ssot = _apply_variant_meta_ssot(hit[0], "")
                return hit[0], "card", k2_ssot

    # Phase 1k 拡張 (= 2026-05-27): C:Card Number 連番 + C:Set 経由 reconstruct
    # 出品くんが Pokemon 等で C:Card Number に連番のみ書込 (= `086`)、
    # C:Set に「Violet ex」 等 set 名書込のケース → catalog で SV1V-086 復元
    if card_num and catalog_valid_pids and catalog_set_map:
        set_val = (row.get(COL_SET) or "").strip()
        cid, reason = catalog_io.reconstruct_card_id(
            card_num, set_val, catalog_set_map, catalog_valid_pids
        )
        if cid and "verified" in reason:
            k2_ssot = _apply_variant_meta_ssot(cid, "")
            return cid, "card", k2_ssot

    # Phase 1l (= 2026-05-27): DON カード fallback (= C:PSA Brand/Subject 列経由)
    don_in_text = "DON" in (psa_subject + title).upper()
    if lookup_don_fn is not None and don_in_text:
        record = lookup_don_fn(
            brand=psa_brand or title,
            subject=psa_subject or title,
        )
        if record and record.get("product_id"):
            k2_ssot = _apply_variant_meta_ssot(record["product_id"], "")
            return record["product_id"], "card", k2_ssot

    # Phase 1l: YGO fallback (= PSA subject 経由 name fuzzy match)
    if lookup_yugioh_fn is not None and psa_brand and psa_subject:
        ygo_marker = any(k in (psa_brand + title).upper()
                          for k in ('YU-GI-OH', 'YUGIOH', 'YGO', '遊戯王'))
        if ygo_marker:
            record = lookup_yugioh_fn(
                brand=psa_brand,
                card_number=card_num,
                subject=psa_subject,
            )
            if record and record.get("product_id"):
                k2_ssot = _apply_variant_meta_ssot(record["product_id"], "")
                return record["product_id"], "card", k2_ssot

    return None, "", ""


def compute_keys_for_row(
    row: Dict[str, str],
) -> Tuple[Optional[str], str]:
    """Phase 1p (= 2026-05-28 C): 出品くん側越境 import 用 helper.

    HQ 出品くん `psa_to_csv.py` で本 fn を呼出して算出された (KEY1, KEY2) を
    CSV の `INTERNAL:KEY1` / `INTERNAL:KEY2` 列に書込 → 重複くん側で直接採用.

    重複くん本体と同じ logic (= extract_keys_from_csv_row) を呼出すが、 catalog
    関連 fn 等は内部で遅延 import (= 出品くん側で catalog 越境 import 不要).

    Returns: (key1, key2) — どちらも空文字列の可能性あり (= fail-closed).
    """
    from . import catalog_io
    from . import image_hash as _ih
    from .checker import extract_priority_key2

    # catalog 系 fn を全部内部で fetch (= 出品くん側からは pure 入出力に見える)
    try:
        con = catalog_io.open_catalog_readonly()
        try:
            valid_pids = catalog_io.load_valid_product_ids(con)
            set_map = catalog_io.load_set_name_map(con)
        finally:
            con.close()
    except Exception:
        valid_pids = None
        set_map = None

    k1, t1, k2 = extract_keys_from_csv_row(
        row,
        priority_extractor2=extract_priority_key2,
        catalog_valid_pids=valid_pids,
        catalog_set_map=set_map,
        lookup_yugioh_fn=catalog_io.lookup_yugioh,
        lookup_don_fn=catalog_io.lookup_don,
        extract_variant_alias_fn=catalog_io.extract_variant_alias,
        get_variant_meta_fn=catalog_io.get_variant_meta,
        get_category_fn=catalog_io.get_category_by_product_id,
        get_catalog_variants_fn=catalog_io.get_catalog_variants,
        identify_variant_by_image_fn=_ih.identify_variant_by_image,
    )
    return (k1 or ""), (k2 or "")


def check_csv(
    csv_path: Path,
    existing_tuples: frozenset,
    priority_extractor2: Callable,
    dry_run: bool = False,
    catalog_valid_pids: Optional[frozenset] = None,
    catalog_set_map: Optional[Dict] = None,
    lookup_yugioh_fn: Optional[Callable] = None,
    lookup_don_fn: Optional[Callable] = None,
    extract_variant_alias_fn: Optional[Callable] = None,
    get_variant_meta_fn: Optional[Callable] = None,
    get_category_fn: Optional[Callable] = None,
    get_catalog_variants_fn: Optional[Callable] = None,
    identify_variant_by_image_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """CSV を読込んで重複 row を除外.

    existing_tuples: 既存出品スプシから構築した (KEY1, KEY2) tuple set
        (= classify_existing_key で card/model 系は upper 正規化済の前提)

    Returns:
        {
          "total": ..., "removed": ..., "kept": ..., "unknown": ...,
          "removed_titles": [str, ...],
          "backup_path": str (= dry_run 時 ""),
          "csv_path": str,
        }
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    result: Dict[str, Any] = {
        "total": len(rows),
        "removed": 0,
        "kept": 0,
        "unknown": 0,
        "removed_titles": [],
        "backup_path": "",
        "csv_path": str(path),
    }

    if not rows:
        return result

    removed_indices = set()
    for i, row in enumerate(rows, start=1):
        k1, t1, k2 = extract_keys_from_csv_row(
            row, priority_extractor2,
            catalog_valid_pids=catalog_valid_pids,
            catalog_set_map=catalog_set_map,
            lookup_yugioh_fn=lookup_yugioh_fn,
            lookup_don_fn=lookup_don_fn,
            extract_variant_alias_fn=extract_variant_alias_fn,
            get_variant_meta_fn=get_variant_meta_fn,
            get_category_fn=get_category_fn,
            get_catalog_variants_fn=get_catalog_variants_fn,
            identify_variant_by_image_fn=identify_variant_by_image_fn,
        )
        if not k1:
            result["unknown"] += 1
            continue
        # card/model 系は upper 正規化、 url は raw
        k1_norm = k1.upper() if t1 in ("card", "model") else k1
        if (k1_norm, k2) in existing_tuples:
            removed_indices.add(i)
            title_preview = (row.get(COL_TITLE) or "")[:60]
            result["removed_titles"].append(
                f"[{i}] (KEY1={k1_norm}, KEY2={k2!r}) {title_preview}"
            )

    kept_rows: List[Dict[str, str]] = [
        row for i, row in enumerate(rows, start=1) if i not in removed_indices
    ]
    result["removed"] = len(removed_indices)
    result["kept"] = len(kept_rows)

    if dry_run or not removed_indices:
        return result

    # backup + 上書き保存
    backup_path = str(path) + ".bak"
    shutil.copy2(str(path), backup_path)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            quoting=csv.QUOTE_NONNUMERIC,
        )
        writer.writeheader()
        writer.writerows(kept_rows)
    result["backup_path"] = backup_path
    return result


# ============================================================================
# Step 4 (= 2026-06-10): canonical KEY 単一化 API
# spec: iMak_data/KEY_REDESIGN_SPEC.md §2, §3
# - resolver 経由 (= 再導出禁止)
# - 単一 KEY 突合 (= tuple 廃止)
# - 表示と実体の SSOT (= 同 removed_indices set を集計・物理書換両方の source とする)
# ============================================================================

def check_csv_canonical(
    csv_path: Path,
    existing_canonical_keys: "frozenset[str]",
    dry_run: bool = False,
    strict_mode: bool = False,
    migration_dual_match: bool = True,
    existing_cert_set: Optional["frozenset[str]"] = None,
) -> Dict[str, Any]:
    """CSV を resolver 経由で canonical KEY 化 → 既存 set と単一突合 → 重複物理除外.

    spec §3, §4, §6:
    - 各 row を resolve() で canonical KEY 解決 (= 再 parse 禁止)
    - existing_canonical_keys に完全一致 → 物理除外
    - 解決不能 ("") → unknown 計上 (= 既定では keep。 strict_mode=True 時のみ除外)

    spec §5 仮説対応: 表示用 statistics と 物理 kept_rows を **同一 indices set** から導出 (= SSOT).
    呼出側で結果 dict と 書込 file を見比べたとき件数一致を保証.

    strict_mode (= 2026-06-16 デフォルト False に是正):
    - **False (デフォルト)**: 解決不能 row は keep。 物理除外は既存 KEY 完全一致の真の重複だけ。
      = グローバル原則 failclosed_must_skip_not_destructive (判定不能は破壊側に倒さない) の正。
      6/16 Mercari (Porter 等 catalog KEY 無し 1 点もの) 全除外事故の根本対応。
    - True (opt-in): 解決不能 row も物理除外 (= 出品 skip、 listing-safety 用途)。
      ※ 旧 6/10 既定。 出品可否の fail-closed は listing script 側で担保済のため dedup 段の
        unresolved 除外は原則 over-reach。 明示時のみ使う。

    2026-08-07 (= 依頼書 `..._dedupe_owns_both_key_and_cert_response.md`):
    - **existing_cert_set** 追加。 CSV row の cert (CDA:Certification Number 列) が
      set に含まれれば **無条件除外** (= 同一物理 slab の二重出品防止)。
    - 判定順序 = **cert → KEY**。 cert で確定した row は KEY 判定を実行しない (= SSOT)。
    - token (= タイトル部分一致) は本関数では **落とさない** (= 別セット同番号巻き込み防止)。
      warning-only 位置づけは呼出側 UX で扱う。
    - 除外理由は result["removed_by_type"] = {"cert":N, "key":M} で内訳保持 (= 台帳監査用)。
    - result["removed_certs"] に除外 cert list を保持 (= 台帳 audit 用)。

    Returns:
        {
          "total": int, "removed": int, "kept": int, "unknown": int,
          "removed_titles": [str, ...],
          "skipped_unresolved": int (= strict_mode で除外された件数),
          "removed_canonical_keys": [str, ...],  (= KEY 一致で除外された canonical KEY)
          "removed_certs": [str, ...],           (= cert 一致で除外された cert list)
          "removed_by_type": {"cert": int, "key": int},  (= 除外理由の内訳)
          "backup_path": str (= dry_run 時 ""),
          "csv_path": str,
        }
    """
    from . import resolver_io  # 遅延 import

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    result: Dict[str, Any] = {
        "total": len(rows),
        "removed": 0,
        "kept": 0,
        "unknown": 0,
        "skipped_unresolved": 0,
        "removed_titles": [],
        "removed_canonical_keys": [],  # 2026-06-12 scope1: DUP マーカー書込用
        "removed_certs": [],           # 2026-08-07: cert 一致で除外された cert list
        "removed_by_type": {"cert": 0, "key": 0},  # 2026-08-07: 除外理由の内訳
        "backup_path": "",
        "csv_path": str(path),
    }

    if not rows:
        return result

    # === SSOT 表示/実体一致: 「除外対象 indices」 を唯一の source とする ===
    # 表示用 (= result["removed"]) も物理書換 (= kept_rows 生成) も同一 set から導出.
    removed_indices: set = set()
    unresolved_indices: set = set()

    # 2026-07-27 Phase1b: 既存 KEー set を group_key 正規化 (= カテゴリ込み突合)。
    # 旧 `ST02-010` と 新 `gundam_tcg:ST02-010` は別 group_key → 別グループ
    # (= 移行期に混ぜない、 出品機会を守る側)。 url-key / 旧形式は恒等 (= 後方互換)。
    from .key_format import group_key, build_key
    existing_grouped = frozenset(group_key(k) for k in existing_canonical_keys)

    # 2026-08-07: cert 集合 (= 同一物理 slab の識別子)。 None なら cert 判定 skip。
    # 依頼書 §Q2: cert 一致 = 無条件除外 (二度売れたら履行不能 = BAN リスク)。
    cert_set = existing_cert_set or frozenset()

    # 2026-07-27 Phase3 案2: 候補を **prefixed で解決**しつつ、既存 set とは
    # **prefixed 形 と bare(product_id) 形 の両方で照合** する移行 dual-mode。
    # - prefixed 形 → 新形式に振り直された既存とマッチ (= Phase2b/upgrade 済分)
    # - bare 形 → 旧形式のまま残る既存とマッチ (= Phase3 未完了分。 fail-open 防止)
    # url-key は category="" で prefix されないため bare 形と一致 (= 従来どおり)。
    # 移行完了 (旧形式が枯れた) 後は migration_dual_match=False で bare 照合を落とす。
    for i, row in enumerate(rows, start=1):
        # 2026-08-07: 判定順序 cert → KEY (= 上位で確定した row は下位を評価しない、 SSOT)。
        # cert は resolver に渡さず直接 CSV の CDA 列を見る (= resolver 挙動に非依存)。
        row_cert = (row.get(COL_CERT) or "").strip()
        if row_cert and row_cert in cert_set:
            # 同一 slab の二重出品 → 無条件除外 (依頼書 §Q2)
            removed_indices.add(i)
            result["removed_by_type"]["cert"] += 1
            if row_cert not in result["removed_certs"]:
                result["removed_certs"].append(row_cert)
            title_preview = (row.get(COL_TITLE) or "")[:60]
            result["removed_titles"].append(
                f"[{i}] (cert={row_cert}) {title_preview}"
            )
            continue

        res = resolver_io.resolve_csv_row_with_category(row, purpose="dedup")
        pid = (res.get("product_id") or "").strip()
        cat = (res.get("category") or "").strip()
        canonical_key = build_key(cat, pid)  # prefixed / url-key / ""
        if not canonical_key:
            # 解決不能 → unknown 計上、 strict_mode で除外対象に
            result["unknown"] += 1
            unresolved_indices.add(i)
            if strict_mode:
                removed_indices.add(i)
                title_preview = (row.get(COL_TITLE) or "")[:60]
                result["removed_titles"].append(
                    f"[{i}] (unresolved) {title_preview}"
                )
                result["skipped_unresolved"] += 1
            continue
        # 照合形の集合: prefixed 形 (+ dual-mode 時は catalog-backed に限り bare 形)
        match_forms = {group_key(canonical_key)}
        if migration_dual_match and cat:
            # catalog-backed のみ bare(product_id) も照合 (= 旧形式既存に当てる)。
            # url-key (cat="") は bare 追加しない (= prefixed 形と同一で二重不要)。
            match_forms.add(pid)
        if match_forms & existing_grouped:
            # 2026-06-12 scope1: 重複除外 KEY を記録 (= DUP マーカー書込用)
            if canonical_key not in result["removed_canonical_keys"]:
                result["removed_canonical_keys"].append(canonical_key)
            removed_indices.add(i)
            result["removed_by_type"]["key"] += 1
            title_preview = (row.get(COL_TITLE) or "")[:60]
            result["removed_titles"].append(
                f"[{i}] (KEY={canonical_key}) {title_preview}"
            )

    # 単一 source (= removed_indices) から両方導出 → 表示/実体 SSOT 保証
    kept_rows: List[Dict[str, str]] = [
        row for i, row in enumerate(rows, start=1) if i not in removed_indices
    ]
    result["removed"] = len(removed_indices)
    result["kept"] = len(kept_rows)

    # invariant assertion (= 表示/実体一致の構造的保証)
    assert result["total"] == result["removed"] + result["kept"], (
        f"SSOT invariant violation: "
        f"total={result['total']} != removed={result['removed']} + kept={result['kept']}"
    )

    if dry_run or not removed_indices:
        return result

    # backup + 上書き保存 (= 同一 kept_rows から書出 = SSOT)
    backup_path = str(path) + ".bak"
    shutil.copy2(str(path), backup_path)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            quoting=csv.QUOTE_NONNUMERIC,
        )
        writer.writeheader()
        writer.writerows(kept_rows)
    result["backup_path"] = backup_path
    return result
