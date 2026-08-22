@echo off
REM 公式サイト由来の生データ保管 (夜間・1回きり)。2026-08-23 登録。
cd /d C:\dev\iMak_catalog\iMakCatalog
set PYTHONIOENCODING=utf-8
python scrapers\official_site_raw_archive.py --all >> C:\dev\iMak_data\catalog\_raw\_archive_run.log 2>&1
