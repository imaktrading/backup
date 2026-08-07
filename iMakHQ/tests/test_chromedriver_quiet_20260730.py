"""chromedriver の黒窓抑止 (2026-07-30 ユーザー指摘).

headless で回していても **chromedriver 自身のコンソール窓**が出る
(実測: 05:30 / 05:58 の `undetected_chromedriver.exe --port=...`)。
無人 cron 中に画面へ出っぱなしになり、**ユーザーが閉じると子プロセスが道連れで死ぬ**
(dispatch の claude.exe で踏んだのと同じ経路) ため、美観でなく事故防止として塞ぐ。

undetected_chromedriver は ChromiumService を creation_flags 無しで作るので、
既定値を注入する形でパッチする。
"""
import os
import subprocess
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakeBayAPI")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import chrome_util  # noqa: E402


def test_silence_is_idempotent():
    """二重に呼んでも壊れない (再帰パッチで無限ループしないこと)。"""
    assert chrome_util.silence_chromedriver_console() is True
    assert chrome_util.silence_chromedriver_console() is True


def test_service_gets_create_no_window():
    """パッチ後に作られる ChromiumService が CREATE_NO_WINDOW を持つこと。"""
    chrome_util.silence_chromedriver_console()
    from selenium.webdriver.chromium.service import ChromiumService
    svc = ChromiumService("dummy-chromedriver.exe")     # start() しないので実行はされない
    assert svc.creation_flags == subprocess.CREATE_NO_WINDOW


def test_explicit_flag_is_not_overridden():
    """呼び手が明示した creation_flags は尊重する (setdefault であること)。

    ★selenium は `popen_kw` の中から creation_flags を取る。トップレベル kwarg では効かない。
    """
    chrome_util.silence_chromedriver_console()
    from selenium.webdriver.chromium.service import ChromiumService
    svc = ChromiumService("dummy-chromedriver.exe", popen_kw={"creation_flags": 0})
    assert svc.creation_flags == 0


def test_hq_scraper_calls_quiet_before_launching_driver():
    """PSA 供給検索が driver 起動前に抑止を呼ぶこと (配線が外れたら落とす)。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "mercari_psa_resource.py"), encoding="utf-8").read()
    assert "_quiet_chromedriver()  " in src        # 呼び出し (定義ではなく)
    assert src.index("_quiet_chromedriver()  ") < src.index("def _mk(profile_dir)")
