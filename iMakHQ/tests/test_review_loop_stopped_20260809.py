"""Regression: 2026-08-09 目視レビューで同じ cert が何度も出続けるループを止める.

ユーザー報告: 「cert 158452540 / 140936782 / 158452539 / 138056958 が新規出品時の HTML で
何回も出てくる」。実測すると 4件とも resolver は **RESOLVED** (答えを持っている) のに、
出題履歴 (`psa_review_results/`) は全部 `NONE` で、一度も OK になっていなかった
(158452539 は4回・138056958 は4回・140936782 は3回・158452540 は2回)。

真因は2つ:

  ②-1 **見せている絵が違う**。Fusion World の LEADER は両面カード (表 = LEADER FRONT /
       裏 = AWAKEN)。PSA は AWAKEN 面を上にして slab するので、viewer が出す
       `CardImageUrl` (表写真) は catalog が持つ表面画像と別の絵になる。
       ところが **PSA の裏写真 (`CardImageUrlBack`) が LEADER FRONT** で、
       catalog の画像と一致する。片面しか出していなかったので照合しようがなく、
       人が「該当なし」を押すのが正しい状態だった。
       (実測: cert158452539 の裏写真 = FB01-071 の LEADER FRONT 15000、
        cert158452540 の裏写真 = FB07-097 の LEADER FRONT 15000)

  ②-2 **自己修復が「引ける」=「人が確定できる」と同一視していた**。
       `active_review_skips` は resolver が RESOLVED を返す cert を cooldown から
       解除する。この4件は RESOLVED なので **NONE を押した翌日にまた出る**。
       14日ループを直したつもりが、この4件では毎日ループに加速していた。

修正:
  - `back_face_url()`: 表面 URL から裏面 URL を導く (公式で 200 実測済の規則)
  - viewer が PSA 両面 + catalog 裏面を並べる
  - `_record_review_skip` が **却下された product_id** を台帳に残す
  - `already_rejected_same_answer()`: 同じ答えを既に断られていたら自己修復で解除しない
"""
import datetime
import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS = _ROOT / "iMakHQ" / "tools"

NOW = datetime.datetime(2026, 8, 9, 20, 0, 0)


def _load_review():
    spec = importlib.util.spec_from_file_location("post_psa_review", str(_TOOLS / "post_psa_review.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _load_batch():
    if str(_ROOT / "iMakTCG") not in sys.path:
        sys.path.insert(0, str(_ROOT / "iMakTCG"))
    import tcg_batch_select as B
    return B


# ------------------------------------------------------------------ ②-1 裏面 URL

def test_back_face_url_dbs_official():
    """dbs-cardgame の `_f` → `_b` (公式で HTTP 200 実測済)."""
    R = _load_review()
    base = "https://www.dbs-cardgame.com/fw/images/cards/card/jp/"
    assert R.back_face_url(base + "FB01-071_f.webp") == base + "FB01-071_b.webp"
    assert R.back_face_url(base + "FB01-071_f_p1.webp") == base + "FB01-071_b_p1.webp"
    assert R.back_face_url(base + "FB07-097_f_p3.webp") == base + "FB07-097_b_p3.webp"


def test_back_face_url_bandai():
    """bandai-tcg-plus の `_Leader_F_` → `_Leader_B_` (公式で HTTP 200 実測済)."""
    R = _load_review()
    u = "https://files.bandai-tcg-plus.com/card_image/DBFW-JA/FB01/JP_FW_FB01-071_Leader_F_PARA_dummy.png"
    assert R.back_face_url(u) == u.replace("_Leader_F_", "_Leader_B_")


def test_back_face_url_returns_none_for_single_sided():
    """両面と判らない URL は None。**推測で存在しない URL を作らない** (fail-closed)."""
    R = _load_review()
    for u in ("", None, "https://www.pokemon-card.com/assets/images/card_images/large/SZD/x.jpg",
              "https://files.bandai-tcg-plus.com/card_image/OP-JA/OP01/OP01-001.png",
              "https://www.dbs-cardgame.com/fw/images/cards/card/jp/FB01-071.webp"):
        assert R.back_face_url(u) is None, u


def test_back_face_url_does_not_touch_path_segments():
    """path 側の 'f' を巻き込まない (置換はファイル名の 1 箇所だけ)."""
    R = _load_review()
    u = "https://www.dbs-cardgame.com/fw/images/cards/card/jp/FB01-071_f.webp"
    got = R.back_face_url(u)
    assert got.count("/fw/") == 1 and got.endswith("FB01-071_b.webp")


# ------------------------------------------------------------------ ②-2 同じ答えを聞き直さない

def test_same_answer_is_not_released():
    """人が却下した product_id と今の resolver の答えが同じなら解除しない."""
    B = _load_batch()
    skips = {"158452539": {"at": "2026-08-09T19:24:55", "choice": "NONE", "pid": "FB01-071_PARA"}}
    got = B.already_rejected_same_answer(skips, ["158452539"],
                                         resolved_pids={"158452539": "FB01-071_PARA"})
    assert got == {"158452539"}


def test_changed_answer_is_released():
    """catalog/resolver が変わって **答えが変わった**なら、もう一度聞く."""
    B = _load_batch()
    skips = {"111": {"at": "2026-08-09T19:24:55", "choice": "NONE", "pid": "OLD-001"}}
    assert B.already_rejected_same_answer(skips, ["111"], resolved_pids={"111": "NEW-002"}) == set()


def test_legacy_entry_without_pid_keeps_self_healing():
    """旧形式 (pid 無し) は歯止めを効かせない = 従来どおり自己修復する (永久 hide に倒さない)."""
    B = _load_batch()
    skips = {"111": {"at": "2026-08-09T19:24:55", "choice": "NONE"}}
    assert B.already_rejected_same_answer(skips, ["111"], resolved_pids={"111": "ANY"}) == set()


def test_active_review_skips_keeps_rejected_same_answer():
    """★本丸: cooldown 内 + resolver は引ける + 同じ答え → **スキップし続ける**.

    この歯止めが無いと、NONE を押した翌日にまた同じ問いが出る (実測4件)。
    """
    B = _load_batch()
    skips = {"138056958": {"at": "2026-08-09T19:24:55", "choice": "NONE", "pid": "BDK-006"}}
    got = B.active_review_skips(skips, NOW, resolvable={"138056958"},
                                out_of_scope=set(), resolved_pids={"138056958": "BDK-006"})
    assert got == {"138056958"}


def test_active_review_skips_still_releases_when_answer_changed():
    """答えが変わった時の自己修復 (2026-08-09 に入れた 29件解除) は壊さない."""
    B = _load_batch()
    skips = {"153420191": {"at": "2026-08-09T19:24:55", "choice": "NONE", "pid": ""}}
    got = B.active_review_skips(skips, NOW, resolvable={"153420191"},
                                out_of_scope=set(), resolved_pids={"153420191": "OP09-051"})
    assert got == set()


def test_resolved_pids_now_is_fail_closed_on_empty():
    B = _load_batch()
    assert B.resolved_pids_now([]) == {}
    assert B.resolved_pids_now(None) == {}


# ------------------------------------------------------------------ 台帳に「何を断ったか」を残す

def test_record_review_skip_stores_rejected_pid(tmp_path):
    """NONE を記録する時、**見せて断られた product_id** を残す (歯止めの入力)."""
    R = _load_review()
    R.REVIEW_SKIP_FILE = tmp_path / "skip.json"
    R._record_review_skip([{"cert": "158452539", "choice": "NONE", "expected": "FB01-071_PARA"}])
    d = json.loads(R.REVIEW_SKIP_FILE.read_text(encoding="utf-8"))
    assert d["158452539"]["pid"] == "FB01-071_PARA"
    assert d["158452539"]["choice"] == "NONE"


def test_record_review_skip_ok_is_not_recorded(tmp_path):
    """OK/CHOSEN は skip 台帳に入れない (verified_certs 側の担当)."""
    R = _load_review()
    R.REVIEW_SKIP_FILE = tmp_path / "skip.json"
    R._record_review_skip([{"cert": "111", "choice": "OK", "expected": "X-1"}])
    assert not R.REVIEW_SKIP_FILE.exists()


# ------------------------------------------------------------------ ②-1 viewer が両面を描く

def _render(tmp_path, target):
    R = _load_review()
    R.HTML_OUTPUT = tmp_path / "out.html"
    R._generate_html([target])
    return R.HTML_OUTPUT.read_text(encoding="utf-8")


def test_html_shows_both_psa_faces(tmp_path):
    """★PSA の **裏写真** を出す。両面カードではこちらが catalog の絵と一致する."""
    html = _render(tmp_path, {
        "cert": "158452539", "brand": "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE",
        "subject": "SON GOHAN : CHILDHOOD ALTERNATE ART", "card_number": "FB01-071",
        "category": "dragonball_scg", "set_code": None, "csv_expected": "FB01-071_PARA",
        "cert_image_url": "https://cdn/x/front.jpg",
        "cert_image_url_back": "https://cdn/x/back.jpg",
        "candidates": [("FB01-071_PARA",
                        "https://www.dbs-cardgame.com/fw/images/cards/card/jp/FB01-071_f.webp")],
    })
    assert "front.jpg" in html
    assert "back.jpg" in html, "PSA の裏写真が出ていない (= 両面カードを照合できない)"


def test_html_shows_catalog_back_face(tmp_path):
    """catalog は表面しか持っていないので、裏面 URL を導いて並べる."""
    html = _render(tmp_path, {
        "cert": "158452540", "brand": "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE",
        "subject": "SHENRON ALTERNATE ART", "card_number": "FB07-097",
        "category": "dragonball_scg", "set_code": None, "csv_expected": "FB07-097_p1",
        "cert_image_url": "https://cdn/x/front.jpg", "cert_image_url_back": "",
        "candidates": [("FB07-097_p1",
                        "https://www.dbs-cardgame.com/fw/images/cards/card/jp/FB07-097_f_p1.webp")],
    })
    assert "FB07-097_b_p1.webp" in html.replace("%2F", "/").replace("%3A", ":"), \
        "catalog 候補の裏面が出ていない (= AWAKEN 面の写真と見比べられない)"


def test_html_says_why_when_catalog_has_no_image(tmp_path):
    """画像0件の候補は「照合不能」と理由を出す。'no image' だけだと毎回 NONE を押させる."""
    html = _render(tmp_path, {
        "cert": "140936782", "brand": "POKEMON JAPANESE SUN & MOON TAG TEAM GX ALL STARS",
        "subject": "FA/JIRACHI GX-HYPER", "card_number": "214",
        "category": "pokemon_tcg", "set_code": "SM12a", "csv_expected": "SM12a-214",
        "cert_image_url": "https://cdn/x/front.jpg", "cert_image_url_back": "",
        "candidates": [("SM12a-214", "")],
    })
    assert "照合不能" in html and "catalog 未収録" in html


# ------------------------------------------------------------------ ログで答えを落とさない

class _Cp932Stdout:
    """cp932 コンソールの再現: 絵文字を書こうとすると落ちる."""
    encoding = "cp932"

    def __init__(self):
        self.written = []

    def write(self, s):
        s.encode("cp932")            # 絵文字なら UnicodeEncodeError
        self.written.append(s)

    def flush(self):
        pass


def test_safe_stdout_survives_unencodable_log():
    """catalog の `🎯 hit` ログで **答えごと落ちない**.

    2026-08-09 実測: cp932 コンソールでは lookup_dragonball が hit した直後の print で
    UnicodeEncodeError になり、`_catalog_lookup_expected` の except に吸われて
    expected=None になっていた (= 引けているのに『期待値特定不能』と表示していた)。
    """
    R = _load_review()
    base = _Cp932Stdout()
    safe = R._SafeStdout(base)
    safe.write("    \U0001f3af iMakCatalog (DBSCG) hit: FB01-071_PARA\n")   # 例外にならない
    safe.write("ふつうの日本語ログ\n")
    assert any("iMakCatalog" in w for w in base.written), "置換して書けていない"
    assert safe.encoding == "cp932"                                        # 属性は素通し


def test_catalog_lookup_restores_stdout():
    """lookup 後に sys.stdout を必ず戻す (例外時も)."""
    R = _load_review()
    before = sys.stdout
    R._catalog_lookup_expected("ONE PIECE", "SABO", "049", "one_piece_tcg")
    assert sys.stdout is before
    R._catalog_lookup_expected("X", "Y", "1", "")          # 早期 return 経路
    assert sys.stdout is before


# ------------------------------------------------------------------ 候補を絞る (2026-08-10)

def _make_dbscg_db(tmp_path):
    """dragonball の実データ縮小版: 同一キャラ (Shenron) が別番号にも居る."""
    import sqlite3
    db = tmp_path / "cat.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE products (category TEXT, product_id TEXT, name_en TEXT, images TEXT)")
    rows = [("dragonball_scg", "FB07-097", "Shenron", '["http://x/a.png"]'),
            ("dragonball_scg", "FB07-097_p1", "Shenron", '["http://x/b.png"]'),
            ("dragonball_scg", "FB07-097_PARA_dummy_s1", "Shenron", '["http://x/c.png"]')]
    # 同じキャラだが別番号 = broad 検索だと混ざってくる側
    rows += [("dragonball_scg", f"FB07-{n:03d}", "Shenron", '["http://x/z.png"]') for n in range(1, 40)]
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)", rows)
    conn.commit(); conn.close()
    return db


def test_card_number_with_set_prefix_pinpoints(tmp_path):
    """★PSA の CardNumber がセット込み ('FB07-097') でも番号一致が効く.

    2026-08-10 実測: `%-FB07-097` は product_id が 'FB07-097...' なので**絶対に当たらず**、
    dragonball は毎回 broad 検索に落ちて関係ないカードが40件並んでいた
    (cert158452540=50件 / cert158452539=40件)。人は選べず「該当なし」を押すしかない。
    """
    R = _load_review()
    R.CATALOG_DB = _make_dbscg_db(tmp_path)
    cands = [p for p, _ in R._get_candidates(
        "dragonball_scg", None, "FB07-097", brand="DRAGON BALL SUPER CARD GAME JAPANESE",
        expected_product_id="FB07-097_p1", subject="SHENRON ALTERNATE ART")]
    assert cands, "候補が空"
    # ★2026-08-19: 番号一致が当たっても **同じキャラの別セット/別promo も候補に足す**
    #   ようにした (cert168157629 チョッパーで、同じカードの変種3件しか出ず人が選べなかった)。
    #   よって「全部 FB07-097」ではなくなる。守るのは
    #     (a) 本命 (番号一致) が先頭に来る  (b) 人が選べる件数に収まる
    #   の2つ。関係ないカードが並ぶ問題は「同じキャラだけ」で担保する。
    assert cands[0].startswith("FB07-097"), f"本命が先頭でない: {cands}"
    assert len(cands) <= 12, f"候補が多すぎる: {len(cands)}件"


def test_bare_card_number_still_pinpoints(tmp_path):
    """One Piece / Pokemon の裸番号 ('049') 側は従来どおり効く (両方の形を受ける)."""
    R = _load_review()
    R.CATALOG_DB = _make_db_op(tmp_path)
    cands = [p for p, _ in R._get_candidates(
        "one_piece_tcg", None, "049", brand="ONE PIECE",
        expected_product_id=None, subject="Sabo")]
    assert cands[0] == "OP10-049", f"番号 pinpoint が壊れた: {cands[:5]}"


def _make_db_op(tmp_path):
    import sqlite3
    db = tmp_path / "op.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE products (category TEXT, product_id TEXT, name_en TEXT, images TEXT)")
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)", [
        ("one_piece_tcg", "OP10-049", "Sabo", '["http://x/1.png"]'),
        ("one_piece_tcg", "OP03-001", "Sabo", '["http://x/2.png"]'),
        ("one_piece_tcg", "OP01-001", "Monkey.D.Luffy", '["http://x/3.png"]'),
    ])
    conn.commit(); conn.close()
    return db


def test_rescue_window_is_capped_but_not_removed(tmp_path):
    """expected 解決済でも救済窓は残す。ただし 40件は足さない.

    救済の目的は 2026-06-26 の Boa Hancock PRB01 (auto-pick が別 base の正解変種を外す) なので
    窓自体は要る。窓を 0 にすると別の取りこぼしが復活する。
    """
    R = _load_review()
    R.CATALOG_DB = _make_dbscg_db(tmp_path)
    assert 0 < R._CHAR_RESCUE_LIMIT < 40
    # 番号一致が取れない subject では broad に落ちるが、窓の上限で止まる
    cands = [p for p, _ in R._get_candidates(
        "dragonball_scg", None, "", brand="DRAGON BALL SUPER CARD GAME JAPANESE",
        expected_product_id="FB07-097_p1", subject="SHENRON ALTERNATE ART")]
    assert len(cands) <= 3 + R._CHAR_RESCUE_LIMIT, f"救済窓が効いていない: {len(cands)}件"
    assert any(c.startswith("FB07-097") for c in cands)
