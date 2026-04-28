"""card_identification_agent - カード特定推論エージェント (独立モジュール).

設計原則 (修正連鎖を生まないため):
  - 既存モジュール (card_identifier.py / pokemon_card_jp.py / listing_validator.py)
  - iMakCatalog DB (One Piece TCG = bandai_jp.py から移行)
    を一切修正しない
  - 各ソースから情報収集 → 仮説生成 → 多角検証 → 確度集計 のエージェント層
  - 既存の card_identifier (Vision) 結果を「補正」して返す形で介入、psa_to_csv は1行差替えで導入可能

設計思想:
  - 目的: カード特定 (手段は柔軟に組合わせ)
  - 各ソース (PSA cert / Vision / 公式DB) は不確実、単一信頼しない
  - 仮説立て + 多角検証で確度を上げる (人間の問題解決プロセス)
  - 検証失敗時は警告出して既存挙動 (フォールバック) に任せる

Phase 1 (現実装): card_number_conflict 仮説のみ
  - PSA cert# (公式記録) vs Vision 画像読み取り card_number の数字部分整合性
  - 不一致 → PSA 信頼、Vision の prefix のみ採用 (合成 card_number 生成)
  - 例: PSA "057" vs Vision "OP07-047" → 合成 "OP07-057" (Vision 誤読補正)

Phase 2 以降の拡張余地:
  - pcc_reracode_lookup_base_set 仮説 (PCC再録 → 元 Bandai セット推定)
  - subject_is_alias_or_technique 仮説 (PERFUME FEMUR 等の異名/技名検証)
  - 確度集計 + 警告ダッシュボード

使用例:
    from card_identification_agent import correct_vision_result_with_psa
    vision_result = card_identifier.identify_from_image(...)
    vision_result = correct_vision_result_with_psa(vision_result, psa_data)
    # → vision_result の card_number が PSA cert と整合性確認/補正された値で返る
"""
from __future__ import annotations

import re
from typing import Optional


def correct_vision_result_with_psa(
    vision_result: Optional[dict], psa_data: dict
) -> Optional[dict]:
    """Vision の結果を PSA cert (公式記録) と公式DB情報で多角補正.

    オーケストレーター: 各仮説検証関数を順に呼んで vision_result を改良。
    各 _resolve_* 関数は独立、vision_result dict を受け取って改良版を返す契約。
    """
    if not vision_result:
        return vision_result
    result = dict(vision_result)
    result["agent_warnings"] = list(result.get("agent_warnings", []))
    result["agent_reasoning"] = list(result.get("agent_reasoning", []))

    # Phase 1: card_number 数字整合性 (PSA 信頼で Vision 誤読補正)
    result = _resolve_number_conflict(result, psa_data)
    # Phase 2: PSA Subject の意味推定 (異名/技名 → 本キャラ + ヒント抽出)
    result = _resolve_subject_meaning(result, psa_data)
    # Phase 3: PCC/再録系セット検出 → 公式DB再lookup で値補完
    result = _resolve_pcc_reracode(result, psa_data)

    return result


# ============================================================================
# 各仮説検証 (resolver) - 独立関数、入出力契約: vision dict in → 改良 vision dict out
# ============================================================================
def _resolve_number_conflict(vision_result: dict, psa_data: dict) -> dict:
    """Phase 1: PSA cert# (公式記録) と Vision card_number の数字部分整合性.
    不一致なら PSA 信頼、Vision の prefix のみ採用 (Vision 誤読の構造的防御)。
    """
    result = vision_result
    psa_card_num = (psa_data.get("CardNumber") or "").strip()
    vision_card_num = (result.get("card_number") or "").strip()

    if not psa_card_num or not vision_card_num:
        return result

    psa_num_only = re.sub(r"\D", "", psa_card_num)
    vision_num_match = re.search(r"(\d+)$", vision_card_num)
    vision_num = vision_num_match.group(1) if vision_num_match else ""

    if not psa_num_only or not vision_num:
        return result

    if psa_num_only.lstrip("0") == vision_num.lstrip("0"):
        result["agent_reasoning"].append(
            f"[Phase1] card_number 数字一致 (PSA={psa_num_only} == Vision={vision_num})"
        )
        return result

    # 不一致補正
    vision_prefix_match = re.match(r"^([A-Z]+\d+|[A-Z]+)-", vision_card_num)
    if vision_prefix_match:
        prefix = vision_prefix_match.group(1)
        pad_width = len(vision_num)
        synthesized = f"{prefix}-{psa_num_only.zfill(pad_width)}"
        warning = (
            f"[Phase1] card_number 不一致補正: Vision={vision_card_num} → {synthesized} "
            f"(PSA信頼、prefix={prefix} 採用)"
        )
        result["card_number"] = synthesized
    else:
        warning = (
            f"[Phase1] card_number 不一致補正: Vision={vision_card_num} → PSA={psa_card_num}"
        )
        result["card_number"] = psa_card_num

    result["agent_warnings"].append(warning)
    result["agent_reasoning"].append(warning)
    print(f"    🤖 [Phase1] {warning}")
    return result


# Phase 2 用: 既知の異名/技名辞書 (Claude API 不要、辞書ヒット優先で高速化)
# PSA Subject (大文字) → (本キャラ名英語, 種別)
_KNOWN_SUBJECT_ALIASES = {
    # One Piece 技名 (キャラ別の必殺技)
    "PERFUME FEMUR":          ("Boa Hancock", "technique"),
    "MERO MERO MELLOW":       ("Boa Hancock", "technique"),
    "SLAVE ARROW":            ("Boa Hancock", "technique"),
    "GOMU GOMU NO":           ("Monkey D. Luffy", "technique"),
    "GEAR FOURTH":            ("Monkey D. Luffy", "technique"),
    "BAJRANG GUN":            ("Monkey D. Luffy", "technique"),
    "SANTORYU":               ("Roronoa Zoro", "technique"),
    "ASURA":                  ("Roronoa Zoro", "technique"),
    "DIABLE JAMBE":           ("Sanji", "technique"),
    "MIRAGE TEMPO":           ("Nami", "technique"),
    "CLIMA-TACT":             ("Nami", "technique"),
    # 必要に応じて追加 (発見の都度蓄積、ナレッジ集約)
}


def _resolve_subject_meaning(vision_result: dict, psa_data: dict) -> dict:
    """Phase 2: PSA Subject (異名/技名等) の意味を辞書で推定.

    PERFUME FEMUR 等の不明な Subject から本キャラを特定して character を補完。
    辞書未登録の場合は何もしない (Claude API での意味推定は将来拡張)。
    """
    result = vision_result
    subject = (psa_data.get("Subject") or "").upper().strip()
    if not subject:
        return result

    # 辞書完全一致 → 本キャラ名で character 補完
    if subject in _KNOWN_SUBJECT_ALIASES:
        true_char, kind = _KNOWN_SUBJECT_ALIASES[subject]
        if not result.get("character") or result["character"] == subject.title():
            warning = (
                f"[Phase2] Subject '{subject}' は {kind} → 本キャラ '{true_char}' を採用"
            )
            result["character"] = true_char
            result["agent_warnings"].append(warning)
            result["agent_reasoning"].append(warning)
            print(f"    🤖 [Phase2] {warning}")
        return result

    # 部分一致 (辞書キーが Subject に含まれる)
    for alias_key, (true_char, kind) in _KNOWN_SUBJECT_ALIASES.items():
        if alias_key in subject:
            warning = (
                f"[Phase2] Subject '{subject}' に '{alias_key}' ({kind}) 含む → 本キャラ '{true_char}'"
            )
            if not result.get("character"):
                result["character"] = true_char
            result["agent_reasoning"].append(warning)
            print(f"    🤖 [Phase2] {warning}")
            return result

    # 未解決 (辞書未登録)
    result["agent_reasoning"].append(
        f"[Phase2] Subject '{subject}' 辞書未登録、意味推定スキップ"
    )
    return result


def _resolve_pcc_reracode(vision_result: dict, psa_data: dict) -> dict:
    """Phase 3: PSA Brand に PCC/Premium 系を検出 → 再録元の Bandai 公式DBで再lookup.

    Brand 例: "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-"
    → 再録セット = OP-07 等の元セット (Vision 由来 card_number で公式DB lookup)

    iMakCatalog DB lookup (Phase 1: bandai_jp.py cache から DB lookup へ移行).
    """
    result = vision_result
    brand = (psa_data.get("Brand") or "").upper()
    is_pcc = any(kw in brand for kw in [
        "PREMIUM CARD COLLECTION", "PREMIUM BOOSTER", "PCC", "BEST SELECTION",
        "MEMORIAL COLLECTION", "ANNIVERSARY COLLECTION",
    ])
    if not is_pcc:
        return result

    # Vision で card_number が確定 (high confidence) しているケースのみ対象
    if result.get("confidence") not in ("high", "medium"):
        result["agent_reasoning"].append(
            f"[Phase3] PCC/Premium 検出だが Vision confidence={result.get('confidence')} で再lookup スキップ"
        )
        return result

    card_num = (result.get("card_number") or "").strip()
    if not re.match(r"^[A-Z]+\d+-\d+$", card_num):
        result["agent_reasoning"].append(
            f"[Phase3] card_number={card_num} が prefix 付き形式でないため再lookup スキップ"
        )
        return result

    # iMakCatalog DB で再録元 card_number を直接 lookup
    try:
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "iMakCatalog"))
        import api as catalog_api
        record = catalog_api.lookup("one_piece_tcg", card_num)
        if record:
            specs = record.get("specs") or {}
            if not result.get("color") and specs.get("Color"):
                result["color"] = specs["Color"]
            if not result.get("cost") and specs.get("Cost/Life"):
                result["cost"] = specs["Cost/Life"]
            if not result.get("power") and specs.get("Power"):
                result["power"] = specs["Power"]
            warning = f"[Phase3] PCC再録元 {card_num} を iMakCatalog から補完"
            result["agent_warnings"].append(warning)
            result["agent_reasoning"].append(warning)
            print(f"    🤖 [Phase3] {warning}")
        else:
            result["agent_reasoning"].append(
                f"[Phase3] PCC検出 ({card_num}) だが iMakCatalog 未登録、補完スキップ"
            )
    except Exception as e:
        result["agent_reasoning"].append(f"[Phase3] iMakCatalog 参照失敗: {type(e).__name__}: {e}")
    return result


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    # サンプル: Hancock cert #142833357 のケース
    psa_sample = {
        "Brand": "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-",
        "CardNumber": "057",
        "Subject": "PERFUME FEMUR",
    }
    vision_sample = {
        "confidence": "high",
        "card_number": "OP07-047",  # Vision 誤読 (047 と読んだ、実際は 057)
        "character": "Boa Hancock",
        "set_name": "500 Years in the Future",
    }
    result = correct_vision_result_with_psa(vision_sample, psa_sample)
    print()
    print("=== 補正結果 ===")
    print(f"  Vision card_number: {vision_sample['card_number']}")
    print(f"  Corrected:          {result['card_number']}")
    print(f"  Warnings:           {result.get('agent_warnings')}")
