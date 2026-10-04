# -*- coding: utf-8 -*-
"""神風のボタンをさらに KAGOYA へ (2026-10-04 ユーザー「移行できるなら、どんどん移行していってや」)。

- KAGOYA で作った画面 (HTML) は、家に取り込んだ後に家のブラウザで開く (home_open)
- API とシートだけの軽いボタンは小さい席で入る (offload.json の button_seat_gb)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "console"))
import home_open as HO  # noqa: E402
import kagoya_button as KB  # noqa: E402


def test_home_open_prints_mark_on_kagoya(monkeypatch, capsys):
    monkeypatch.setenv("IMAK_NO_BROWSER", "1")
    opened = []
    monkeypatch.setattr(HO.webbrowser, "open", lambda u: opened.append(u))
    HO.open_for_user(r"C:/dev/iMak_data/hq/x.html")
    assert opened == []
    assert HO.targets_in(capsys.readouterr().out.splitlines()) == [r"C:/dev/iMak_data/hq/x.html"]


def test_home_open_opens_at_home(monkeypatch):
    monkeypatch.delenv("IMAK_NO_BROWSER", raising=False)
    opened = []
    monkeypatch.setattr(HO.webbrowser, "open", lambda u: opened.append(u))
    HO.open_for_user("https://docs.google.com/x")
    assert opened == ["https://docs.google.com/x"]


def test_targets_dedup_and_missing_file_not_opened(monkeypatch, tmp_path):
    f = tmp_path / "a.html"
    f.write_text("x", encoding="utf-8")
    lines = [HO.MARK + str(f) + "\n", "ほかの行\n", HO.MARK + str(f) + "\n", HO.MARK + str(tmp_path / "none.html")]
    t = HO.targets_in(lines)
    assert t == [str(f), str(tmp_path / "none.html")]
    opened = []
    monkeypatch.setattr(HO.webbrowser, "open", lambda u: opened.append(u))
    HO.open_targets(t)
    assert len(opened) == 1


def test_seat_size_from_env():
    assert KB.seat_gb_from_envs(["IMAK_SEAT_GB=0.4"], 1.2) == 0.4
    assert KB.seat_gb_from_envs(["X=1"], 1.2) == 1.2
    assert KB.seat_gb_from_envs(["IMAK_SEAT_GB=abc"], 1.2) == 1.2


def test_server_passes_seat_size_for_light_buttons():
    import server as SV
    cfg = {"remote_buttons": ["💰 オファー対応"], "button_seat_gb": {"💰 オファー対応": 0.4}}
    cmd = SV.remote_command({"label": "💰 オファー対応", "cwd": "c:/x", "cmd": ["python", "offer_calc.py"]},
                            ["python", "offer_calc.py"], cfg)
    assert "IMAK_SEAT_GB=0.4" in cmd and cmd[-1] == "offer_calc.py"
    cmd2 = SV.remote_command({"label": "💰 オファー対応", "cwd": "c:/x"}, ["python", "offer_calc.py"],
                             {"remote_buttons": ["💰 オファー対応"]})
    assert not any("IMAK_SEAT_GB" in c for c in cmd2)


def test_html_tools_use_home_open():
    for f in ("offer_calc.py", "market_ledger.py"):
        src = open(os.path.join(HERE, "..", "tools", f), encoding="utf-8").read()
        assert "open_for_user(" in src
