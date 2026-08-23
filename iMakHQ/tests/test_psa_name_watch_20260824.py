# -*- coding: utf-8 -*-
"""PSAラベル ↔ カタログ英名 の定期突合 (2026-08-24)。

## なぜこの面が要るか
カタログの英名が「別人の名前」や「直訳」になっている事故が 8/23-24 で3件出た。
カタログ側の「英名が割れている」検出では **半分しか捕まらない** — 全行が同じ誤りなら
カタログの中で矛盾せず、気づけない (カナリィ=Canary 3行がまさにそれ)。

カタログからの回答 (`2026-08-23_hq_translated_names_pokekid_canari_response.md`):
> 「日本語名の直訳が英名になっている」型は、カタログの中だけでは検出できません。
>  外の正解と突き合わせるしかありません。
>  → **そちらの突合が、この型に対する唯一の検出面です。**
>  (こちらから live の cert 一覧は見えないので、この面はそちらにしか作れません)

入稿前の照合 (csv_auditor) は **今から出す分**しか見ない。こちらは **出品済を含む全行**。
"""
import os
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import csv_auditor as A  # noqa: E402
import psa_name_watch as W  # noqa: E402


def _sheet(rows):
    """[header, ...] を作る。列は itemID=1 / タイトル=2 / cert=8 / カテゴリ=17 / KEY=34。"""
    hdr = [""] * 35
    hdr[17] = "カテゴリ"
    hdr[34] = "KEY"
    out = [hdr]
    for itemid, cert, key, cat in rows:
        r = [""] * 35
        r[1], r[8], r[17], r[34] = itemid, cert, cat, key
        out.append(r)
    return out


def test_only_tcg_rows_with_key_and_cert():
    vals = _sheet([
        ("820001", "111", "pokemon_tcg:SV3-130", "TCG"),      # 出品中
        ("", "222", "one_piece_tcg:OP01-001", "TCG"),          # 未出品
        ("820003", "333", "pokemon_tcg:X", "gshock"),          # TCG でない
        ("820004", "444", "", "TCG"),                          # KEY 無し
        ("820005", "", "pokemon_tcg:Y", "TCG"),                # cert 無し
        ("820006", "666", "bare_pid_no_colon", "TCG"),         # KEY の形が違う
    ])
    got = W.rows_to_check(vals, 34)
    assert got == [("111", "pokemon_tcg:SV3-130", True),
                   ("222", "one_piece_tcg:OP01-001", False)]


# ── 突合そのもの ──────────────────────────────────────────────────
_NAMES = {
    ("pokemon_tcg", "SV3-130"): ("オルティガ", "Arven", "Arven"),        # ★誤り
    ("pokemon_tcg", "SV1S-097"): ("ジニア", "Jacq", "Jacq"),             # 直った後
    ("one_piece_tcg", "OP01-001"): ("モンキー・D・ルフィ", "Monkey.D.Luffy", ""),
}
_META = {
    "111": {"Brand": "POKEMON JAPANESE SV3-RULER OF THE BLACK FLAME",
            "Subject": "ORTEGA SUPER", "CardNumber": "130"},
    "222": {"Brand": "ONE PIECE JAPANESE OP01-ROMANCE DAWN",
            "Subject": "MONKEY D. LUFFY", "CardNumber": "001"},
    "333": {"Brand": "POKEMON JAPANESE SV1S-SCARLET EX",
            "Subject": "JACQ SUPER", "CardNumber": "097"},
}


def _run(rows):
    return W.mismatches(rows, _NAMES, _META.get, A.psa_identity_findings)


def test_catches_the_wrong_person_name():
    """★オルティガ の現物に ペパー(Arven) の名前が付いている。"""
    bad, checked = _run([("111", "pokemon_tcg:SV3-130", True)])
    assert checked == 1 and len(bad) == 1
    b = bad[0]
    assert b["catalog_jp"] == "オルティガ" and b["catalog_en"] == "Arven"
    assert b["psa_subject"] == "ORTEGA SUPER"
    assert b["live"] is True


def test_correct_rows_are_quiet():
    bad, checked = _run([("222", "one_piece_tcg:OP01-001", False),
                         ("333", "pokemon_tcg:SV1S-097", True)])
    assert checked == 2 and bad == []


def test_rows_without_psa_or_catalog_are_skipped_not_flagged():
    """材料が無い行を「食い違い」に数えない (推測で依頼を出さない)。"""
    bad, checked = _run([("999", "pokemon_tcg:SV3-130", True),        # PSA 無し
                         ("111", "pokemon_tcg:NOT-IN-CATALOG", True)])  # カタログ無し
    assert checked == 0 and bad == []


def test_same_judgement_as_the_pre_upload_check():
    """入稿前の照合と **同じ関数**を使っていること (真理表を2か所に作らない)。"""
    import inspect
    src = inspect.getsource(W.mismatches)
    assert "findings_fn(" in src, "自前で判定を書き直している"


def test_exit_code_is_nonzero_when_something_is_found(monkeypatch):
    """0件が正常。見つかったら 1 で返す (走行の締めで拾えるように)。"""
    src = inspect_source()
    assert "return 1 if bad else 0" in src


def inspect_source():
    return open(os.path.join(_TOOLS, "psa_name_watch.py"), encoding="utf-8").read()


@pytest.mark.parametrize("needle", ["--json", "--live-only"])
def test_useful_switches_exist(needle):
    assert needle in inspect_source()
