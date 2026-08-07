"""KEY のカテゴリ接頭辞で catalog 引きが空振りしていた回帰テスト (2026-07-29).

実害: live PSA 246件中 **217件(88%)** が `one_piece_tcg:OP08-052` 形式の接頭辞つき KEY で、
`card_meta_for_key` が接頭辞を付けたまま product_id を引いていたため **全件 None**。
→ name_jp / hint が空 → 検索語が「PSA10 <番号>」だけになり、変種の絞り込みも無効化。
→ 同番号の別変種を掴み、確証UIで人が「違う」を押し続ける状態だった (7/29 実測3件とも本件)。

同型のバグは 2026-07-28 に `psa_hoju_fill._card_no_from_key` で1度直している。
**同じ接頭辞問題が別関数に残っていた**ので、両方を固定する。
"""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import mercari_psa_resource as mp  # noqa: E402
import psa_hoju_fill as hf  # noqa: E402


def _mkdb(tmp_path):
    """product_id が **作品を跨いで衝突する** 最小 catalog (実データと同じ形)。"""
    db = tmp_path / "products.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (product_id TEXT, name_jp TEXT, images TEXT, set_name TEXT,"
                " specs TEXT, category TEXT, language TEXT, name_en TEXT)")
    con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?)", [
        ("ST04-005", "クイーン", "[]", "BOOSTER -TWO LEGENDS-[OP-08]",
         '{"variant_type":"","rarity":"C"}', "one_piece_tcg", "ja", "Queen"),
        ("ST04-005", "ストライクダガー", "[]", "STARTER DECK", '{}', "gundam_tcg", "ja", "Strike Dagger"),
        ("ST04-005_p3", "クイーン", "[]", None, '{"variant_type":"alt_art"}', "one_piece_tcg", "ja", "Queen"),
        ("EB03-053", "ナミ", "[]", "EXTRA BOOSTER [EB-03]",
         '{"get_info":"エクストラブースター","rarity":"SR"}', "one_piece_tcg", "ja", "Nami"),
    ])
    con.commit()
    con.close()
    return str(db)


def _clear_caches():
    mp.card_meta_for_key.__defaults__[0].clear()      # _cache
    mp._is_multi_variant.__defaults__[1].clear()


def test_split_key_strips_category_prefix():
    assert mp.split_key("one_piece_tcg:ST04-005_OP08") == ("one_piece_tcg", "ST04-005_OP08")
    assert mp.split_key("OP08-052") == ("", "OP08-052")
    assert mp.split_key("") == ("", "")
    # url-key は catalog の product_id ではない → 引かせない (fail-closed)
    assert mp.split_key("item:m12345") == ("", "")
    assert mp.split_key("shops:abc") == ("", "")


def test_prefixed_key_resolves_catalog(tmp_path, monkeypatch):
    """接頭辞つき KEY でも name_jp / hint が引けること (これが空だと番号だけ検索になる)。"""
    _clear_caches()
    db = _mkdb(tmp_path)
    m = mp.card_meta_for_key("one_piece_tcg:EB03-053", _db=db)
    assert m is not None, "接頭辞つき KEY で catalog が引けていない (本バグの再発)"
    assert m["name_jp"] == "ナミ"
    assert any("EB-03" in t for t in m["hint"] if t)


def test_category_prefix_prevents_cross_title_collision(tmp_path, monkeypatch):
    """同じ product_id が別作品にも在る。KEY のカテゴリで正しい方を選ぶこと。

    番号体系は作品を跨いで衝突する (実測 ST04-005 = ワンピース クイーン / ガンダム ストライクダガー)。
    ここを間違えると **別作品のカードを仕入れ候補として探しに行く**。
    """
    _clear_caches()
    db = _mkdb(tmp_path)
    assert mp.card_meta_for_key("one_piece_tcg:ST04-005", _db=db)["name_jp"] == "クイーン"
    _clear_caches()
    assert mp.card_meta_for_key("gundam_tcg:ST04-005", _db=db)["name_jp"] == "ストライクダガー"


def test_ambiguous_without_category_is_failclosed(tmp_path):
    """接頭辞が無く候補が複数 = どれか分からない → None (推測で掴まない)。"""
    _clear_caches()
    db = _mkdb(tmp_path)
    assert mp.card_meta_for_key("ST04-005", _db=db) is None


def test_variants_are_scoped_by_category(tmp_path):
    """変種一覧もカテゴリで絞れること (絞らないと別作品が変種として混ざる)。"""
    db = _mkdb(tmp_path)
    allv = mp.catalog_variants_for_cardno("ST04-005", _db=db)
    op = mp.catalog_variants_for_cardno("ST04-005", _db=db, category="one_piece_tcg")
    assert {d["name_jp"] for d in allv} == {"クイーン", "ストライクダガー"}
    assert {d["name_jp"] for d in op} == {"クイーン"}


def test_gate_scopes_variant_choices_by_category():
    """確証ゲート② の変種候補は **KEY のカテゴリで絞って**引くこと。

    絞らないと、人が選ぶ選択肢に別作品のカードが並ぶ (ST04-005 にガンダムのカードが混ざる)。
    選べてしまう = 別作品を仕入れに行く経路になるので、UI に出す前に閉じる。
    """
    src = (Path(__file__).parent.parent / "tools" / "psa_resource_gate.py").read_text(encoding="utf-8")
    assert "category=mp.split_key(r.get(\"key\"))[0]" in src, "変種候補がカテゴリで絞られていない"
    # ⚠️多変種バッジ側も同様 (別作品を変種として数えない)
    assert 'mp._is_multi_variant(cn, mp.split_key(k)[0])' in src
    assert 'mp._is_multi_variant(rc.get("card_no") or "", mp.split_key(rc.get("key"))[0])' in src
    assert '"key": r.get("key", "")' in src, "restock_cands が key を持ち回っていない(判定に使えない)"


def test_multi_variant_recomputed_after_key_fallback(monkeypatch):
    """title に番号が無い行でも、KEY から番号を取って多変種判定をすること。

    取り直さないと ⚠️多変種バッジが出ず、同番号別変種を流し見で掴む (「違う」の主因)。

    ★2026-08-03 改訂: KEY 優先は **build_card_query 本体**へ移った
    (以前は `build_search_query` が後から上書きするパッチだった)。
    本体を mock で潰すと「補ったか」を確かめられないので、**本体を動かして**検証する。
    catalog DB だけ mock する。
    """
    calls = []

    def fake_mv(card_no, category="", *a, **k):
        calls.append((card_no, category))
        return True

    monkeypatch.setattr(mp, "card_meta_for_key", lambda k: {"name_jp": "クイーン"})
    monkeypatch.setattr(mp, "name_jp_for_card", lambda n: None)
    monkeypatch.setattr(mp, "_is_multi_variant", fake_mv)
    q = hf.build_search_query({"title": "【PSA10】クイーン 二つの伝説 SP",
                               "key": "one_piece_tcg:ST04-005_OP08"}, mp)
    assert q["card_no"] == "ST04-005", "KEY から番号を取れていない"
    assert q["kw"] == "PSA10 クイーン ST04-005"
    assert q["multi_variant"] is True, "多変種判定をしていない"
    assert ("ST04-005", "one_piece_tcg") in calls,         f"カテゴリ込みで判定していない (別作品の変種を数える): {calls}"
