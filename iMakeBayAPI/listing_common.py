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
def _truncate_at_word(s: str, n: int) -> str:
    """n文字以内に **語境界** で切り詰める(語を途中で割らない)。純関数。

    2026-06-21: title[:80] の文字切断が 'Japan New' を 'Ja New' に割る defect の是正。
    n以内に収まる最後の空白で切る。空白が無ければやむなく文字切り(極端な長語のみ)。
    """
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n].rstrip()
    sp = cut.rfind(" ")
    return (cut[:sp].rstrip() if sp > 0 else cut)


def enforce_title_coherence(title: str, is_new: bool = None, condition_id: int = None,
                             max_chars: int = 80) -> str:
    """旧シグネチャ(is_new)と新シグネチャ(condition_id)の両方に対応。
    Word boundary正規表現で偽陽性防止 (例: "Renewed" は "New" と判定しない)。
    """
    # 引数の相互変換 (Breaking Change 回避)
    if condition_id is None and is_new is not None:
        condition_id = 1000 if is_new else 3000
    if condition_id is None:
        return _truncate_at_word(title, max_chars)

    master = CONDITION_MASTER.get(condition_id)
    if not master:
        return _truncate_at_word(title, max_chars)

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
        return _truncate_at_word(title, max_chars)

    # マーカーがない場合、最適なものを末尾付与
    current_len = len(title)
    best_marker = get_title_marker_for_condition(condition_id, max_chars - current_len)
    if best_marker:
        # base を語境界で切り詰めてから marker 付与(marker は必ず残す。'Ja New' 切断を防ぐ)
        base = _truncate_at_word(title.strip(), max_chars - len(best_marker) - 1)
        return f"{base} {best_marker}".strip()

    # スペース不足時の強制ねじ込み（最短 marker をねじ込み、タイトル末尾を語境界で削る）
    shortest_marker = master["title_markers"][-1]
    truncated_title = _truncate_at_word(title, max_chars - len(shortest_marker) - 1)
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
        'Water Resistance', 'Movement',  # 時計系 (G-SHOCK 等。検索語: water resistant / quartz)
        'Theme', 'Franchise',  # フィギュア系 (一番くじ。検索語: anime & manga / 作品名)
        'Type', 'Activity', 'Season',  # アパレル系 (Workman/montbell。検索語: jacket / outdoor 等)
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
# 重複しても自然なカード/商品用語(set名+品名で正当に再出現)。dedup しない。
_TITLE_DEDUP_WHITELIST = {
    'vmax', 'vstar', 'v', 'vunion', 'ex', 'gx', 'gex', 'x', 'break', 'go',
    'tag', 'team', 'prime', 'star',
}


def dedup_title_words(title: str) -> str:
    """タイトルの重複語の2回目以降を除去(2026-06-21)。純関数。

    set名+言語/condition マーカーの重複('Japanese Japanese' / 'Japan Brand New Japan')是正。
    whitelist のカード用語(VMAX/EX/V…)は set名+品名で正当に再出現するので残す。番号/記号は対象外。

    ★2026-08-03: **連続した繰り返しは残す**。作品名そのものが同じ語を続けて含むケースを
      壊していた (実害: 一番くじ 幽☆遊☆白書 の 'Yu Yu Hakusho' → 'Yu Hakusho' が2件。
      検索キーワードそのものが消えるので露出が落ちる)。
      この関数が本来直したいのは 'Japanese … Japanese' のような **離れた** 再出現であって、
      隣り合う繰り返しではない。隣接は作品名の一部とみなして残す
      (他例: 'Deux Deux' / 'Duran Duran' / 'Boutades Boutades' 等、固有名詞は珍しくない)。
    """
    seen, out = set(), []
    prev_wl = None
    for w in (title or "").split():
        wl = w.lower()
        is_word = wl.isalpha() and len(wl) > 1
        if (is_word and wl not in _TITLE_DEDUP_WHITELIST and wl in seen
                and wl != prev_wl):          # 隣接の繰り返し(= 作品名)は落とさない
            prev_wl = wl
            continue
        out.append(w)
        if is_word:
            seen.add(wl)
        prev_wl = wl
    return ' '.join(out)


def normalize_title(title: str, is_new: bool, item_specifics: dict, category: str = None,
                    target_min: int = 70, max_chars: int = 80) -> str:
    """Title整合性保証 + 文字数パディング + 重複語除去を一括実行（推奨API）。"""
    title = enforce_title_coherence(title, is_new=is_new, max_chars=max_chars)
    title = pad_title_to_target(title, item_specifics, category=category,
                                 target_min=target_min, max_chars=max_chars)
    title = dedup_title_words(title)
    return title


def run_self_audit(csv_path):
    """生成直後に CSV監査くん(csv_auditor)を自動実行し結果を表示する (報告のみ・非致命)。

    監査を「待たず」生成時に品質確認する共通フック。全 listing 生成スクリプトの末尾から呼ぶ。
    dry-run なので生成物は書き換えない。with_market=False で offline/高速 (eBay API を叩かない)。
    """
    import os as _os
    import sys as _sys
    try:
        _tools = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                               "iMakHQ", "tools")
        if _tools not in _sys.path:
            _sys.path.insert(0, _tools)
        import csv_auditor as _auditor
        print("\n🔍 生成時セルフ監査 (CSV監査くん) ──────────")
        _auditor.audit(csv_path, dry_run=True, with_market=False)
    except Exception as _e:
        print(f"⚠️ セルフ監査 失敗 (非致命): {type(_e).__name__}: {_e}")


# ===================================================================
# 市場価格チェック有効化マップ（pricing_engine の status="ALERT" を物理 HOLD する対象）
# Porter等の1点ものは enabled=False で除外（相場無視のコストプラス維持）
# 倍率/閾値は SSOT である pricing_engine.TIER_PARAMS に一任。ここでは ON/OFF のみ管理。
# 2026-05-10: 一番くじ collectibles は新発売時 eBay 市場未成熟で median 信頼性が低く、
# 全 HOLD 化する構造的問題があり ichibankuji=False に変更 (warning は print 継続).
# ===================================================================
PRICE_CHECK_CONFIG = {
    "reel":        {"enabled": True},
    "tshirt":      {"enabled": False},  # 2026-06-21 価格NO-GO廃止(ユーザー指示「全て出品で」)。
    #                                     cost-plus=損なし(無在庫)+ 高めは既存メンテ追跡。TCG本丸と同方針。
    "ichibankuji": {"enabled": False},  # 2026-05-10: collectibles 特性で median gate 無効化
    "tomica":      {"enabled": True},
    "gshock":      {"enabled": False},  # スクリプト未結線。price_status を渡す実装が入るまで False で統一
    "montbell":    {"enabled": True},
    "porter":      {"enabled": False},  # 1点もの・相場形成不能
}


# ===================================================================
# eBay Item Specifics フィールド長制限 (2026-05-10 追加)
# eBay 側で長さ超過すると入稿失敗 (例 ErrorCode 21919308 "Series's value is too long").
# 新たに別 field で長さエラーが出たら、本 dict に 1 行追記するだけで物理ゲート発火.
# (= 修正連鎖を生まないデータ駆動型バリデータ)
# ===================================================================
EBAY_FIELD_MAX_LEN = {
    "C:Series": 65,  # 一番くじ入稿失敗 (2026-05-10) を契機に追加
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

    # 0b. eBay Item Specifics フィールド長制限チェック (Error)
    #     eBay 側で超過すると入稿失敗 (ErrorCode 21919308 等) → 物理ゲート
    for field, max_len in EBAY_FIELD_MAX_LEN.items():
        v = str(row_data.get(field, ""))
        if len(v) > max_len:
            violations.append((
                field,
                f"値が {max_len} 文字超 (現在 {len(v)} 文字): {v[:60]}...",
                "error",
            ))

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
# LOW スプシ 仕入値 抽出 (N列 > M列 > F列 優先順、2026-08-02 M列追加)
# LOW スプシ には 3 つの仕入関連列があり:
#   F (index 5)  = 商品価格      (= supplier listing 価格、取得時の値)
#   M (index 12) = 現在価格      (= 監視くん更新の最新観測値・生きてる最安)
#   N (index 13) = 仕入れ価格(円) (= SSOT (M or F)−K の ARRAYFORMULA 結果)
# 優先順:
#   1) N (SSOT) が数値で有れば N
#   2) 空/#REF! なら M (最新観測値) — 2026-07-24 DON!! カード事故 (N#REF!→F の
#      古い値 ¥23,000 拾い過大 pricing) の再発防止。SSOT 定義 N=(M or F)−K は M を
#      F より優先するので、コード側も N空でも M を先に見る
#   3) M も空なら F (取得時)
# K (ポイント円) は reader 側で控除しない (N が生きている時は N=(M or F)−K で控除済。
# 空フォールバック時に更に引くと二重控除で仕入¥過小 → 利益過大表示 → 赤字承諾方向 fail-safe と逆)
# ===================================================================
def pick_cost_jpy(row, f_idx: int = 5, n_idx: int = 13, m_idx: int = 12) -> str:
    """LOW スプシ row から仕入値を抽出 (N列 > M列 > F列 優先順)。純関数。

    Returns: 数値のみ抽出した string ("¥24,750" → "24750")。#REF!/非数値は自然に次候補へ。
    全空なら "".
    """
    def _clean(s):
        import re as _re
        return _re.sub(r"[^0-9]", "", str(s or ""))
    if n_idx is not None and len(row) > n_idx:
        n_val = _clean(row[n_idx])
        if n_val:
            return n_val
    if m_idx is not None and len(row) > m_idx:
        m_val = _clean(row[m_idx])
        if m_val:
            return m_val
    if f_idx is not None and len(row) > f_idx:
        return _clean(row[f_idx])
    return ""


# ===================================================================
# Free Shipping 移行 (2026-05-18)
# 旧: item price + shipping cost (DDP profile 別行) → eBay 表示 = price + ship
# 新: bundled price (item + DDP 加算) + Free Shipping profile → eBay 表示 = Free ship バッジ
# eBay 公表 fee は (subtotal+ship+tax) 全てに乗るため買い手 total は実質変化なし、
# Free Shipping バッジ表示で search 露出 + 転換率向上を狙う構造変更。
# ===================================================================
_DDP_TIERS_CACHE = None
_FREE_SHIPPING_CFG_CACHE = None


def _load_global_yaml() -> dict:
    """global.yaml を 1 回ロードしてキャッシュ。"""
    from pathlib import Path
    import yaml
    cfg_path = Path(__file__).resolve().parent / "config" / "global.yaml"
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_ddp_amount(base_price_usd: float) -> float:
    """商品本体価格 ($) から DDP 加算額を返す (price tier 逆引き).
    例: $45 → $20, $125 → $50, $700 → $210
    """
    global _DDP_TIERS_CACHE
    if _DDP_TIERS_CACHE is None:
        _DDP_TIERS_CACHE = _load_global_yaml().get("ddp_shipping_tiers", [])
    for tier in _DDP_TIERS_CACHE:
        if base_price_usd <= tier.get("max_usd", 0):
            return float(tier.get("ddp_usd", 0))
    # 範囲外 (>$1000) は最大 tier の ddp_usd を採用
    return float(_DDP_TIERS_CACHE[-1].get("ddp_usd", 260)) if _DDP_TIERS_CACHE else 260.0


def compute_free_shipping_price(base_price_usd: float) -> tuple:
    """商品本体価格から Free Shipping 用 統合価格を計算.
    Returns: (new_price_usd, ddp_amount_usd)
    例: $45.00 → ($65.98, 20.0)  [= INT(45+20)+0.98, DDP $20]
    """
    ddp = get_ddp_amount(base_price_usd)
    new_price = int(base_price_usd + ddp) + 0.98
    return (new_price, ddp)


def get_free_shipping_profile_name() -> str:
    """global.yaml から Free Shipping policy 名を取得."""
    global _FREE_SHIPPING_CFG_CACHE
    if _FREE_SHIPPING_CFG_CACHE is None:
        _FREE_SHIPPING_CFG_CACHE = _load_global_yaml()
    return _FREE_SHIPPING_CFG_CACHE.get("free_shipping_profile", "Free")


def is_free_shipping_mode() -> bool:
    """Free Shipping mode が有効か (true = 新規 listing は Free Shipping)."""
    global _FREE_SHIPPING_CFG_CACHE
    if _FREE_SHIPPING_CFG_CACHE is None:
        _FREE_SHIPPING_CFG_CACHE = _load_global_yaml()
    return bool(_FREE_SHIPPING_CFG_CACHE.get("free_shipping_mode", True))


# ---------------------------------------------------------------------------
# 目視で確定した cert → canonical product_id (2026-08-09)
#
# ★ここに置く理由: check_csv (検出側) と csv_auditor (退役側) の **両方**が要る。
#   別々に実装すると「canonical とは何か」がズレる (それが 2026-08-08 の真因そのもの:
#   除外リストは canonical PID で判定するのに、渡していたのは印刷番号 `746/742` だった)。
_VERIFIED_CERTS_PATH = r"C:/dev/iMak_data/dedupe/verified_certs.json"
_VERIFIED_PID_CACHE = None


def canonical_pid_for_cert(cert) -> str:
    """PSA cert → 目視で確定した canonical product_id。無ければ ""。

    fail-closed: choice が CHOSEN/OK 以外 / product_id 空 / 台帳が読めない → "" を返し、
    呼び手は従来どおり印刷番号で判定する (悪化させない)。
    """
    global _VERIFIED_PID_CACHE
    c = str(cert or "").strip()
    if c.startswith("PSA10-"):
        c = c[len("PSA10-"):]
    if not c:
        return ""
    if _VERIFIED_PID_CACHE is None:
        try:
            import json as _json
            with open(_VERIFIED_CERTS_PATH, encoding="utf-8") as f:
                _VERIFIED_PID_CACHE = _json.load(f) or {}
        except Exception:
            _VERIFIED_PID_CACHE = {}
    rec = _VERIFIED_PID_CACHE.get(c)
    if not isinstance(rec, dict):
        return ""
    if (rec.get("choice") or "").upper() not in ("CHOSEN", "OK"):
        return ""
    return (rec.get("product_id") or "").strip()


# ---------------------------------------------------------------------------
# 禁止ワードの照合 (2026-08-09)
#
# ★ここに置く理由: 生成側 (psa_to_csv) は **単語境界**で照合していたのに、検査側
#   (各カテゴリの check_csv) は素の `in` = **部分一致**だった。単語リストだけコピーして
#   照合ルールをコピーしなかったのが原因。
#   実害: "Shenron" の中の "nr" に反応して、¥79,000 / $799 の Dragon Ball が
#   「禁止ワード 'nr'」で出品除外された (2026-08-09 の入稿。Shenron は DBSCG 頻出なので
#   直すまで永久に出品されない状態だった)。
#   4カテゴリが同じ間違いをしていたので、**照合そのものを1本化**する。
def banned_title_words_in(title: str, banned_words) -> list:
    """タイトルに含まれる禁止ワードを返す (単語境界・大小無視)。純関数。

    境界は英数字で判定するので "l@@k" や "gem-mt" のような記号入りもそのまま扱える。
    "Shenron" は "nr" に一致しない / "NR" 単独や "Near Mint" の "mint" は一致する。
    """
    t = str(title or "")
    hits = []
    for w in banned_words or []:
        if not w:
            continue
        pat = r'(?i)(?<![A-Za-z0-9])' + re.escape(str(w)) + r'(?![A-Za-z0-9])'
        if re.search(pat, t):
            hits.append(w)
    return hits


def get_shipping_policy_name(price_usd: float, category: str) -> str:
    """V6 / V5 / Free モード別に Shipping Profile 名を返す (listing scripts 共通).

    優先順:
      1. v6_pricing.enabled=true → "DDP-{group}-P{NN}" (= eBay Policy 名、B→A remap 適用)
      2. free_shipping_mode=true → "Free" (= free_shipping_profile)
      3. それ以外 → 旧 V5 価格帯 tier ("40-60" / "100-200" 等)

    Args:
      price_usd: listing 価格 (USD, INT+0.98 後)
      category: v5_GS 設定 HTS_RATE のカテゴリ名 (例: "TCG(PSA10)", "Tシャツ(UT)")

    Returns:
      Shipping Profile 名 (eBay Business Policies に登録済の値)
    """
    import os, sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    import config_loader
    # V6 mode
    if config_loader.is_v6_pricing_enabled():
        v6 = config_loader.get_v6_pricing()
        group = v6.get("category_to_group", {}).get(category, "A")
        uppers = v6.get("price_tier_uppers", [])
        tier_name = "P31"
        for i, upper in enumerate(uppers, 1):
            if price_usd <= upper:
                tier_name = f"P{i:02d}"
                break
        raw = v6.get("policy_name_format", "DDP-{group}-{tier}").format(group=group, tier=tier_name)
        return v6.get("policy_remap", {}).get(raw, raw)
    # Free Shipping mode (= V5 既存運用)
    if is_free_shipping_mode():
        return get_free_shipping_profile_name()
    # 旧 V5 paid shipping tier (= fallback)
    OLD_TIERS = [
        (39, "<39"), (60, "40-60"), (100, "60-100"), (200, "100-200"),
        (300, "200-300"), (400, "300-400"), (500, "400-500"),
        (600, "500-600"), (800, "600-800"), (1000, "800-1000"),
    ]
    for threshold, name in OLD_TIERS:
        if price_usd <= threshold:
            return name
    return "800-1000"


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

    # 8. pick_cost_jpy (N列 優先 / F列 fallback)
    # row: A=URL B=itemID C=title D=売切 E=状態 F=商品価格 G=写真URL H=説明 I=Title J=Desc K=未使用 L=ConditionID M=価格上昇 N=仕入れ価格
    row_with_n = ["url","iid","title","","新品","￥24,750","","","","","","1000","","19,601"]
    assert pick_cost_jpy(row_with_n) == "19601", pick_cost_jpy(row_with_n)
    row_n_blank = ["url","iid","title","","新品","￥24,750","","","","","","1000","",""]
    assert pick_cost_jpy(row_n_blank) == "24750", pick_cost_jpy(row_n_blank)
    row_both_blank = ["url","iid","title","","新品","","","","","","","1000","",""]
    assert pick_cost_jpy(row_both_blank) == ""
    print(f"  [OK] pick_cost_jpy: N優先(19601) / F fallback(24750) / 両空(\"\") 全動作")

    # 9. Free Shipping 関数 (2026-05-18 追加)
    p1, d1 = compute_free_shipping_price(45.0)
    assert p1 == 65.98 and d1 == 20.0, f"$45→$65.98 expected, got ({p1}, {d1})"
    p2, d2 = compute_free_shipping_price(125.0)
    assert p2 == 175.98 and d2 == 50.0, f"$125→$175.98 expected, got ({p2}, {d2})"
    p3, d3 = compute_free_shipping_price(350.0)
    assert p3 == 455.98 and d3 == 105.0, f"$350→$455.98 expected, got ({p3}, {d3})"
    p4, d4 = compute_free_shipping_price(38.5)
    assert p4 == 53.98 and d4 == 15.0, f"$38.5→$53.98 expected, got ({p4}, {d4})"
    assert get_free_shipping_profile_name() == "Free"
    assert is_free_shipping_mode() is True

    print("✅ All smoke tests passed. System is now deterministic.")
