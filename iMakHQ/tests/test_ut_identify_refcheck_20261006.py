"""UT 目視: 参考URLをその場で調べて 可/否 を返す / カタログ化を見送る (2026-10-06)。

ユーザー「参考URLを入れたら、すぐ調べて可否を返してほしい。否なら別のURLを探す。
可になるまでやるか、カタログ化をいったん見送るか。このフローにして」
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ut_identify as U  # noqa: E402


def test_ref_page_facts_finds_pid_and_photos():
    html = ("<meta property='og:image' content='https://www.fashion-press.net/img/news/63094/a.jpg'>"
            "<img src='/img/news/63094/b.jpg'><img src='/common/logo.png'><p>品番 E440690-000</p>")
    f = U.ref_page_facts("https://www.fashion-press.net/news/63094", html, ["E440690-000"])
    assert f["pid"] == "E440690-000" and f["in_catalog"]
    assert f["images"] == ["https://www.fashion-press.net/img/news/63094/a.jpg",
                           "https://www.fashion-press.net/img/news/63094/b.jpg"]           # ロゴは外す


def test_pid_from_uniqlo_url():
    f = U.ref_page_facts("https://www.uniqlo.com/jp/ja/products/E425620-000/00", "")
    assert f["pid"] == "E425620-000" and not f["in_catalog"]


def test_bad_url_is_ng():
    assert U.check_ref_url("abc")["verdict"] == "ng"


def test_skip_reason_and_imgs_pass_through():
    assert ("nocat_skip", "カタログ化を見送り (参考URLが見つからない)") in U.OUT_REASONS
    res = U.parse_result({"nocat": [5], "nocat_info": {"5": {"ref": "https://x/a", "checked": "ok",
                                                              "imgs": ["https://x/1.jpg", "javascript:x"]}}})
    assert res["nocat_info"][5] == {"work": "", "ref": "https://x/a", "imgs": ["https://x/1.jpg"], "checked": "ok"}
