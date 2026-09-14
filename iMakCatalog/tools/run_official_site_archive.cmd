@echo off
rem Official site raw archive (catalog). ASCII only: a UTF-8 Japanese REM broke cmd parsing
rem on 2026-08-24, the cd line was skipped and python ran in System32 (exit 2).
cd /d C:\dev\iMak_catalog\iMakCatalog
set PYTHONIOENCODING=utf-8
python C:\dev\iMak_catalog\iMakCatalog\scrapers\official_site_raw_archive.py --all >> C:\dev\iMak_data\catalog\_raw\_archive_run.log 2>&1
