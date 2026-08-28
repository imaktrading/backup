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
# ★2026-08-27: Pack/Box/Lot/Bundle/Set of の除去は **listing_common が SSOT**。
#   ここで語リストも照合も再実装しない (2026-08-09 に語だけコピーして照合ルールがズレ、
#   "Shenron" の "nr" で $799 のカードを誤除外した同型事故を繰り返さないため)。
#   import できない = miscat 語が素通りする (= eBay ErrorCode 240 で入稿が止まる) ので
#   握り潰さず落とす (fail-closed)。
_EBAY_API_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'iMakeBayAPI')
if _EBAY_API_DIR not in sys.path:
    sys.path.insert(0, _EBAY_API_DIR)
from listing_common import SINGLES_CATEGORY, strip_miscat_title_words  # noqa: E402

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


# 単独では意味を持たない「イニシャル」(D. / D / J. 等)。名前が重複除去で消えた時に
# 取り残されると `#OP05-060 D.` のような壊れた末尾になる (2026-08-24 実害)。
_INITIAL_RE = re.compile(r"^[A-Za-z]\.?$")


# ── セット名は「1語のまとまり」として守る (2026-08-28) ─────────────────
# セット名の中にゲーム名がもう一度入る形 (`One Piece Day` / `Premium Booster One Piece
# The Best`) を、先頭のゲーム名と重複していると見なして削っていた。
#   PSA 10 One Piece Japanese One Piece Day #ST10-006 …  → `One Piece Day` が `Day` になる
# `Tony Tony Chopper` (a72586f) / 末尾 `D.` (1919b22) と同じ形の3回目なので、
# **カード個別ではなく発生源** (= 何がセット名かを知らないこと) を直す。
#
# 何がセット名かは **カタログの set_name_ebay** と、プロモ配布元名の確定値
# (tcg_promo_store。PSA ラベル由来なので catalog には置けない値) が持っている。
# タイトルはその文字列から組んでいるので、同じ語列がタイトルに並んでいたら触らない。
_SET_PHRASE_INDEX = None


def known_set_phrase_index():
    """{先頭語(小文字): [語列 tuple, …]} = タイトル内で守るセット名の並び。

    出典は **カタログの set_name_ebay** (iMakCatalog/set_reference.tcg_set_master) と
    **確定済 promo 名** (iMakTCG/promo_overrides.json) だけ。ここで語を足さない。
    1語のセット名は「まとまりが壊れる」形が無いので入れない (= 副作用を最小に)。

    ★読めなければ **例外で落とす**。空集合に倒すと守りが黙って消えて、同じ事故が
      再発しても誰も気づかない (listing_common の import と同じ fail-closed)。
      呼び元 (control_panel) は try/except で包んでいるので、落ちても元 CSV は無傷。
    """
    global _SET_PHRASE_INDEX
    if _SET_PHRASE_INDEX is not None:
        return _SET_PHRASE_INDEX

    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for _p in (os.path.join(_root, 'iMakCatalog'), os.path.join(_root, 'iMakTCG')):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    from set_reference import tcg_set_master          # カタログ (公式値)
    from tcg_promo_store import load_all              # promo 配布元名 (HQ 所有)

    phrases = set(tcg_set_master())
    for rec in load_all().values():
        v = (rec.get('promo') if isinstance(rec, dict) else rec) or ''
        if isinstance(v, str) and v.strip():
            phrases.add(v.strip())

    index = {}
    for p in phrases:
        toks = tuple(w.lower() for w in p.split())
        if len(toks) >= 2:
            index.setdefault(toks[0], []).append(toks)
    _SET_PHRASE_INDEX = index
    return _SET_PHRASE_INDEX


def _set_phrase_spans(parts):
    """タイトル内で **セット名の語列** が並んでいる範囲の index 集合。純関数。

    守るのは **最初に見つかった1つ** (同じ位置なら最長)。タイトルに載るセット名は
    1つだけで、必ずゲーム名の後・カード番号の前に来るため。
    ★全出現を守ると、**セット名と同じ名前のカード** で末尾が守られてしまう
      (`PURPLE Monkey D. Luffy` は catalog の set_name_ebay にも在る)。
      2026-08-24 の壊れた末尾 `#OP05-060 D.` は末尾側を消して直したものなので、
      そこを守ると あの修正が無効になる。
    """
    low = [w.lower() for w in parts]
    index = known_set_phrase_index()
    for i, w in enumerate(low):
        best = 0
        for toks in index.get(w, ()):
            j = i + len(toks)
            if len(toks) > best and j <= len(low) and tuple(low[i:j]) == toks:
                best = len(toks)
        if best:
            return set(range(i, i + best))
    return set()


def _protected_span(parts, card_name):
    """タイトル内で **カード名そのもの** が並んでいる範囲 (最後の出現) の index 集合。

    カード名に同じ語が2回入るものがある (`Tony Tony Chopper` / `Dr. Doctor` 等)。
    重複語除去はそれを「重複」と見なして削り、**別人の名前にしてしまう**。
    2026-08-24 実害: `Tony Tony Chopper` → `Tony Chopper` のまま出品された
    (ItemID 820041238874)。カタログの名前は写すだけの値なので、ここで削ってはいけない。

    最後の出現を守るのは、セット名の中に同じ語が入る形 (`Great Detective Pikachu` +
    `Detective Pikachu`) で、**カード名の側**を残すため。純関数。
    """
    name = [w.lower() for w in (card_name or "").split() if w]
    if not name:
        return set()
    low = [w.lower() for w in parts]
    for i in range(len(low) - len(name), -1, -1):          # 後ろから探す
        if low[i:i + len(name)] == name:
            return set(range(i, i + len(name)))
    return set()


def remove_duplicate_words(title, card_name=""):
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
    drop = [False] * len(parts)
    # カード名そのもの + セット名の語列は触らない (どちらも catalog の値を写しただけ)
    keep = _protected_span(parts, card_name) | _set_phrase_spans(parts)
    for i, w in enumerate(parts):
        wl = w.lower()
        is_word = wl.isalpha() and len(wl) > 1   # 英字語のみ (番号/記号は常に残す)
        if i in keep:
            seen.add(wl)
            continue
        if is_word and wl not in _DEDUP_WHITELIST and wl in seen:
            drop[i] = True                        # 重複語 (非whitelist) → 削除
            continue
        if is_word:
            seen.add(wl)
    # ★2026-08-24: 消した語の隣に **イニシャルだけが取り残される**。
    #   'PURPLE Monkey D. Luffy #OP05-060 Monkey D. Luffy' で 2つ目の Monkey と Luffy が
    #   重複として消え、`D.` は英字語でないので残り、`#OP05-060 D.` という壊れた末尾で
    #   **eBay に出てしまった** (ItemID 820038886892 / 修正済)。
    #   イニシャルは単独では意味を持たないので、**続く名前が消えた時だけ**一緒に落とす。
    #   「次が消えた時だけ」なのが肝で、`Flying Pikachu V` の V (カード名の一部) は残る。
    changed = True
    while changed:
        changed = False
        for i, w in enumerate(parts):
            if drop[i] or not _INITIAL_RE.match(w):
                continue
            if i + 1 < len(parts) and drop[i + 1]:
                drop[i] = True
                changed = True
    new = ' '.join(w for i, w in enumerate(parts) if not drop[i]).strip()
    return new, new != title


# eBay が title/subtitle/item specifics で禁止する装飾文字 (ErrorCode 240 /
# LP_SNB_CutsieCharacters)。superscript/subscript/★/™/½ 等。混入すると入稿が
# **物理的に失敗**する (2026-07-18 発覚: DBSCG rarity 'C★'/'SR★'/'L★' がタイトルと
# C:Rarity に流入 → Frieza FS04-11 が毎バッチ ErrorCode 240 で失敗、DBSCG 911件が同地雷)。
# アクセント文字 (é in Pokémon 等) は eBay 許容なので **絶対に含めない** (curated set)。
_EBAY_BANNED_CHARS = (
    "★☆✩✪✫✬✭✮✯✰⭐"       # 星 (= 今回の主犯。DBSCG parallel rarity marker)
    "™®©℠"                 # 商標/著作権
    "♥♡♦♣♠❤️❤♪♫"           # スート/ハート/音符
    "½¼¾⅓⅔⅛⅜⅝⅞"           # 分数記号
    "⁰¹²³⁴⁵⁶⁷⁸⁹"           # 上付き数字
    "₀₁₂₃₄₅₆₇₈₉"           # 下付き数字
    "•‣►▶◄◀▲▼"             # 装飾 bullet/矢印
)
_EBAY_BANNED_RE = re.compile('[' + re.escape(_EBAY_BANNED_CHARS) + ']')


def strip_ebay_banned_chars(text, collapse_ws=True):
    """eBay 禁止装飾文字を除去する最終ガード (title / item specifics / description 共通)。

    混入経路 (catalog rarity コードの ★ 等) を問わず、CSV 出力の**直前**で物理除去する
    = 入稿失敗 (ErrorCode 240) を構造的に防ぐ。値の「正しさ」(C★→Common 等の正規化) は
    別レイヤ (Catalog SSOT) の責務で、ここは「禁止文字を絶対に eBay へ出さない」に専念する。

    collapse_ws: title/spec は True で連続/末尾スペースを整理。**Description(HTML)は False**
      にして改行・インデント等の空白を保持する (collapse すると HTML が壊れる)。

    Returns: (新テキスト, 除去したか bool)。
    """
    if not text or not _EBAY_BANNED_RE.search(text):
        return text, False
    new = _EBAY_BANNED_RE.sub('', text)
    if collapse_ws:
        new = re.sub(r'\s+', ' ', new).strip()
    return new, new != text


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


def pad_title(title, language='', rarity='', year='',
              min_len=SHORT_TITLE_THRESHOLD, target_len=TARGET_TITLE_LEN,
              max_len=MAX_TITLE_LEN):
    """短タイトルに Item Specifics ベースで補強.

    優先順位 (2026-05-31 改訂: 'TCG' filler 廃止 = PDF Rank 圏外 + game 表記重複リスク):
        1. Rarity (RARITY_TO_TITLE にマップあるもの)
        2. Language が Japanese なら "Japanese"
        3. year (= C:Year Manufactured)。miscat 語を落とした行だけ渡される (2026-08-27)
        4. "Card" (TCG カードは事実)

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
    # 3. 年号 (2026-08-27)。miscat 語 (Pack/Box 等) を落として短くなった時だけ
    #    呼び出し側が渡す。C:Year Manufactured = カタログの値なので推測フィラーではない。
    _y = str(year or '').strip()
    if _y.isdigit():
        candidates.append(_y)
    # 4. Card (= TCG カードは事実)
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


def fix_title(title, language, rarity, rescues, card_name="", category="", year=""):
    """1タイトルに対する全処理パイプライン.

    Returns:
        (新タイトル, 操作ログ dict)
    """
    log = {'rescue': [], 'pokemon_dedup': False, 'word_dedup': False, 'pad': [],
           'jp_strip': False, 'banned_strip': False, 'miscat_strip': []}

    title, rescue_applied = apply_rescue(title, rescues)
    log['rescue'] = rescue_applied

    title, deduped = remove_redundant_pokemon(title)
    log['pokemon_dedup'] = deduped

    # 汎用の重複語除去 (Japanese Japanese / Japan…Japan 等。カード用語は whitelist で残す)
    title, word_deduped = remove_duplicate_words(title, card_name=card_name)
    log['word_dedup'] = word_deduped

    # 日本語混入を pad の「前」に除去 (TitleAgent が JP名でパディングした分)。
    # 先に英語のみにしてから pad することで、除去後に短くならず英語キーワードで補強される。
    title, jp_stripped = strip_japanese(title)
    log['jp_strip'] = jp_stripped

    # eBay 禁止文字 (★ 等) を pad の前に除去 (rarity 'C★' 由来のタイトル混入を潰す)。
    title, banned_stripped = strip_ebay_banned_chars(title)

    # ★2026-08-27: 同じ「禁止」の口で、シングルのカテゴリ (183454) のタイトルからは
    #   Pack / Box / Lot / Bundle / Set of も落とす。eBay がこれを「複数枚売っている」と
    #   読んで ErrorCode 240 (miscat) で入稿を弾くため。
    #   ★C:Set は落とさない (実測で通る)。ここは title だけ。
    miscat_hits = []
    if str(category or '').strip() == SINGLES_CATEGORY:
        before = title
        title, miscat_stripped = strip_miscat_title_words(title, card_name=card_name)
        if miscat_stripped:
            miscat_hits = [before, title]
            banned_stripped = True          # 既存の banned_strip の口に合流 (分岐を増やさない)
    log['banned_strip'] = banned_stripped
    log['miscat_strip'] = miscat_hits

    # 落として短くなった分は年号等で補う (miscat を落とした行だけ year を渡す)
    title, pad_applied = pad_title(title, language=language, rarity=rarity,
                                   year=(year if miscat_hits else ''))
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
        return {'rescued': 0, 'padded': 0, 'pokemon_dedup': 0, 'word_dedup': 0,
                'jp_stripped': 0, 'banned_stripped': 0, 'spec_banned_stripped': 0, 'unchanged': 0}

    # item specifics 列 (C:*) = eBay 禁止文字サニタイズ対象。title と別軸で、
    # 全 C: 列 (C:Rarity='C★' 等) から ★ 等を除去 (ErrorCode 240 の入稿失敗を防ぐ)。
    # カード名 = 重複語除去で削ってはいけない語 (Tony Tony Chopper 等)
    name_idx = header.index('C:Card Name') if 'C:Card Name' in header else None
    # miscat 語 (Pack/Box 等) 除去はシングルのカテゴリ限定 → *Category を見る (2026-08-27)
    cat_idx = header.index('*Category') if '*Category' in header else None
    year_idx = (header.index('C:Year Manufactured')
                if 'C:Year Manufactured' in header else None)
    spec_idxs = [j for j, h in enumerate(header) if h.startswith('C:')]
    # Description(HTML)内の Specs ブロックにも rarity 'C★' 等が反映される。240 の対象
    # (title/description) なので除去。ただし HTML なので空白は collapse しない。
    desc_idx = header.index('*Description') if '*Description' in header else None

    stats = {'rescued': 0, 'padded': 0, 'pokemon_dedup': 0, 'word_dedup': 0,
             'jp_stripped': 0, 'banned_stripped': 0, 'spec_banned_stripped': 0, 'unchanged': 0}
    for i, row in enumerate(rows[1:], start=1):
        original = row[title_idx]
        new_title, log = fix_title(
            original,
            language=row[lang_idx] if lang_idx < len(row) else '',
            rarity=row[rarity_idx] if rarity_idx < len(row) else '',
            rescues=rescues,
            card_name=(row[name_idx] if name_idx is not None and name_idx < len(row) else ''),
            category=(row[cat_idx] if cat_idx is not None and cat_idx < len(row) else ''),
            year=(row[year_idx] if year_idx is not None and year_idx < len(row) else ''),
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
        if log['banned_strip']:
            stats['banned_stripped'] += 1
            _what = "禁止語(Pack/Box等)" if log['miscat_strip'] else "禁止文字"
            log_func(f"  [#{i}] 🚫 eBay{_what}除去(title): {original!r} → {new_title!r}")

        if new_title != original:
            row[title_idx] = new_title

        # item specifics の禁止文字除去 (title と独立。C:Rarity='C★' 等)
        spec_changed = False
        for j in spec_idxs:
            if j >= len(row):
                continue
            cleaned, changed = strip_ebay_banned_chars(row[j])
            if changed:
                log_func(f"  [#{i}] 🚫 eBay禁止文字除去({header[j]}): {row[j]!r} → {cleaned!r}")
                row[j] = cleaned
                spec_changed = True
        # Description(HTML)の禁止文字除去 (空白は保持)
        if desc_idx is not None and desc_idx < len(row):
            cleaned, changed = strip_ebay_banned_chars(row[desc_idx], collapse_ws=False)
            if changed:
                log_func(f"  [#{i}] 🚫 eBay禁止文字除去(*Description HTML内)")
                row[desc_idx] = cleaned
                spec_changed = True
        if spec_changed:
            stats['spec_banned_stripped'] += 1

        if new_title == original and not spec_changed:
            stats['unchanged'] += 1

    if any(stats[k] for k in ('rescued', 'padded', 'pokemon_dedup', 'word_dedup',
                              'jp_stripped', 'banned_stripped', 'spec_banned_stripped')):
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
        f"jp_strip={stats['jp_stripped']} banned_strip={stats['banned_stripped']} "
        f"spec_banned={stats['spec_banned_stripped']} unchanged={stats['unchanged']}\n"
    )


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    run_post_title_fix_for_latest_csv(print)
