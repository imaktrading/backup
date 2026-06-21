#!/usr/bin/env python3
"""TCG CSV のタイトル後処理 (psa_to_csv.py 出力を補強)

設計方針 (memory: no_modification_chain.md):
    既存の psa_to_csv.py には1行も touch しない. 出力 CSV を後処理する独立スクリプト.
    control_panel.py から呼ばれる (poll_queue 内 _run_excluder_for_latest_csv の隣).
    失敗しても元 CSV は無傷 (try/except でフェイルセーフ).

主機能:
    1. PSA 名前省略の正規化 (config/psa_name_rescue.yaml の辞書ベース)
    2. 短タイトル (<60字) を Item Specifics ベースで補強
       - Rarity (Secret Rare / Shiny Holo Rare 等の検索価値ある語のみ)
       - Language (Japanese)
       - "TCG" / "Card"
    3. 'Pokémon Card' の Pokémon 重複削除 (Set 名に Pokemon GO 含む等で発生)

CLAUDE.md 準拠:
    - 確証ある Item Specifics 値のみ使用 (推測フィラー禁止)
    - id_strict_with_explicit_rescue: rescue は専用関数で明示
"""
import csv
import glob
import os
import re
import shutil
import sys
import time
from pathlib import Path

# ============================================================================
# 定数
# ============================================================================
WORKSPACE = r"c:/dev/iMak"
CSV_DIR = os.path.join(WORKSPACE, "iMakHQ", "csv_output")
CSV_GLOB = "tcg_upload_*.csv"
RECENT_THRESHOLD_SEC = 600  # 10分以内の CSV のみ対象 (古い CSV を二重処理しない)
SHORT_TITLE_THRESHOLD = 60  # 60字未満を補強対象
TARGET_TITLE_LEN = 72  # 補強の目標 (達したら追加停止). 既存 pad_title (psa_to_csv.py:681) と同値
MAX_TITLE_LEN = 80  # eBay の上限

# Rarity 正規化マップ (キー = PSA から来る Rarity, 値 = タイトル末尾に追加する語)
# 検索価値のないもの (Common/Uncommon) と曖昧な略号 (RR) は除外
RARITY_TO_TITLE = {
    "Secret Rare": "Secret Rare",
    "Shiny Holo Rare": "Shiny Holo Rare",
    "Radiant Rare": "Holo",  # Radiant カードは Holo 仕様
    "Holo Rare": "Holo Rare",
    "Special Art Rare": "Special Art",
    "Special Illustration Rare": "Special Illustration",
    "Ultra Rare": "Ultra Rare",
    "Hyper Rare": "Hyper Rare",
}


# ============================================================================
# core 関数群 (pytest から呼ばれる純粋関数)
# ============================================================================
def load_rescue_dict(yaml_path):
    """psa_name_rescue.yaml を読込んで exact_replacements リストを返す."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("PyYAML 未インストール: pip install pyyaml")
    if not os.path.exists(yaml_path):
        return []
    with open(yaml_path, encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return data.get('exact_replacements', [])


def apply_rescue(title, rescues):
    """PSA 名前省略の置換を適用. 部分文字列の完全一致で置換.

    Returns:
        (新タイトル, 適用ルールのリスト)
    """
    applied = []
    for r in rescues:
        src, dst = r['from'], r['to']
        # 既に正規形が含まれている場合は重複置換しない
        if dst in title:
            continue
        if src in title:
            title = title.replace(src, dst)
            applied.append(f"{src!r} → {dst!r}")
    return title, applied


def remove_redundant_pokemon(title):
    """'Pokémon' (アクセント付) と 'Pokemon' の重複を削除.
    例: 'PSA 10 Pokemon GO #011 Radiant Charizard Pokémon Card'
        → 'PSA 10 Pokemon GO #011 Radiant Charizard Card'
    """
    if 'Pokémon' not in title:
        return title, False
    # アクセント付 Pokémon を削除 (前後スペースも含めて)
    new = re.sub(r'\s+Pokémon\s+', ' ', title).strip()
    new = re.sub(r'\s+', ' ', new)
    return new, new != title


# 重複しても自然なカード用語 (セット名+カード名で正当に再出現する。例: 'VMAX Climax' set +
# 'Orbeetle VMAX' card)。これらは dedup しない (= 情報を壊さない)。
_DEDUP_WHITELIST = {
    'vmax', 'vstar', 'v', 'vunion', 'ex', 'gx', 'gex', 'x', 'break', 'go',
    'tag', 'team', 'prime', 'star',
}


def remove_duplicate_words(title):
    """タイトル内の **重複語の2回目以降を除去** (2026-06-21)。

    語が既出と完全一致 (大小無視) なら削除。ただし上記カード用語 whitelist は残す
    (セット名+カード名で正当に再出現するため)。番号/記号 (#037/070 等) は対象外。
    例:
      'Japanese Japanese Promo'        → 'Japanese Promo'   (言語×set名の重複)
      'NWT Japan Brand New Japan'      → 'NWT Japan Brand New' (語順問わず)
      'VMAX Climax #215 Orbeetle VMAX' → 不変 (VMAX は whitelist)
    """
    parts = title.split()
    seen = set()
    out = []
    for w in parts:
        wl = w.lower()
        is_word = wl.isalpha() and len(wl) > 1   # 英字語のみ (番号/記号は常に残す)
        if is_word and wl not in _DEDUP_WHITELIST and wl in seen:
            continue                              # 重複語 (非whitelist) → 削除
        out.append(w)
        if is_word:
            seen.add(wl)
    new = ' '.join(out)
    return new, new != title


# 日本語文字 (ひらがな/カタカナ/漢字/半角カナ). eBay タイトルは英語必須。
_JP_CHAR_RE = re.compile(r'[぀-ヿ一-鿿ｦ-ﾟ]')


def strip_japanese(title):
    """eBay タイトルから日本語文字を除去する最終ガード.

    TitleAgent 等が catalog の JP 名 (例: Gundam RP-009 の 'リソース') で
    短タイトルをパディングして混入させる事故への防壁. eBay タイトルに日本語が
    入ると検索ヒットせず + 不格好 (= SNAD/品質低下). 混入経路を問わず最終 CSV
    から消す (no_modification_chain: 既存ロジックは触らず後処理で防御).

    Returns:
        (新タイトル, 除去したか bool)
    """
    if not _JP_CHAR_RE.search(title):
        return title, False
    new = _JP_CHAR_RE.sub('', title)
    new = re.sub(r'\s+', ' ', new).strip()  # 除去で生じた連続/末尾スペース整理
    return new, new != title


def pad_title(title, language='', rarity='',
              min_len=SHORT_TITLE_THRESHOLD, target_len=TARGET_TITLE_LEN,
              max_len=MAX_TITLE_LEN):
    """短タイトルに Item Specifics ベースで補強.

    優先順位 (2026-05-31 改訂: 'TCG' filler 廃止 = PDF Rank 圏外 + game 表記重複リスク):
        1. Rarity (RARITY_TO_TITLE にマップあるもの)
        2. Language が Japanese なら "Japanese"
        3. "Card" (TCG カードは事実)

    既に title 内にある語はスキップ. max_len を超える追加もスキップ.
    target_len に達したら追加停止. min_len 未満のみ補強対象.

    Why: 'TCG' を全 game に pad すると Yugioh/Pokemon/One Piece (= PDF Rank 1/13/19) 等
    短縮表記方針と矛盾 (= 「TCG」 つけると Rank 圏外で SEO 損失)、 game 表記は
    build_title の game_short mapping で確定済 (= memory:official_x_ebay_filter_max_activation).
    """
    if len(title) >= min_len:
        return title, []

    candidates = []
    # 1. Rarity
    rar_key = (rarity or '').strip()
    rar_val = RARITY_TO_TITLE.get(rar_key)
    if rar_val:
        candidates.append(rar_val)
    # 2. Language
    if language and language.strip().lower() == 'japanese':
        candidates.append('Japanese')
    # 3. Card (= TCG カードは事実)
    candidates.append('Card')

    title_lower = title.lower()
    applied = []
    for c in candidates:
        # 既に title 内にあればスキップ (語幹一致も含む簡易判定)
        if c.lower() in title_lower:
            continue
        new_title = f"{title} {c}"
        if len(new_title) > max_len:
            continue
        title = new_title
        title_lower = title.lower()
        applied.append(c)
        if len(title) >= target_len:
            break
    return title, applied


def fix_title(title, language, rarity, rescues):
    """1タイトルに対する全処理パイプライン.

    Returns:
        (新タイトル, 操作ログ dict)
    """
    log = {'rescue': [], 'pokemon_dedup': False, 'word_dedup': False, 'pad': [], 'jp_strip': False}

    title, rescue_applied = apply_rescue(title, rescues)
    log['rescue'] = rescue_applied

    title, deduped = remove_redundant_pokemon(title)
    log['pokemon_dedup'] = deduped

    # 汎用の重複語除去 (Japanese Japanese / Japan…Japan 等。カード用語は whitelist で残す)
    title, word_deduped = remove_duplicate_words(title)
    log['word_dedup'] = word_deduped

    # 日本語混入を pad の「前」に除去 (TitleAgent が JP名でパディングした分)。
    # 先に英語のみにしてから pad することで、除去後に短くならず英語キーワードで補強される。
    title, jp_stripped = strip_japanese(title)
    log['jp_strip'] = jp_stripped

    title, pad_applied = pad_title(title, language=language, rarity=rarity)
    log['pad'] = pad_applied

    return title, log


# ============================================================================
# CSV 処理
# ============================================================================
def process_csv(csv_path, rescues, log_func=print):
    """CSV を読み、全行のタイトルを補強して書き戻し.

    書換え発生時のみ backup + 書戻しを行う (no-op 時はディスク無駄を回避).

    Returns:
        stats dict {'rescued': N, 'padded': N, 'pokemon_dedup': N, 'unchanged': N}
    """
    with open(csv_path, encoding='utf-8', newline='') as f:
        rows = list(csv.reader(f))

    header = rows[0]
    try:
        title_idx = header.index('*Title')
        rarity_idx = header.index('C:Rarity')
        lang_idx = header.index('C:Language')
    except ValueError as e:
        log_func(f"  ⚠️ ヘッダ列不足、skip: {e}")
        return {'rescued': 0, 'padded': 0, 'pokemon_dedup': 0, 'jp_stripped': 0, 'unchanged': 0}

    stats = {'rescued': 0, 'padded': 0, 'pokemon_dedup': 0, 'word_dedup': 0, 'jp_stripped': 0, 'unchanged': 0}
    for i, row in enumerate(rows[1:], start=1):
        original = row[title_idx]
        new_title, log = fix_title(
            original,
            language=row[lang_idx] if lang_idx < len(row) else '',
            rarity=row[rarity_idx] if rarity_idx < len(row) else '',
            rescues=rescues,
        )

        if log['rescue']:
            stats['rescued'] += 1
            log_func(f"  [#{i}] rescue: {'; '.join(log['rescue'])}")
        if log['pokemon_dedup']:
            stats['pokemon_dedup'] += 1
            log_func(f"  [#{i}] Pokémon 重複削除")
        if log['word_dedup']:
            stats['word_dedup'] += 1
            log_func(f"  [#{i}] 重複語除去: {original!r} → {new_title!r}")
        if log['pad']:
            stats['padded'] += 1
            log_func(f"  [#{i}] +pad: {', '.join(log['pad'])} ({len(original)}→{len(new_title)}字)")
        if log['jp_strip']:
            stats['jp_stripped'] += 1
            log_func(f"  [#{i}] 🚫 日本語除去: {original[:50]!r} → {new_title[:50]!r}")

        if new_title != original:
            row[title_idx] = new_title
        else:
            stats['unchanged'] += 1

    if stats['rescued'] or stats['padded'] or stats['pokemon_dedup'] or stats['word_dedup'] or stats['jp_stripped']:
        bak = csv_path + f'.bak_post_title_{int(time.time())}'
        shutil.copy2(csv_path, bak)
        log_func(f"  📦 backup: {os.path.basename(bak)}")
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            writer.writerows(rows)

    return stats


# ============================================================================
# entry point (control_panel.py から import)
# ============================================================================
def find_latest_tcg_csv(csv_dir=CSV_DIR, recent_sec=RECENT_THRESHOLD_SEC):
    """csv_dir 内の tcg_upload_*.csv のうち最新 (recent_sec 以内). 該当なしなら None."""
    candidates = glob.glob(os.path.join(csv_dir, CSV_GLOB))
    if not candidates:
        return None
    latest = max(candidates, key=os.path.getmtime)
    if time.time() - os.path.getmtime(latest) > recent_sec:
        return None
    return latest


def run_post_title_fix_for_latest_csv(append_log_func=print):
    """control_panel.py から呼ばれるエントリポイント.
    最新 tcg_upload_*.csv を補強. TCG 以外の CSV (g-shock 等) なら no-op.
    """
    csv_path = find_latest_tcg_csv()
    if not csv_path:
        return  # 該当 CSV なし、TCG 以外のタスク完了 → 何もしない

    yaml_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config', 'psa_name_rescue.yaml',
    )
    rescues = load_rescue_dict(yaml_path)

    append_log_func(f"\n🔧 post_title_fix: {os.path.basename(csv_path)}\n")
    stats = process_csv(
        csv_path, rescues,
        log_func=lambda m: append_log_func(m + '\n' if not m.endswith('\n') else m),
    )
    append_log_func(
        f"  完了: rescue={stats['rescued']} pad={stats['padded']} "
        f"pokemon_dedup={stats['pokemon_dedup']} word_dedup={stats['word_dedup']} "
        f"jp_strip={stats['jp_stripped']} unchanged={stats['unchanged']}\n"
    )


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    run_post_title_fix_for_latest_csv(print)
