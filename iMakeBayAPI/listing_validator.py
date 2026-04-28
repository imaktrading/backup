#!/usr/bin/env python3
"""
iMak Trading Japan - リスティングCSV出力前セルフチェック
全リスティングスクリプト共通。CSV行を出力する前に呼び出す。
問題があればERRORを返し、CSV出力を止める。
"""
import re


def validate_title_against_psa(title, psa_brand, psa_card_number):
    """タイトル中のセットコード/番号がPSAデータと整合するか検証。
    今回のOP09-091バグのような誤りを防ぐ。
    Returns: list[str] of error messages
    """
    errors = []
    if not title:
        return errors
    title_upper = title.upper()
    psa_brand_upper = (psa_brand or "").upper()
    psa_brand_normalized = psa_brand_upper.replace('-', '').replace(' ', '')

    # 1. タイトル中のセットコード(OP09, ST01等)がPSA brandに存在するか
    # ハイフン付き(OP09-091)/なし(OP09)両対応
    #
    # 2026-04-24 プロモ二重国籍汎用化:
    # PSA がプロモ封入セット名で登録しているが Bandai DB は元の発売セットで返すケース
    # (例: Ace EB02-028 vs PSA "OP13-CARRYING ON HIS WILL" / Shanks ST16-004 vs PSA "OP11-A PROMO")
    # → PSA brand に何らかのセットコード(Y)が既にあれば「元セット参照パターン」として許容
    # 2026-04-24 Gemini 監査後修正:
    # 正規化済文字列 (psa_brand_normalized) で `(OP|ST|EB|PRB)(\d+)` を照合すると、
    # 「STOP15」「SHOP15」等の単語内部の OP/ST にも部分一致してしまう偽陽性リスクあり。
    # 非正規化の元文字列 (psa_brand.upper()) に対して \b 語頭境界付きで照合することで、
    #   - 本来の型番 "OP13" 等は空白/ハイフン/文字列先頭後で \b 有 → マッチ
    #   - 単語内部の "STOP15" の OP は隣接文字が word char で \b 無 → 非マッチ
    # 2026-04-25 ケース2 拡張:
    # PSA brand に set code が一切無い「プロモ命名のみ」のケースも _is_promo_dual_citizenship 経由で許容
    psa_has_any_set_code = bool(re.search(r'\b(OP|ST|EB|PRB)(\d+)', psa_brand.upper()))
    promo_dual_reason = _is_promo_dual_citizenship(title, psa_brand)

    for match in re.finditer(r'\b(OP|ST|EB|PRB)(\d+)(?:-?\d+)?\b', title_upper):
        prefix = match.group(1)
        num = match.group(2)
        code = f"{prefix}{num}"  # OP09
        code_hyphen = f"{prefix}-{num}"  # OP-09
        if code not in psa_brand_normalized and code_hyphen.replace('-', '') not in psa_brand_normalized:
            if psa_has_any_set_code or promo_dual_reason:
                # プロモ二重国籍パターン許容（ケース1: 別セットコード混在 / ケース2: PSA がプロモ命名のみ）
                # ERROR にせず、ログにも残さない（既知の許容パターンとして黙認）
                pass
            else:
                errors.append(
                    f"タイトルに'{code}'があるが PSA brand に存在しない: '{psa_brand}'"
                )

    # 2. タイトル中の #数字 が PSA card_number と一致するか
    if psa_card_number:
        psa_num_str = str(psa_card_number).lstrip('0').split('/')[0]
        for match in re.finditer(r'#(\d+)', title):
            title_num = match.group(1).lstrip('0')
            if title_num != psa_num_str:
                errors.append(
                    f"タイトル '#{match.group(1)}' が PSA card# {psa_card_number} と不一致"
                )

    # 3. ハイフン形式のカード番号 (OP09-091等) の番号部分照合
    for match in re.finditer(r'\b(?:OP|ST|EB|PRB)\d+-(\d+)\b', title_upper):
        title_num = match.group(1).lstrip('0')
        if psa_card_number:
            psa_num_str = str(psa_card_number).lstrip('0').split('/')[0]
            if title_num != psa_num_str:
                errors.append(
                    f"タイトル '{match.group(0)}' の番号部分 '{match.group(1)}' が "
                    f"PSA card# {psa_card_number} と不一致"
                )

    return errors


def validate_row(title, specs, model, category, condition_id, price, pic_url, condition_desc="",
                 psa_brand=None, psa_card_number=None, intermediate=False):
    """CSV出力前のセルフチェック。ERRORがあればCSVに入れない。
    intermediate=True: category/pic_url/condition_id 未確定の中間段階バリデーション
                      （タイトル/Specs/PSAだけ厳格、それ以外は warning化）
    Returns: (errors: list[str], warnings: list[str])
    """
    errors = []
    warnings = []

    # ===== PSA データとの整合性チェック (TCGリスティング限定) =====
    if psa_brand or psa_card_number:
        psa_errors = validate_title_against_psa(title, psa_brand, psa_card_number)
        errors.extend(psa_errors)

    # ===== タイトル =====
    if not title:
        errors.append("タイトルが空")
    if len(title) > 80:
        errors.append(f"タイトル{len(title)}字 > 80字上限")
    if len(title) < 50:
        warnings.append(f"タイトル{len(title)}字 < 50字（短すぎ）")
    elif len(title) < 70:
        warnings.append(f"タイトル{len(title)}字 < 70字（キーワード追加余地あり）")

    # 型番チェック: WARNING のみ（カテゴリによってタイトル含めない方針あり、例: UNIQLO UT）
    if model and model != "NA" and model not in title:
        warnings.append(f"型番 '{model}' がItem Specificsにあるがタイトルに含まれていない（要件次第）")

    # ===== Item Specifics =====
    required_specs = {
        "Brand": "ブランド",
        "Type": "タイプ",
        "Size": "サイズ",
        "Color": "カラー",
    }
    for key, label in required_specs.items():
        val = specs.get(key, "")
        if not val:
            errors.append(f"必須Item Specific '{key}' ({label}) が空")

    # NAが入っていないか（TOPセラーのNA値が混入する問題）
    for key, val in specs.items():
        if val == "NA":
            warnings.append(f"Item Specific '{key}' が 'NA'（TOPセラーからの混入？）")

    # ===== カテゴリ / ConditionID / PicURL（中間段階はwarning化） =====
    _missing_msg = (warnings.append if intermediate else errors.append)

    if not category:
        _missing_msg("eBayカテゴリが空")

    if not condition_id:
        _missing_msg("ConditionIDが空")

    # 新品(1000)なのにConditionDescriptionがある
    if str(condition_id) == "1000" and condition_desc:
        warnings.append("新品(1000)にConditionDescriptionが設定されている（eBayが無視する）")

    # 中古(3000)なのにConditionDescriptionがない
    if str(condition_id) == "3000" and not condition_desc:
        _missing_msg("中古(3000)なのにConditionDescriptionが空")

    # ===== 価格 =====
    try:
        p = float(price)
        if p <= 0:
            errors.append("価格が0以下")
        if p > 1000:
            warnings.append(f"価格${p}が$1000超（確認要）")
    except (ValueError, TypeError):
        errors.append(f"価格が不正: {price}")

    # ===== PicURL =====
    if not pic_url:
        _missing_msg("PicURLが空")

    return errors, warnings


_gemini_client_cache = None


def _get_gemini_client():
    """Gemini client を遅延初期化＋キャッシュ"""
    global _gemini_client_cache
    if _gemini_client_cache is not None:
        return _gemini_client_cache
    try:
        from pathlib import Path
        from google import genai
        # iMakAudit/gemini_key.txt から読込
        script_dir = Path(__file__).resolve().parent
        key_file = script_dir.parent / "iMakAudit" / "gemini_key.txt"
        if not key_file.exists():
            return None
        api_key = key_file.read_text().strip()
        if not api_key:
            return None
        _gemini_client_cache = genai.Client(api_key=api_key)
        return _gemini_client_cache
    except Exception:
        return None


def gemini_cross_check(title, specs, psa_brand=None, psa_card_number=None):
    """Gemini に listing をクロスチェックさせる。
    返値: list of warning messages。失敗時も `[Gemini API失敗]` を返して可視化。"""
    client = _get_gemini_client()
    if client is None:
        return ["[Gemini] 利用不可（SDK未/keyファイル無/key空）"]
    import json as _json
    specs_text = "\n".join(f"  {k}: {v}" for k, v in (specs or {}).items() if v)
    psa_section = ""
    if psa_brand or psa_card_number:
        psa_section = f"\n[PSA cert データ]\nBrand: {psa_brand or ''}\nCard#: {psa_card_number or ''}"
    prompt = f"""あなたはeBayリスティング検証官。タイトル/Item Specifics/PSAデータの整合性を独立判定してください。

[タイトル]
{title}

[Item Specifics]
{specs_text}
{psa_section}

判定して JSON のみ返してください（前後にテキストなし）:
{{
  "verdict": "OK" または "WARNING",
  "issues": ["具体的な矛盾点", ...]
}}

判定基準:
- タイトル中の番号/コード(OP09-091, #119等)が Item Specifics や PSA brand と一致するか
- Item Specifics の Set/Year/Manufacturer が PSA brand と整合するか
- 商品説明として明らかに矛盾する組合せはないか
- 軽微な表記揺れは指摘不要"""
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = (resp.text or "").strip()
        # JSON抽出（```json ... ``` がある場合の対処）
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        data = _json.loads(text)
        if data.get("verdict") == "WARNING":
            return [f"[Gemini] {issue}" for issue in (data.get("issues") or [])]
        return []
    except Exception as e:
        return [f"[Gemini] API失敗（縮退）: {type(e).__name__}: {str(e)[:80]}"]


_groq_client_cache = None


def _get_groq_client():
    global _groq_client_cache
    if _groq_client_cache is not None:
        return _groq_client_cache
    try:
        from pathlib import Path
        from groq import Groq
        script_dir = Path(__file__).resolve().parent
        key_file = script_dir.parent / "iMakAudit" / "groq_key.txt"
        if not key_file.exists():
            return None
        api_key = key_file.read_text().strip()
        if not api_key:
            return None
        _groq_client_cache = Groq(api_key=api_key)
        return _groq_client_cache
    except Exception:
        return None


def groq_cross_check(title, specs, psa_brand=None, psa_card_number=None):
    """Groq でリスティングをクロスチェック。
    返値: list of warning messages。失敗時も `[Groq API失敗]` を返して可視化。"""
    client = _get_groq_client()
    if client is None:
        return ["[Groq] 利用不可（SDK未/keyファイル無/key空）"]
    import json as _json
    specs_text = "\n".join(f"  {k}: {v}" for k, v in (specs or {}).items() if v)
    psa_section = ""
    if psa_brand or psa_card_number:
        psa_section = f"\n[PSA cert データ]\nBrand: {psa_brand or ''}\nCard#: {psa_card_number or ''}"
    prompt = f"""You are an eBay listing verification AI. Check the consistency between the title, Item Specifics, and PSA cert data. Output JSON only.

[Title]
{title}

[Item Specifics]
{specs_text}
{psa_section}

Check criteria:
- Do codes/numbers in title (e.g., OP09-091, #119) match Item Specifics and PSA brand?
- Does Set/Year/Manufacturer in Specs align with PSA brand?
- Any obvious product description contradictions?
- Ignore minor spelling/format differences.

Respond JSON only (no surrounding text):
{{"verdict": "OK" or "WARNING", "issues": ["specific issue 1", ...]}}"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=512,
        )
        text = resp.choices[0].message.content.strip()
        data = _json.loads(text)
        if data.get("verdict") == "WARNING":
            return [f"[Groq] {issue}" for issue in (data.get("issues") or [])]
        return []
    except Exception as e:
        return [f"[Groq] API失敗（縮退）: {type(e).__name__}: {str(e)[:80]}"]


_anthropic_client_cache = None


def _get_anthropic_client():
    global _anthropic_client_cache
    if _anthropic_client_cache is not None:
        return _anthropic_client_cache
    try:
        from pathlib import Path
        import anthropic as _anth
        script_dir = Path(__file__).resolve().parent
        key_file = script_dir / "API key.txt"
        if not key_file.exists():
            return None
        api_key = key_file.read_text().strip()
        if not api_key:
            return None
        _anthropic_client_cache = _anth.Anthropic(api_key=api_key)
        return _anthropic_client_cache
    except Exception:
        return None


EBAY_CONSTRAINTS_CONTEXT = """
【eBay運用上の重要制約 — 必ず考慮すること】
1. eBay の Item Specifics 'Game' フィールドは事前定義された選択肢のみ。
   「Dragon Ball Super Card Game」しか選べず「Dragon Ball Super Card Game Fusion World」のような
   サブシリーズ名は eBay 側に存在しない。PSA brandが詳細表記でも、Item Specs で簡略表記なのは正しい。
2. PSA brandの "FUSION WORLD" "MANGA BOOSTER" "ENERGY MARKER PACK" 等のセット詳細は、
   eBay側で表現できない場合あり。Brand同一性ではなくカード番号の同一性で判定すること。
3. Type "Token" はBandai公式分類。タイトルで「Card」と表記しても整合性違反ではない。
4. Item Specs Brand 'Bandai' は製造会社で、PSA brand のセット名とは概念が違う。並列比較すべきでない。
5. PSA brandと Item Specs Game の表記差で「商品が違う」と判定するのは誤り。
   カード番号(Card Number)が一致していれば同一商品とみなす。
6. 真に問題なのは: カード番号不一致、キャラクター名不一致、年/Set系統の根本的矛盾、誤った商品名 等。
"""


def _build_listing_context(title, specs, psa_brand, psa_card_number):
    """3AIに同じ context を渡すため共通フォーマット"""
    specs_text = "\n".join(f"  {k}: {v}" for k, v in (specs or {}).items() if v)
    psa_section = ""
    if psa_brand or psa_card_number:
        psa_section = f"\n[PSA cert データ]\nBrand: {psa_brand or ''}\nCard#: {psa_card_number or ''}"
    return f"""[タイトル]
{title}

[Item Specifics]
{specs_text}
{psa_section}
{EBAY_CONSTRAINTS_CONTEXT}"""


# 既知の許容パターン（事前allowlist - AI判定前にPASSと確定する）
_KNOWN_ACCEPTABLE_PATTERNS = [
    # (検査関数, 説明)
    (
        lambda title, specs, brand, num: (
            brand and "FUSION WORLD" in (brand or "").upper()
            and specs.get("Game", "").lower() == "dragon ball super card game"
        ),
        "PSA brand に FUSION WORLD 詳細あり vs Item Specs Game = 'Dragon Ball Super Card Game'（eBayに該当カテゴリなし、許容）"
    ),
    (
        lambda title, specs, brand, num: (
            specs.get("Type", "").lower() == "token"
            and "card" in title.lower()
            and ("energy marker" in title.lower() or "e0" in (num or "").lower() or "e-" in (num or "").lower())
        ),
        "Energy Marker Token (Bandai公式分類) vs タイトル 'Card' 表記（許容）"
    ),
]


# 2026-04-25 拡張: PSA brand がセットコード(OP/ST/EB/PRB+数字)を持たない
# 「プロモ系コレクション名のみ」のケースを救済するためのキーワード辞書。
# Gemini 監査後、誤検出リスクの高い汎用語 (EVENT/PACK/MAGAZINE/V-JUMP 等) を除外し、
# 高シグナル 5 語に絞り込んだ。\bPR\b 検出は誤検出多発のため廃止。
_PROMO_BRAND_KEYWORDS = [
    "PROMO",                         # PROMOS / PROMO CARDS
    "PREMIUM CARD COLLECTION",       # ベストセレクション / 25周年等
    "ANNIVERSARY",                   # 25TH ANNIVERSARY 等
    "BEST SELECTION",
    "WEEKLY SHONEN JUMP",            # 雑誌付録
]

# 2026-04-25 ザル判定修正: ケース1 で許容するのは「既知のプロモ封入セットコード」のみ。
# PRB02 (Premium Booster) や通常 booster は別カードの可能性が高いので除外。
# 実証済みの dual citizenship 事例:
#   - OP11 (FIST OF DIVINE SPEED) ↔ ST16 (Shanks)
#   - OP13 (CARRYING ON HIS WILL) ↔ EB02 / OP07 (Ace / Sabo)
# 新たな dual citizenship が確認されたら 追加する（コードまたは yaml 経由）
KNOWN_PROMO_SET_CODES = {"OP11", "OP13"}


def _is_promo_dual_citizenship(title, psa_brand, psa_card_number=None):
    """PSA brand と title のセットコードが異なる「プロモ二重国籍」を許容する判定ヘルパ。

    Returns:
        str: 許容パターン該当時はログ用の理由文字列（ケース種別＋ヒット情報を含む）。
             非該当時は空文字。
             ※bool 文脈での真偽判定はそのまま機能する。

    2026-04-24 Gemini監査: TCG ブランドガード追加（ガシャポン等への誤適用防止）
    2026-04-25 Gemini監査: プロモ命名のみで set code を持たない PSA brand に対応(ケース2)。
    2026-04-25 ザル判定修正:
      cert #143570665 で PRB02-005 (SR/Cost4/Power5000) を ST16-005 (C/Cost2/Power3000) として
      誤通過させた事故を受け、ケース1 を「既知のプロモセットコード」白リストに制限。
      PRB02/通常 booster set codes の同番号別カード混在を防ぐ。
    """
    if not title or not psa_brand:
        return ""
    psa_upper_full = psa_brand.upper()
    TCG_BRAND_MARKERS = ["ONE PIECE", "BANDAI", "GUNDAM", "DRAGON BALL"]
    if not any(m in psa_upper_full for m in TCG_BRAND_MARKERS):
        return ""
    title_upper = title.upper()
    brand_norm = psa_upper_full.replace('-', '').replace(' ', '')
    psa_codes = set()
    for m in re.finditer(r'(OP|ST|EB|PRB)(\d+)', brand_norm):
        psa_codes.add(f"{m.group(1)}{m.group(2)}")
    title_codes = set()
    for m in re.finditer(r'\b(OP|ST|EB|PRB)(\d+)', title_upper):
        title_codes.add(f"{m.group(1)}{m.group(2)}")

    # ケース1 (既存 + 白リスト制限): 両者に set code、title に PSA にないコード混入
    #   (例: Shanks PSA=OP11-A vs title=ST16, Ace PSA=OP13 vs title=EB02)
    #   ★PSA codes に KNOWN_PROMO_SET_CODES が含まれている時のみ許容★
    if psa_codes and title_codes and (title_codes - psa_codes):
        if psa_codes & KNOWN_PROMO_SET_CODES:
            matched_promo = sorted(psa_codes & KNOWN_PROMO_SET_CODES)
            return (
                f"プロモ二重国籍ケース1: PSA={sorted(psa_codes)} (既知promo {matched_promo}) / "
                f"Bandai補完={sorted(title_codes)}（PSA封入セット ≠ Bandai 元セット）"
            )
        # 白リスト外: 別カード疑いで拒否（PRB02-005 vs ST16-005 のような同番号別カード防止）
        return ""

    # ケース2 (2026-04-25 拡張): PSA brand に set code 無し
    #   (プロモ命名のみ "ONE PIECE PROMO" 等) + title に Bandai 補完由来 code
    if not psa_codes and title_codes:
        hit_keyword = next((kw for kw in _PROMO_BRAND_KEYWORDS if kw in psa_upper_full), None)
        if hit_keyword:
            return (
                f"プロモ二重国籍ケース2 (PROMO): PSA brand=\"{hit_keyword}\" 含む / "
                f"Bandai補完={sorted(title_codes)}（PSA は set code 無し、プロモ命名のみ）"
            )

    return ""


def _check_acceptable(title, specs, psa_brand, psa_card_number):
    """既知の許容パターンに該当すれば (True, 理由) を返す"""
    for checker, reason in _KNOWN_ACCEPTABLE_PATTERNS:
        try:
            if checker(title, specs or {}, psa_brand, psa_card_number):
                return True, reason
        except Exception:
            continue
    promo_reason = _is_promo_dual_citizenship(title, psa_brand)
    if promo_reason:
        return True, promo_reason
    return False, ""


def _ask_claude(context, peer_opinions=None):
    """Claude API に判定を求める。peer_opinions があれば再考プロンプト"""
    client = _get_anthropic_client()
    if client is None:
        return {"verdict": "ABSTAIN", "reason": "Claude API利用不可"}
    import json as _json
    instructions = "あなたはeBayリスティング検証AI。タイトル/Item Specifics/PSAデータの整合性を判定し、JSON形式で回答してください。"
    if peer_opinions:
        peer_text = "\n".join(f"  - {ai}: {op['verdict']} ({op['reason']})" for ai, op in peer_opinions.items())
        instructions += f"\n\n他のAIの判定:\n{peer_text}\n\nこれを踏まえて再考してください。維持でも変更でも構いませんが、根拠を述べてください。"
    prompt = f"""{instructions}

{context}

eBayの運用制約も考慮してください（カテゴリ選択肢が限られる、Item Specifics の選択肢制約等）。
回答は JSON のみ:
{{"verdict": "PASS" or "BLOCK", "reason": "..."}}"""
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        data = _json.loads(text)
        return {"verdict": data.get("verdict", "ABSTAIN"), "reason": data.get("reason", "")}
    except Exception as e:
        return {"verdict": "ABSTAIN", "reason": f"Claude例外: {type(e).__name__}"}


def _ask_gemini(context, peer_opinions=None):
    client = _get_gemini_client()
    if client is None:
        return {"verdict": "ABSTAIN", "reason": "Gemini利用不可"}
    import json as _json
    instructions = "あなたはeBayリスティング検証AI。タイトル/Item Specifics/PSAデータの整合性を判定。"
    if peer_opinions:
        peer_text = "\n".join(f"  - {ai}: {op['verdict']} ({op['reason']})" for ai, op in peer_opinions.items())
        instructions += f"\n\n他のAIの判定:\n{peer_text}\n\nこれを踏まえて再考してください。"
    prompt = f"""{instructions}

{context}

eBayの運用制約（カテゴリ・Specs選択肢の制約）も考慮。回答はJSONのみ:
{{"verdict": "PASS" or "BLOCK", "reason": "..."}}"""
    try:
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        text = (resp.text or "").strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        data = _json.loads(text)
        return {"verdict": data.get("verdict", "ABSTAIN"), "reason": data.get("reason", "")}
    except Exception as e:
        return {"verdict": "ABSTAIN", "reason": f"Gemini例外: {type(e).__name__}"}


def _ask_groq(context, peer_opinions=None):
    client = _get_groq_client()
    if client is None:
        return {"verdict": "ABSTAIN", "reason": "Groq利用不可"}
    import json as _json
    instructions = "You are an eBay listing verification AI. Judge title/Item Specifics/PSA data consistency."
    if peer_opinions:
        peer_text = "\n".join(f"  - {ai}: {op['verdict']} ({op['reason']})" for ai, op in peer_opinions.items())
        instructions += f"\n\nOther AI verdicts:\n{peer_text}\n\nReconsider with this in mind."
    prompt = f"""{instructions}

{context}

Consider eBay constraints (limited category/Specs options). Respond JSON only:
{{"verdict": "PASS" or "BLOCK", "reason": "..."}}"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=512,
        )
        text = resp.choices[0].message.content.strip()
        data = _json.loads(text)
        return {"verdict": data.get("verdict", "ABSTAIN"), "reason": data.get("reason", "")}
    except Exception as e:
        return {"verdict": "ABSTAIN", "reason": f"Groq例外: {type(e).__name__}"}


def deliberate_3ai(title, specs, psa_brand=None, psa_card_number=None, max_rounds=5,
                   override_context=None):
    """3AI（Claude/Gemini/Groq）議論で合意形成。
    最大max_rounds回まで意見交換、合意できなければHOLD。
    - override_context: cert_overrides 適用時に各AIのプロンプトに追加するコンテキスト
                        (人手検証済の旨を伝え、cert#数値一致のみで誤BLOCKしないよう示唆)
    Returns: dict {
      "final_verdict": "PASS" / "BLOCK" / "HOLD",
      "rounds": [{round, opinions}, ...],
      "history": str (人間向け要約)
    }
    """
    context = _build_listing_context(title, specs, psa_brand, psa_card_number)
    if override_context:
        context = context + "\n\n=== HUMAN OVERRIDE CONTEXT ===\n" + override_context
    askers = {"Claude": _ask_claude, "Gemini": _ask_gemini, "Groq": _ask_groq}

    rounds = []
    opinions = {}
    from concurrent.futures import ThreadPoolExecutor

    for round_num in range(1, max_rounds + 1):
        peer = opinions.copy() if opinions else None
        new_ops = {}
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {name: ex.submit(asker, context, peer) for name, asker in askers.items()}
            for name, fut in futs.items():
                try:
                    new_ops[name] = fut.result(timeout=30)
                except Exception as e:
                    new_ops[name] = {"verdict": "ABSTAIN", "reason": f"{type(e).__name__}"}
        opinions = new_ops
        rounds.append({"round": round_num, "opinions": dict(opinions)})

        # 合意チェック (ABSTAINは除外して判定)
        active = [op["verdict"] for op in opinions.values() if op["verdict"] in ("PASS", "BLOCK")]
        if not active:
            # 全員 ABSTAIN → HOLD
            break
        if len(set(active)) == 1:
            return {
                "final_verdict": active[0],
                "rounds": rounds,
                "history": f"ラウンド{round_num}で全員 {active[0]} に合意",
            }

    # max_rounds 終了後も不一致 → HOLD
    return {
        "final_verdict": "HOLD",
        "rounds": rounds,
        "history": f"{max_rounds}ラウンド議論しても合意形成できず、人間判断要求",
    }


_HOLD_LOG_PATH = None  # 遅延初期化


def _append_hold_log(idx, title, deliberation):
    """HOLD案件をログファイルに追記（人間レビュー用）"""
    from pathlib import Path
    import json as _json
    from datetime import datetime
    global _HOLD_LOG_PATH
    if _HOLD_LOG_PATH is None:
        script_dir = Path(__file__).resolve().parent
        log_dir = script_dir.parent / "iMakHQ" / "review_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        _HOLD_LOG_PATH = log_dir / "ai_hold_queue.jsonl"
    entry = {
        "ts": datetime.now().isoformat(),
        "idx": str(idx),
        "title": title,
        "rounds": deliberation.get("rounds", []),
        "history": deliberation.get("history", ""),
    }
    with _HOLD_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    return _HOLD_LOG_PATH


def validate_and_report(idx, title, specs, model, category, condition_id, price, pic_url, condition_desc="",
                        psa_brand=None, psa_card_number=None,
                        use_gemini=True, use_groq=True, intermediate=False,
                        use_deliberation=True, override_context=None):
    """セルフチェック実行＋表示。
    - intermediate=True: 中間段階バリデーション（category/pic_url未確定OK）
    - use_deliberation=True: 3AI議論方式（Claude/Gemini/Groq、最大5R、HOLDで人間判断）
    - override_context: cert_overrides 適用時の人手検証コンテキスト (3AI への追加プロンプト)
    Returns: bool (False=CSV除外、True=CSV出力)
    """
    errors, warnings = validate_row(
        title, specs, model, category, condition_id, price, pic_url, condition_desc,
        psa_brand=psa_brand, psa_card_number=psa_card_number, intermediate=intermediate,
    )

    # 構造validatorで既にerror出てるなら3AI不要（コスト削減）
    if errors:
        if errors:
            print(f"    ❌ セルフチェック失敗 (#{idx}):")
            for e in errors:
                print(f"       ❌ {e}")
        if warnings:
            for w in warnings:
                print(f"       ⚠️ {w}")
        print(f"    → この商品はCSVに含めません")
        return False

    # 既知の許容パターンチェック（議論前のショートカット）
    if use_deliberation:
        is_acceptable, accept_reason = _check_acceptable(title, specs, psa_brand, psa_card_number)
        if is_acceptable:
            if warnings:
                for w in warnings:
                    print(f"       ⚠️ {w}")
            print(f"    ✅ 既知の許容パターン: {accept_reason}")
            return True

    # 3AI議論モード
    if use_deliberation:
        delib = deliberate_3ai(title, specs, psa_brand, psa_card_number, max_rounds=5,
                               override_context=override_context)
        verdict = delib["final_verdict"]

        if verdict == "PASS":
            # 全AI合意 PASS → 出品OK
            if warnings:
                for w in warnings:
                    print(f"       ⚠️ {w}")
            print(f"    ✅ 3AI合意: PASS ({delib['history']})")
            return True

        elif verdict == "BLOCK":
            # 全AI合意 BLOCK → 除外
            print(f"    ❌ 3AI合意: BLOCK (#{idx})")
            print(f"       {delib['history']}")
            for r in delib["rounds"]:
                print(f"       === Round {r['round']} ===")
                for ai, op in r["opinions"].items():
                    print(f"         {ai}: {op['verdict']} | {op['reason'][:120]}")
            print(f"    → この商品はCSVに含めません")
            return False

        else:  # HOLD
            log_path = _append_hold_log(idx, title, delib)
            print(f"    🟠 HOLD (#{idx}): 5R議論しても合意未到達、人間判断要求")
            for r in delib["rounds"]:
                print(f"       === Round {r['round']} ===")
                for ai, op in r["opinions"].items():
                    print(f"         {ai}: {op['verdict']} | {op['reason'][:120]}")
            print(f"    → CSV除外、判断ログ追記: {log_path}")
            return False

    # 議論モード OFF の場合は warning出力だけ
    if warnings:
        for w in warnings:
            print(f"       ⚠️ {w}")
    return True
