"""iMakTCG/psa_to_csv.py 向けのアダプタ — 旧 bandai_jp.lookup_bandai_card の drop-in 置換.

設計原則:
  - **ID 完全一致 lookup のみ**. 名前検索フォールバック禁止 (= PRB02-005 事故再発防止)
  - 旧 bandai_jp.fetch_card 互換の dict を返す → psa_to_csv 側のコード変更を最小化
  - eBay フィルタ値変換 (set_name / rarity) は iMakCatalog.api.to_ebay_value で完結
    → psa_to_csv の `_onepiece_set_to_ebay` / `_onepiece_rarity_to_ebay` /
      `_extract_set_name_from_get_info` / `_ONEPIECE_SET_NAME_MAP` は不要 (削除推奨)

iMakTCG/psa_to_csv.py への適用例:

    # 削除する import:
    # import bandai_jp

    # 追加する import:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "iMakCatalog"))
    from integrations import psa_to_csv as catalog_psa

    # 変更する callsite (元: psa_to_csv.py:1528 周辺):
    # OLD:
    #   bandai = lookup_bandai_card(driver, brand, card_number, subject)
    # NEW:
    #   bandai = catalog_psa.lookup_one_piece(brand, card_number, subject)
    #   ※ driver 引数は不要 (DB 検索のみ、Selenium 不要)

    # 削除可: lookup_bandai_card / _onepiece_rarity_to_ebay /
    #         _onepiece_set_to_ebay / _onepiece_set_code_to_name /
    #         _extract_set_name_from_get_info / _ONEPIECE_SET_NAME_MAP
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# iMakCatalog/api.py を import
_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # noqa: E402

CATEGORY = "one_piece_tcg"


# ============================================================================
# Set code → eBay 公式名 (旧 psa_to_csv._onepiece_set_code_to_name の置換)
# ============================================================================
def set_code_to_ebay_name(set_value: str) -> str:
    """set_code または set 全文を eBay 公式名に変換. 未収録は元の値をそのまま返す
    (旧 _onepiece_set_code_to_name の挙動を踏襲、Vision OCR 長文にも対応).

    検索順: set_code → set (full string) フィールド.

    例:
      'OP-13'                                       → 'Carrying On His Will'
      'BOOSTER PACK -WINGS OF THE CAPTAIN- [OP-06]' → 'Wings of the Captain'  (set_code 抽出)
      'PREMIUM BOOSTER -ONE PIECE CARD THE BEST-'   → 'Premium Booster One Piece The Best' (set 全文一致)
      'OP-99'                                       → 'OP-99'  (未登録)
      ''                                            → ''
    """
    if not set_value:
        return set_value
    # 1st: set_code 直接一致 (例: 'OP-13')
    ebay = api.to_ebay_value(CATEGORY, "set_code", set_value)
    if ebay:
        return ebay
    # 2nd: 文字列内に bracket [XX-NN] / 【XX-NN】 が含まれていれば抽出して set_code 引き
    import re
    m = re.search(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]", set_value)
    if m:
        ebay = api.to_ebay_value(CATEGORY, "set_code", m.group(1))
        if ebay:
            return ebay
    # 3rd: set 全文一致 (Vision OCR 由来の長文等)
    ebay = api.to_ebay_value(CATEGORY, "set", set_value)
    if ebay:
        return ebay
    return set_value


# ============================================================================
# PSA Brand → 公式 set_code 抽出 (旧 psa_to_csv.extract_set_code_from_brand 移植)
# ============================================================================
def extract_set_code_from_brand(brand: str) -> Optional[str]:
    """PSA Brand 文字列から Bandai 公式 set_code を抽出.

    例:
      'ONE PIECE JAPANESE OP08-TWO LEGENDS'  → 'OP08'
      'ONE PIECE JAPANESE PRB02 PROMOS'      → 'PRB02'
      'ONE PIECE DAY 23 PROMOS'              → 'P'
    """
    if not brand:
        return None
    b = brand.upper()
    m = re.search(r"\b(OP\d+|ST\d+|EB\d+|PRB\d+)\b", b)
    if m:
        return m.group(1)
    promo_keywords = [
        "PROMOS", "PROMO", "ONE PIECE DAY", "BANDAI CARD GAME FEST",
        "ANNIVERSARY", "PREMIUM CARD COLLECTION", "CHAMPIONSHIP",
        # 2026-05-01: Mini-Tin Vol.2 Bonney(P-113)/Robin(P-111) 事故対応.
        # PSA brand 'MINI-TIN VOL.2 ROKUSHIRO' 等が認識されず PSA Subject にフォールバック →
        # C:Card Name 汚染 / P- prefix 欠落の連鎖.
        "MINI-TIN", "MINI TIN",
    ]
    if any(k in b for k in promo_keywords):
        return "P"
    return None


# ============================================================================
# PSA Subject ↔ DB record の名前検証 (= ID hit 後の sanity check、search fallback ではない)
# ============================================================================
_SUBJECT_STOPWORDS = {
    # PSA 上の修飾語・カテゴリ語 (キャラ名ではないので除外)
    "THE", "OF", "AND", "FOR", "WITH",
    "ALTERNATE", "ALT", "SPECIAL", "ART", "PARALLEL", "MANGA", "FOIL", "HOLO",
    "RARE", "PROMO", "PROMOS", "PURCHASE", "BONUS",
    "ONE", "PIECE", "CARD", "CARDS", "GAME", "TCG",
    "DAY", "FEST", "BANDAI", "PACKS", "BATTLE", "WINNER", "KING", "PIRATES",
    "ANNIVERSARY", "PREMIUM", "COLLECTION",
    "ICHIBAN", "KUJI", "WEEKLY", "SHONEN", "JUMP",
    "MINI", "TIN", "SET", "VOL", "EDITION",
    "PCC", "SP", "FA", "AR", "SR", "RR", "SAR",
    "JAPANESE", "JAPAN", "JPN", "JP",
}


def _subject_tokens(subject: str) -> set[str]:
    """PSA Subject から名前検証に使う有意トークンを抽出 (3文字以上、stopword/数字除外)."""
    if not subject:
        return set()
    raw = re.split(r"[\s/\-]+", subject.upper())
    out: set[str] = set()
    for w in raw:
        w = w.strip(".,;:'’\"")
        if len(w) < 3 or w.isdigit():
            continue
        if w in _SUBJECT_STOPWORDS:
            continue
        out.add(w)
    return out


# JA-only record 用の補助マップ: 日本語キャラ名 → 想定 PSA Subject token 群.
# 使用箇所は **検証 (ID hit 後の sanity check) のみ**, lookup には使わない (CLAUDE.md の
# 「名前検索フォールバック禁止」とは目的が異なる).
# 不足キャラがあると false negative (= reject) になるが、selfcheck が下流で再チェックする.
_JA_CHAR_TO_EN_TOKENS: dict[str, set[str]] = {
    "モンキー・D・ルフィ":   {"MONKEY", "LUFFY"},
    "モンキー・Ｄ・ルフィ":   {"MONKEY", "LUFFY"},
    "ロロノア・ゾロ":         {"RORONOA", "ZORO"},
    "ナミ":                   {"NAMI"},
    "ウソップ":               {"USOPP"},
    "サンジ":                 {"SANJI"},
    "トニートニー・チョッパー": {"TONY", "CHOPPER"},
    "ニコ・ロビン":           {"NICO", "ROBIN"},
    "フランキー":             {"FRANKY"},
    "ブルック":               {"BROOK"},
    "ジンベエ":               {"JINBE"},
    "ヤマト":                 {"YAMATO"},
    "ウタ":                   {"UTA"},
    "シャンクス":             {"SHANKS"},
    "トラファルガー・ロー":   {"TRAFALGAR", "LAW"},
    "ポートガス・D・エース":  {"PORTGAS", "ACE"},
    "ボア・ハンコック":       {"BOA", "HANCOCK"},
    "ジュエリー・ボニー":     {"JEWELRY", "BONNEY"},
    "レベッカ":               {"REBECCA"},
    "カイドウ":               {"KAIDOU", "KAIDO"},
    "ビッグ・マム":           {"BIG", "MOM"},
    "マルコ":                 {"MARCO"},
    "エドワード・ニューゲート": {"EDWARD", "NEWGATE", "WHITEBEARD"},
    "ドンキホーテ・ドフラミンゴ": {"DONQUIXOTE", "DOFLAMINGO"},
    "ネフェルタリ・ビビ":     {"NEFELTARI", "VIVI"},
    "ビビ":                   {"VIVI"},
    "ペローナ":               {"PERONA"},
    "サボ":                   {"SABO"},
    "バルトロメオ":           {"BARTOLOMEO"},
    "クロコダイル":           {"CROCODILE"},
    "ジュラキュール・ミホーク": {"DRACULE", "MIHAWK"},
    "ミホーク":               {"MIHAWK"},
    "スモーカー":             {"SMOKER"},
    "クザン":                 {"KUZAN", "AOKIJI"},
    "ボルサリーノ":           {"BORSALINO", "KIZARU"},
    "サカズキ":               {"SAKAZUKI", "AKAINU"},
    "ガープ":                 {"GARP"},
    "センゴク":               {"SENGOKU"},
    "レイリー":               {"RAYLEIGH"},
    "ゴール・D・ロジャー":    {"ROGER"},
    "マーシャル・D・ティーチ": {"MARSHALL", "TEACH", "BLACKBEARD"},
    "ベポ":                   {"BEPO"},
    "バギー":                 {"BUGGY"},
    "エネル":                 {"ENEL", "ENERU"},
    "アーロン":               {"ARLONG"},
    "キッド":                 {"KID", "EUSTASS"},
    "ユースタス・キッド":     {"EUSTASS", "KID"},
    "シーザー":               {"CAESAR"},
    "ローラ":                 {"LOLA"},
    "カポネ":                 {"CAPONE", "BEGE"},
    "ウルージ":               {"UROUGE"},
    "ホーキンス":             {"HAWKINS"},
    "しらほし":               {"SHIRAHOSHI"},
    "コビー":                 {"KOBY"},
    "ローラ・ベイ":           {"ROLLER"},
    "カク":                   {"KAKU"},
    "モダ":                   {"MODA"},
    "アルファ":               {"ALPHA"},
    "ゼフ":                   {"ZEFF"},
    "リューマ":               {"RYUMA", "RYUUMA"},
}


def _record_name_matches_subject(record: dict, subject: str) -> bool:
    """ID hit した record の name (en + jp) が PSA Subject トークンと交差するか.

    交差しない場合 = 同じ ID が DB と PSA で別カードを指している ≒ Bonney 事件パターン.
    トークンが取れない (subject 空 or stopwords のみ) → 検証スキップで True.

    JA-only record (name フィールドが日本語) の場合、_JA_CHAR_TO_EN_TOKENS を介して
    PSA Subject トークンと照合する.
    """
    tokens = _subject_tokens(subject)
    if not tokens:
        return True
    name_en = (record.get("name") or "").upper()
    name_jp = record.get("name_jp") or ""
    # 1. EN/混在 name の直接一致
    combined = name_en + " " + name_jp.upper()
    if any(t in combined for t in tokens):
        return True
    # 2. JA-only record: 日本語名 → 想定 EN tokens に変換して照合
    expected = _JA_CHAR_TO_EN_TOKENS.get(name_jp, set())
    if expected & tokens:
        return True
    return False


# ============================================================================
# variant 候補 (PSA Subject ヒント → product_id suffix)
# ============================================================================
_VARIANT_HINT_TO_SUFFIXES = {
    "ALTERNATE ART":   ["p1", "p2", "p3", "p", "p4"],
    "ALT ART":         ["p1", "p2", "p3", "p"],
    "ALTERNATE":       ["p1", "p2", "p3", "p"],
    "PARALLEL":        ["p1", "p2", "p3", "p"],
    "SPECIAL ART":     ["p1", "p2", "p3", "p"],
    "SPECIAL CARD":    ["p1", "p2", "p"],
    "SPECIAL":         ["p1", "p2", "p3", "p"],
    "MANGA":           ["p1", "p2", "p"],
    "FOIL":            ["p1", "p"],
}


def _variant_candidates(subject: str) -> list[str]:
    """PSA Subject から variant suffix 候補を返す (探索順)."""
    if not subject:
        return []
    subj = subject.upper()
    seen: set[str] = set()
    out: list[str] = []
    for hint, suffixes in _VARIANT_HINT_TO_SUFFIXES.items():
        if hint in subj:
            for s in suffixes:
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


# ============================================================================
# 旧 bandai_jp.fetch_card 形式に変換
# ============================================================================
def _to_legacy_dict(record: dict) -> dict:
    """iMakCatalog の lookup() result → 旧 bandai_jp 形式.

    psa_to_csv.py:1530 周辺がアクセスする全フィールドを満たす.

    新規追加 (旧形式に無い):
      - set_name_ebay   : eBay フィルタ表示値 (record.set_name と同じ、明示用)
      - card_text       : eBay description / 検索性向上で活用可
      - card_text_jp    : 日本語効果テキスト
      - language        : 'en' / 'ja' / 'both'
    """
    specs = record.get("specs") or {}
    return {
        # 旧 bandai_jp 互換フィールド
        "card_id":       record.get("product_id", ""),
        "name_en":       record.get("name", ""),
        "name_jp":       record.get("name_jp"),
        "type_en":       specs.get("Card Type", ""),
        "rarity_en":     specs.get("Rarity", ""),
        "color_en":      specs.get("Color", ""),
        "power":         specs.get("Power", ""),
        "life_or_cost":  specs.get("Cost/Life", ""),
        "counter":       specs.get("Counter+", ""),
        "attribute_en":  specs.get("Attribute", ""),
        "feature_jp":    specs.get("Type", ""),     # Bandai の "Type" = キャラ特徴 (例: "麦わらの一味")
        "get_info_jp":   record.get("set_name_official", ""),
        "image_file":    "",                          # 旧形式の互換用 (使われていない)
        # iMakCatalog 拡張フィールド (新規)
        "set_name_ebay": record.get("set_name", ""),
        "set_name_official": record.get("set_name_official", ""),
        "card_text":     specs.get("card_text", ""),
        "card_text_jp":  specs.get("card_text_jp", ""),
        "language":      record.get("language"),
        "card_set_id":   record.get("card_set_id"),
        "regulations":   specs.get("regulations", []),
        "legality":      specs.get("legality", {}),
        "illustrator":   specs.get("illustrator"),
        "images":        record.get("images", []),
    }


# ============================================================================
# メイン: lookup_one_piece
# ============================================================================
def lookup_one_piece(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """One Piece カードを iMakCatalog DB から ID 完全一致で lookup.

    手順:
      1) PSA Brand から set_code 抽出 → base product_id を組み立て (例: "OP06-022")
      2) base lookup
      3) None の場合のみ、PSA Subject の variant ヒント (ALTERNATE ART / PARALLEL 等)
         から候補 suffix を試行 (`OP06-022_p`, `_p1`, `_p2` ...)
      4) 全部 None なら → return None (= フォールバック禁止、psa_to_csv 側で空欄出品)

    Args:
        brand: PSA Brand 文字列 (例: 'ONE PIECE JAPANESE OP06-WINGS OF THE CAPTAIN')
        card_number: PSA card number (例: '022')
        subject: PSA Subject (例: 'MONKEY D LUFFY ALTERNATE ART') — variant 推測のみに使用
        verbose: True で stdout に進捗を出す (旧 bandai_jp.fetch_card 互換)

    Returns:
        旧 bandai_jp.fetch_card 互換 dict | None
    """
    if not card_number:
        return None
    set_code = extract_set_code_from_brand(brand)
    if not set_code:
        if verbose:
            print(f"    ⚠️ set_code 抽出失敗: brand={brand!r}")
        return None

    # 安全装置: promo brand (set_code='P') で subject トークン無し → ID 検証不能なので skip.
    # P-XXX は別キャラに当たることが多く (P-019=Bepo 等)、subject 検証無しに採用すると
    # 誤マッチの温床になる. Phase 1 booster (set_code='OP07' 等) は PSA brand が specific
    # なので subject 無しでも ID 一致を信頼する.
    if set_code == "P" and not _subject_tokens(subject):
        if verbose:
            print(f"    ⚠️ promo brand で PSA Subject トークン無し → 検証不能なので Skip "
                  f"(brand={brand!r}, subject={subject!r})")
        return None

    base_pid = f"{set_code}-{card_number}"

    # 1. base lookup + 名前検証 (Bonney→Bepo 事件防止)
    record = api.lookup(CATEGORY, base_pid)
    if record and not _record_name_matches_subject(record, subject):
        if verbose:
            print(f"    ⚠️ iMakCatalog ID hit {base_pid} ({record['name']}) "
                  f"だが PSA Subject {subject!r} と名前不一致 → reject")
        record = None

    # 2. variant 試行 (PSA Subject ヒント) — 同じ名前検証を適用
    if record is None:
        for suffix in _variant_candidates(subject):
            candidate_pid = f"{base_pid}_{suffix}"
            cand = api.lookup(CATEGORY, candidate_pid)
            if cand and _record_name_matches_subject(cand, subject):
                record = cand
                if verbose:
                    print(f"    🎯 iMakCatalog hit (variant): {candidate_pid}")
                break

    # 3. Promo brand fallback: PSA brand に specific set 無し (set_code="P") で base miss
    #    → 全 OP/ST/EB/PRB set_code に対して {番号} / {番号}_P / {番号}_p1 等を試行 + 名前検証
    #    例: PSA Brand 'PROMOS' + 番号 '019' + Subject 'JEWELRY BONNEY' →
    #        P-019 (Bepo) reject 後、OP07-019_P (Bonney WSJ 付録版) を救済
    if record is None and set_code == "P":
        record = _search_one_piece_promo_by_number(card_number, subject, verbose=verbose)

    # 4. Reprint/SP Alt fallback: PSA brand に specific set あり (例: OP11) で base miss
    #    → 全 set_code に対して {番号}_{PSA_set_code} suffix を試行 + 名前検証
    #    例: PSA Brand 'OP11' + 番号 '057' + Subject 'SHIRAHOSHI' →
    #        OP11-057 (Pedro) reject 後、EB01-057_OP11 (Shirahoshi 再録 SP Alt) を救済
    if record is None and set_code != "P":
        record = _search_one_piece_reprint_by_number(
            card_number, subject, set_code, verbose=verbose
        )

    if record is None:
        if verbose:
            print(f"    ⚠️ iMakCatalog 未登録 or 名前不一致: {base_pid} → Skip "
                  f"(subject={subject!r})")
        return None

    if verbose and "_" not in record["product_id"]:
        # base hit のみログ (variant hit は既にログ済み)
        print(f"    🎯 iMakCatalog hit: {record['product_id']} "
              f"{record['name']} ({record['specs'].get('Card Type', '?')}, "
              f"rarity={record['specs'].get('Rarity', '?')!r})")

    return _to_legacy_dict(record)


def _search_one_piece_reprint_by_number(
    card_number: str,
    subject: str,
    psa_set_code: str,
    verbose: bool = True,
) -> Optional[dict]:
    """SP Alt / Reprint fallback: PSA brand に specific set ({psa_set_code}) があるが
    base `{psa_set_code}-{number}` が別キャラに当たるケースを救済.

    DB には product_id `{ORIGINAL_SET}-{number}_{REPRINT_SET}` 形式で再録版が保存されている.
    例: PSA 'OP11-057 Shirahoshi' → DB は EB01-057_OP11 (EB-01 Shirahoshi の OP-11 再録)

    安全装置:
      - PSA Subject から有意トークンが取れること必須 (旧『名前検索フォールバック』とは別)
      - 番号は完全一致
      - PSA set_code が record の suffix (_OP11 等) に含まれることを確認
    """
    if not _subject_tokens(subject):
        return None
    if not psa_set_code:
        return None

    psa_sc_up = psa_set_code.upper()
    conn = api._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM products WHERE category = ? AND product_id LIKE ?",
            (CATEGORY, f"%-{card_number}_%"),
        ).fetchall()
    finally:
        conn.close()

    pat = re.compile(rf"^[A-Z]+\d*-{re.escape(card_number)}_(.+)$")
    candidates: list[dict] = []
    for r in rows:
        pid = r["product_id"]
        m = pat.match(pid)
        if not m:
            continue
        suffix = m.group(1)
        # PSA set_code (例 'OP11') が suffix のどこかに含まれることを要求
        # (suffix は 'OP11' / 'OP11_p' / 'OP11_LF' 等の形式)
        if psa_sc_up not in suffix.upper().split("_"):
            continue
        rec = api._row_to_dict(r)
        if _record_name_matches_subject(rec, subject):
            candidates.append(rec)

    if not candidates:
        return None

    # 同名 candidate が複数 → subject ヒントで base / SP Alt / parallel を選択
    subj_up = (subject or "").upper()
    wants_sp = any(k in subj_up for k in ("SPECIAL", "ALTERNATE", " SP", "ALT ART"))

    def _score(c: dict) -> int:
        pid = c.get("product_id", "")
        rarity = (c.get("specs") or {}).get("Rarity", "")
        s = 0
        # SP Alt ヒント時: '_SP' / '_dummy' suffix / rarity に 'SP' 含むものを優先
        if wants_sp:
            if "_SP" in pid:
                s += 200
            if "_dummy" in pid:
                s += 100
            if "SP" in (rarity or "").upper():
                s += 50
        else:
            # 通常: 短い product_id (base reprint) 優先
            s -= len(pid)
        return s

    candidates.sort(key=_score, reverse=True)
    chosen = candidates[0]
    if verbose:
        print(f"    🎯 iMakCatalog hit (reprint fallback): {chosen['product_id']} "
              f"{chosen['name']} (PSA set={psa_set_code} の再録版、{len(candidates)}件中"
              f"{', SP Alt 優先' if wants_sp else ''})")
    return chosen


def _search_one_piece_promo_by_number(
    card_number: str,
    subject: str,
    verbose: bool = True,
) -> Optional[dict]:
    """Promo brand fallback: 番号 + 名前検証で 全 set_code を横断検索.

    PSA Brand に specific set code が無い (= set_code='P') 時、`P-{number}` lookup が
    別キャラに当たるケース (例: P-019 = Bepo, でも実カードは OP07-019_P = Bonney) を救済.

    安全装置:
      - 番号は完全一致 (LIKE で曖昧検索しない)
      - 名前検証で PSA Subject トークンが record name と交差すること必須
      - 旧『名前検索フォールバック』(番号無視で名前検索) とは別物
    """
    # PSA Subject から有意な検証トークンが取れない → 救済しない (誤マッチ防止)
    if not _subject_tokens(subject):
        return None
    conn = api._connect()
    try:
        # product_id が `{prefix}-{card_number}` または `{prefix}-{card_number}_*` 形式
        # のもの全てを取得. SQL の LIKE は曖昧過ぎるので Python で厳密フィルタ.
        rows = conn.execute(
            "SELECT * FROM products WHERE category = ? AND product_id LIKE ?",
            (CATEGORY, f"%-{card_number}%"),
        ).fetchall()
    finally:
        conn.close()

    pat = re.compile(rf"^[A-Z]+\d*-{re.escape(card_number)}(_.+)?$")
    candidates: list[dict] = []
    for r in rows:
        pid = r["product_id"]
        if not pat.match(pid):
            continue
        # P-XXX 自体は base lookup で既に試行済み + 名前不一致だったのでスキップ
        if pid.startswith("P-") or pid == f"P-{card_number}":
            continue
        rec = api._row_to_dict(r)
        if _record_name_matches_subject(rec, subject):
            candidates.append(rec)

    if not candidates:
        return None

    # Promo brand の場合: _P / _P_* suffix 付き record を優先 (実物が promo 版だから)
    def _promo_score(rec: dict) -> int:
        pid = rec.get("product_id", "")
        # 末尾 '_P' または '_P_' suffix → 高優先 (promo 版そのもの)
        if re.search(r"_P(_|$)", pid):
            return 100
        # set_name_official が 'Promotion' / 'プロモーション' 含む → 中優先
        sn = (rec.get("set_name_official") or "").lower()
        if "promotion" in sn or "プロモーション" in (rec.get("set_name_official") or ""):
            return 50
        # base record (suffix 無し) → 低優先
        if "_" not in pid:
            return 10
        return 0

    candidates.sort(key=_promo_score, reverse=True)
    chosen = candidates[0]
    if verbose:
        pid = chosen["product_id"]
        print(f"    🎯 iMakCatalog hit (promo fallback): {pid} "
              f"{chosen['name']} (Subject='{subject}' と名前一致, "
              f"{len(candidates)}件中 promo 優先)")
    return chosen


# ============================================================================
# ============================================================================
# Gundam Card Game (game_id=16/15)
# ============================================================================
# ============================================================================
GUNDAM_CATEGORY = "gundam_tcg"


def extract_set_code_from_brand_gundam(brand: str) -> Optional[str]:
    """PSA Brand → Gundam 公式 set_code 抽出.
    例:
      'GUNDAM JAPANESE GD01-NEWTYPE RISING' → 'GD01'
      'GUNDAM CARD GAME ST01 EXTRA STARTER' → 'ST01'
    """
    if not brand:
        return None
    b = brand.upper()
    m = re.search(r"\b(GD\d+|ST\d+|EX\d+)\b", b)
    if m:
        return m.group(1)
    if any(k in b for k in ("PROMO", "PROMOS", "ANNIVERSARY", "CHAMPIONSHIP")):
        return "P"
    return None


# Gundam variant suffix 候補 (PSA Subject ヒント)
_GUNDAM_VARIANT_HINT_TO_SUFFIXES: dict[str, list[str]] = {
    "ALTERNATE ART":  ["para", "SP"],
    "ALT ART":        ["para", "SP"],
    "PARALLEL":       ["para"],
    "SPECIAL ART":    ["SP", "para"],
    "SPECIAL":        ["SP"],
    "FOIL":           ["para"],
}


def _variant_candidates_gundam(subject: str) -> list[str]:
    if not subject:
        return []
    subj = subject.upper()
    seen: set[str] = set()
    out: list[str] = []
    for hint, suffixes in _GUNDAM_VARIANT_HINT_TO_SUFFIXES.items():
        if hint in subj:
            for s in suffixes:
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


def _to_legacy_dict_gundam(record: dict) -> dict:
    """Gundam 用 record → psa_to_csv 互換 dict."""
    specs = record.get("specs") or {}
    return {
        # 旧 bandai_tcg_plus.fetch_card(game='gundam') 互換
        "card_name":     record.get("name", ""),
        "card_id":       record.get("product_id", ""),
        "card_number":   record.get("product_id", "").split("_")[0],  # variant 剥がし
        "name_en":       record.get("name", ""),
        "name_jp":       record.get("name_jp"),
        "card_type":     specs.get("Card Type", ""),
        "type_en":       specs.get("Card Type", ""),
        "rarity":        specs.get("Rarity", ""),
        "rarity_en":     specs.get("Rarity", ""),
        "color":         specs.get("Color", ""),
        "color_en":      specs.get("Color", ""),
        "power":         specs.get("AP", ""),     # Gundam: AP = Attack Power (One Piece の Power 相当)
        "hp":            specs.get("HP", ""),     # Gundam 固有
        "cost":          specs.get("Cost", ""),
        "level":         specs.get("Lv. (Level)", ""),
        "trait":         specs.get("Trait", ""),
        "feature_jp":    specs.get("Trait", ""),  # 旧形式互換
        "link_requirement": specs.get("Link Requirement", ""),
        "source_title":  specs.get("Source Title", ""),
        "zone":          specs.get("Zone", ""),
        "set_name":      record.get("set_name", ""),
        "set_name_ebay": record.get("set_name", ""),
        "set_name_official": record.get("set_name_official", ""),
        "get_info_jp":   record.get("set_name_official", ""),
        "card_text":     specs.get("card_text", ""),
        "card_text_jp":  specs.get("card_text_jp", ""),
        "language":      record.get("language"),
        "card_set_id":   record.get("card_set_id"),
        "regulations":   specs.get("regulations", []),
        "legality":      specs.get("legality", {}),
        "illustrator":   specs.get("illustrator"),
        "images":        record.get("images", []),
    }


def lookup_gundam(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """Gundam Card Game カードを iMakCatalog DB から ID 完全一致で lookup."""
    if not card_number:
        return None
    set_code = extract_set_code_from_brand_gundam(brand)
    if not set_code:
        if verbose:
            print(f"    ⚠️ Gundam set_code 抽出失敗: brand={brand!r}")
        return None

    base_pid = f"{set_code}-{card_number}"

    record = api.lookup(GUNDAM_CATEGORY, base_pid)
    if record and not _record_name_matches_subject(record, subject):
        if verbose:
            print(f"    ⚠️ iMakCatalog (Gundam) ID hit {base_pid} ({record['name']}) "
                  f"だが PSA Subject {subject!r} と名前不一致 → reject")
        record = None

    if record is None:
        for suffix in _variant_candidates_gundam(subject):
            cand = api.lookup(GUNDAM_CATEGORY, f"{base_pid}_{suffix}")
            if cand and _record_name_matches_subject(cand, subject):
                record = cand
                if verbose:
                    print(f"    🎯 iMakCatalog (Gundam) hit (variant): {base_pid}_{suffix}")
                break

    if record is None:
        if verbose:
            print(f"    ⚠️ iMakCatalog (Gundam) 未登録 or 名前不一致: {base_pid} → Skip "
                  f"(subject={subject!r})")
        return None

    if verbose and "_" not in record["product_id"]:
        print(f"    🎯 iMakCatalog (Gundam) hit: {record['product_id']} "
              f"{record['name']} ({record['specs'].get('Card Type', '?')}, "
              f"rarity={record['specs'].get('Rarity', '?')!r})")

    return _to_legacy_dict_gundam(record)


def set_code_to_ebay_name_gundam(set_value: str) -> str:
    """Gundam 用 set_code/set 文字列 → eBay 公式名."""
    if not set_value:
        return set_value
    ebay = api.to_ebay_value(GUNDAM_CATEGORY, "set_code", set_value)
    if ebay:
        return ebay
    m = re.search(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]", set_value)
    if m:
        ebay = api.to_ebay_value(GUNDAM_CATEGORY, "set_code", m.group(1))
        if ebay:
            return ebay
    ebay = api.to_ebay_value(GUNDAM_CATEGORY, "set", set_value)
    return ebay if ebay else set_value


# ============================================================================
# ============================================================================
# Dragon Ball Super Card Game (Fusion World) (game_id=10/11)
# ============================================================================
# ============================================================================
DRAGONBALL_CATEGORY = "dragonball_scg"


def extract_set_code_from_brand_dragonball(brand: str) -> Optional[str]:
    """PSA Brand → DBSCG 公式 set_code 抽出.
    例:
      'DRAGON BALL SUPER FUSION WORLD JAPANESE FB02 BLAZING AURA' → 'FB02'
      'DRAGON BALL FUSION WORLD JAPANESE FS04 STARTER FRIEZA'      → 'FS04'
    """
    if not brand:
        return None
    b = brand.upper()
    m = re.search(r"\b(FB\d+|FS\d+|SB\d+|FP\d+)\b", b)
    if m:
        return m.group(1)
    if any(k in b for k in ("PROMO", "PROMOS", "TOURNAMENT", "CHAMPIONSHIP")):
        return "FP"  # DBSCG promo prefix (要確認)
    return None


# DBSCG variant suffix 候補
_DRAGONBALL_VARIANT_HINT_TO_SUFFIXES: dict[str, list[str]] = {
    "ALTERNATE ART":  ["Leader_F_PARA", "PARA", "Leader_F_SUPERPARA"],
    "ALT ART":        ["Leader_F_PARA", "PARA"],
    "PARALLEL":       ["PARA", "Leader_F_PARA"],
    "SUPER PARALLEL": ["SUPERPARA", "Leader_F_SUPERPARA"],
    "SPECIAL":        ["SUPERPARA", "PARA"],
    "FOIL":           ["Leader_F", "PARA"],
}


def _variant_candidates_dragonball(subject: str) -> list[str]:
    if not subject:
        return []
    subj = subject.upper()
    seen: set[str] = set()
    out: list[str] = []
    for hint, suffixes in _DRAGONBALL_VARIANT_HINT_TO_SUFFIXES.items():
        if hint in subj:
            for s in suffixes:
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


def _to_legacy_dict_dragonball(record: dict) -> dict:
    """DBSCG 用 record → psa_to_csv 互換 dict."""
    specs = record.get("specs") or {}
    return {
        # 旧 bandai_tcg_plus.fetch_card(game='dragonball') 互換
        "card_name":     record.get("name", ""),
        "card_id":       record.get("product_id", ""),
        "card_number":   record.get("product_id", "").split("_")[0],
        "name_en":       record.get("name", ""),
        "name_jp":       record.get("name_jp"),
        "card_type":     specs.get("Type", ""),         # DBSCG: 'Type' = card type
        "type_en":       specs.get("Type", ""),
        "rarity":        specs.get("Rarity", ""),
        "rarity_en":     specs.get("Rarity", ""),
        "color":         specs.get("Color", ""),
        "color_en":      specs.get("Color", ""),
        "power":         specs.get("Power", ""),
        "cost":          specs.get("Energy", ""),       # DBSCG: 'Energy' = cost
        "specified_cost": specs.get("Specified Cost", ""),
        "combo_power":   specs.get("Combo power", ""),
        "special_trait": specs.get("Special Trait", ""),
        "feature_jp":    specs.get("Special Trait", ""),
        "set_name":      record.get("set_name", ""),
        "set_name_ebay": record.get("set_name", ""),
        "set_name_official": record.get("set_name_official", ""),
        "get_info_jp":   record.get("set_name_official", ""),
        "card_text":     specs.get("card_text", ""),
        "card_text_jp":  specs.get("card_text_jp", ""),
        "language":      record.get("language"),
        "card_set_id":   record.get("card_set_id"),
        "regulations":   specs.get("regulations", []),
        "legality":      specs.get("legality", {}),
        "illustrator":   specs.get("illustrator"),
        "images":        record.get("images", []),
    }


def lookup_dragonball(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """Dragon Ball SCG カードを iMakCatalog DB から ID 完全一致で lookup."""
    if not card_number:
        return None
    set_code = extract_set_code_from_brand_dragonball(brand)
    if not set_code:
        if verbose:
            print(f"    ⚠️ DBSCG set_code 抽出失敗: brand={brand!r}")
        return None

    base_pid = f"{set_code}-{card_number}"

    record = api.lookup(DRAGONBALL_CATEGORY, base_pid)
    if record and not _record_name_matches_subject(record, subject):
        if verbose:
            print(f"    ⚠️ iMakCatalog (DBSCG) ID hit {base_pid} ({record['name']}) "
                  f"だが PSA Subject {subject!r} と名前不一致 → reject")
        record = None

    if record is None:
        for suffix in _variant_candidates_dragonball(subject):
            cand = api.lookup(DRAGONBALL_CATEGORY, f"{base_pid}_{suffix}")
            if cand and _record_name_matches_subject(cand, subject):
                record = cand
                if verbose:
                    print(f"    🎯 iMakCatalog (DBSCG) hit (variant): {base_pid}_{suffix}")
                break

    if record is None:
        if verbose:
            print(f"    ⚠️ iMakCatalog (DBSCG) 未登録 or 名前不一致: {base_pid} → Skip "
                  f"(subject={subject!r})")
        return None

    if verbose and "_" not in record["product_id"]:
        print(f"    🎯 iMakCatalog (DBSCG) hit: {record['product_id']} "
              f"{record['name']} ({record['specs'].get('Type', '?')}, "
              f"rarity={record['specs'].get('Rarity', '?')!r})")

    return _to_legacy_dict_dragonball(record)


def set_code_to_ebay_name_dragonball(set_value: str) -> str:
    """DBSCG 用 set_code/set 文字列 → eBay 公式名."""
    if not set_value:
        return set_value
    ebay = api.to_ebay_value(DRAGONBALL_CATEGORY, "set_code", set_value)
    if ebay:
        return ebay
    m = re.search(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]", set_value)
    if m:
        ebay = api.to_ebay_value(DRAGONBALL_CATEGORY, "set_code", m.group(1))
        if ebay:
            return ebay
    ebay = api.to_ebay_value(DRAGONBALL_CATEGORY, "set", set_value)
    return ebay if ebay else set_value


# ============================================================================
# ============================================================================
# Pokemon TCG (Japanese, pokemon-card.com)
# ============================================================================
# ============================================================================
POKEMON_CATEGORY = "pokemon_tcg"


# PSA Brand に set_code が含まれず set 名のみの場合の逆引きマップ.
# 出典: 各 set の公式日本語名 + 対応 set_code (image_url 由来).
# 新弾追加時は本マップにも追記.
_POKEMON_SET_NAME_TO_CODE: dict[str, str] = {
    # Sword & Shield
    "25TH ANNIVERSARY COLLECTION": "S8a",
    "VSTAR UNIVERSE":              "S12a",
    "VMAX CLIMAX":                 "S8b",
    "SHINY STAR V":                "S4a",
    "EEVEE HEROES":                "S6a",
    "STAR BIRTH":                  "S9",
    "BATTLE REGION":               "S9a",
    "TIME GAZER":                  "S10D",
    "SPACE JUGGLER":               "S10P",
    "DARK PHANTASMA":              "S10a",
    "LOST ABYSS":                  "S11",
    "INCANDESCENT ARCANA":         "S11a",
    "PARADIGM TRIGGER":            "S12",
    # Scarlet & Violet
    "SHINY TREASURE EX":           "SV4a",
    "TERASTAL FESTIVAL EX":        "SV8a",
    "POKEMON 151":                 "SV2a",
    "RULER OF THE BLACK FLAME":    "SV3",
    "RAGING SURF":                 "SV3a",
    "FUTURE FLASH":                "SV4",
    "WILD FORCE":                  "SV5K",
    "CYBER JUDGE":                 "SV5M",
    "CRIMSON HAZE":                "SV5a",
    "MASK OF CHANGE":              "SV6",
    "NIGHT WANDERER":              "SV6a",
    "STELLAR MIRACLE":             "SV7",
    "PARADISE DRAGONA":            "SV7a",
    "SUPER ELECTRIC BREAKER":      "SV8",
    "BATTLE PARTNERS":             "SV9",
    "HEAT WAVE ARENA":             "SV9a",
    "ROCKET GANG":                 "SV10",
    "BLACK BOLT":                  "SV11B",
    "WHITE FLARE":                 "SV11W",
    # Mega
    "MEGA DREAM EX":               "M2a",
    # Sun & Moon
    "TAG ALL STARS":               "SM12a",
    "TAG TEAM":                    "SM12a",
    "GX ULTRA SHINY":              "SM8b",
    "GX BATTLE BOOST":             "SM4p",
    "THE BEST OF XY":              "XY",
}


def extract_set_code_from_brand_pokemon(brand: str) -> Optional[str]:
    """PSA Brand → Pokemon 公式 set_code 抽出.

    Pokemon set codes は多様で混在 (M2a, S8a, S9a, SV1, SV2a, sv5K 等).
    大文字小文字も微妙 (公式 image_url='M2a', PSA brand='M2A').

    抽出順:
      1) Brand に set_code 文字列が直接含まれる (例: 'M2A', 'SV8A') → 末尾英字小文字化
      2) Brand に set 名キーワードが含まれる (例: '25TH ANNIVERSARY COLLECTION' → 'S8a')
      3) PROMO/PROMOS/JUMBO → 'P'
      4) None
    """
    if not brand:
        return None
    b = brand.upper()
    # 1) Standard alphanumeric set codes
    m = re.search(r"\b(SV[0-9]+[A-Z]?|S[0-9]+[A-Z]?|M[0-9]+[A-Z]?|SM[0-9]+|XY[0-9]+|BW[0-9]+|HGSS[0-9]?|DP[0-9]+)\b", b)
    if m:
        code = m.group(1)
        m2 = re.match(r"^([A-Z]+\d+)([A-Z])$", code)
        if m2:
            return m2.group(1) + m2.group(2).lower()
        return code
    # 2) Set name キーワードからの逆引き
    for keyword, code in _POKEMON_SET_NAME_TO_CODE.items():
        if keyword in b:
            return code
    # 3) Promo prefix
    if any(k in b for k in ("PROMO", "PROMOS", "JUMBO")):
        return "P"
    return None


def _to_legacy_dict_pokemon(record: dict) -> dict:
    """Pokemon 用 record → psa_to_csv 互換 dict.

    旧 pokemon_card_jp.fetch_card 互換フィールド + iMakCatalog 拡張.
    """
    specs = record.get("specs") or {}
    # variant suffix を剥がした card_number (e.g., 'M2a-240' → '240')
    pid = record.get("product_id", "")
    card_number_only = pid.split("-", 1)[1] if "-" in pid else pid

    return {
        # 旧 pokemon_card_jp 互換
        "name_jp":            record.get("name", ""),
        "name_en":            record.get("name", ""),  # サイト JA のみなので同値
        "card_number":        card_number_only,
        "card_number_full":   specs.get("card_number_text", card_number_only),
        "card_number_total":  specs.get("card_number_total", ""),
        "set_code":           pid.split("-", 1)[0] if "-" in pid else "",
        "rarity_jp":          specs.get("rarity", ""),
        "rarity_en":          specs.get("rarity", ""),
        "rarity":             specs.get("rarity", ""),
        "type_jp":            specs.get("type_jp", ""),
        "type_en":            specs.get("type_en", ""),
        "hp":                 specs.get("hp", ""),
        "stage":              specs.get("stage", ""),
        "weakness":           specs.get("weakness", ""),
        "resistance":         specs.get("resistance", ""),
        "retreat":            specs.get("retreat", ""),
        "regulation":         specs.get("regulation", ""),
        "illustrator":        specs.get("illustrator"),
        "card_type":          specs.get("card_type", ""),    # Pokémon / Trainer / Energy
        # iMakCatalog 拡張
        "card_id":            pid,
        "set_name":           record.get("set_name", ""),
        "set_name_ebay":      record.get("set_name", ""),
        "set_name_official":  record.get("set_name_official", ""),
        "language":           record.get("language"),
        "images":             record.get("images", []),
    }


# Pokemon Promo set codes (FA/Promo の hint で優先選択する候補)
# 各シリーズの promo 系を網羅:
#   S-P (Sword & Shield Promo), SV-P (Scarlet & Violet Promo), M-P (Mega Promo),
#   SMP (Sun & Moon Promo), XYP (X & Y Promo), BWP (Black & White Promo),
#   DPP (Diamond & Pearl Promo), SVD/SVM (SV special promo)
_POKEMON_PROMO_SET_CODES = ("S-P", "SV-P", "M-P", "SMP", "XYP", "BWP", "DPP", "SVD", "SVM", "SC")


def _is_pokemon_promo_hint(subject: str) -> bool:
    """PSA Subject に FA / Full Art / Promo / Jumbo 等の promo 系ヒントがあるか.

    注意: 'ANNIVERSARY' に 'SAR' が部分一致するため SAR / AR は word boundary で照合.
    """
    if not subject:
        return False
    subj = subject.upper()
    # 部分一致 OK: FA/, FULL ART, PROMO, JUMBO, SPECIAL ART, JUMBO
    if any(k in subj for k in ("FA/", "FULL ART", "PROMO", "JUMBO", "SPECIAL ART")):
        return True
    # word boundary 必須: SAR, AR (ANNIVERSARY を誤検出しないため)
    if re.search(r"\b(SAR|AR)\b", subj):
        return True
    return False


def _name_matches_pokemon_subject(record: dict, subject: str) -> bool:
    """Pokemon 用名前検証. PSA Subject は英語、record.name は日本語なので
    JA→EN dict + 部分一致で緩めに照合.
    """
    if not subject:
        return True
    subj_up = subject.upper()
    name_jp = record.get("name_jp") or record.get("name") or ""
    # 簡易: PSA 英語 token と record 日本語名の交差を JA→EN dict で見る
    # フル実装は複雑なので、当面 name に PSA Subject の主要トークンを部分一致
    # でチェック (例: 'PIKACHU' subject ↔ 'ピカチュウ' name は照合できないが、
    # 'CHARIZARD' subject ↔ 'リザードン' は dict 必要 → 当面 OK と判定)
    # 安全側: name_jp が空 or unknown → True (rejection しない)
    return True   # Pokemon は ID 一致を信頼、name 検証は将来の拡張


def lookup_pokemon(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = True,
) -> Optional[dict]:
    """Pokemon カードを iMakCatalog DB から ID 完全一致で lookup.

    手順:
      1) PSA Brand から set_code 抽出
      2) PSA Subject に FA/Promo ヒントあり → 先に promo set codes (S-P, SV-P 等) で試行
      3) base lookup `{set_code}-{card_number}`
      4) set_code 表記揺れ対応 (大文字/小文字)
    """
    if not card_number:
        return None
    set_code = extract_set_code_from_brand_pokemon(brand)
    if not set_code:
        if verbose:
            print(f"    ⚠️ Pokemon set_code 抽出失敗: brand={brand!r}")
        return None

    base_pid = f"{set_code}-{card_number}"

    # 1. base lookup を先に行って、その record の name を「正しいキャラ」として確定
    record = api.lookup(POKEMON_CATEGORY, base_pid)
    if record is None and set_code != set_code.upper():
        record = api.lookup(POKEMON_CATEGORY, f"{set_code.upper()}-{card_number}")
    if record is None and set_code != set_code.lower():
        record = api.lookup(POKEMON_CATEGORY, f"{set_code.lower()}-{card_number}")

    # 2. FA/Promo ヒントあり + base hit あり → promo set codes に **同名の record** があれば乗り換え
    #    (ANNIVERSARY の 'SAR' 部分一致や、無関係な S-P-XXX への誤マッチを防ぐ)
    if record is not None and _is_pokemon_promo_hint(subject):
        base_name_jp = record.get("name_jp") or record.get("name") or ""
        for promo_set in _POKEMON_PROMO_SET_CODES:
            promo_pid = f"{promo_set}-{card_number}"
            cand = api.lookup(POKEMON_CATEGORY, promo_pid)
            if not cand:
                continue
            cand_name_jp = cand.get("name_jp") or cand.get("name") or ""
            # 完全一致 (キャラ名同じ) のみ promo に切替
            if cand_name_jp == base_name_jp:
                record = cand
                if verbose:
                    print(f"    🎯 iMakCatalog (Pokemon) FA/promo upgrade: "
                          f"{base_pid} → {promo_pid} ({cand['name']}, subject FA hint)")
                break

    if record is None:
        if verbose:
            print(f"    ⚠️ iMakCatalog (Pokemon) 未登録: {base_pid} → Skip "
                  f"(subject={subject!r})")
        return None

    if verbose and record["product_id"] != "":
        # promo hit はすでにログ済 → base hit のみログ
        if not record["product_id"].startswith(tuple(f"{p}-" for p in _POKEMON_PROMO_SET_CODES)):
            print(f"    🎯 iMakCatalog (Pokemon) hit: {record['product_id']} "
                  f"{record['name']} (rarity={record['specs'].get('rarity', '?')!r}, "
                  f"hp={record['specs'].get('hp', '?')!r})")

    return _to_legacy_dict_pokemon(record)


def set_code_to_ebay_name_pokemon(set_value: str) -> str:
    """Pokemon 用 set_code/set 文字列 → eBay 公式名.

    Pokemon set_code は大文字小文字混在 (公式 image_url='M2a', PSA brand='M2A') のため
    複数表記を試行する.
    """
    if not set_value:
        return set_value
    candidates: list[str] = [set_value]
    # 末尾英字を小文字化したバリアント (例: 'M2A' → 'M2a')
    m_norm = re.match(r"^([A-Z]+\d+)([A-Z])$", set_value)
    if m_norm:
        candidates.append(m_norm.group(1) + m_norm.group(2).lower())
    # 末尾英字を大文字化 (逆方向)
    m_norm = re.match(r"^([A-Z]+\d+)([a-z])$", set_value)
    if m_norm:
        candidates.append(m_norm.group(1) + m_norm.group(2).upper())
    # 全大文字 / 全小文字
    if set_value != set_value.upper():
        candidates.append(set_value.upper())
    if set_value != set_value.lower():
        candidates.append(set_value.lower())

    for c in candidates:
        ebay = api.to_ebay_value(POKEMON_CATEGORY, "set_code", c)
        if ebay:
            return ebay
    # set 全文一致 fallback
    ebay = api.to_ebay_value(POKEMON_CATEGORY, "set", set_value)
    return ebay if ebay else set_value


# ============================================================================
# JA→EN character dict 拡張 (DBSCG 用キャラクター追加 — Phase 2 で必要に応じて拡充)
# ============================================================================
# 注: lookup_one_piece と共通の _record_name_matches_subject を使うため、
#     _JA_CHAR_TO_EN_TOKENS に DBSCG キャラを追加 (Goku/Vegeta 等) する形で拡張する.
_JA_CHAR_TO_EN_TOKENS.update({
    # Dragon Ball — JA-only プロモ向け
    "孫悟空":         {"GOKU", "SON"},
    "ベジータ":       {"VEGETA"},
    "孫悟飯":         {"GOHAN", "SON"},
    "ピッコロ":       {"PICCOLO"},
    "トランクス":     {"TRUNKS"},
    "クリリン":       {"KRILLIN"},
    "フリーザ":       {"FRIEZA"},
    "セル":           {"CELL"},
    "魔人ブウ":       {"MAJIN", "BUU"},
    "ブロリー":       {"BROLY"},
    "ゴジータ":       {"GOGETA"},
    "ベジット":       {"VEGITO"},
    "悟天":           {"GOTEN"},
    "亀仙人":         {"ROSHI", "MASTER"},
    "ヤムチャ":       {"YAMCHA"},
    "天津飯":         {"TIEN", "SHINHAN"},
    "チャオズ":       {"CHIAOTZU"},
    "餃子":           {"CHIAOTZU"},
    "ナッパ":         {"NAPPA"},
    "ラディッツ":     {"RADITZ"},
    "ザマス":         {"ZAMASU"},
    "ビルス":         {"BEERUS"},
    "ウイス":         {"WHIS"},
    "ジレン":         {"JIREN"},
    "シャロット":     {"SHALLOT"},

    # Gundam — JA-only プロモ向け (mecha + pilot)
    "アムロ・レイ":          {"AMURO", "RAY"},
    "シャア・アズナブル":    {"CHAR", "AZNABLE"},
    "ガンダム":              {"GUNDAM"},
    "ザク":                  {"ZAKU"},
    "ユニコーンガンダム":    {"UNICORN"},
    "バナージ・リンクス":    {"BANAGHER", "LINKS"},
    "刹那・F・セイエイ":     {"SETSUNA"},
    "ロックオン・ストラトス": {"LOCKON", "STRATOS"},
    "三日月・オーガス":      {"MIKAZUKI", "AUGUS"},
    "ガンダムバルバトス":    {"BARBATOS"},
    "ストライクガンダム":    {"STRIKE"},
    "フリーダムガンダム":    {"FREEDOM"},
    "キラ・ヤマト":          {"KIRA", "YAMATO"},
})
