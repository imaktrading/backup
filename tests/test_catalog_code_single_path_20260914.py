# -*- coding: utf-8 -*-
"""カタログのコードを読む場所を1つにする (2026-09-14・残務 №41)。

判定: ②が誤り (出品くん側の読み込み経路がばらばら)。master の iMakCatalog は古い
(psa_to_csv.py で catalog branch と +4060行差、2026-09-14 実測)。psa_to_csv.py:24-29 と
同じ形 (catalog worktree があればそれ、無ければ master にフォールバック) に以下の
4か所を揃えた:
  - iMakTCG/tcg_listing_fields.py
  - iMakTCG/catalog_reference.py
  - iMakMercari/montbell_listing.py
  - iMakTCG/card_identification_agent.py

set_reference.py は catalog branch に存在しない (master にだけある) ので、それを読む
check_csv.py:444/463 と catalog_set_audit.py:31 は据え置き (触らない)。
"""
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_WORKTREE_STR = "C:/dev/iMak_catalog/iMakCatalog"

FIXED_FILES = [
    ROOT / "iMakTCG" / "tcg_listing_fields.py",
    ROOT / "iMakTCG" / "catalog_reference.py",
    ROOT / "iMakMercari" / "montbell_listing.py",
    ROOT / "iMakTCG" / "card_identification_agent.py",
]

UNTOUCHED_MASTER_ONLY = {
    ROOT / "iMakTCG" / "check_csv.py":
        ['_cat = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakCatalog")'],
    ROOT / "iMakHQ" / "tools" / "catalog_set_audit.py":
        ['"..", "..", "iMakCatalog"))'],
}


def _read(p: Path) -> str:
    return io.open(p, encoding="utf-8").read()


def test_four_files_prefer_catalog_worktree_over_master():
    """4か所とも「worktree があればそれ、無ければ master」の形になっていること。

    これが無いと、psa_to_csv 経由(先に読まれた方が勝つ)では表に出ず、単体実行時だけ
    古い master の iMakCatalog (variant_meta.py 等の新 module が無い) を読んでしまう。
    """
    for f in FIXED_FILES:
        src = _read(f)
        assert CATALOG_WORKTREE_STR in src, f"{f.name}: catalog worktree 優先の記述が無い"
        assert "isdir" in src, f"{f.name}: worktree 有無の分岐 (フォールバック) が無い"
        # worktree のパスが master のパスより先に出てくること (優先順位の保証)
        i_worktree = src.index(CATALOG_WORKTREE_STR)
        i_isdir = src.index("isdir", i_worktree)
        assert i_isdir > i_worktree, f"{f.name}: worktree 判定の順序がおかしい"


def test_set_reference_sites_are_untouched():
    """set_reference.py 用の master 参照 (据え置き対象) を壊していないこと。"""
    for f, needles in UNTOUCHED_MASTER_ONLY.items():
        src = _read(f)
        for n in needles:
            assert n in src, f"{f}: set_reference 用の master 参照が変わっている ({n!r} が消えた)"


def test_fixed_files_do_not_hardcode_master_only_path():
    """★回帰防止: 4か所のどれかが「master だけ」の旧形に巻き戻っていないこと。

    旧形の例: `_CATALOG_ROOT = r"C:/dev/iMak/iMakCatalog"` (worktree 判定が無い決め打ち)。
    """
    bad_patterns = [
        'r"C:/dev/iMak/iMakCatalog"',
        "os.path.join(SCRIPT_DIR, \"..\", \"iMakCatalog\")",
    ]
    for f in FIXED_FILES:
        src = _read(f)
        for bad in bad_patterns:
            if bad not in src:
                continue
            # フォールバック文脈 (isdir チェックの後) でだけ許可。単独行での決め打ちは禁止
            i = src.index(bad)
            before = src[max(0, i - 200):i]
            assert "isdir" in before, f"{f.name}: {bad!r} が worktree 判定なしで使われている"
