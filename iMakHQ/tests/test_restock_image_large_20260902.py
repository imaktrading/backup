# -*- coding: utf-8 -*-
"""再出品くんの PSA 画像が /small/ (380px) のまま出ていた (2026-09-02)。

実害: 2026-09-02 の ♻ が出した16件すべてに
`PSA 画像 2枚が /small/ (380px) のまま = eBay のズームが効かない` が付いた。
eBay のズームは1600px以上が要るので、380pxではスラブの状態が見えない。
高額カードほど購入判断されにくい ($467 Sabo / $406 Newgate 等が該当した)。

原因: 新規側 psa_to_csv は 2026-08-21 から /large/ に上げているが、
**この fork に入っていなかった**。今日3件目の「本家に入った修正が fork に無い」
(1件目=相場停止→cost-plus / 2件目=グレード取り直し)。

対策: fork に同じ処理を書かず、**本家の関数に委譲する**。本家が直れば fork も直る。
"""
import io
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_FORK = os.path.join(_ROOT, "iMakTCG", "psa_restock_csv.py")
_MAIN = os.path.join(_ROOT, "iMakTCG", "psa_to_csv.py")


def _src(p):
    return io.open(p, encoding="utf-8").read()


def test_fork_upgrades_images():
    """キャッシュから返す時も、取り直した時も /large/ に上げること。"""
    s = _src(_FORK)
    assert "def _upgrade_images" in s, "画像を上げる経路が無い"
    body = s[s.index("def get_psa_data"):]
    assert body.count("_upgrade_images(cert_number") >= 2, (
        "キャッシュ経路と scrape 経路の両方で上げること (片方だけだと保存済 cert が素通り)")


def test_fork_delegates_to_main_not_duplicates():
    """fork に同じ判定を書かない。本家が直れば fork も直る形にしておく。"""
    s = _src(_FORK)
    i = s.index("def _upgrade_images")
    body = s[i:s.index(chr(10) + "def ", i + 10)]
    assert "from psa_to_csv import _upgrade_cached_images" in body, "本家に委譲していない"
    assert 'replace("/small/"' not in body, (
        "URL の書き換えを fork に写してはいけない (二重実装)。説明で触れるのは可")


def test_upgrade_never_stops_the_run():
    """画像を上げられなくても出品は続ける (380pxでも出せる。止める方が損)。"""
    s = _src(_FORK)
    i = s.index("def _upgrade_images")
    body = s[i:s.index(chr(10) + "def ", i + 10)]
    assert "except Exception" in body and "return data" in body


def test_main_still_owns_the_rule():
    """判断は本家が持っていること (存在しない /large/ に差し替えない、を含む)。"""
    s = _src(_MAIN)
    assert "def psa_large_variant" in s and "def upgrade_psa_images" in s
    assert "def _upgrade_cached_images" in s, "fork が呼ぶ関数が本家に無い"
    i = s.index("def upgrade_psa_images")
    body = s[i:s.index(chr(10) + "def ", i + 10)]
    assert "exists" in body, "実在確認なしで差し替えてはいけない (404をPicURLに載せる)"
