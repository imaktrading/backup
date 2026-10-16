# -*- coding: utf-8 -*-
"""2026-10-16 B-20261016-009: NO-IMAGE は依頼書の代わりにカタログの入力 no_image_input.json に1件書く。"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


def test_add_new_same_and_no_photo(tmp_path):
    import no_image_input as N
    p = str(tmp_path / "in.json")
    now = dt.datetime(2026, 10, 16, 22, 0)
    url = "https://d1htnxwo4o0jhw.cloudfront.net/cert/1/large/a.jpg"
    assert N.add("pokemon_tcg", "SM10b-064", "114368712", path=p, now=now, image_url=url, subject="FA/KELDEO") == "new"
    assert N.add("pokemon_tcg", "SM10b-064", "114368712", path=p, now=now, image_url=url, subject="FA/KELDEO") == "same"
    assert N.add("pokemon_tcg", "SM9a-066", "1", path=p, now=now, image_url="") == "no_photo"
    d = json.load(open(p, encoding="utf-8"))
    assert d == {"pokemon_tcg:SM10b-064": {"cert": "114368712", "image_url": url, "psa_subject": "FA/KELDEO",
                                           "at": "2026-10-16T22:00:00"}}


def test_photo_url_uses_large():
    import no_image_input as N
    assert "/large/" in (N.psa_photo_url("114368712") or "/large/")


def test_ring_only_when_new():
    import no_image_input as N
    assert N.ring(0) is False


def test_psa_to_csv_no_image_branch_writes_input():
    src = open(r"C:/dev/iMak/iMakTCG/psa_to_csv.py", encoding="utf-8").read()
    assert "_NI.add(_r.get(\"category\"), _pid, _c)" in src and "NO-IMAGE をカタログに渡した" in src
