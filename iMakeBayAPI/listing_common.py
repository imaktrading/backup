#!/usr/bin/env python3
"""
iMak Trading Japan - 全カテゴリ共通リスティング処理ライブラリ

## 目的
全 listing スクリプト (mercari_to_ebay_csv.py / tshirt_listing.py / montbell_listing.py /
gshock_to_csv.py / ichibankuji_to_csv.py) で共通利用する deterministic 検証・整形ロジック。

## 提供機能
- CONDITION_MASTER: ConditionID ↔ Title marker / ConditionDescription / メルカリ状態 物理マッピング
- enforce_title_coherence(): ConditionID と Title 末尾の整合保証 (Pre-owned/Brand New)
- pad_title_to_target(): タイトル文字数 70-79 字目標に自動パディング
- extract_sku_from_url(): URL末尾12文字 SKU化（カテゴリ別prefix fallback）
- is_new_condition(): スプシ E列「状態」値から新品判定
- determine_condition_id(): L列(ConditionID)優先 + E列(状態)fallback + cfg値
- detect_condition_id_from_state(): メルカリ状態 → ConditionID 逆引き
- get_default_condition_description(): ConditionID + メルカリ状態 → ConditionDescription 確定生成
- get_title_marker_for_condition(): 残り文字数に応じた最適 Title marker 選択
- fetch_amazon_title(): Amazon URL から specific variation タイトル取得
- audit_csv_row(): CSV行を最終検証、違反リスト返却

## 設計原則
- SYSTEM_PROMPT に依存しない deterministic 実行
- 全カテゴリで同じロジック (水平展開漏れ防止)
- 違反を物理的にブロック or 自動修正
"""
import re
from datetime import datetime


# ===================================================================
# CONDITION_MASTER (ConditionID ↔ メルカリ状態 ↔ Title marker ↔ Description 物理マッピング)
# ===================================================================
CONDITION_MASTER = {
    1000: {
        "name": "Brand New",
        "title_markers": ["Brand New Japan", "Brand New", "New Japan", "New"],
        "description_default": "Brand new, unused condition. Comes with original packaging when applicable.",
        "mercari_states": ["新品", "新品、未使用", "未使用"],
    },
    1500: {
        "name": "New (Other)",
        "title_markers": ["New", "Open Box"],
        "description_default": "",
        "mercari_states": [],
    },
    3000: {
        "name": "Pre-owned",
        "title_markers": ["Pre-owned Japan", "Pre-owned", "Used Japan", "Used"],
        # キー名は description_default で統一（型は dict、メルカリ状態→英訳マッピング）
        "description_default": {
            "未使用に近い": "Near mint condition. Almost no signs of use.",
            "目立った傷や汚れなし": "Excellent condition. Very minor signs of use if any.",
            "やや傷や汚れあり": "Good condition. Some minor scratches or signs of wear.",
            "傷や汚れあり": "Fair condition. Visible scratches and signs of use.",
            "全体的に状態が悪い": "Poor condition. Heavy signs of use, please check photos carefully.",
        },
        "mercari_states": ["未使用に近い", "目立った傷や汚れなし", "やや傷や汚れあり", "傷や汚れあり", "全体的に状態が悪い"],
    },
    7000: {
        "name": "For parts or not working",
        "title_markers": ["For Parts", "Junk"],
        "description_default": "AS-IS condition. Sold for parts or repair only.",
        "mercari_states": [],
    },
}


# ===================================================================
# SKU 抽出
# ===================================================================
SKU_PREFIX_BY_CATEGORY = {
    "porter": "PORT",
    "reel": "REEL",
    "tomica": "TOMI",
    "ichibankuji": "KUJI",
    "tshirt": "TSHT",
    "montbell": "MONT",
    "gshock": "GSHK",
    "tcg": "TCG",
}


def extract_sku_from_url(url: str, category: str = None) -> str:
    """URLの末尾12文字を SKU として抽出（スプシURL逆引き用）。
    クエリ・末尾スラッシュ除去後、末尾12文字。空URLはカテゴリprefix+日時。"""
    if not url:
        prefix = SKU_PREFIX_BY_CATEGORY.get(category, "ITEM")
        return f"{prefix}-{datetime.now().strftime('%m%d%H%M%S')}"
    cleaned = url.split("?")[0].split("#")[0].rstrip("/")
    return cleaned[-12:].lstrip("/")


# ===================================================================
# 新品/中古判定
# ===================================================================
def is_new_condition(condition_jp: str) -> bool:
    """スプシE列の状態値から新品か判定。"""
    if not condition_jp:
        return False
    c = str(condition_jp).strip()
    if c in ("新品、未使用", "新品", "未使用"):
        return True
    if c.startswith("新品"):
        return True
    return False


_VALID_CONDITION_IDS = ("1000", "1500", "2000", "2010", "2020", "2030", "2500", "2750", "3000", "4000", "5000", "6000", "7000")


def determine_condition_id(condition_id_sheet: str, condition_jp: str, cfg_default: int) -> tuple:
    """L列(ConditionID)優先 → E列(状態)fallback → cfg値。
    Returns: (final_condition_id, is_new)
    """
    s = str(condition_id_sheet or "").strip()
    if s in _VALID_CONDITION_IDS:
        cid = int(s)
        return cid, (cid == 1000)
    is_new = is_new_condition(condition_jp)
    return (1000 if is_new else cfg_default), is_new


def detect_condition_id_from_state(mercari_state: str):
    """メルカリ状態文字列から ConditionID を逆引き（CONDITION_MASTER の mercari_states を走査）"""
    if not mercari_state:
        return None
    for cid, data in CONDITION_MASTER.items():
        if mercari_state in data.get("mercari_states", []):
            return cid
    return None


def get_default_condition_description(condition_id: int, mercari_state: str = "") -> str:
    """ConditionID + メルカリ状態 から ConditionDescription を deterministic 生成。
    - 1000 (新品) → CONDITION_MASTER[1000]["description_default"] 固定
    - 3000 (中古) → メルカリ状態に対応する英訳テンプレ + "Please review all photos for details."
    - その他 → CONDITION_MASTER の description_default (空文字 or 定型)
    """
    master = CONDITION_MASTER.get(condition_id)
    if not master:
        return ""
    default_data = master.get("description_default", "")
    # 辞書型 (3000) の場合は メルカリ状態でルックアップ
    if isinstance(default_data, dict):
        base_desc = default_data.get(mercari_state, "Pre-owned condition.")
        return f"{base_desc} Please review all photos for details."
    return default_data


def get_title_marker_for_condition(condition_id: int, available_chars: int) -> str:
    """空き文字数に応じた最適な title_marker を CONDITION_MASTER から選ぶ（長い順に試行）"""
    master = CONDITION_MASTER.get(condition_id)
    if not master:
        return ""
    for marker in master["title_markers"]:
        if len(marker) + 1 <= available_chars:  # +1 はスペース分
            return marker
    return ""


# ===================================================================
# Amazon variation 正式タイトル取得
# ===================================================================
_AMAZON_TITLE_CACHE = {}


def fetch_amazon_title(url: str) -> str:
    """Amazon URLから specific variation のページタイトル取得。"""
    if not url or "amazon" not in url.lower():
        return ""
    if url in _AMAZON_TITLE_CACHE:
        return _AMAZON_TITLE_CACHE[url]
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
            "Accept-Language": "ja,en-US;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        if not m:
            _AMAZON_TITLE_CACHE[url] = ""
            return ""
        title = m.group(1).strip()
        parts = [p.strip() for p in title.split('|')]
        if len(parts) >= 2 and parts[0].lower().startswith('amazon'):
            result = parts[1]
        else:
            result = title
        _AMAZON_TITLE_CACHE[url] = result
        return result
    except Exception:
        _AMAZON_TITLE_CACHE[url] = ""
        return ""


# ===================================================================
# Title 整合性保証 (ConditionID ↔ Title)
# ===================================================================
def enforce_title_coherence(title: str, is_new: bool = None, condition_id: int = None,
                             max_chars: int = 80) -> str:
    """旧シグネチャ(is_new)と新シグネチャ(condition_id)の両方に対応。
    Word boundary正規表現で偽陽性防止 (例: "Renewed" は "New" と判定しない)。
    """
    # 引数の相互変換 (Breaking Change 回避)
    if condition_id is None and is_new is not None:
        condition_id = 1000 if is_new else 3000
    if condition_id is None:
        return title[:max_chars].strip()

    master = CONDITION_MASTER.get(condition_id)
    if not master:
        return title[:max_chars].strip()

    # 反対側の marker を除去（新品なら Pre-owned系除去、中古なら Brand New系除去）
    if condition_id == 1000:
        title = re.sub(r'\s*\bPre-?owned(\s+Japan)?\b', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*\bUsed(\s+Japan)?\b', '', title, flags=re.IGNORECASE)
    elif condition_id == 3000:
        title = re.sub(r'\s*\bBrand New(\s+Japan)?\b', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*\bNew\s+Japan\b', '', title, flags=re.IGNORECASE)
        # "New" 単独除去（ただし Pre-owned 含む既存タイトルは触らない）
        if not re.search(r'\bPre-?owned\b', title, re.IGNORECASE):
            title = re.sub(r'\s*\bNew\b', '', title, flags=re.IGNORECASE)

    title = re.sub(r'\s+', ' ', title).strip()

    # 既に適切なマーカーが含まれているか word boundary でチェック
    has_marker = False
    for marker in master["title_markers"]:
        pattern = rf"\b{re.escape(marker)}\b"
        if re.search(pattern, title, re.IGNORECASE):
            has_marker = True
            break
    if has_marker:
        return title[:max_chars].strip()

    # マーカーがない場合、最適なものを末尾付与
    current_len = len(title)
    best_marker = get_title_marker_for_condition(condition_id, max_chars - current_len)
    if best_marker:
        return f"{title.strip()} {best_marker}"[:max_chars].strip()

    # スペース不足時の強制ねじ込み（最短 marker をねじ込み、タイトル末尾を削る）
    shortest_marker = master["title_markers"][-1]
    truncated_title = title[:(max_chars - len(shortest_marker) - 1)].strip()
    return f"{truncated_title} {shortest_marker}"


# ===================================================================
# Title 文字数パディング (70-79字目標)
# ===================================================================
def pad_title_to_target(title: str, item_specifics: dict, category: str = None,
                        target_min: int = 70, max_chars: int = 80) -> str:
    """タイトル長 < target_min なら Item Specifics と PDF キーワードで自動パディング。
    全カテゴリ共通実装。"""
    if len(title) >= target_min:
        return title

    # 1. "Reel" → "Fishing Reel" (リール限定)
    if category == "reel" and re.search(r'\bReel\b', title) and 'Fishing Reel' not in title:
        new_title = re.sub(r'\bReel\b', 'Fishing Reel', title, count=1)
        if len(new_title) <= max_chars:
            title = new_title

    # 2-N. Item Specifics の値を順次挿入（既に含まれてる値はスキップ）
    pad_keys_priority = [
        'Item Weight', 'Gear Ratio', 'Maximum Drag',  # リール系
        'Color', 'Material', 'Size', 'Style',  # 全カテゴリ
        'Year Manufactured', 'Series',
    ]
    for key in pad_keys_priority:
        if len(title) >= target_min:
            break
        val = item_specifics.get(key, '')
        if not val or val in ('Multicolor', 'Multi-Color', 'Does not apply', 'Other'):
            continue
        val_clean = str(val).replace(' ', '') if key == 'Item Weight' else str(val)
        if val_clean.lower() in title.lower():
            continue
        insert = f' {val_clean}'
        if len(title) + len(insert) > max_chars:
            continue
        # "Brand New"/"Pre-owned" の前に挿入
        pat = re.search(r'\b(Brand New|Pre-owned|New)\b', title)
        if pat:
            title = title[:pat.start()].rstrip() + insert + ' ' + title[pat.start():]
        else:
            title = title.strip() + insert

    return re.sub(r'\s+', ' ', title).strip()


# ===================================================================
# 統合: enforce + pad
# ===================================================================
def normalize_title(title: str, is_new: bool, item_specifics: dict, category: str = None,
                    target_min: int = 70, max_chars: int = 80) -> str:
    """Title整合性保証 + 文字数パディングを一括実行（推奨API）。"""
    title = enforce_title_coherence(title, is_new=is_new, max_chars=max_chars)
    title = pad_title_to_target(title, item_specifics, category=category,
                                 target_min=target_min, max_chars=max_chars)
    return title


# ===================================================================
# 市場価格チェック有効化マップ（pricing_engine の status="ALERT" を物理 HOLD する対象）
# Porter等の1点ものは enabled=False で除外（相場無視のコストプラス維持）
# 倍率/閾値は SSOT である pricing_engine.TIER_PARAMS に一任。ここでは ON/OFF のみ管理。
# ===================================================================
PRICE_CHECK_CONFIG = {
    "reel":        {"enabled": True},
    "tshirt":      {"enabled": True},
    "ichibankuji": {"enabled": True},
    "tomica":      {"enabled": True},
    "gshock":      {"enabled": False},  # スクリプト未結線。price_status を渡す実装が入るまで False で統一
    "montbell":    {"enabled": True},
    "porter":      {"enabled": False},  # 1点もの・相場形成不能
}


# ===================================================================
# CSV行の最終監査 (機能統合版)
# ===================================================================
def audit_csv_row(row_data: dict, category: str = None, mercari_state: str = "",
                  price_status: str = "GO", median_usd: float = 0) -> list:
    """既存の全チェック項目を包含し、新機能(Condition整合性 + 価格相場乖離)を統合した最終ゲート。

    Args:
      row_data: CSV1行 (dict)
      category: "reel","tshirt","porter" 等 — PRICE_CHECK_CONFIG / whitelist_registry のキー
      mercari_state: メルカリ状態文字列（ConditionID 逆引き照合用）
      price_status: pricing_engine.compute_listing_price の status ("GO"/"ALERT"/"NO_MEDIAN")
      median_usd: 取得した eBay 市場中央値（HOLD理由メッセージ用）

    Returns: [(field, issue, severity), ...] severity: "error" or "warning"
    """
    violations = []
    title = str(row_data.get("*Title", ""))
    cid = row_data.get("ConditionID")
    cd = str(row_data.get("ConditionDescription", ""))
    brand = row_data.get("C:Brand")

    # 0. 市場価格乖離チェック (Error/HOLD)
    #    pricing_engine が ALERT (= ティア別 gap_limit 超過) を出し、
    #    かつ当該カテゴリで価格チェック有効なら物理 HOLD
    cfg = PRICE_CHECK_CONFIG.get(category, {"enabled": False})
    if cfg.get("enabled") and price_status == "ALERT":
        try:
            current_price = float(row_data.get("*StartPrice", 0))
        except (ValueError, TypeError):
            current_price = 0.0
        msg = (f"Price ${current_price:.2f} exceeds market tier limit "
               f"vs median ${median_usd:.2f} (pricing_engine ALERT)")
        violations.append(("*StartPrice", msg, "error"))

    # 1. 必須項目欠落 (Error)
    for f in ["*Title", "*Category", "*StartPrice", "ConditionID"]:
        if not row_data.get(f):
            violations.append((f, "Field is required", "error"))

    # 2. タイトル長 (Warning/Error)
    t_len = len(title)
    if t_len > 80:
        violations.append(("*Title", f"Length {t_len} > 80", "error"))
    elif t_len < 50:
        violations.append(("*Title", f"Too short ({t_len} < 50)", "warning"))
    elif t_len < 70:
        violations.append(("*Title", f"Suboptimal length ({t_len} < 70)", "warning"))

    # 3. ブランド必須 (Error)
    if not brand:
        violations.append(("C:Brand", "Brand is required for most categories", "error"))

    # 4. Title Marker 整合性 (\b 単語境界版) (Error)
    master = CONDITION_MASTER.get(cid)
    if master:
        has_m = any(re.search(rf"\b{re.escape(m)}\b", title, re.IGNORECASE)
                    for m in master["title_markers"])
        if not has_m:
            violations.append(("*Title", f"Missing condition marker for ID {cid}", "error"))

    # 5. Mercari 状態と ConditionID の逆引き照合 (Warning)
    if mercari_state:
        expected_cid = detect_condition_id_from_state(mercari_state)
        if expected_cid and cid != expected_cid:
            violations.append(("ConditionID",
                              f"Mismatch with Mercari state '{mercari_state}' (Expected {expected_cid})",
                              "warning"))

    # 6. ConditionDescription 整合性
    if cid == 1000:
        default_desc = CONDITION_MASTER[1000]["description_default"]
        if cd and cd != default_desc:
            violations.append(("ConditionDescription", "Non-standard description for Brand New", "warning"))
    elif cid == 3000 and not cd:
        violations.append(("ConditionDescription", "Required for Pre-owned", "error"))

    # 7. whitelist_registry の category別 enum/range/max_length と照合 (eBay APIがrejectするレベルの違反検出)
    if category:
        try:
            from whitelist_registry import validate_and_normalize as _v
            specs_for_audit = {k[2:]: v for k, v in row_data.items() if k.startswith("C:")}
            _, white_viol = _v(specs_for_audit, category)
            for f, o, _ex, r in white_viol:
                # max_length / regex_mismatch / not_in_whitelist は error 級
                if "max_length" in str(_ex).lower() or "超過" in r or "regex_mismatch" in r:
                    violations.append((f"C:{f}", f"{r} (eBay reject-grade): {o}", "error"))
                elif "範囲外" in r or "異種商品混入" in r:
                    violations.append((f"C:{f}", f"{r}: {o}", "error"))
                # whitelist違反 (strict=True) も error
                elif "not_in_whitelist" in r:
                    violations.append((f"C:{f}", f"非フィルタ値: {o}", "error"))
        except Exception:
            pass

    return violations


# ===================================================================
# HOLDキュー: audit_csv_row でerror検出した行を隔離保存
# ===================================================================
_HOLD_QUEUE_PATH = None


def _hold_queue_path():
    """HOLDキューファイル(JSONL)のパスを返す。iMakHQ/review_logs/csv_hold_queue.jsonl"""
    global _HOLD_QUEUE_PATH
    if _HOLD_QUEUE_PATH is not None:
        return _HOLD_QUEUE_PATH
    from pathlib import Path
    here = Path(__file__).resolve().parent  # iMakeBayAPI/
    log_dir = here.parent / "iMakHQ" / "review_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _HOLD_QUEUE_PATH = log_dir / "csv_hold_queue.jsonl"
    return _HOLD_QUEUE_PATH


def append_to_hold_queue(category: str, sku: str, title: str,
                          violations: list, row_data: dict = None) -> None:
    """audit_csv_row で error検出した行を HOLDキュー(JSONL)に追記。
    violations: [(field, issue, severity), ...]
    """
    import json as _json
    from datetime import datetime as _dt
    try:
        path = _hold_queue_path()
        entry = {
            "ts": _dt.now().isoformat(),
            "category": category,
            "sku": sku,
            "title": title,
            "violations": [{"field": f, "issue": i, "severity": s} for f, i, s in violations],
        }
        if row_data:
            # 全列保持はサイズ大なので、Title/ConditionID/Brand/Category 等の主要キーのみ
            entry["row_summary"] = {
                k: row_data.get(k, "")
                for k in ("*Title", "*Category", "*StartPrice", "ConditionID",
                          "ConditionDescription", "C:Brand", "CustomLabel")
            }
        with path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as _e:
        # HOLD書込失敗は warning のみ（CSV出力は継続）
        print(f"    ⚠️ HOLDキュー書込失敗: {_e}")


def gate_row_or_hold(row_data: dict, category: str = None,
                     mercari_state: str = "", sku: str = "",
                     price_status: str = "GO", median_usd: float = 0) -> tuple:
    """物理ゲート: audit_csv_row 実行 → error あれば HOLDへ隔離 + False返却。

    Args:
      price_status: pricing_engine の status ("GO"/"ALERT"/"NO_MEDIAN")
      median_usd: eBay 市場中央値（HOLD理由用）

    Returns: (allowed: bool, violations: list)
      allowed=True: CSVに書き込んでよい (warningのみ or 違反なし)
      allowed=False: HOLDキューに移動済、CSV書込スキップ
    """
    violations = audit_csv_row(row_data, category=category, mercari_state=mercari_state,
                                price_status=price_status, median_usd=median_usd)
    errors = [v for v in violations if v[2] == "error"]
    if errors:
        title = str(row_data.get("*Title", ""))
        append_to_hold_queue(category or "unknown", sku, title, violations, row_data)
        return False, violations
    return True, violations


# ===================================================================
# Smoke tests (適用後の deterministic 動作確認)
# ===================================================================
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("Starting comprehensive smoke tests...")

    # 1. CONDITION_MASTER 基本構造検証
    assert 1000 in CONDITION_MASTER
    assert "新品" in CONDITION_MASTER[1000]["mercari_states"]
    assert isinstance(CONDITION_MASTER[3000]["description_default"], dict)

    # 2. 状態判定ロジック
    assert detect_condition_id_from_state("新品") == 1000
    assert detect_condition_id_from_state("やや傷や汚れあり") == 3000
    assert detect_condition_id_from_state("不明") is None

    # 3. get_default_condition_description
    assert "Brand new" in get_default_condition_description(1000)
    desc_used = get_default_condition_description(3000, "傷や汚れあり")
    assert "scratches" in desc_used.lower() or "wear" in desc_used.lower()
    assert "Please review all photos" in desc_used

    # 4. enforce_title_coherence (Word Boundary & シグネチャ互換性)
    t1 = enforce_title_coherence("Shimano Reel", is_new=True)
    assert "Brand New" in t1, f"Expected 'Brand New' in '{t1}'"
    # 偽陽性防止 (Renewed という単語があっても 'New' marker を別途付与する)
    t2 = enforce_title_coherence("Daiwa Renewed Item", condition_id=1000)
    new_count = len(re.findall(r"\bNew\b", t2, re.IGNORECASE))
    assert new_count == 1, f"Expected 1 'New' word boundary, got {new_count} in '{t2}'"

    # 5. audit_csv_row 正常系 (必須項目を網羅)
    row_ok = {
        "*Title": "Daiwa Reel Brand New Japan",
        "*Category": 261030,
        "*StartPrice": 100,
        "ConditionID": 1000,
        "ConditionDescription": CONDITION_MASTER[1000]["description_default"],
        "C:Brand": "Daiwa",
    }
    v_ok = audit_csv_row(row_ok, category="reel", mercari_state="新品")
    errors = [m for f, m, s in v_ok if s == "error"]
    assert len(errors) == 0, f"Unexpected errors: {errors}"

    # 6. audit_csv_row 異常系 (物理ゲート作動確認)
    row_bad = {
        "*Title": "Incomplete Title",  # マーカー欠落、短い
        "*Category": 261030,
        # *StartPrice 欠落
        "ConditionID": 1000,
        "C:Brand": "",  # Brand 欠落
    }
    v_bad = audit_csv_row(row_bad, category="reel", mercari_state="新品")
    err_fields = [f for f, m, s in v_bad if s == "error"]
    assert "*StartPrice" in err_fields
    assert "C:Brand" in err_fields
    assert "*Title" in err_fields  # マーカー欠落エラー

    # 7. gate_row_or_hold 動作テスト
    row_pass = {
        "*Title": "Daiwa Reel Brand New Japan",
        "*Category": 261030, "*StartPrice": 100,
        "ConditionID": 1000, "ConditionDescription": CONDITION_MASTER[1000]["description_default"],
        "C:Brand": "Daiwa",
    }
    allowed, _ = gate_row_or_hold(row_pass, category="reel", mercari_state="新品", sku="TEST_PASS")
    assert allowed, "正常行が gate ブロックされた"

    row_fail = {
        "*Title": "Bad No Brand No Marker",
        "*Category": 261030, "*StartPrice": 100,
        "ConditionID": 1000,
        "C:Brand": "",  # Brand欠落 → error
    }
    allowed_bad, _ = gate_row_or_hold(row_fail, category="reel", mercari_state="新品", sku="TEST_FAIL")
    assert not allowed_bad, "Brand欠落の異常行が gate を通過した"

    print("✅ All smoke tests passed. System is now deterministic.")
