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
PSA_IMG_HOST = "d1htnxwo4o0jhw.cloudfront.net"  # PSA 画像 CDN (psa_to_csv と同値)
BANNED_TITLE_WORDS = [
    # 2026-06-08: psa_to_csv.py:721 と同期。"japanese"/"japan" は削除 (生成側は 2026-05-01 に既に削除済)。
    # JP 印刷版を eBay US で売る運用で事実情報・SEO価値高 (TOP競合多数が使用)。spam語のみ残す。
    # 生成 (psa_to_csv) が SSOT。post_title_fix が "Japanese" pad しても誤検出しないようになる。
    "gem mt", "gem-mt", "gemmt",
    "mint", "graded", "l@@k", "look", "wow", "nr",
]


def _banned_title_words_in(title, words):
    """禁止ワード照合。**定義は listing_common が SSOT** (単語境界・大小無視)。

    ここで再実装しない。2026-08-09: 4カテゴリの check_csv が素の `in` (部分一致) で
    照合していて "Shenron" の "nr" に反応していた。import 不能時も **部分一致には戻さない**。
    """
    import os as _o
    import sys as _s
    _p = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "iMakeBayAPI")
    if _p not in _s.path:
        _s.path.insert(0, _p)
    from listing_common import banned_title_words_in
    return banned_title_words_in(title, words)


# 必須Item Specifics（空欄だと品質低下）
REQUIRED_SPECIFICS = ["C:Game", "C:Set", "C:Card Name", "C:Character", "C:Rarity"]


# ★2026-07-29: レアリティ/キャラが **構造的に存在しない** カード種別。
# Catalog が1件ずつ実機判定して確定したもの (「取れなかった」ではなく「存在しない」)。
# 出所: hq/requests/2026-07-29_audit_exclusions_final_and_rarity_in_title.md (Advisor 経由)
#   - dragonball_scg ENERGY MARKER 257件 … 同base に rarity 持ち兄弟 0件
#   - gundam_tcg RESOURCE 140 / EX RESOURCE 13 / EX BASE 13 … 同上
# 粒度は **card_type / 番号 prefix 単位**。カテゴリ丸ごとの除外は本当の欠損を見逃すので禁止。
NO_RARITY_CARD_TYPES = {"don", "resource", "ex resource", "ex base", "energy marker"}
# 番号 prefix (小文字比較・DON! / Gundam RESOURCE のような番号体系)
# 2026-07-30 追加: Pokemon 番号 prefix 系 (Advisor 2026-07-29 応答 §1)
#   MC-* / SI-*  : スタートデッキ100 系 (1,185件)。デッキ収録カードは印刷レアリティ記号なし
#   CP4-* / CP5- : Classic 系 (件数未確認、要実測)。印刷レアリティ表記なし
# 番号 prefix 単位で判定 (C:Set の表記依存は禁止=Advisor 明示指示)。
NO_RARITY_NUMBER_PREFIXES = (
    "don-", "rp-",                 # One Piece DON!! / Gundam リソース
    "mc-", "si-", "cp4-", "cp5-",  # Pokemon スタートデッキ100 / Classic 系 (2026-07-30)
)
# キャラクター概念が無い種別 (name='リソース' / 'エナジーマーカー')
NO_CHARACTER_CARD_TYPES = {"resource", "ex resource", "ex base", "energy marker"}

# ★2026-07-30: Pokemon の hi-class パック系 set code prefix 単位除外。
# Advisor 応答 (2026-07-29): 「set 名の部分一致は却下、set code prefix で判定してください。
# C:Set の表記は生成側の都合で変わるので、判定が表記に依存すると静かに壊れる」。
# 対象は Advisor 提示の 11 件出品済 (公式 pokemon-card.com に rarity 表記が無い hi-class 系):
#   S8b   VMAXクライマックス       (S8b-101, S8b-126)
#   M2a   MEGAドリームex           (M2a-012, M2a-079)  ← 2026-07-29 実害はここ
#   SM8b  GXウルトラシャイニー     (SM8b-001, SM8b-089, SM8b-105)
#   SV4a  シャイニートレジャーex   (SV4a-055)
#   S6K   (7/29 一覧の 1 件)       (S6K-037)
#   XY    プロモ系                 (XY-139, XY-140)
#   HSZm  BW期プロモ               (HSZm-014)  ← セット同定不能で別途空欄確定
# 番号 prefix は小文字比較 (card_number.lower().startswith)。
# 判定粒度: `S8b-XXX` の "S8b-" 部分。product_id 全体でなく先頭 (英字+数字+"-") のみ照合。
NO_RARITY_POKEMON_SET_PREFIXES = (
    "s8b-", "m2a-", "sm8b-", "sv4a-", "s6k-", "xy-", "hszm-",
)


def required_specifics_for_card(card_number, card_type=""):
    """カード種別に応じた必須Item Specifics(純関数, test可)。

    DON!!カード(One Piece、card number 'DON-' prefix)は構造的に rarity を持たない特殊カード
    → C:Rarity を必須から外す。C:Type-on-bags と同型の「非該当spec誤検出」で、DON カードが
    毎監査で「C:Rarity 空」を出していた根本対策(2026-07-02)。won't-fix で隠すのでなく監査
    ルール自体を賢くする方針(Gemini 推奨: 恒久ロジックで識別できる例外はルール化が正)。

    2026-07-29: 同じ理屈で **Gundam RESOURCE系 / DBSCG ENERGY MARKER** も除外する
    (Catalog 実機判定で「存在しない」と確定)。これらは C:Character も持たない。

    2026-07-30: Pokemon hi-class パック系 set code prefix (S8b/M2a/SM8b/SV4a/S6K/XY/HSZm)
    + スタートデッキ100 / Classic 系 (MC/SI/CP4/CP5) を C:Rarity 除外に追加
    (公式 pokemon-card.com に rarity 表記無し = catalog 側で構造的に取得不能)。
    Advisor 応答 (2026-07-29): set 名部分一致は却下、set code prefix 単位で判定。
    """
    num = str(card_number).strip().lower()
    ctype = str(card_type).strip().lower()
    drop = set()
    if num.startswith(NO_RARITY_NUMBER_PREFIXES) or ctype in NO_RARITY_CARD_TYPES:
        drop.add("C:Rarity")
    # Pokemon set code prefix (hi-class + Classic 系)。既存 NO_RARITY_NUMBER_PREFIXES と
    # 別配列で管理する理由: 前者は franchise 横断 (DON!!/RESOURCE) だが本群は Pokemon 専用
    # で追加/削除の粒度が違う。監査ノイズ削減目的の除外は catalog の rarity 有無に追随して
    # 頻繁に更新される見込み。
    if num.startswith(NO_RARITY_POKEMON_SET_PREFIXES):
        drop.add("C:Rarity")
    if ctype in NO_CHARACTER_CARD_TYPES:
        drop.add("C:Character")
    return [s for s in REQUIRED_SPECIFICS if s not in drop] if drop else REQUIRED_SPECIFICS
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
# 価格帯別パラメータ: SSOT 抽象化 (profit_params.get_tier_params 経由)
from profit_params import get_tier_params  # noqa: F401

# TOPセラー判定閾値
TOP_SELLER_MIN_FEEDBACK = 500       # 取引実績500件以上
TOP_SELLER_MIN_PERCENTAGE = 98.0    # ポジティブ率98%以上

# 市場 median gate skip 条件 (psa_to_csv.py と SSOT、OR で評価):
#  (a) 出品数 ≤ MARKET_GATE_MIN_LISTINGS = 薄商い、median 不安定
#  (b) target_usd ≤ MARKET_GATE_MAX_TARGET_USD = 低額帯、焦付きリスク低
# どちらか満たせば 緩和 (gate skip でコストプラス価格採用、機会損失回避)
MARKET_GATE_MIN_LISTINGS = 10
MARKET_GATE_MAX_TARGET_USD = 250.0

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
    # 2026-05-01: getaddrinfo 失敗時に DNS flush + 1 回 retry (dns_resilience).
    # psa_to_csv → check_csv 連携時の DNS 切れも自動回復させる.
    import sys as _sys, os as _os
    _imakeBayAPI = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI")
    if _imakeBayAPI not in _sys.path:
        _sys.path.insert(0, _imakeBayAPI)
    from dns_resilience import with_dns_retry
    resp = with_dns_retry(
        requests.post,
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
    Returns: (items_list, total_count)

    2026-04-28 SSOT 化:
      実体は iMakeBayAPI/market_gate.py (psa_to_csv ↔ check_csv 共通).
      旧ロジック (本ファイル直書き) は market_gate に統合済.
      psa_to_csv が直前に同 query を fetch してれば cache hit で同 data 返却 →
      median ブレ解消 (dual_gate_disagreement.md CRITICAL の根本対処).
    """
    import sys as _sys, os as _os
    _imakeBayAPI = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI")
    if _imakeBayAPI not in _sys.path:
        _sys.path.insert(0, _imakeBayAPI)
    from market_gate import fetch_market_items as _fetch_mg
    return _fetch_mg(token, keywords, limit=limit)


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
        "One Piece CCG": "One Piece",  # 2026-05-31: eBay 正規値、 検索 query は短縮
        "Gundam CCG": "Gundam",  # 旧 listing 互換
        "Gundam Card Game": "Gundam",  # 2026-05-31: 当店 catalog 正規値
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
# ★2026-08-11: 契約 v1.2 (co-sign) に従い、set 整合の helper は **iMakCatalog 経由**で呼ぶ。
#   旧 import path (iMakHQ/tools/catalog_set_audit) は catalog 境界を越えていたため廃止。
#   catalog 側 (iMakCatalog/set_reference.py) が SSOT。ここでは cache だけ持つ。
_CATALOG_SET_REF = None  # {set_name_ebay: 主流total} を一度だけ catalog helper から構築・cache
_TCG_SET_MASTER = None  # eBay カテゴリ 183454 の master set_name_ebay 集合


def _tcg_set_master():
    """catalog helper から 183454 の master set_name_ebay 集合を取得。

    ★2026-08-11: 契約 v1.2 §4 CI 「183454 master に無い値が CSV に出ていない」用。
    生成側の脱線 (master 外の自由文字列が C:Set に混入) を出品前に弾く。
    catalog 読取失敗時は空集合を返して判定を降ろす (fail-open で誤ブロック回避)。

    ★2026-08-12 修正: 当初 `pokemon_set_master()` を使っていたが、183454 は
      **全 TCG 共通**の eBay カテゴリ (ポケモン/ワンピ/ドラゴンボール/ガンダム/遊戯王)。
      ポケモン専用 master を全行に当てていたため、catalog に実在する
      'Awakened Pulse' (dragonball) や '500 Years in the Future' (one_piece) まで
      「master に存在しない」で ERROR → 物理除外していた。
      実害: 8/12 の入稿は残り6件が全部ワンピ/ドラゴンボールで、**入稿0件**になった。
    """
    global _TCG_SET_MASTER
    if _TCG_SET_MASTER is None:
        try:
            import sys as _sys, os as _os
            _cat = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakCatalog")
            if _cat not in _sys.path:
                _sys.path.insert(0, _cat)
            from set_reference import tcg_set_master
            _TCG_SET_MASTER = tcg_set_master()
        except Exception:
            _TCG_SET_MASTER = set()
    return _TCG_SET_MASTER


def _catalog_set_consistency(set_name, card_number, year=""):
    """C:Set の整合チェック2種 (2026-06-07 set誤マップ事故対策)。矛盾なら理由、OK/判定不能は None。

    (A) Set ↔ カード番号total: catalog多数派total と食い違い (cross-era/total違いを検出)
    (B) Set世代 ↔ Year: set名の世代と Year が年代レンジ外 (catalog汚染に依存せず堅い)
    """
    global _CATALOG_SET_REF
    try:
        import sys as _sys, os as _os
        _cat = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakCatalog")
        if _cat not in _sys.path:
            _sys.path.insert(0, _cat)
        from set_reference import set_total_reference, row_set_issue, eb_era, ERA_YEARS
        if _CATALOG_SET_REF is None:
            _CATALOG_SET_REF = set_total_reference()
        # (A) total 整合
        issue = row_set_issue(set_name, card_number, _CATALOG_SET_REF)
        if issue:
            return issue
        # (B) 世代×Year 整合 (catalog参照に依存しない)
        import re as _re
        ee = eb_era(set_name or "")
        m = _re.search(r"(20\d\d)", str(year or ""))
        if ee in ERA_YEARS and m:
            y = int(m.group(1)); lo, hi = ERA_YEARS[ee]
            if not (lo <= y <= hi):
                return (f"Set世代↔Year 不整合: Set='{set_name}'(世代 {ee}:{lo}-{hi}) なのに Year={y} "
                        f"→ set_name_ebay 誤マップ疑い")
        return None
    except Exception:
        return None


def _canonical_pid(cert):
    """cert → 目視確定の canonical product_id。定義は listing_common に SSOT (再実装しない)。"""
    try:
        import os as _os
        import sys as _sys
        _api = _os.path.join(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__))), "iMakeBayAPI")
        if _api not in _sys.path:
            _sys.path.insert(0, _api)
        from listing_common import canonical_pid_for_cert
        return canonical_pid_for_cert(cert)
    except Exception:
        return ""


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

    # ★照合は listing_common に1本化 (2026-08-09)。素の `in` = 部分一致だったため
    #   "Shenron" の中の "nr" に反応し、$799 の Dragon Ball を誤って出品除外していた。
    #   生成 (psa_to_csv) は元から単語境界。リストだけ同期して照合ルールがズレていた。
    for banned in _banned_title_words_in(title, BANNED_TITLE_WORDS):
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

    # --- 価格・送料整合性 (V6 mode: DDP-{group}-P{tier} / V5 mode: tier 名) ---
    try:
        price_f = float(price)
        # listing_common.get_shipping_policy_name() 経由で期待値取得 (yaml v6_pricing.enabled で自動切替)
        try:
            import sys, os
            _eb = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI")
            if _eb not in sys.path:
                sys.path.insert(0, _eb)
            from listing_common import get_shipping_policy_name
            expected = get_shipping_policy_name(price_f, "TCG(PSA10)")
        except Exception:
            # fallback: 旧 V5 tier 名
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

    # --- 必須Item Specifics (card-aware: DON!!カードは C:Rarity 非該当) ---
    # ★2026-08-11: 契約 v1.2 §追加条 (2026-08-10 co-sign) に従い、判定キーは
    #   **canonical product_id のみ**。印刷番号 (`746/742`) を fallback で使わない。
    #   canonical が引けない場合は「除外を判定できない = 必須のまま扱う」に倒す
    #   (fail-closed: 誤って rarity を消すより defect のまま残す方が安全)。
    #   経緯: 7/29-7/30 に足した11個の Pokemon prefix が印刷番号では**1件も発火せず**、
    #   同じ pattern を fallback で許すと生成側の脱線 (canonical 未登録) を隠す。
    _card_key = _canonical_pid(cert)
    for spec in required_specifics_for_card(_card_key,
                                            get_col(row, "C:Card Type")):
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

    # --- カタログ内部整合: Set↔カード番号total / Set世代↔Year (2026-06-07 set誤マップ事故対策) ---
    _setissue = _catalog_set_consistency(get_col(row, "C:Set"), get_col(row, "C:Card Number"),
                                         get_col(row, "C:Year Manufactured"))
    if _setissue:
        issues.append(("ERROR", _setissue))

    # --- 183454 master 突合 CI (契約 v1.2 §4, 2026-08-11) ---
    # 183454 (= 全 TCG 共通カテゴリ) の C:Set 値は必ず catalog master に存在すること。
    # 生成側で master 外の自由文字列が混入していないかを毎行チェックする
    # (master 読取失敗時=空集合の時はスキップ、fail-open で誤ブロック回避)。
    if category == "183454":
        c_set = (get_col(row, "C:Set") or "").strip()
        master = _tcg_set_master()
        if c_set and master and c_set not in master:
            issues.append(("ERROR",
                f"C:Set='{c_set}' が catalog 183454 master に存在しない "
                f"(生成側で master 外の値が混入)"))

    issues.extend(description_issues(get_col(row, "*Description")))
    issues.extend(image_issues(get_col(row, "PicURL")))
    issues.extend(specifics_sanity_issues(row, title))

    return issues


# ===== 2026-08-13 追加の3チェック =====
# いずれも「実際に出てしまった不良」から起こしたもの。推測で足したものは無い。

# 商品説明テンプレは 13KB 前後。テンプレを読めなかった時の代替文は 72字。
# 間を広く取って 2,000字を下限にする (テンプレ差替えで多少縮んでも誤検出しない)。
_DESC_MIN_LEN = 2000


def description_issues(desc):
    """商品説明が「本物のテンプレ」になっているか (2026-08-13 実害から)。

    ★実害: 2026-08-12 19:43 の走行で、テンプレ(PSA10_snkrdunk.txt)を読めなかった6件が
      **1行のダミー文**(72字)のまま CSV に載り、監査も素通りして「入稿OK」になった。
      psa_to_csv.load_description() が読取失敗を握り潰してダミーを返す作りだったため、
      **誰も気づけない**(= fail-OPEN)。ユーザーが目視で発見した。
      過去78本を調べた結果、ダミー化はこの1本だけ = 一過性だが、次に起きても分からない。
    """
    d = str(desc or "")
    out = []
    if not d.strip():
        out.append(("ERROR", "商品説明が空 (テンプレ未挿入)"))
        return out
    if len(d) < _DESC_MIN_LEN:
        out.append(("ERROR",
                    f"商品説明が{len(d)}字しかない (テンプレ未挿入/読取失敗の疑い。"
                    f"通常は{_DESC_MIN_LEN}字以上)"))
    if "Specifications" not in d:
        out.append(("ERROR", "商品説明に Specifications ブロックが無い"))
    for tag in ("<ul>", "<li>"):
        if tag not in d:
            out.append(("ERROR", f"商品説明に {tag} が無い (HTML が壊れている疑い)"))
            break
    for op, cl in (("<ul>", "</ul>"), ("<li>", "</li>"), ("<p>", "</p>")):
        if d.count(op) != d.count(cl):
            out.append(("ERROR",
                        f"商品説明の {op} と {cl} の数が合わない "
                        f"({d.count(op)} vs {d.count(cl)})"))
    return out


def image_issues(pic_url):
    """商品画像のチェック (2026-08-13 実害から)。

    ★実害: PSA 画像 URL が /small/(380px) のまま出た行があった。380px では eBay の
      ズームが効かず、スラブの状態が見えない (memory: psa_large_variant の経緯)。
      /large/ が実在しない cert では /small/ のままが正しいので **WARN 止まり**。
    """
    urls = [u.strip() for u in str(pic_url or "").split("|") if u.strip()]
    out = []
    psa = [u for u in urls if PSA_IMG_HOST in u]
    if not psa:
        out.append(("ERROR", "PSA 画像が1枚も無い"))
    small = [u for u in psa if "/small/" in u]
    if small:
        out.append(("WARN",
                    f"PSA 画像 {len(small)}枚が /small/ (380px) のまま "
                    f"= eBay のズームが効かない"))
    return out


def specifics_sanity_issues(row, title):
    """Item Specifics に「変換前の生値」が残っていないか (2026-08-13 実害から)。

    ★実害: ドラゴンボール FB01-071 の C:Rarity が catalog の生値 'L★' のまま入り、
      post_title_fix が★を落として **'L'** になった。タイトルも「… Childhood L」で
      終わり、買い手には意味不明。catalog の変換表は L★ → SCR と定めているのに
      products 側が変換前の値を持っていた (= ①カタログのデータ側の誤り)。
      同型は dragonball_scg 5,577件中 **1,164件**が★付きの生値。
    ここは「eBay 正規値の一覧」と突合しない: ワンピは 'Rare'、ドラゴンボールは 'R' と
    表記系が揃っておらず、突合すると正しい行まで落ちる。**明らかに壊れている形**だけ見る。
    """
    out = []
    for col in ("C:Rarity", "C:Card Type", "C:Features"):
        v = (get_col(row, col) or "").strip()
        if not v:
            continue
        bad = [ch for ch in v if ord(ch) > 0x2000 and not ch.isalnum()]
        if bad:
            out.append(("ERROR",
                        f"{col}='{v}' に変換前の記号が残っている ({''.join(bad)}) "
                        f"= catalog の変換表を通していない値"))
    rarity = (get_col(row, "C:Rarity") or "").strip()
    if len(rarity) == 1 and rarity.isalpha():
        out.append(("ERROR",
                    f"C:Rarity='{rarity}' が1文字だけ "
                    f"(記号が落ちて潰れた疑い。例 'L★'→'L')"))
    t = str(title or "").strip()
    last = t.split()[-1] if t.split() else ""
    if len(last) == 1 and last.isalpha():
        out.append(("ERROR",
                    f"タイトルが1文字'{last}'で終わっている (末尾が欠けた疑い): {t}"))
    return out


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

        # 市場価格で売れた場合の利益(参考)。コストプラス出品では実際の出品価格で売るので非該当。
        revenue_jpy = ref_median * p["exchange_rate"]
        profit_jpy = revenue_jpy * net_ratio - costs_jpy
        profit_rate = profit_jpy / revenue_jpy if revenue_jpy > 0 else 0
        # 実際の出品価格(コストプラス=target_usd)で売れた場合の利益。= 我々が実際に list する価格。
        # 構造上 黒字(cost+margin)。AI レビューにはこちらを渡し「赤字」誤認を防ぐ(2026-06-21)。
        list_profit_jpy = target_usd * p["exchange_rate"] * net_ratio - costs_jpy
        list_profit_rate = list_profit_jpy / (target_usd * p["exchange_rate"]) if target_usd > 0 else 0

        calc = {
            "cost_jpy": cost_jpy,
            "breakeven_usd": breakeven_usd,
            "target_usd": target_usd,
            "market_usd": ref_median,
            "profit_jpy": profit_jpy,
            "profit_rate": profit_rate,
            "list_profit_jpy": list_profit_jpy,
            "list_profit_rate": list_profit_rate,
            "gap_pct": gap_pct,
            "tier_profit": tier_profit,
            "gap_limit_pct": gap_limit_pct,
        }

        if total_count <= MARKET_GATE_MIN_LISTINGS or target_usd <= MARKET_GATE_MAX_TARGET_USD:
            # 緩和条件 (OR、psa_to_csv.py と SSOT):
            #  (a) 薄商い: 出品数 ≤ MARKET_GATE_MIN_LISTINGS → median 信頼度低
            #  (b) 低額帯: target_usd ≤ MARKET_GATE_MAX_TARGET_USD → 焦付きリスク低
            # コストプラス価格 (target_usd) で出品継続、機会損失回避
            gate_status = "RELAX"
            if total_count <= MARKET_GATE_MIN_LISTINGS and target_usd <= MARKET_GATE_MAX_TARGET_USD:
                relax_reason = (f"出品{total_count}件≤{MARKET_GATE_MIN_LISTINGS}+"
                                f"target≤${MARKET_GATE_MAX_TARGET_USD:.0f}")
            elif total_count <= MARKET_GATE_MIN_LISTINGS:
                relax_reason = f"出品{total_count}件≤{MARKET_GATE_MIN_LISTINGS} (median 不安定)"
            else:
                relax_reason = f"target ${target_usd:.0f}≤${MARKET_GATE_MAX_TARGET_USD:.0f} (低額帯)"
            gate_msg = (f"🔓 緩和 — 仕入¥{cost_jpy:,} → "
                        f"{relax_reason}→gate skip → "
                        f"${target_usd:.0f}で出品")
        elif gap_pct <= 0:
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
            gate_status = "NOGO"   # 内部status名は維持(market_log/集計の互換)。表示は「高め(出品)」。
            # 2026-06-20 価格NO-GO廃止: コストプラス(損なし)+無在庫+既存メンテ追跡 → 価格で見送らない。
            gate_msg = (f"🔵 高め — 仕入¥{cost_jpy:,} → "
                        f"全体中央値${ref_median:.0f} (乖離{gap_pct:.0f}% > 許容{gap_limit_pct:.0f}%) → "
                        f"出品(既存メンテ追跡)")

        findings.append(("GATE", gate_msg))
        gate_result = {
            "status": gate_status,
            "calc": calc,
            "ref_median": ref_median,
            "total": total_count,
        }

    # 2026-06-15: 競合タイトルのキーワード傾向抽出は廃止。タイトルは catalog(SSOT)決定論生成なので
    # 競合語の注入は推測(catalog-official-only/fail-closed 違反)。価格ゲートのみ残す。
    return findings, gate_result


# ===== Claude API レビュー =====
def load_anthropic_key():
    try:
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def claude_review(rows, all_issues, all_comp_findings, all_gates):
    """Claude APIで総合レビュー (2026-08-13 既定 OFF)。

    ★止めた理由: 講評が **post_title_fix で直る前の値**を見ており、
      「81字で超過」「2022を削れ」等の**既に解決済みの指摘**を毎回85行出していた。
      戻したい時は global.yaml の ai_review.enabled を true に。
    """
    try:
        from config_loader import is_ai_review_enabled as _ai_on
        if not _ai_on():
            return None
    except Exception:
        return None
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
            # AI には **出品価格(コストプラス)で売れた場合の利益**を渡す(= 我々が実際に list する価格)。
            # 市場中央値での利益(profit_jpy)は「中央値で売った場合の参考」で、コストプラス出品では非該当。
            # これを渡すと高め品で負になり AI が「赤字/値下げ」と誤助言する → list_profit を正とする。
            _c = g['calc']
            gate_text = (f" | GATE: {g['status']} | 出品価格${_c['target_usd']:.0f}で売れた場合の利益"
                         f"¥{_c.get('list_profit_jpy', 0):,.0f}({_c.get('list_profit_rate', 0):.0%})"
                         f" | 市場中央値${g['ref_median']:.0f}(参考・コストプラス出品では売値はこの限りでない)")

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
2. PRICING: コストプラス価格(=出品価格)が SSOT。GATE の「出品価格で売れた場合の利益」は構造上 黒字。
   - **絶対にしてはいけない**: 「赤字」と書くこと(出品価格で売る=損はしない。市場中央値の利益は"中央値で
     売った場合の参考"でコストプラス出品では非該当。これを根拠に赤字判定しない)。「値下げ推奨」「出品しない/
     見送り」も書かない(値段は維持。無在庫=売れなくても損なし=free option)。
   - GO items: TOP seller median 前後を提案して可。RELAX/高め items: **コストプラス価格のまま維持**を推奨。
   - 高め(target>median 乖離超過)は **そのまま出品 + 既存メンテ追跡**(sell-through 監視 / より安い仕入れ
     再探索 / median 上昇時に price-revise)を flag。値下げ強制でなく「追跡」と書く。
3. ITEM SPECIFICS: Are important fields missing that competitors typically fill?
4. OVERALL: Any patterns or systematic issues across all listings?

Rules to enforce:
- "PSA 10" must be at the start of every title
- Forbidden words in TITLE (spam/redundant): GEM MT, Mint, Graded, L@@K
  ★ "Japanese" は **日本版カードの必須言語表記 = 有効な検索語**。禁止語ではない。
    タイトルに "Japanese" が在っても **絶対に flag/削除助言しないこと**(意図的に入れている)。
- Game short names in TITLE (= iMakKeywords PDF Q1 2026 Rank 準拠):
  * Pokemon (never "Pokemon TCG") / Yugioh (no hyphen) / One Piece (never "One Piece TCG") /
    Dragon Ball SCG / Gundam TCG (never "Gundam Card Game" in title)
  ★ タイトルが既に "Pokemon"(= "Pokemon TCG" でない)なら **正しい**。下の C:Game (Item Specifics)
    が "Pokémon TCG" でも、それは eBay 正規値で **タイトルとは別物**。タイトルを
    "Pokemon TCG → Pokemon" に直せ等と助言してはいけない(タイトルは既に正しい)。
- Finish 追加禁止 ("Foil"/"Holo" 等 SNAD クレーム直結リスク)
- C:Game (= Item Specifics、タイトルとは別) は eBay 正規値: Pokémon TCG / Yu-Gi-Oh! TCG / One Piece CCG / Dragon Ball Super Card Game / Gundam Card Game
- Title should be 70-80 characters ideally

Respond in Japanese. Be concise and actionable. Use bullet points.
Format: まず各リスティングの個別フィードバック、最後に全体の改善提案。"""

    try:
        from card_identifier import CLAUDE_MODEL  # モデル名 SSOT (1箇所集約)
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        print(f"\n⚠️ Claude APIエラー: {e}")
        return None


# ===== メイン =====
def main(csv_path: str | None = None):
    """check_csv エントリポイント.

    Phase D (2026-04-29): 関数呼出と CLI 単独実行の両対応にする.
      - csv_path 引数を渡せば直接処理 (psa_to_csv からの import 用途)
      - None なら sys.argv[1] か find_latest_csv() で従来通り解決 (CLI 用途)

    Why: psa_to_csv → check_csv を同一プロセスで連結し、market_gate の
    in-memory cache を共有させる (subprocess 跨ぎだと cache 喪失 → median ブレ).
    """
    print("=== iMak Trading Japan - eBay CSV チェッカー ===\n")

    # CSV特定
    if csv_path is None:
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

    # === 禁止 field 強制空欄化 (= W チェック gate、 2026-06-01 追加) ===
    # memory:finish_only_blank_other_keep_processed
    # variant_meta 等の別経路から finish 投入される事故防止 = 最終 gate で物理空欄化.
    # 違反検出時: 警告 log + 自動空欄化 + CSV 上書き保存.
    FORBIDDEN_BLANK_FIELDS = ["C:Finish"]
    _forbidden_hits = []
    for fld in FORBIDDEN_BLANK_FIELDS:
        if fld not in headers:
            continue
        idx = headers.index(fld)
        for i, r in enumerate(rows, 1):
            if idx < len(r) and r[idx]:
                _forbidden_hits.append((i, fld, r[idx]))
                r[idx] = ""
    if _forbidden_hits:
        print()
        print("=" * 60)
        print(f"⚠️ 禁止 field 強制空欄化 ({len(_forbidden_hits)} 件、 SNAD リスク回避):")
        for i, fld, val in _forbidden_hits[:10]:
            print(f"  [{i}] {fld}={val!r} → \"\" 強制空欄化")
        # CSV 上書き保存 (= 入稿前に物理修正、 入稿は空欄状態で行われる)
        try:
            import csv as _csv
            _bak = csv_path + ".bak_forbidden_strip"
            import shutil as _sh
            _sh.copy(csv_path, _bak)
            with open(csv_path, "w", newline="", encoding="utf-8") as _f:
                _w = _csv.writer(_f, quoting=_csv.QUOTE_NONNUMERIC)
                _w.writerow(headers)
                _w.writerows(rows)
            print(f"  📦 backup: {_bak}")
            print(f"  ✏️ CSV 上書き済 (= 禁止 field 空欄化反映)")
        except Exception as _e:
            print(f"  ⚠️ CSV 上書き失敗: {type(_e).__name__}: {_e}")
        print("=" * 60)
        print()

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

    # eBay API準備 (= 競合比較 / GATE 用。相場停止中は接続もしない)
    try:
        from config_loader import is_market_lookup_enabled as _mkt_on
        _market_lookup = _mkt_on()
    except Exception:
        _market_lookup = False
    ebay_keys = load_ebay_keys() if _market_lookup else {}
    token = None
    if not _market_lookup:
        print("(相場取得は停止中 — 価格は cost-plus。global.yaml market_lookup)\n")
    elif ebay_keys.get("AppID") and ebay_keys.get("AppSecret"):
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

            # 2026-06-15: TOPセラー Item Specifics 比較は廃止。生成は catalog(SSOT)決定論なので
            # 競合値は使わない(取り込むと catalog-official-only/fail-closed 違反)。市場は価格ゲートのみ参照。
            time.sleep(0.5)  # API rate limit
        elif not _market_lookup:
            pass  # 相場停止中 = 何も出さない (行ごとに同じ文言を並べない)
        else:
            comp_findings.append(("INFO", "eBay API未接続のため競合比較スキップ"))

        all_comp_findings.append(comp_findings)
        all_gates.append(gate_result)

        if not issues and not [f for f in comp_findings if f[0] in ("ERROR", "WARN")]:
            print("  ✅ 問題なし")

    # === GATE判定サマリー ===
    # ★2026-08-13: 相場停止中は判定していないので**判定行を出さない**。
    #   出すと全行に「競合なし($100で先行出品)」と並び、実際の価格 (cost-plus で
    #   $529.98 等) と食い違う **嘘のログ**になる (gate=None=未判定 を「競合なし」と
    #   読み替えていたため)。
    print(f"\n{'═'*60}")
    print("  🏁 GATE判定サマリー" if _market_lookup
          else "  🏁 価格: cost-plus のみ (相場取得は停止中 = GATE判定なし)")
    print(f"{'═'*60}")

    go_count = 0
    relax_count = 0
    hold_count = 0
    nogo_count = 0
    no_data_count = 0

    for i, gate in enumerate(all_gates if _market_lookup else []):
        title_short = get_col(rows[i], "*Title")[:40]
        if gate is None:
            no_data_count += 1
            print(f"  [{i+1}] {title_short}... → ⬜ 競合なし（$100で先行出品）")
        elif gate["status"] == "GO":
            go_count += 1
            c = gate["calc"]
            print(f"  [{i+1}] {title_short}... → ✅ GO  出品{gate['total']}件 ${c['market_usd']:.0f} 利益¥{c['profit_jpy']:,.0f} ({c['profit_rate']:.0%}) [目標{c['tier_profit']:.0%}]")
        elif gate["status"] == "RELAX":
            relax_count += 1
            c = gate["calc"]
            # 緩和理由 (出品数 / target_usd / 両方)
            if gate['total'] <= MARKET_GATE_MIN_LISTINGS and c['target_usd'] <= MARKET_GATE_MAX_TARGET_USD:
                tag = f"出品{gate['total']}件+target≤${MARKET_GATE_MAX_TARGET_USD:.0f}"
            elif gate['total'] <= MARKET_GATE_MIN_LISTINGS:
                tag = f"出品{gate['total']}件≤{MARKET_GATE_MIN_LISTINGS}"
            else:
                tag = f"target ${c['target_usd']:.0f}≤${MARKET_GATE_MAX_TARGET_USD:.0f}"
            print(f"  [{i+1}] {title_short}... → 🔓 緩和 {tag} → ${c['target_usd']:.0f}で出品")
        elif gate["status"] == "HOLD":
            hold_count += 1
            c = gate["calc"]
            print(f"  [{i+1}] {title_short}... → 🟡 保留  出品{gate['total']}件 ${c['market_usd']:.0f} 乖離{c['gap_pct']:.0f}%/許容{c['gap_limit_pct']:.0f}% → ${c['target_usd']:.0f}で出品")
        else:
            nogo_count += 1
            c = gate["calc"]
            # 2026-06-20 価格NO-GO廃止: 高めは除外せず出品 + 既存メンテ追跡(excluder が高めとして記録)。
            print(f"  [{i+1}] {title_short}... → 🔵 高め 出品{gate['total']}件 ${c['market_usd']:.0f} 乖離{c['gap_pct']:.0f}% > 許容{c['gap_limit_pct']:.0f}% → 出品(既存メンテ追跡)")

    print(f"\n  結果: ✅ GO {go_count} / 🔓 緩和 {relax_count} / 🟡 保留 {hold_count} / 🔵 高め(出品) {nogo_count} / ⬜ 不明 {no_data_count}")

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
    # ★2026-08-13: 停止中は**見出しも出さない**。中身が空なのに枠線+タイトルで3行使うのは
    #   「無駄なログを消す」の趣旨に反する。
    review = claude_review(rows, all_issues, all_comp_findings, all_gates)
    if review:
        print(f"\n{'═'*60}")
        print("  🤖 AI総合レビュー")
        print(f"{'═'*60}")
        print(f"\n{review}")

    print(f"\n{'═'*60}")
    print("  チェック完了")
    print(f"{'═'*60}")


if __name__ == "__main__":
    main()
