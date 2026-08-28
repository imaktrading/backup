# -*- coding: utf-8 -*-
"""目視枠を「カタログ無し」で食わない (2026-08-11 Advisor 依頼)。

背景: 10件に絞った **後**で GAP/対象外が落ちていたため、入稿が 2〜6件に張り付いていた。
      枠を選ぶ前に psa_preflight.classify で落とす。あわせて枠を 10→15。

ここで固定すること (どれも実害から来ている):
  - GAP / OUT-OF-SCOPE は枠の前で落ちる
  - RESOLVED / REVIEW / INDEX-FAILURE は **残る** (REVIEW は目視で解決しうる = 落とすと機会損失)
  - ★判定不能 (PSA cache 無し / classify が例外) は **落とさない**。
    「読めなかった」を「対象外」に倒すと、静かに出品機会を失う (fail-OPEN と逆向きの事故)
  - PSA_BATCH_LIMIT が 15 であること (無駄玉を先に落とした後だから上げられる)
"""
import os
import re

PSA = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG", "psa_to_csv.py"))
SRC = open(PSA, encoding="utf-8").read()


def _prefilter(certs, status_of, cache_has=None, raise_on=()):
    """psa_to_csv の前置きフィルタと同じ規則 (純関数として再現)。

    status_of: cert -> status / cache_has: cert -> bool / raise_on: classify が飛ぶ cert
    """
    drop, kept, unknown = [], [], 0
    for c in certs:
        if cache_has is not None and not cache_has(c):
            kept.append(c); unknown += 1; continue
        if c in raise_on:
            kept.append(c); unknown += 1; continue
        if status_of(c) in ("GAP", "OUT-OF-SCOPE"):
            drop.append(c)
        else:
            kept.append(c)
    return kept, drop, unknown


def test_gap_and_out_of_scope_are_dropped_before_the_batch():
    st = {"a": "RESOLVED", "b": "GAP", "c": "OUT-OF-SCOPE", "d": "REVIEW"}
    kept, drop, _ = _prefilter(list(st), st.get)
    assert kept == ["a", "d"]
    assert drop == ["b", "c"]


def test_review_and_index_failure_survive():
    """REVIEW は目視で解決しうる。落とすと出品機会を失う。"""
    st = {"a": "REVIEW", "b": "INDEX-FAILURE", "c": "AMBIGUOUS", "d": "CATEGORY-UNKNOWN"}
    kept, drop, _ = _prefilter(list(st), st.get)
    assert kept == list(st) and drop == []


def test_missing_cache_is_kept_not_dropped():
    """PSA cache が無い = 判定不能。落とさず残す (機会損失を作らない)。"""
    kept, drop, unknown = _prefilter(["a", "b"], lambda c: "GAP",
                                     cache_has=lambda c: c != "b")
    assert "b" in kept and unknown == 1
    assert drop == ["a"]


def test_classify_exception_is_kept_not_dropped():
    kept, drop, unknown = _prefilter(["a", "b"], lambda c: "GAP",
                                     cache_has=lambda c: True, raise_on=("b",))
    assert "b" in kept and unknown == 1


def test_empty_input_is_safe():
    assert _prefilter([], lambda c: "GAP") == ([], [], 0)


# ----- 実ファイルに対する固定 -----

def test_batch_limit_is_15():
    m = re.search(r"PSA_BATCH_LIMIT\s*=\s*(\d+)", SRC)
    assert m and m.group(1) == "15", "枠は 15 (無駄玉を先に落とした後だから上げられる)"


def test_prefilter_runs_before_batch_limit():
    """前置きが **PSA_BATCH_LIMIT の前** にあること。後ろだと枠を食う元の不具合に戻る。"""
    i_pf = SRC.find("import psa_preflight as _pf")
    i_lim = SRC.find("PSA_BATCH_LIMIT = 15")
    assert i_pf > 0 and i_lim > 0 and i_pf < i_lim


def test_prefilter_failure_does_not_stop_the_run():
    """preflight が落ちても生成は続く (出品を止めない)。"""
    assert "preflight 前置き skip (従来動作で継続)" in SRC


def test_only_gap_and_out_of_scope_are_dropped_in_source():
    assert '("GAP", "OUT-OF-SCOPE")' in SRC


# ----- NO-IMAGE (2026-08-11 追加: 出る数を増やすための本命) -----

def test_no_image_is_dropped_before_the_batch():
    """catalog に画像が無いカードは目視で照合できず **必ず落ちる**。枠の前で除く。

    2026-08-10 実走: 10件中2件 (SM9a-067 / SM11-112) がこれで脱落し、枠を食っていた。
    """
    assert '"NO-IMAGE"' in SRC
    assert "catalogに画像が無く目視不能" in SRC


def test_no_image_check_only_drops_when_images_are_readable():
    """images が読めなかった時は落とさない (catalog の事実が取れた時だけ判断する)。

    ★2026-08-18: 窓を 400→900字に広げた。落とす所で「catalog へ依頼を積む」処理を
      足したぶん、同じ except 節までの距離が伸びただけ。見ている性質は変えていない。
    """
    i = SRC.find('_drop.setdefault("NO-IMAGE"')
    tail = SRC[i:i + 900]
    assert "except Exception:" in tail and "読めなければ落とさない" in tail


def test_prefilter_drop_set_is_explicit():
    """落とす条件は3つだけ。増やす時はテストも増やす。

    ★2026-08-28: GAP の見出しを「catalog未収録」→「catalog に行が無い(未収録の疑い)」に
      変えた。名前で引いて確かめるまで未収録と断定しないため (提案2)。条件の数は同じ。
    """
    for label in ("catalog に行が無い(未収録の疑い)", "参入しないゲーム",
                  "catalogに画像が無く目視不能"):
        assert label in SRC
    assert "catalog未収録" not in SRC, "断定する言い回しが復活している"


# ----- LIVE-DUP (2026-08-11: 後段で必ず消える分も枠の前で落とす) -----

def test_live_dup_is_dropped_before_the_batch():
    """live に同じカードがある cert は重複くんが CSV から物理除外する = 枠に入れても消える。

    2026-08-10 実走: CSV 7件 → 重複除外 2件。枠を2つ無駄にしていた。
    """
    assert '"LIVE-DUP"' in SRC
    assert "同じカードが既に出品中" in SRC


def test_live_dup_uses_same_canonical_key_as_dedupe():
    """判定は出品側と同じ canonical KEY (dup_guard.group_key)。独自実装しない。"""
    assert "dup_guard as _dg" in SRC
    assert "_dg.group_key(" in SRC
    assert "_dg.live_card_index(" in SRC


def test_live_dup_skipped_when_cache_is_empty():
    """live cache が使えない = 判定不能。除外に倒さない (0件を『重複なし』と誤読しない)。"""
    assert "重複の前置きは skip" in SRC


def test_live_dup_keeps_cert_without_product_id():
    """KEY を作れない cert は残す (判定不能を落とさない)。"""
    i = SRC.find("_r2 = _cls.get(_c)")
    assert i > 0 and "KEY を作れない = 判定不能 → 残す" in SRC[i:i + 300]


def test_live_dup_refreshes_cache_before_judging():
    """★古い cache を live の根拠にしない。

    2026-08-11 実走: prefilter 時点の cache が **24.5時間前**で、重複5件を1件も
    検出できなかった (後段 excluder が拾い、枠が5つ無駄になった)。
    2026-08-09 に excluder 側で直したのと同じ穴。取り直す担当をここにも置く。
    """
    assert "_dg.ensure_fresh_live_cache()" in SRC
    assert "古い cache を live の根拠にしない" in SRC


def test_live_dup_skips_when_refresh_failed():
    """新鮮化に失敗したら判定しない (古い cache で誤除外も見逃しも作らない)。"""
    assert "if _fresh_ok else set()" in SRC
    assert "live cache を新鮮化できず" in SRC
