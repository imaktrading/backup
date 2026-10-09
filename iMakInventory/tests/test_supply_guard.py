"""仕入元の中身の急変 (2026-10-09 シャワーズ PSA10→PSA7 で赤字) を止める判定."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import supply_guard as G  # noqa: E402

SHOWERS_ROW = "【PSA10】シャワーズex SAR 205/187 テラスタルフェスex"
SHOWERS_THEN = "シャワーズEX SAR テラスタルフェス SV8A 205/187 (PSA10) 傷有り"
SHOWERS_NOW = "シャワーズex SAR テラスタルフェス SV8a 205/187 (PSA7) ポケモンカード ポケカ"


def test_grade_not_psa10_is_caught():
    assert G.grade_problem(SHOWERS_ROW, SHOWERS_NOW)
    assert not G.grade_problem(SHOWERS_ROW, SHOWERS_THEN)


def test_row_title_with_lowercase_spaced_psa_10():
    """ホウオウ (820105875382) の行タイトルは 'psa 10'。仕入元は 'psa 9' に変わった."""
    assert G.grade_problem("ホウオウex SAR psa 10", "ホウオウex SAR psa 9")
    assert not G.grade_problem("ホウオウex SAR psa 10", "ホウオウex SAR psa 10 美品")


def test_non_psa_row_is_not_judged():
    assert not G.grade_problem("UNIQLO エヴァンゲリオンUT", "UNIQLO エヴァ Tシャツ S")
    assert not G.grade_problem(SHOWERS_ROW, "")
    assert not G.grade_problem(SHOWERS_ROW, "(deleted)")


def test_other_grader_and_equivalent_are_not_psa10():
    assert G.grade_problem(SHOWERS_ROW, "シャワーズ 205/187 BGS 10")
    assert G.grade_problem(SHOWERS_ROW, "シャワーズ 205/187 PSA10相当")


def test_name_change_grade():
    assert "鑑定" in G.name_change(SHOWERS_THEN, SHOWERS_NOW)


def test_name_change_card_number_swapped_in_shops():
    assert "カード番号" in G.name_change("【PSA10】ナミ OP08-106 SR", "【PSA10】ロビン OP08-110 SR")


def test_cosmetic_edits_are_not_changes():
    assert not G.name_change("【PSA10】ナミ OP08-106 SR", "✅【PSA10】ナミ OP08-106 SR★ 美品 即日発送")
    assert not G.name_change("ピカチュウ 031/087 PSA10", "ピカチュウ 31/87 PSA 10")     # 0 埋め・空白
    assert not G.name_change("ピカチュウ ０３１／０８７ ＰＳＡ１０", "ピカチュウ 031/087 PSA10")  # 全角
    assert not G.name_change("番号なし PSA10 ルフィ", "番号なし PSA10 ルフィ 値下げ")


def test_price_drop_vs_other_sources():
    """シャワーズ: 相場 ¥12,900〜16,000 に ¥4,830."""
    assert G.price_drop(4830, [12900, 16000], None)
    assert not G.price_drop(11000, [12900, 16000], None)


def test_price_drop_vs_previous_m():
    assert G.price_drop(15000, [], 42800)            # ソーナンス: 目視に回る
    assert not G.price_drop(30000, [], 42800)
    assert not G.price_drop(4830, [], None)          # 基準が無ければ判定しない


def test_baseline_keeps_first_seen_name(tmp_path):
    p = tmp_path / "b.json"
    b = G.NameBaseline(p)
    assert b.check("u1", SHOWERS_THEN) == ""         # 初めて = 控えるだけ
    b.save()
    b2 = G.NameBaseline(p)
    assert "鑑定" in b2.check("u1", SHOWERS_NOW)
    b2.save()
    assert json.loads(p.read_text(encoding="utf-8"))["u1"]["name"] == SHOWERS_THEN


def test_baseline_merges_concurrent_writers(tmp_path):
    p = tmp_path / "b.json"
    a, b = G.NameBaseline(p), G.NameBaseline(p)
    a.check("ua", "A 001/100 PSA10")
    b.check("ub", "B 002/100 PSA10")
    a.save()
    b.save()
    d = json.loads(p.read_text(encoding="utf-8"))
    assert set(d) == {"ua", "ub"}


def test_parse_jpy():
    assert G.parse_jpy("42800") == 42800
    assert G.parse_jpy("¥42,800") == 42800
    assert G.parse_jpy("") is None and G.parse_jpy(None) is None


# ── 巡回に組み込んだ形 (monitor_listings) ───────────────────────────────
def _merc(name, in_stock, price):
    return {"name": name, "status": "ON_SALE" if in_stock else "SOLD_OUT",
            "skus": [{"in_stock": in_stock, "price_jpy": price if in_stock else None}]}


def _setup(monkeypatch, tmp_path, pages):
    import monitor_listings as m
    monkeypatch.setattr(G, "_BASELINE", G.NameBaseline(tmp_path / "b.json"))
    monkeypatch.setattr(G, "REVIEW_PATH", tmp_path / "r.jsonl")
    monkeypatch.setattr(G, "_REVIEWED_THIS_RUN", set())
    monkeypatch.setattr(G, "_ALREADY_LOGGED", None)
    monkeypatch.setattr(m, "fetch_mercari", lambda url, **_k: pages[url])
    monkeypatch.setattr(m.time, "sleep", lambda *_a, **_k: None)
    return m


def test_showers_backup_psa7_is_not_used(monkeypatch, tmp_path):
    """主は売切、補 (Shops) が PSA7 ¥4,830 → 補は売切と同じ扱い = 行は売切 (取下げ) で ¥4,830 は採らない."""
    main, bk = "https://jp.mercari.com/item/m1", "https://jp.mercari.com/shops/product/2JXi"
    m = _setup(monkeypatch, tmp_path, {main: _merc("シャワーズ 205/187 PSA10", False, None),
                                       bk: _merc(SHOWERS_NOW, True, 4830)})
    row = {"row_index": 9, "item_id": "820133532757", "title": SHOWERS_ROW, "url": main,
           "backup_url_slots": [bk, None, None, None, None], "current_m_jpy_str": "12900"}
    r = m.check_one_row_with_fallback(row, sleep_sec=0)
    assert r["is_sold"] is True
    assert r["price_jpy"] is None
    assert r["backup_slot_results"][0]["sold_reconfirmed"] is True      # 補URL消込に乗る
    assert (tmp_path / "r.jsonl").read_text(encoding="utf-8").count('"grade"') == 1


def test_cheap_backup_kept_in_stock_but_price_not_adopted(monkeypatch, tmp_path):
    main, bk = "https://jp.mercari.com/item/m2", "https://jp.mercari.com/item/m3"
    m = _setup(monkeypatch, tmp_path, {main: _merc("ソーナンス 013/032 PSA10", True, 42800),
                                       bk: _merc("ソーナンス 013/032 PSA10 1ED", True, 15000)})
    row = {"row_index": 5, "item_id": "820192589083", "title": "ソーナンス 013/032 PSA10 1ED", "url": main,
           "backup_url_slots": [bk, None, None, None, None], "current_m_jpy_str": "42800"}
    r = m.check_one_row_with_fallback(row, sleep_sec=0)
    assert r["is_sold"] is False
    assert r["price_jpy"] is None          # M は前回のまま (書かない)


def test_legit_cheap_m_does_not_jump_to_other_source(monkeypatch, tmp_path):
    """ミュウex (10/09 試走): M=¥10,999 がスニダンの正しい安値。Shops ¥35,000 に乗り換えない."""
    main, bk = "https://jp.mercari.com/shops/product/2JX5", "https://jp.mercari.com/item/m5"
    m = _setup(monkeypatch, tmp_path, {main: _merc("PSA10 ミュウex 327/190", True, 35000),
                                       bk: _merc("PSA10 ミュウex 327/190 SSR", True, 10999)})
    row = {"row_index": 7, "item_id": "820110211566", "title": "PSA10 ミュウex sv4a 327/190 SSR", "url": main,
           "backup_url_slots": [bk, None, None, None, None], "current_m_jpy_str": "10999"}
    r = m.check_one_row_with_fallback(row, sleep_sec=0)
    assert r["is_sold"] is False and r["price_jpy"] == 10999     # 既に採っている安値は見ない


def test_established_cheap_price_is_not_flagged():
    assert not G.price_drop(10999, [35000], 10999)
    assert not G.price_drop(5555, [9999, 10000], 5555)


def test_normal_row_unchanged(monkeypatch, tmp_path):
    main = "https://jp.mercari.com/item/m4"
    m = _setup(monkeypatch, tmp_path, {main: _merc("ルフィ OP10-118 PSA10", True, 39980)})
    row = {"row_index": 3, "item_id": "1", "title": "PSA10 ルフィ OP10-118", "url": main,
           "backup_url_slots": [None] * 5, "current_m_jpy_str": "35000"}
    r = m.check_one_row_with_fallback(row, sleep_sec=0)
    assert r["is_sold"] is False and r["price_jpy"] == 39980


def test_review_file_does_not_repeat_across_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "REVIEW_PATH", tmp_path / "r.jsonl")
    for _run in range(3):                       # 3 回の巡回で同じ物
        monkeypatch.setattr(G, "_REVIEWED_THIS_RUN", set())
        monkeypatch.setattr(G, "_ALREADY_LOGGED", None)
        G.record_review("price", "u1", {"row_index": 1}, "安い", "", 100)
    assert len((tmp_path / "r.jsonl").read_text(encoding="utf-8").splitlines()) == 1
