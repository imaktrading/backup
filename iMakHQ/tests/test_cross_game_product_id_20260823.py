# -*- coding: utf-8 -*-
"""2026-08-23 の誤出品の回帰テスト。

何が起きたか:
  PSA の現物は ワンピース の Eustass "Captain" Kid (cert154825163)。生成ログでは
  正しく `One Piece ... Eustass "captain" Kid` とタイトルまで作れていた。ところが
  catalog から Item Specifics を引く所で **Gundam の Wing Gundam** に化け、
  `PSA 10 Gundam Japanese Wings of Advance #ST02-001 Wing Legend Rare` として
  eBay に出た (ItemID 820036000051 / 取り下げ済)。

なぜ:
  `product_id` はカタログ全体では一意でない。ワンピとガンダムは採番規則が同じで
  `ST02-001` `EB01-003` など **283件が両方に実在**する。category を付けずに
  `WHERE product_id=?` で引くと、先に入っている方 (= 別ゲームの別カード) が返る。

守ること:
  ① catalog を引く時は category を必ず添える
  ② category が決まらないのに複数カテゴリに当たったら、**どれかを選ばない**
  ③ 中間ファイル (sidecar) は category と枝番を落とさない
  ④ 監査くんは PSA の現物と CSV を突き合わせて、この型を入稿前に止める
"""
import os
import sys

import pytest

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HQ)
for p in (os.path.join(HQ, "tools"), os.path.join(ROOT, "iMakTCG")):
    if p not in sys.path:
        sys.path.insert(0, p)


# ── ① / ② catalog の引き方 ────────────────────────────────────────
def test_catalog_specs_requires_category_when_ambiguous(monkeypatch):
    """category 無しで複数カテゴリに当たったら None (= 解決不能)。片方を選ばない。"""
    import tcg_listing_fields as T

    rows_by_args = {}

    class _FakeCon:
        def execute(self, sql, args):
            rows_by_args["sql"], rows_by_args["args"] = sql, args

            class _R:
                @staticmethod
                def fetchall():
                    # category 指定が無ければ 2 カテゴリ分ヒットする状況を再現
                    if "category=?" in sql:
                        return [{"name_en": "Eustass Kid", "language": "ja", "specs": "{}"}]
                    return [{"name_en": "Wing Gundam", "language": "ja", "specs": "{}"},
                            {"name_en": "Eustass Kid", "language": "ja", "specs": "{}"}]
            return _R()

        def close(self):
            pass

    monkeypatch.setattr(T.sqlite3, "connect", lambda *_a, **_k: _FakeCon())

    assert T._catalog_specs("ST02-001") is None, "曖昧なのに片方を選んでいる"

    got = T._catalog_specs("ST02-001", "one_piece_tcg")
    assert got is not None and got["_name_en"] == "Eustass Kid"
    assert "category=?" in rows_by_args["sql"], "category で絞っていない"
    assert rows_by_args["args"] == ("ST02-001", "one_piece_tcg")


def test_catalog_specs_sql_never_drops_category():
    """SQL 本文に category 条件が残っていること (文言の作り直しで消えるのを防ぐ)。"""
    import inspect

    import tcg_listing_fields as T
    src = inspect.getsource(T._catalog_specs)
    assert "category=?" in src


@pytest.mark.parametrize("raw,want", [
    ("one_piece_tcg:ST02-001_OTHER PRODUCT CARD_En",
     ("one_piece_tcg", "ST02-001_OTHER PRODUCT CARD_En")),
    ("gundam_tcg:ST02-001", ("gundam_tcg", "ST02-001")),
    ("ST02-001", ("", "ST02-001")),
    ("", ("", "")),
])
def test_split_category(raw, want):
    import tcg_listing_fields as T
    assert T._split_category(raw) == want


# ── ③ sidecar が category を落とさない ────────────────────────────
def test_sidecar_keeps_category_when_person_confirms():
    """人が確定した PID は bare でも、控えてある category を引き継ぐ。"""
    import canonical_pid_sidecar as S

    assert S._keep_category("one_piece_tcg:ST02-001_D", "ST02-001") == "one_piece_tcg:ST02-001"
    # 既に category 付きなら触らない
    assert S._keep_category("one_piece_tcg:X", "gundam_tcg:Y") == "gundam_tcg:Y"
    # 控えが無ければそのまま (作り話をしない)
    assert S._keep_category("", "ST02-001") == "ST02-001"


def test_sidecar_payload_keeps_category(tmp_path):
    import canonical_pid_sidecar as S

    csv_p = str(tmp_path / "tcg_upload_x.csv")
    open(csv_p, "w").close()
    out = S.write_sidecar(csv_p,
                          {"154825163": "one_piece_tcg:ST02-001_OTHER PRODUCT CARD_En"},
                          confirmed_pids={"154825163": "ST02-001"})
    import json
    got = json.load(open(out, encoding="utf-8"))["by_cert"]["154825163"]
    assert got.startswith("one_piece_tcg:"), f"category が落ちている: {got}"


# ── ④ 監査くんが PSA の現物と突き合わせる ──────────────────────────
_HDRS = ["*Title", "C:Game", "C:Card Name", "C:Character",
         "CDA:Certification Number - (ID: 27503)"]


def _row(title, game, name, char="", cert="154825163"):
    return [title, game, name, char, cert]


def test_auditor_catches_wrong_game():
    """今回の現物そのもの: ワンピの slab が Gundam として出ようとしたら止める。"""
    import csv_auditor as A

    meta = {"Brand": "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -LEADER COLLECTION-",
            "Subject": 'EUSTASS "CAPTAIN" KID', "CardNumber": "001"}
    row = _row("PSA 10 Gundam Japanese Wings of Advance #ST02-001 Wing Legend Rare",
               "Gundam Card Game", "Wing Gundam", "Wing Gundam")
    out = A.psa_identity_findings(_HDRS, row, meta)
    assert out and out[0][0] == "ERROR"
    assert "別ゲーム" in out[0][1]
    # 止める側 (報告+除外) に分類されること
    assert A.classify_finding(*out[0]) == A.REPORT_PROGRAM


def test_auditor_catches_wrong_person_name():
    """Jacq の現物に Zinnia (別人) の名前が付いたら止める。"""
    import csv_auditor as A

    meta = {"Brand": "POKEMON JAPANESE SV1S-SCARLET EX",
            "Subject": "JACQ SUPER", "CardNumber": "097"}
    row = _row("PSA 10 Pokemon Japanese Sv1s: Scarlet Ex #097/078 Zinnia Super Rare 2023",
               "Pokémon TCG", "Zinnia", "Zinnia", cert="85270924")
    out = A.psa_identity_findings(_HDRS, row, meta)
    assert out and "名前が一致しない" in out[0][1]


def test_auditor_accepts_correct_row():
    import csv_auditor as A

    meta = {"Brand": "POKEMON JAPANESE SV1S-SCARLET EX",
            "Subject": "JACQ SUPER", "CardNumber": "097"}
    row = _row("PSA 10 Pokemon Japanese Sv1s: Scarlet Ex #097/078 Jacq Super Rare 2023",
               "Pokémon TCG", "Jacq", "Jacq", cert="85270924")
    assert A.psa_identity_findings(_HDRS, row, meta) == []


def test_auditor_tolerates_psa_abbreviations():
    """PSA はラベル幅の都合で母音を落とす。正しい行を誤って止めないこと。

    実データ (2026-07-26 cert153444937): Subject='RESHRM. & CHARZRD.GX DOUBLE BLAZE'
    に対して catalog 名は 'Reshiram & Charizard-GX'。
    """
    import csv_auditor as A

    meta = {"Brand": "POKEMON JAPANESE SM-DOUBLE BLAZE",
            "Subject": "RESHRM. & CHARZRD.GX DOUBLE BLAZE", "CardNumber": "096"}
    row = _row("PSA 10 Pokemon Japanese Double Blaze #096 Reshiram & Charizard-GX",
               "Pokémon TCG", "Reshiram & Charizard-GX", "", cert="153444937")
    assert A.psa_identity_findings(_HDRS, row, meta) == []


def test_auditor_catches_translated_instead_of_official_name():
    """★2026-08-23 実測の見逃し。公式名は Poké Kid なのに catalog が直訳を持っていた。

    最初は略記の許容が緩く (4文字以上)、`poke` が `pokemon` に含まれてしまうため
    「一致した」ことになって素通りしていた (S4a-197 / 出品中1件)。
    """
    import csv_auditor as A

    meta = {"Brand": "POKEMON JAPANESE SWORD & SHIELD SHINY STAR V",
            "Subject": "FA/POKE KID SHINY STAR V", "CardNumber": "197"}
    row = _row("PSA 10 Pokemon Japanese Shining Fates #197/190 Imitation Pokémon",
               "Pokémon TCG", "Imitation Pokémon", "Imitation Pokémon", cert="144091892")
    out = A.psa_identity_findings(_HDRS, row, meta)
    assert out and "名前が一致しない" in out[0][1]


def test_auditor_still_allows_real_abbreviations():
    """5文字以上の略記は今までどおり通す (UMBRN. = Umbreon)。

    ここを6文字に絞ると、実在するこの略記まで止めてしまう。
    実データ 927行で 5文字が「誤検出0・見逃し0」の境目だった。
    """
    import csv_auditor as A

    meta = {"Brand": "POKEMON JAPANESE SM12A-TAG TEAM GX ALL STARS",
            "Subject": "FA/UMBRN. & DRKR. GX TAG TEAM", "CardNumber": "181"}
    row = _row("PSA 10 Pokemon Japanese Tag Team GX All Stars #181 Umbreon & Darkrai GX",
               "Pokémon TCG", "Umbreon & Darkrai GX", "", cert="1")
    assert A.psa_identity_findings(_HDRS, row, meta) == []


def test_auditor_silent_without_psa_data():
    """PSA データが無い行は何も言わない (推測で止めない)。"""
    import csv_auditor as A
    assert A.psa_identity_findings(_HDRS, _row("t", "Pokémon TCG", "x"), None) == []
