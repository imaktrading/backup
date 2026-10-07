# -*- coding: utf-8 -*-
"""目視で OK しても出品の手前で落ち、毎回目視に戻っていた2件 (2026-10-07)。

ユーザー「新規の目視で何回も出てくる奴は？」「普通、新規の目視には１回しか出ないはずでしょ」
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HQ)
sys.path.insert(0, os.path.join(HQ, "tools"))
sys.path.insert(0, os.path.join(ROOT, "iMakeBayAPI"))

import listing_validator as V  # noqa: E402
import psa_variant_gate as G  # noqa: E402


def _r(pid, rarity, lang, alias=None, vt="starter_deck"):
    return {"product_id": pid, "specs": {"rarity": rarity, "variant_type": vt},
            "language": lang, "alias_of": alias}


def test_gundam_plus_label_picks_the_plus_row_body():
    # cert 122484177 ST04-010 COMMON+: 公式のパラレル行はレアリティ C のまま 7本 → 決められなかった
    good = [_r("ST04-010_bp", "C+", "en"), _r("ST04-010_bp_JP", "C+", "ja", alias="ST04-010_p1")] + \
           [_r("ST04-010_p%d" % i, "C", None, vt="alt_art") for i in (1, 2, 3, 4, 5, 7)]
    ok = [r["product_id"] for r in good]
    b = "GUNDAM JAPANESE SEED STRIKE"
    assert G.narrow_gundam_plus(b, "KIRA YAMATO COMMON+", good, ok) == ["ST04-010_p1"]
    # 英語版のラベルなら英語の行
    assert G.narrow_gundam_plus("GUNDAM SEED STRIKE", "KIRA YAMATO COMMON+", good, ok) == ok  # en/ja 2本 → 絞らない
    # 「+」の無いラベルは触らない
    assert G.narrow_gundam_plus(b, "KIRA YAMATO COMMON", good, ok) == ok


def test_film_red_encore_pack_promo_passes_selfcheck():
    # cert 84299672 新時代 ST11-004_p1: PSA brand にセット記号が無い配布プロモ
    errs = V.validate_title_against_psa(
        "PSA 10 One Piece Promo Cards #ST11-004 New Genesis 2023 Super Rare",
        "ONE PIECE JAPANESE FILM RED: ENCORE PACK", "004", "Promo Cards")
    assert errs == []
    # 番号が違えば今までどおり落とす
    assert V.validate_title_against_psa(
        "PSA 10 One Piece Promo Cards #ST11-005 New Genesis",
        "ONE PIECE JAPANESE FILM RED: ENCORE PACK", "004", "Promo Cards")


def test_repeat_counts_lists_certs_answered_before():
    import post_psa_review as P
    vc = {"122484177": {"choice": "OK", "product_id": "ST04-010", "times": 5},
          "84299672": {"choice": "OK", "product_id": "ST11-004_p1", "times": 2},
          "111": {"choice": "NONE"}}
    t = [{"cert": "84299672"}, {"cert": "122484177"}, {"cert": "111"}, {"cert": "999"}]
    assert P.repeat_counts(t, vc) == [("122484177", 5), ("84299672", 2)]
    assert P.repeat_counts([{"cert": "999"}], vc) == []


# ---- 理由を覚えて、繰り返したら残務へ (ユーザー「理由わからず手当せずに何回も出てくるものを防ぎたい」)
LOG = """\
 → #010 KIRA YAMATO ✓
    ⏭️ Skip (刷りがPSAラベルと合わない): #122484177 ST04-010 — PSA はパラレル (COMMON+) だが行は通常
 → #004 NEW GENESIS ✓
    ❌ セルフチェック失敗 (#84299672):
       ❌ タイトルに'ST11'があるが PSA brand に存在しない
    → この商品はCSVに含めません
    ⚠️ Skipping #84299672: selfcheck failed in build_row
 → #088 RIKA SPECIAL ART ✓
    🚫 PSA8 を検出(PSAページ) → **出品しない**
    ⚠️ Skipping #137111174: selfcheck failed in build_row
    #161378204: $118.98
失敗: 84299672, 137111174
"""


def test_parse_fail_reasons_from_run_log():
    import build_fail_watch as B
    r, ok = B.parse_fail_reasons(LOG)
    assert ok == {"161378204"}
    assert r["122484177"].startswith("刷りがPSAラベルと合わない — ST04-010")
    assert "ST11" in r["84299672"]
    assert r["137111174"].startswith("PSA8 を検出")


def test_backlog_after_second_fail_of_answered_cert_only_once():
    import build_fail_watch as B
    vc = {"122484177": {"choice": "OK", "product_id": "ST04-010", "times": 5}}
    r = {"122484177": "刷り", "999": "未回答で落ちた"}
    led, todo = B.update_ledger({}, r, set(), vc, "t1")
    assert todo == [] and led["122484177"]["fails"] == 1 and "answered" not in led["999"]
    led, todo = B.update_ledger(led, r, set(), vc, "t2")
    assert [c for c, _ in todo] == ["122484177"]          # 目視の答えがある物だけ
    led["122484177"]["backlog"] = "№600"
    led, todo = B.update_ledger(led, r, set(), vc, "t3")
    assert todo == []                                     # 同じ cert は1回だけ
    led, _ = B.update_ledger(led, {}, {"122484177"}, vc, "t4")
    assert "122484177" not in led                         # 出品できたら外す


def test_run_writes_ledger_and_always_logs(tmp_path):
    import json
    import build_fail_watch as B
    lp, vp = str(tmp_path / "l.json"), tmp_path / "v.json"
    vp.write_text(json.dumps({"84299672": {"choice": "OK", "product_id": "ST11-004_p1", "times": 2}}), encoding="utf-8")
    logs, added = [], []
    B.run("", logs.append, ledger_path=lp, verified_path=str(vp))
    assert logs[-1].startswith("🩹 目視 OK 済みなのに出品の手前で落ちた: 0件")   # 0件でも出す
    for _ in range(2):
        B.run(LOG, logs.append, ledger_path=lp, verified_path=str(vp),
              add_backlog=lambda c, rec: added.append(c) or "№1")
    assert added == ["84299672"]
    assert json.loads(open(lp, encoding="utf-8").read())["84299672"]["backlog"] == "№1"


def test_repeat_note_shows_reason_and_backlog():
    import post_psa_review as P
    s = P.repeat_note(5, {"reason": "刷り <x>", "fails": 2, "backlog": "№600"})
    assert "6回目" in s and "刷り &lt;x&gt;" in s and "№600" in s
    assert "記録なし" in P.repeat_note(1, None)
