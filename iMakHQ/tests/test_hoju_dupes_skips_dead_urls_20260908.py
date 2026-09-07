"""補URL に **書いた時点で死んでいる URL** を入れない (2026-09-08 ユーザーGO).

従来のゲートは候補行の D列 (仕入元 売り切れ) しか見ておらず、この列は
**監視くんの巡回でしか更新されない**。23:30 の書込み時点で古ければ死んだURLが入る。
補URLは「主が売れた時に買う先」なので、死んでいると意味がない。
"""
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import hoju_url_from_dupes as D  # noqa: E402
import mercari_psa_resource as mp  # noqa: E402


def test_known_dead_urls_are_dropped(tmp_path, monkeypatch):
    led = tmp_path / "nb.json"
    led.write_text(json.dumps({"https://a/dead": {"why": "オークション"}}), encoding="utf-8")
    monkeypatch.setattr(mp, "load_not_buyable", lambda path=None: json.loads(
        led.read_text(encoding="utf-8")))
    keep, drop = D.drop_known_dead(["https://a/dead", "https://a/ok"])
    assert keep == ["https://a/ok"]
    assert drop and drop[0][0] == "https://a/dead"


def test_ledger_unreadable_keeps_everything(monkeypatch):
    """台帳が読めない時に供給を捨てない (fail-open)."""
    def _boom(path=None):
        raise OSError("no file")
    monkeypatch.setattr(mp, "load_not_buyable", _boom)
    keep, drop = D.drop_known_dead(["https://a/1"])
    assert keep == ["https://a/1"] and drop == []


def test_verify_alive_fails_open_without_driver(monkeypatch):
    """driver を起こせない時は落とさない (書込み自体は今までどおり)."""
    def _boom():
        raise RuntimeError("no chrome")
    monkeypatch.setattr(mp, "new_scrape_driver", _boom)
    alive, dead = D.verify_alive(["https://a/1"], verbose=False)
    assert alive == ["https://a/1"] and dead == []


def test_verify_alive_empty_input():
    assert D.verify_alive([]) == ([], [])


def test_driver_factory_is_shared():
    """driver の作り方を二重実装しない (profile / version 固定の方針が割れるため)."""
    assert callable(getattr(mp, "new_scrape_driver", None))
    src = (TOOLS / "hoju_url_from_dupes.py").read_text(encoding="utf-8")
    assert "mp.new_scrape_driver()" in src
    assert "uc.Chrome" not in src
