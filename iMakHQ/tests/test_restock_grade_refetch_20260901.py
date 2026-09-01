# -*- coding: utf-8 -*-
"""再出品くん (RESTOCK fork) の グレード取り直し 回帰テスト (2026-09-01)。

実害: 2026-09-01 の ♻ 走行は 16件中 **15件**が
`🚫 グレードを確かめられなかった → 再出品しない` で落ち、CSV が1行になった。

原因: 8/31 に PSA10 ゲートを入れたが、この fork の `get_psa_data` は
**Subject さえ在れば保存分をそのまま返す**ため、グレードを保存していない古い cert
(実測 1,358件中 1,143件 = 84%) は永久にグレードが空 → 全部 fail-closed で落ちる。
新規側 psa_to_csv は 2026-08-23 に「Grade が無い保存分は取り直す」を入れており、
**fork にだけ入っていなかった** (値付けの $100 と同じ、fork 置き去りの形)。

規約は変えない: PSA10 だけ出品する / 確かめられなければ出さない。
変えるのは「一次情報を取りに行かずに諦めていた」ところだけ。
"""
import io
import os

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_FORK = os.path.join(_ROOT, "iMakTCG", "psa_restock_csv.py")
_MAIN = os.path.join(_ROOT, "iMakTCG", "psa_to_csv.py")


def _src(p):
    return io.open(p, encoding="utf-8").read()


def _fn(src, name):
    i = src.index("def " + name)
    j = src.find(chr(10) + "def ", i + 10)
    return src[i:j if j > 0 else len(src)]


def test_cached_cert_without_grade_is_refetched():
    body = _fn(_src(_FORK), "get_psa_data")
    assert "'Grade' not in cached" in body, (
        "グレードが無い保存分を取り直していない (= PSA10ゲートが永久に落とし続ける)")
    i = body.index("'Grade' not in cached")
    assert "return cached" not in body[:i], "早期 return が取り直しより先に在る"


def test_grade_key_is_always_stored_after_a_fetch():
    """取り直しても読めなかった時に毎回 PSA を叩かない (キーだけは置く)。"""
    body = _fn(_src(_FORK), "get_psa_data")
    assert "data.setdefault('Grade', '')" in body
    assert body.index("data.setdefault('Grade', '')") < body.index("cache[cert_number] = data"), (
        "キャッシュ保存より前に置くこと")


def test_gate_itself_is_unchanged():
    """PSA10 だけ出品する規定は緩めていない。"""
    s = _src(_FORK)
    assert "if _grade != '10':" in s, "PSA10 ゲートが消えている"
    assert "return None" in s[s.index("if _grade != '10':"):][:900], "落とす経路が無い"


def test_fork_matches_the_main_generator():
    """fork だけ古い、を二度とやらない。"""
    for p in (_FORK, _MAIN):
        body = _fn(_src(p), "get_psa_data")
        assert "'Grade' not in cached" in body, os.path.basename(p) + " に取り直しが無い"
