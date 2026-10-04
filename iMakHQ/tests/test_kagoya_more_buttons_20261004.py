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


def test_recent_report_files_only_last_days(tmp_path):
    """Seller Hub のレポートは直近の日付フォルダだけ送る (ファネルを KAGOYA で動かすため・2026-10-04)。"""
    for d in ("20261001", "20261002", "20261003", "資料"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "a.csv").write_text("x", encoding="utf-8")
    got = KB.recent_report_files(str(tmp_path), days=2)
    assert sorted(got) == ["20261002/a.csv", "20261003/a.csv"]


def test_imakmercari_code_is_sent_to_kagoya():
    """iMakMercari の部品 (ut_catalog_values 等) も KAGOYA へ送る (ファネルで ModuleNotFoundError だった)。"""
    import kagoya_offload as K
    files = [f.replace("\\\\", "/") for f in K._code_files()]
    assert any(f.replace("\\\\", "/").endswith("ut_catalog_values.py") for f in files)


def test_validator_keys_are_synced_to_kagoya():
    """出品前の3者合議の鍵を KAGOYA に送る (無いと全件「保留」→ CSV 0件・2026-10-04 モンベル試走)。"""
    assert any(p.endswith("iMakeBayAPI/API key.txt") for p in KB.SYNC_KEYS)
    assert any(p.endswith("gemini_key.txt") for p in KB.SYNC_KEYS)
    assert any(p.endswith("groq_key.txt") for p in KB.SYNC_KEYS)
    assert KB.file_fingerprint(b"abc") == KB.file_fingerprint(b"abc") != KB.file_fingerprint(b"abd")
    assert KB.file_fingerprint(b"") is None


def test_server_matches_category_label_for_seat():
    import server as SV
    cfg = {"remote_buttons": ["Montbell 新規"], "button_seat_gb": {"Montbell 新規": 0.6}}
    cmd = SV.remote_command({"label": "新規", "category": "Montbell", "cwd": "c:/x"},
                            ["python", "montbell_listing.py"], cfg)
    assert "IMAK_SEAT_GB=0.6" in cmd


def test_gacha_review_relays_on_kagoya(monkeypatch, capsys, tmp_path):
    """ガチャの目視画面を KAGOYA で出す時は決まった番号で出し、中継の合図の行を出す (2026-10-04)。"""
    import gacha_review as G
    monkeypatch.setenv("IMAK_NO_BROWSER", "1")
    monkeypatch.setenv("IMAK_REVIEW_PORT", "18799")
    monkeypatch.setattr(G._EVENT, "wait", lambda timeout=None: False)
    G.run_review([{"url": "u1", "title": "t", "photos": []}], open_browser=True, timeout_sec=0,
                 ledger_path=str(tmp_path / "ledger.json"))
    out = capsys.readouterr().out
    assert "ブラウザで確認してください → http://127.0.0.1:18799/" in out
