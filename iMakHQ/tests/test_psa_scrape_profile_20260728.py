"""PSA 供給検索に専用 Chrome プロファイルを与えた回帰テスト (2026-07-28).

従来 PSA 側だけ --user-data-dir 指定なし = 毎回まっさらな一時 profile で、
「初回訪問の匿名 headless」として最も弾かれやすかった (一番くじ側は専用profileで保温済)。
ジョブごとに別ディレクトリにすることで、同時実行してもプロファイルロックが競合しない。

固定したいのは:
  1. 専用 profile を使うこと / ディレクトリがジョブ間で衝突しないこと
  2. **ログインしない** 方針 (仕入アカBAN→仕入不能を避ける)
  3. profile で起動できない時に一時 profile へ落ちて走行を止めないこと (fail-safe)
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import ichibankuji_restock as I  # noqa: E402
import mercari_psa_resource as mp  # noqa: E402


def test_dedicated_profile_dir_is_defined():
    assert mp.PSA_SCRAPE_PROFILE_DIR
    assert "psa_mercari_scrape_profile" in mp.PSA_SCRAPE_PROFILE_DIR


def test_profile_dirs_do_not_collide_between_jobs():
    """一番くじと PSA が同じディレクトリを使うと、同時実行でロック競合して起動不能になる。"""
    assert os.path.normcase(mp.PSA_SCRAPE_PROFILE_DIR) != os.path.normcase(I.MERCARI_PROFILE_DIR)


def test_driver_uses_profile_and_falls_back():
    src = inspect.getsource(mp.fetch_mercari_cheapest)
    assert "--user-data-dir=" in src
    assert "PSA_SCRAPE_PROFILE_DIR" in src
    assert "mkdtemp" in src          # 起動できない時の fallback


def test_no_login_in_scrape_path():
    """仕入アカウントにログインしない (BAN=仕入不能に直結)。"""
    src = inspect.getsource(mp.fetch_mercari_cheapest)
    for ng in ("login", "password", "signin"):
        assert ng not in src.lower()
