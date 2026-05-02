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


def pad_title(title, language='', rarity='',
              min_len=SHORT_TITLE_THRESHOLD, target_len=TARGET_TITLE_LEN,
              max_len=MAX_TITLE_LEN):
    """短タイトルに Item Specifics ベースで補強.

    優先順位:
        1. Rarity (RARITY_TO_TITLE にマップあるもの)
        2. Language が Japanese なら "Japanese"
        3. "TCG" (高ヒット PDF キーワード)
        4. "Card" (TCG カードは事実)

    既に title 内にある語はスキップ. max_len を超える追加もスキップ.
    target_len に達したら追加停止. min_len 未満のみ補強対象.
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
    # 3. TCG
    candidates.append('TCG')
    # 4. Card
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
    log = {'rescue': [], 'pokemon_dedup': False, 'pad': []}

    title, rescue_applied = apply_rescue(title, rescues)
    log['rescue'] = rescue_applied

    title, deduped = remove_redundant_pokemon(title)
    log['pokemon_dedup'] = deduped

    title, pad_applied = pad_title(title, language=language, rarity=rarity)
    log['pad'] = pad_applied

    return title, log


# ============================================================================
# CSV 処理
# ============================================================================
def process_csv(csv_path, rescues, log_func=print):
    """CSV を読み、全行のタイトルを補強して書き戻し.

    Returns:
        stats dict {'rescued': N, 'padded': N, 'pokemon_dedup': N, 'unchanged': N}
    """
    bak = csv_path + f'.bak_post_title_{int(time.time())}'
    shutil.copy2(csv_path, bak)
    log_func(f"  📦 backup: {os.path.basename(bak)}")

    with open(csv_path, encoding='utf-8', newline='') as f:
        rows = list(csv.reader(f))

    header = rows[0]
    try:
        title_idx = header.index('*Title')
        rarity_idx = header.index('C:Rarity')
        lang_idx = header.index('C:Language')
    except ValueError as e:
        log_func(f"  ⚠️ ヘッダ列不足、skip: {e}")
        return {'rescued': 0, 'padded': 0, 'pokemon_dedup': 0, 'unchanged': 0}

    stats = {'rescued': 0, 'padded': 0, 'pokemon_dedup': 0, 'unchanged': 0}
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
        if log['pad']:
            stats['padded'] += 1
            log_func(f"  [#{i}] +pad: {', '.join(log['pad'])} ({len(original)}→{len(new_title)}字)")

        if new_title != original:
            row[title_idx] = new_title
        else:
            stats['unchanged'] += 1

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
        f"pokemon_dedup={stats['pokemon_dedup']} unchanged={stats['unchanged']}\n"
    )


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    run_post_title_fix_for_latest_csv(print)
