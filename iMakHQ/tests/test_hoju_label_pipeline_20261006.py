"""補の目視にもラベルの記録を通す (2026-10-06 ユーザー「パイプラインなんだよ」/「残さないのは無駄」)。

- 新規で鑑定番号を打った出品 (商品管理シート A+I) が補の候補に来たら、ラベルでカードを決める
  (同じなら印を付けて目視へ / 違うカードなら出さない)
- 補で「同じ」と答えた候補の鑑定番号が分かれば、ラベルの記録に足す
- 同じタイトルの出品も「同じ」と扱う (番号が書いてあり、版違いの無いカードだけ)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_hoju_fill as H  # noqa: E402
import psa_label_learned as L  # noqa: E402

META = {"111": {"Brand": "ONE PIECE JPN OP09", "CardNumber": "118", "Subject": "LUFFY"}}
U1 = "https://jp.mercari.com/item/m111"
U2 = "https://jp.mercari.com/item/m222"


def _rows():
    r = [""] * 40
    r[H.A], r[H.CERT] = U1, "111"
    return [["hdr"], r]


def test_url_label_pids_from_sheet():
    learned = {}
    L.remember(learned, L.key_for_psa("one_piece_tcg", META["111"]), "OP09-118", cert="111")
    assert H.url_label_pids(_rows(), META, learned, L) == {L.norm_url(U1): "OP09-118"}


def test_split_uses_label_same_and_drops_other_card(monkeypatch):
    monkeypatch.setattr(H, "_URL_LABEL_PID", {L.norm_url(U1): "OP09-118"})
    same, rest = H.split_known_same([{"url": U1, "name": "x"}, {"url": U2, "name": "y"}],
                                    "one_piece_tcg:OP09-118", L, {"https://x/z": {}})
    # 目視は飛ばさない: ラベルで同じカードは印を付けて目視に出す
    assert same == [] and [(c["url"], c.get("label_same")) for c in rest] == [(U1, True), (U2, None)]
    same, rest = H.split_known_same([{"url": U1, "name": "x"}], "one_piece_tcg:OP01-001", L, {"https://x/z": {}})
    assert same == [] and rest == []                      # ラベルで別のカード → 出さない


def test_same_answers_with_cert_go_to_label(monkeypatch):
    monkeypatch.setattr(L, "category_of", lambda pid, db=None: "one_piece_tcg")
    out = H.same_label_picks([("OP09-118", U1, "same", "補URL③", "t"), ("OP09-118", U2, "same", "補URL③", "")],
                             {L.norm_url(U1): "111"}, META, L)
    assert out == [(L.key_for_psa("one_piece_tcg", META["111"]), "OP09-118", "111")]


def test_title_kept_and_used_only_without_diff(tmp_path):
    p = tmp_path / "u.json"
    L.remember_url_verdicts([("P1", U1, "same", "補URL③", " PSA10 ルフィ  OP09-118 ")], path=str(p))
    data = L.load(str(p))
    assert L.title_same_cards(data) == {"P1": {"PSA10 ルフィ OP09-118"}}
    L.remember_url_verdicts([("P1", U2, "diff", "補URL③", "PSA10 ルフィ OP09-118")], path=str(p))
    assert L.title_same_cards(L.load(str(p))) == {"P1": set()}


def test_backfill_titles():
    data = {U1: {"P1": {"v": "same"}}}
    assert L.backfill_titles(data, {L.norm_url(U1): "a  b"}) == 1 and data[U1]["P1"]["t"] == "A B"


def test_sync_cert_pids(tmp_path):
    lab, cp = tmp_path / "l.json", tmp_path / "c.json"
    L.save({"111": {"key": "one_piece_tcg:OP09-118"}, "999": {"key": "one_piece_tcg:X"}}, str(cp))
    assert L.sync_cert_pids(str(lab), str(cp), META) == 1
    assert L.sync_cert_pids(str(lab), str(cp), META) == 0          # 二重には入らない


def test_diff_url_and_diff_title_are_not_shown_again(monkeypatch):
    monkeypatch.setattr(H, "_URL_LABEL_PID", {})
    H._SNKR_MEMO.clear()
    uv = {U1: {"OP09-118": {"v": "diff", "t": "PSA10 ルフィ 偽"}}}
    U3 = "https://jp.mercari.com/item/m333"
    same, rest = H.split_known_same([{"url": U1, "name": "a"}, {"url": U3, "name": "psa10 ルフィ 偽"},
                                     {"url": U2, "name": "別"}], "one_piece_tcg:OP09-118", L, uv)
    assert same == [] and [c["url"] for c in rest] == [U2]


def test_label_not_is_kept_and_used(monkeypatch):
    learned = {}
    k = L.key_for_psa("one_piece_tcg", META["111"])
    L.remember_not(learned, k, "OP09-118", cert="111")
    assert L.is_not(learned, k, "one_piece_tcg:OP09-118")
    L.remember(learned, k, "OP09-118")
    assert L.learned_pid(learned, k) is None                  # 同じカードに「違う」も出ている → 決めない
    nots = H.url_label_nots({L.norm_url(U1): "111"}, META, learned, L)
    monkeypatch.setattr(H, "_URL_LABEL_PID", {})
    monkeypatch.setattr(H, "_URL_LABEL_NOT", nots)
    H._SNKR_MEMO.clear()
    same, rest = H.split_known_same([{"url": U1, "name": "a"}], "one_piece_tcg:OP09-118", L, {"https://x/z": {}})
    assert same == [] and rest == []


def test_diff_answers_with_cert_go_to_label_not(monkeypatch):
    monkeypatch.setattr(L, "category_of", lambda pid, db=None: "one_piece_tcg")
    out = H.same_label_picks([("OP09-118", U1, "diff", "補URL③", "")], {L.norm_url(U1): "111"}, META, L, want="diff")
    assert out == [(L.key_for_psa("one_piece_tcg", META["111"]), "OP09-118", "111")]
