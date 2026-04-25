#!/usr/bin/env python3
"""
iMak Trading Japan - eBay CSV チェッカー
生成済みCSVを検証し、eBay競合リスティングと比較してレポートを出力する。

使い方:
  python check_csv.py ebay_upload_20260413_082744.csv
  python check_csv.py                          # 最新のCSVを自動検出
"""

import csv
import sys
import os
import re
import json
import time
import glob
import base64
import requests
import anthropic

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ===== 設定 =====
EBAY_KEYS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI", "ebay keys.txt"
)
API_KEY_FILE = "API key.txt"

# タイトルルール
MAX_TITLE_LEN = 80
IDEAL_TITLE_MIN = 70
BANNED_TITLE_WORDS = [
    "japanese", "japan", "gem mt", "gem-mt", "gemmt",
    "mint", "graded", "l@@k", "look", "wow", "nr",
]

# 必須Item Specifics（空欄だと品質低下）
REQUIRED_SPECIFICS = ["C:Game", "C:Set", "C:Card Name", "C:Character", "C:Rarity"]
# あると望ましいItem Specifics
RECOMMENDED_SPECIFICS = [
    "C:Card Type", "C:Features", "C:Finish", "C:Attribute/MTG:Color",
    "C:Cost", "C:Attack/Power",
]

# ===== 利益計算パラメータ（SSOT 抽象化: profit_params.get_check_csv_params 経由） =====
# 2026-04-24 二重基準解消、2026-04-25 Step 7 SSOT 抽象化で再リファクタ:
#   各プロジェクトはカテゴリ名を渡すだけ。共通モジュール側に if 分岐は持たない。
import sys as _sys_pp
_sys_pp.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI"))
from profit_params import get_check_csv_params as _gccp_pp
PROFIT_PARAMS = _gccp_pp("TCG(PSA10)")
# net_ratio = 1 - fvf - promo - payo （profit_params の SSOT 値を使用）

# 価格帯別パラメータ（GATE判定パラメータ検討.xlsx確定値）
# (中央値上限, 目標利益率, 許容乖離率)
TIER_PARAMS = [
    (39,   0.25, 0.50),   # $0-39:   利益25%, 乖離50%まで
    (60,   0.25, 0.50),   # $40-60:  利益25%, 乖離50%まで
    (100,  0.20, 0.50),   # $60-100: 利益20%, 乖離50%まで
    (200,  0.15, 0.50),   # $100-200:利益15%, 乖離50%まで
    (300,  0.10, 0.40),   # $200-300:利益10%, 乖離40%まで
    (400,  0.10, 0.25),   # $300-400:利益10%, 乖離25%まで
    (500,  0.10, 0.20),   # $400-500:利益10%, 乖離20%まで
    (600,  0.10, 0.15),   # $500-600:利益10%, 乖離15%まで
    (800,  0.10, 0.10),   # $600-800:利益10%, 乖離10%まで
    (9999, 0.10, 0.10),   # $800+:   利益10%, 乖離10%まで
]

def get_tier_params(median_usd):
    for threshold, profit_target, gap_limit in TIER_PARAMS:
        if median_usd <= threshold:
            return profit_target, gap_limit
    return 0.10, 0.10

# TOPセラー判定閾値
TOP_SELLER_MIN_FEEDBACK = 500       # 取引実績500件以上
TOP_SELLER_MIN_PERCENTAGE = 98.0    # ポジティブ率98%以上

# CSV列名 → インデックスのマッピング（ヘッダーから動的に構築）
HEADER_MAP = {}


# ===== eBay API =====
def load_ebay_keys():
    keys = {}
    try:
        with open(EBAY_KEYS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    keys[k.strip()] = v.strip()
    except FileNotFoundError:
        print("  ⚠️ eBay APIキーが見つかりません。競合比較はスキップします。")
    return keys


def get_oauth_token(app_id, app_secret):
    credentials = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_ebay_active(token, keywords, limit=50):
    """Browse API で同一カードのアクティブ出品を検索（最大50件）。
    Returns: (items_list, total_count)"""
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {
        "q": keywords,
        "filter": (
            "buyingOptions:{FIXED_PRICE},"
            "conditionIds:{2750},"  # Graded
            "categoryIds:{183454}"  # CCG
        ),
        "sort": "price",
        "limit": min(limit, 200),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            return [], 0
        data = resp.json()
        total = data.get("total", 0)
        return data.get("itemSummaries", []), total
    except Exception as e:
        print(f"  eBay API error: {e}")
        return [], 0


def fetch_top_seller_specs(token, items, max_items=3):
    """TOPセラーのリスティングからItem Specificsを取得して集約"""
    top_items = []
    for item in items:
        seller = item.get("seller", {})
        score = seller.get("feedbackScore", 0)
        pct_str = seller.get("feedbackPercentage", "0")
        try:
            pct = float(pct_str)
        except (ValueError, TypeError):
            pct = 0
        if score >= TOP_SELLER_MIN_FEEDBACK and pct >= TOP_SELLER_MIN_PERCENTAGE:
            item_id = item.get("itemId", "")
            if item_id:
                top_items.append(item_id)
        if len(top_items) >= max_items:
            break

    if not top_items:
        for item in items[:max_items]:
            item_id = item.get("itemId", "")
            if item_id:
                top_items.append(item_id)

    all_specs = []
    for item_id in top_items:
        try:
            url = f"https://api.ebay.com/buy/browse/v1/item/{item_id}"
            headers = {
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                "Content-Type": "application/json",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            aspects = data.get("localizedAspects", [])
            specs = {}
            for asp in aspects:
                name = asp.get("name", "")
                value = asp.get("value", "")
                if name and value:
                    specs[name] = value
            if specs:
                all_specs.append(specs)
            time.sleep(0.3)
        except Exception:
            pass

    if not all_specs:
        return {}

    from collections import Counter
    merged = {}
    all_keys = set()
    for specs in all_specs:
        all_keys.update(specs.keys())
    for key in all_keys:
        values = [s[key] for s in all_specs if key in s]
        if values:
            merged[key] = Counter(values).most_common(1)[0][0]
    return merged


# eBay Item Specifics名 → CSV列名
EBAY_SPEC_TO_CSV = {
    "Game": "C:Game", "Set": "C:Set", "Card Type": "C:Card Type",
    "Card Name": "C:Card Name", "Character": "C:Character",
    "Card Number": "C:Card Number", "Rarity": "C:Rarity",
    "Features": "C:Features", "Finish": "C:Finish",
    "Attribute/MTG:Color": "C:Attribute/MTG:Color",
    "Cost": "C:Cost", "Attack/Power": "C:Attack/Power",
}


def compare_item_specifics(row, top_specs):
    """自社リスティング vs TOPセラーのItem Specificsを比較"""
    findings = []
    if not top_specs:
        return findings

    for ebay_name, csv_col in EBAY_SPEC_TO_CSV.items():
        my_val = get_col(row, csv_col).strip()
        top_val = top_specs.get(ebay_name, "").strip()

        if not top_val:
            continue

        if not my_val and top_val:
            findings.append(("WARN", f"'{ebay_name}' が空 → TOPセラーは「{top_val}」"))
        elif my_val != top_val and my_val and top_val:
            findings.append(("INFO", f"'{ebay_name}' 自分「{my_val}」 vs TOP「{top_val}」"))

    # TOPセラーにあって自分のCSVにない項目
    known_csv_cols = set(EBAY_SPEC_TO_CSV.values())
    for ebay_name, top_val in top_specs.items():
        if ebay_name not in EBAY_SPEC_TO_CSV and top_val:
            # CSV列に対応がない項目は情報として表示
            pass  # 既存マッピング外は無視

    return findings


def classify_sellers(items):
    """競合をTOPセラーと全セラーに分類して価格情報を返す"""
    all_prices = []
    top_prices = []

    for item in items:
        try:
            price = float(item.get("price", {}).get("value", 0))
            if price <= 0:
                continue
        except (ValueError, TypeError):
            continue

        all_prices.append(price)

        seller = item.get("seller", {})
        feedback_score = seller.get("feedbackScore", 0)
        feedback_pct_str = seller.get("feedbackPercentage", "0")
        try:
            feedback_pct = float(feedback_pct_str)
        except (ValueError, TypeError):
            feedback_pct = 0

        if feedback_score >= TOP_SELLER_MIN_FEEDBACK and feedback_pct >= TOP_SELLER_MIN_PERCENTAGE:
            top_prices.append(price)

    def stats(prices):
        if not prices:
            return None
        s = sorted(prices)
        return {
            "count": len(s),
            "min": s[0],
            "max": s[-1],
            "median": s[len(s) // 2],
            "avg": sum(s) / len(s),
        }

    return stats(all_prices), stats(top_prices)


def build_search_query(row):
    """CSV行から競合検索用キーワードを構築"""
    character = get_col(row, "C:Character")
    card_number = get_col(row, "C:Card Number")
    game = get_col(row, "C:Game")

    game_short = {
        "Dragon Ball Super Card Game": "Dragon Ball",
        "One Piece Card Game": "One Piece",
        "Gundam CCG": "Gundam",
        "Pokemon": "Pokemon",
        "Pokémon TCG": "Pokemon",
    }.get(game, game)
    # カード番号から分母を除去（"231/193" → "231"）eBay検索では分母不要
    card_number = card_number.split("/")[0] if "/" in card_number else card_number

    query = f"PSA 10 {game_short} #{card_number} {character}"
    return query.strip()


# ===== 利益計算 =====

# ===== CSV読み込み =====
def get_col(row, col_name):
    """ヘッダー名から値を取得"""
    idx = HEADER_MAP.get(col_name)
    if idx is not None and idx < len(row):
        return str(row[idx]).strip()
    return ""


def find_latest_csv():
    """最新のebay_upload CSVを探す"""
    patterns = ["ebay_upload_*.csv", "data/ebay_upload_*.csv"]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    # _cost.json を除外
    files = [f for f in files if f.endswith(".csv")]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def load_csv(filepath):
    """CSVを読み込んでヘッダーとデータ行を返す"""
    global HEADER_MAP
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        HEADER_MAP = {h: i for i, h in enumerate(headers)}
        rows = list(reader)
    return headers, rows


def load_cost_data(csv_path):
    """サイドカーJSONから仕入値データを読み込む"""
    cost_file = csv_path.replace(".csv", "_cost.json")
    if os.path.exists(cost_file):
        with open(cost_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# ===== 内部バリデーション =====
def validate_row(row, row_idx):
    """1行のCSVデータをバリデーション。問題リストを返す"""
    issues = []
    title = get_col(row, "*Title")
    price = get_col(row, "*StartPrice")
    category = get_col(row, "*Category")
    condition = get_col(row, "ConditionID")
    shipping = get_col(row, "ShippingProfileName")
    cert = get_col(row, "CDA:Certification Number - (ID: 27503)")

    # --- タイトル ---
    if len(title) > MAX_TITLE_LEN:
        issues.append(("ERROR", f"タイトル{len(title)}字 > 上限{MAX_TITLE_LEN}字"))
    elif len(title) < IDEAL_TITLE_MIN:
        issues.append(("WARN", f"タイトル{len(title)}字 < 推奨{IDEAL_TITLE_MIN}字（キーワード不足の可能性）"))

    if not title.startswith("PSA 10"):
        issues.append(("ERROR", "タイトルが 'PSA 10' で始まっていない"))

    title_lower = title.lower()
    for banned in BANNED_TITLE_WORDS:
        if banned in title_lower:
            issues.append(("ERROR", f"禁止ワード '{banned}' がタイトルに含まれている"))

    # 単語重複チェック
    words = title.lower().split()
    seen = set()
    for w in words:
        if w in seen and len(w) >= 3 and w not in {"the", "of", "and", "in", "for"}:
            issues.append(("WARN", f"タイトル内で '{w}' が重複"))
            break
        seen.add(w)

    # --- カテゴリ・条件 ---
    if category != "183454":
        issues.append(("ERROR", f"カテゴリが 183454 でない: {category}"))
    if condition != "2750":
        issues.append(("ERROR", f"ConditionID が 2750 でない: {condition}"))

    # --- 価格・送料整合性 ---
    try:
        price_f = float(price)
        expected_policies = [
            (39, "<39"), (60, "40-60"), (100, "60-100"), (200, "100-200"),
            (300, "200-300"), (400, "300-400"), (500, "400-500"),
            (600, "500-600"), (800, "600-800"), (1000, "800-1000"),
        ]
        expected = "800-1000"
        for threshold, policy in expected_policies:
            if price_f <= threshold:
                expected = policy
                break
        if shipping != expected:
            issues.append(("WARN", f"送料ポリシー '{shipping}' が価格${price}に対して不一致（期待: {expected}）"))
    except ValueError:
        issues.append(("ERROR", f"価格が数値でない: {price}"))

    # --- 必須Item Specifics ---
    for spec in REQUIRED_SPECIFICS:
        val = get_col(row, spec)
        if not val:
            issues.append(("WARN", f"必須Item Specific '{spec}' が空"))

    # --- 推奨Item Specifics ---
    empty_recommended = [s for s in RECOMMENDED_SPECIFICS if not get_col(row, s)]
    if empty_recommended:
        names = ", ".join(s.replace("C:", "") for s in empty_recommended)
        issues.append(("INFO", f"推奨Item Specifics が空: {names}"))

    # --- PSA鑑定番号 ---
    if not cert or not cert.isdigit():
        issues.append(("ERROR", f"PSA鑑定番号が不正: {cert}"))

    return issues


# ===== 競合比較 =====
def compare_with_competitors(row, competitors, total_count, cost_jpy=None):
    """自社リスティング vs 競合を比較して所見を返す。
    価格基準: 全セラー中央値。TOPセラーは参考表示のみ。"""
    findings = []
    gate_result = None

    if not competitors:
        findings.append(("INFO", "競合0件 → $100で先行出品（市場未形成・先行者利益パターン）"))
        return findings, gate_result

    my_title = get_col(row, "*Title")

    # セラー分類
    all_stats, top_stats = classify_sellers(competitors)

    # 出品数（total）+ 全セラー統計
    if all_stats:
        top_info = ""
        if top_stats:
            top_info = f" (TOP${top_stats['median']:.0f})"
        findings.append(("INFO",
            f"出品{total_count}件 | 全体中央値${all_stats['median']:.0f}"
            f" (${all_stats['min']:.0f}-${all_stats['max']:.0f}){top_info}"))

    # 価格基準は全セラー中央値
    ref_median = all_stats["median"] if all_stats else 0

    # GATE判定（仕入値がある場合）— 価格帯別パラメータ適用
    if cost_jpy is not None and ref_median > 0:
        p = PROFIT_PARAMS
        net_ratio = 1 - p["ebay_fee_rate"] - p["promo_rate"] - p["payo_rate"]
        tier_profit, tier_gap_limit = get_tier_params(ref_median)
        costs_jpy = cost_jpy + p["shipping_jpy"]
        target_usd = costs_jpy / (p["exchange_rate"] * (net_ratio - tier_profit))
        breakeven_usd = costs_jpy / (p["exchange_rate"] * net_ratio)
        gap_pct = (target_usd - ref_median) / ref_median * 100 if ref_median > 0 else 999
        gap_limit_pct = tier_gap_limit * 100

        # 市場価格での利益計算
        revenue_jpy = ref_median * p["exchange_rate"]
        profit_jpy = revenue_jpy * net_ratio - costs_jpy
        profit_rate = profit_jpy / revenue_jpy if revenue_jpy > 0 else 0

        calc = {
            "cost_jpy": cost_jpy,
            "breakeven_usd": breakeven_usd,
            "target_usd": target_usd,
            "market_usd": ref_median,
            "profit_jpy": profit_jpy,
            "profit_rate": profit_rate,
            "gap_pct": gap_pct,
            "tier_profit": tier_profit,
            "gap_limit_pct": gap_limit_pct,
        }

        if gap_pct <= 0:
            gate_status = "GO"
            gate_msg = (f"✅ GO — 仕入¥{cost_jpy:,} → "
                        f"全体中央値${ref_median:.0f} → "
                        f"利益¥{profit_jpy:,.0f} ({profit_rate:.0%}) [目標{tier_profit:.0%}]")
        elif gap_pct <= gap_limit_pct:
            gate_status = "HOLD"
            gate_msg = (f"🟡 保留 — 仕入¥{cost_jpy:,} → "
                        f"全体中央値${ref_median:.0f} (乖離{gap_pct:.0f}%/許容{gap_limit_pct:.0f}%) → "
                        f"${target_usd:.0f}で出品")
        else:
            gate_status = "NOGO"
            gate_msg = (f"❌ NO-GO — 仕入¥{cost_jpy:,} → "
                        f"全体中央値${ref_median:.0f} (乖離{gap_pct:.0f}% > 許容{gap_limit_pct:.0f}%) → "
                        f"CSV除外済")

        findings.append(("GATE", gate_msg))
        gate_result = {
            "status": gate_status,
            "calc": calc,
            "ref_median": ref_median,
            "total": total_count,
        }

    # 競合タイトルからキーワード傾向を抽出
    comp_words = {}
    for item in competitors:
        t = item.get("title", "").lower()
        for w in t.split():
            w = w.strip('.,;:!?()[]"\'')
            if len(w) >= 3 and w not in {"psa", "the", "and", "for", "new"}:
                comp_words[w] = comp_words.get(w, 0) + 1

    my_words = set(my_title.lower().split())
    frequent = sorted(comp_words.items(), key=lambda x: -x[1])
    missing_keywords = []
    for word, count in frequent[:20]:
        if count >= 2 and word not in my_words and word not in {"card", "cards", "game"}:
            missing_keywords.append(f"{word}({count}件)")
    if missing_keywords:
        findings.append(("INFO", f"競合で頻出だが自分のタイトルにない語: {', '.join(missing_keywords[:5])}"))

    return findings, gate_result


# ===== Claude API レビュー =====
def load_anthropic_key():
    try:
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def claude_review(rows, all_issues, all_comp_findings, all_gates):
    """Claude APIで総合レビュー"""
    api_key = load_anthropic_key()
    if not api_key:
        print("\n⚠️ Claude APIキーなし。AI総合レビューをスキップします。")
        return None

    summary_lines = []
    for i, row in enumerate(rows):
        title = get_col(row, "*Title")
        price = get_col(row, "*StartPrice")
        game = get_col(row, "C:Game")
        character = get_col(row, "C:Character")
        rarity = get_col(row, "C:Rarity")
        features = get_col(row, "C:Features")
        card_type = get_col(row, "C:Card Type")
        set_name = get_col(row, "C:Set")
        finish = get_col(row, "C:Finish")

        issues_text = ""
        if all_issues[i]:
            issues_text = " | Issues: " + "; ".join(f"[{sev}] {msg}" for sev, msg in all_issues[i])

        comp_text = ""
        if all_comp_findings[i]:
            comp_text = " | Market: " + "; ".join(f"{msg}" for sev, msg in all_comp_findings[i])

        gate_text = ""
        if all_gates[i]:
            g = all_gates[i]
            gate_text = f" | GATE: {g['status']} (市場${g['ref_median']:.0f}, 利益¥{g['calc']['profit_jpy']:,.0f}, {g['calc']['profit_rate']:.0%})"

        summary_lines.append(
            f"#{i+1} Title: {title}\n"
            f"   Price: ${price} | Game: {game} | Set: {set_name} | Character: {character}\n"
            f"   Rarity: {rarity} | Features: {features} | Type: {card_type} | Finish: {finish}\n"
            f"   {issues_text}{comp_text}{gate_text}"
        )

    prompt = f"""You are an eBay listing quality reviewer for Japanese PSA-graded trading cards.
Review these {len(rows)} listings and provide actionable feedback.

LISTINGS:
{chr(10).join(summary_lines)}

Review each listing for:
1. TITLE QUALITY: Is it keyword-optimized? Does it include the most searchable terms? Max 80 chars.
2. PRICING: Based on GATE analysis, suggest specific listing prices. For GO items, recommend price at or slightly below TOP seller median. For NO-GO items, recommend not listing.
3. ITEM SPECIFICS: Are important fields missing that competitors typically fill?
4. OVERALL: Any patterns or systematic issues across all listings?

Rules to enforce:
- "PSA 10" must be at the start of every title
- No forbidden words: Japanese, GEM MT, Japan, Mint, Graded, L@@K
- Game short names: One Piece TCG, Dragon Ball SCG, Gundam CCG, Pokemon
- Title should be 70-80 characters ideally

Respond in Japanese. Be concise and actionable. Use bullet points.
Format: まず各リスティングの個別フィードバック、最後に全体の改善提案。"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        print(f"\n⚠️ Claude APIエラー: {e}")
        return None


# ===== メイン =====
def main():
    print("=== iMak Trading Japan - eBay CSV チェッカー ===\n")

    # CSV特定
    if len(sys.argv) >= 2:
        csv_path = sys.argv[1]
    else:
        csv_path = find_latest_csv()
        if not csv_path:
            print("エラー: ebay_upload CSVが見つかりません。パスを引数で指定してください。")
            return

    print(f"対象: {csv_path}")
    headers, rows = load_csv(csv_path)
    print(f"件数: {len(rows)} リスティング")

    # 仕入値データ読み込み
    cost_data = load_cost_data(csv_path)
    if cost_data:
        print(f"仕入値: {len(cost_data)}件のコストデータあり")
    else:
        print("仕入値: コストデータなし（certs.txtに「証明番号,仕入値」形式で記載するとGATE判定が有効になります）")

    # 利益計算パラメータ表示
    p = PROFIT_PARAMS
    net = 1 - p["ebay_fee_rate"] - p["promo_rate"] - p["payo_rate"]
    print(f"利益計算: 為替¥{p['exchange_rate']} | 手数料{p['ebay_fee_rate']:.1%}+プロモ{p['promo_rate']:.0%}+Payo{p['payo_rate']:.1%} | "
          f"net={net:.0%} | 送料¥{p['shipping_jpy']:,} | 目標利益=価格帯別")

    # eBay API準備
    ebay_keys = load_ebay_keys()
    token = None
    if ebay_keys.get("AppID") and ebay_keys.get("AppSecret"):
        try:
            token = get_oauth_token(ebay_keys["AppID"], ebay_keys["AppSecret"])
            print("✓ eBay API 接続OK\n")
        except Exception as e:
            print(f"⚠️ eBay API認証失敗: {e}\n")

    # === 各行チェック ===
    all_issues = []
    all_comp_findings = []
    all_gates = []

    for i, row in enumerate(rows):
        title = get_col(row, "*Title")
        cert = get_col(row, "CDA:Certification Number - (ID: 27503)")
        print(f"{'─'*60}")
        print(f"[{i+1}/{len(rows)}] {title}")

        # 仕入値取得
        cost_jpy = cost_data.get(cert)
        if cost_jpy is not None:
            print(f"  💰 仕入値: ¥{cost_jpy:,}")

        # 1) 内部バリデーション
        issues = validate_row(row, i)
        all_issues.append(issues)

        for sev, msg in issues:
            icon = {"ERROR": "❌", "WARN": "⚠️", "INFO": "ℹ️"}.get(sev, "•")
            print(f"  {icon} {msg}")

        # 2) 競合比較 + GATE判定
        comp_findings = []
        gate_result = None
        if token:
            query = build_search_query(row)
            print(f"  🔍 検索: {query}")
            competitors, total_count = search_ebay_active(token, query, limit=50)
            comp_findings, gate_result = compare_with_competitors(row, competitors, total_count, cost_jpy)
            for sev, msg in comp_findings:
                icon = {"ERROR": "❌", "WARN": "⚠️", "INFO": "ℹ️", "GATE": "🏁"}.get(sev, "•")
                print(f"  {icon} {msg}")

            # 3) TOPセラーItem Specifics比較
            if competitors:
                top_specs = fetch_top_seller_specs(token, competitors)
                if top_specs:
                    spec_findings = compare_item_specifics(row, top_specs)
                    for sev, msg in spec_findings:
                        icon = {"ERROR": "❌", "WARN": "⚠️", "INFO": "ℹ️"}.get(sev, "•")
                        print(f"  {icon} {msg}")
                    comp_findings.extend(spec_findings)

            time.sleep(0.5)  # API rate limit
        else:
            comp_findings.append(("INFO", "eBay API未接続のため競合比較スキップ"))

        all_comp_findings.append(comp_findings)
        all_gates.append(gate_result)

        if not issues and not [f for f in comp_findings if f[0] in ("ERROR", "WARN")]:
            print("  ✅ 問題なし")

    # === GATE判定サマリー ===
    print(f"\n{'═'*60}")
    print("  🏁 GATE判定サマリー")
    print(f"{'═'*60}")

    go_count = 0
    hold_count = 0
    nogo_count = 0
    no_data_count = 0

    for i, gate in enumerate(all_gates):
        title_short = get_col(rows[i], "*Title")[:40]
        if gate is None:
            no_data_count += 1
            print(f"  [{i+1}] {title_short}... → ⬜ 競合なし（$100で先行出品）")
        elif gate["status"] == "GO":
            go_count += 1
            c = gate["calc"]
            print(f"  [{i+1}] {title_short}... → ✅ GO  出品{gate['total']}件 ${c['market_usd']:.0f} 利益¥{c['profit_jpy']:,.0f} ({c['profit_rate']:.0%}) [目標{c['tier_profit']:.0%}]")
        elif gate["status"] == "HOLD":
            hold_count += 1
            c = gate["calc"]
            print(f"  [{i+1}] {title_short}... → 🟡 保留  出品{gate['total']}件 ${c['market_usd']:.0f} 乖離{c['gap_pct']:.0f}%/許容{c['gap_limit_pct']:.0f}% → ${c['target_usd']:.0f}で出品")
        else:
            nogo_count += 1
            c = gate["calc"]
            print(f"  [{i+1}] {title_short}... → ❌ NO-GO 出品{gate['total']}件 ${c['market_usd']:.0f} 乖離{c['gap_pct']:.0f}% > 許容{c['gap_limit_pct']:.0f}%")

    print(f"\n  結果: ✅ GO {go_count} / 🟡 保留 {hold_count} / ❌ NO-GO {nogo_count} / ⬜ 不明 {no_data_count}")

    # === チェックサマリー ===
    print(f"\n{'═'*60}")
    print("  チェックサマリー")
    print(f"{'═'*60}")

    error_count = sum(1 for issues in all_issues for sev, _ in issues if sev == "ERROR")
    warn_count = sum(1 for issues in all_issues for sev, _ in issues if sev == "WARN")

    print(f"  ❌ エラー: {error_count}件")
    print(f"  ⚠️ 警告:   {warn_count}件")

    if error_count == 0 and warn_count == 0:
        print("\n  🎉 全リスティング問題なし！")

    # === Claude AI 総合レビュー ===
    print(f"\n{'═'*60}")
    print("  🤖 AI総合レビュー")
    print(f"{'═'*60}")

    review = claude_review(rows, all_issues, all_comp_findings, all_gates)
    if review:
        print(f"\n{review}")

    print(f"\n{'═'*60}")
    print("  チェック完了")
    print(f"{'═'*60}")


if __name__ == "__main__":
    main()
