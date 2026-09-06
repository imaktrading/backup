@echo off
REM ---------------------------------------------------------------------------
REM Nightly stock of aux-supply-URL candidates (slice2 search only).
REM
REM ASCII ONLY. Do not write Japanese in this file.
REM   2026-07-30: this batch was saved as UTF-8 with Japanese comments. cmd.exe
REM   reads .bat with the OEM codepage (932), so the comments turned into mojibake
REM   and were parsed as commands ("'do' is not recognized ..."). The for-loop was
REM   destroyed, nothing ran, no log was written, and the task still reported
REM   exit code 0 = "success". It had never run since it was created on 07-28.
REM   Keeping this file ASCII-only makes it codepage-independent.
REM
REM What it does (step 0 writes the KEY column; the rest only caches candidates):
REM   0) fill blank canonical KEY  : key_backfill_live.py
REM   1) zero-backup listings first  : search --limit=30
REM   2) top-up (1 backup)           : search --max-backups=2 --limit=10
REM   3) restock prefetch            : search-restock --limit=0 (all)
REM   3b) restock stock re-check     : psa_resource_gate.py --nightly (ledger only)
REM   3c) spare supply from newcand   : psa_hoju_fill.py newcand-aux
REM   4) ichibankuji prefetch        : ichibankuji_restock.py prefetch 10
REM   5) ichibankuji live aux        : ichibankuji_restock.py prefetch-live 10
REM   5c) UT aux-supply              : ut_hoju_fill.py search (all)
REM   5d) UT restock                 : ut_hoju_fill.py restock-search (all)
REM   6c) funnel + analyses           : listing_funnel / funnel_diff / demand_winners
REM   6d) ichibankuji night search     : run_kuji_night.py
REM   6e) price-down / title lists     : noconvert_pricedown / noclick_targets
REM   NOTE: nothing here writes to eBay. Ending, relisting and restoring quantity
REM         stay manual buttons on purpose (they are not reversible).
REM   30 items per run = slow and steady, to keep the BAN risk low.
REM   Google Sheets API can return 503, so step 1 retries up to 3 times.
REM ---------------------------------------------------------------------------
setlocal
set PYTHONIOENCODING=utf-8
cd /d C:\dev\iMak\iMakHQ\tools

REM Build YYYY-MM-DD from %date% (e.g. 2026/07/30). Fall back to "unknown" if the
REM locale format is unexpected, so the log path is always valid.
set TODAY=unknown
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set TODAY=%%a-%%b-%%c
set LOG=C:\dev\iMak\iMakHQ\review_logs\hoju_search_cron_%TODAY%.log
if not exist C:\dev\iMak\iMakHQ\review_logs mkdir C:\dev\iMak\iMakHQ\review_logs

echo [start] %date% %time% >> "%LOG%"

REM --- 0) fill the canonical KEY of live listings that are still blank.
REM        2026-08-16: KEY was only filled for rows in that day's CSV, so a row
REM        missed at listing time stayed blank forever. A blank KEY makes the
REM        aux-URL search skip the row ("no card number") and disables the
REM        duplicate check. The value comes from the cert (already confirmed by
REM        a human at listing time), so no review is needed. fail-closed: it
REM        writes nothing when the cert cannot be resolved.
echo [keyfill] %date% %time% >> "%LOG%"
python -u key_backfill_live.py >> "%LOG%" 2>&1

REM --- 1) zero-backup listings (a listing whose only supplier died = instant death)
for %%i in (1 2 3) do (
    echo [try %%i] zero-backup %date% %time% >> "%LOG%"
    python -u psa_hoju_fill.py search --limit=30 >> "%LOG%" 2>&1
    if not errorlevel 1 goto :topup
    echo [try %%i] failed, retry in 120s >> "%LOG%"
    timeout /t 120 /nobreak > nul
)
echo [warn] zero-backup step failed 3 times >> "%LOG%"
goto :done

:topup
REM --- 2) keep stocking listings that are not yet full (fewer than 5 backups).
REM        2026-09-06: this step used --max-backups=2 --limit=10, so the night
REM        only ever refreshed 40 listings (30 zero-backup + 10 one-backup) while
REM        the daytime review screen covers every listing below 5 backups (398).
REM        The review screen only accepts a cache entry that is 3 days old or
REM        less, so 325 of those 398 were permanently stuck as "not searched yet"
REM        and never appeared no matter how often the button was pressed.
REM        398 / 3 days = ~133 per night. Measured rate is ~2.2 items/min, so this
REM        adds roughly an hour; the night still ends well before the morning.
REM        Do NOT narrow the daytime threshold instead: listings with 1-4 backups
REM        must reach the screen or the cheaper-supplier swap never fires (2026-09-05).
echo [topup] max-backups=5 %date% %time% >> "%LOG%"
python -u psa_hoju_fill.py search --max-backups=5 --limit=130 >> "%LOG%" 2>&1

REM --- 3) prefetch for the RESTOCK gate (shares psa_research_cache, makes the
REM        button answer instantly and cuts re-scraping)
echo [restock] prefetch %date% %time% >> "%LOG%"
python -u psa_hoju_fill.py search-restock --limit=0 >> "%LOG%" 2>&1

REM --- 3b) PSA restock: re-check whether supply came back, for listings whose variant
REM         was already confirmed by eye, and update the waiting ledger.
REM         2026-09-05: the ledger only moved when the daytime button was pressed, so a
REM         listing whose supplier came back stayed "waiting" until someone noticed it.
REM         --nightly opens no browser, writes no catalog request and no RESTOCK
REM         confirmation; it only re-checks stock and updates the ledger.
REM         Unconfirmed variants are left alone (a wrong variant must not be revived).
echo [restock-recheck] %date% %time% >> "%LOG%"
set RESTOCK_TARGET_NEW=0
python -u psa_resource_gate.py --nightly >> "%LOG%" 2>&1
set RESTOCK_TARGET_NEW=

REM --- 3c) move the spare supply URLs that a human already identified (the tab
REM         "new listing candidates", rows marked as aux use) into the aux columns
REM         of the matching listing. 2026-09-05: those rows had no destination at
REM         all, so 163 of them were sitting unused while 45 listings had no spare
REM         supplier at all. The card is already confirmed by a human, so no new
REM         judgement is needed here.
echo [newcand-aux] %date% %time% >> "%LOG%"
python -u psa_hoju_fill.py newcand-aux >> "%LOG%" 2>&1

REM --- 4) prefetch for ichibankuji aux URLs (candidates only, no UI, no sheet)
echo [ichibankuji] prefetch %date% %time% >> "%LOG%"
python -u ichibankuji_restock.py prefetch 10 >> "%LOG%" 2>&1

REM --- 5) prefetch for ichibankuji LIVE listings that are thin on aux URLs
REM        2026-08-16: step 4 fills out-of-stock rows first and there are ~50 of
REM        them, so live listings never got a slot. Aux URLs are insurance and
REM        must be stocked BEFORE the supplier dies, so give live its own step.
echo [ichibankuji] prefetch-live %date% %time% >> "%LOG%"
python -u ichibankuji_restock.py prefetch-live 10 >> "%LOG%" 2>&1

REM --- 5b) pre-open the candidate detail pages (condition / shipping / seller
REM         reviews). 2026-08-16: this was most of the 22 minutes the ichibankuji
REM         restock button took (9 items x 10 candidates, 3s wait each). Those
REM         fields never change, so cache them here and the button only shows.
echo [ichibankuji] prefetch-detail %date% %time% >> "%LOG%"
python -u ichibankuji_restock.py prefetch-detail 120 >> "%LOG%" 2>&1

REM --- 5c) UT (Uniqlo/GU collab tee) aux-supply candidates. Collect only; the
REM         sheet is written after a human check in the daytime.
REM         2026-09-03: the tee line stalled because the single supplier sold out
REM         and the listing work was wasted. Same fix as PSA: keep spares.
echo [ut] hoju search %date% %time% >> "%LOG%"
python -u ut_hoju_fill.py search >> "%LOG%" 2>&1

REM --- 5d) UT restock: sold-out tees are still Active with qty 0 (verified
REM         2026-09-03), so finding a live supplier is enough to bring them back.
echo [ut] restock search %date% %time% >> "%LOG%"
python -u ut_hoju_fill.py restock-search >> "%LOG%" 2>&1

REM --- 6) warm the daytime review screen (candidates -> ref image -> art match).
REM        2026-08-16: pressing the daytime button spent ~7 of its 8 minutes
REM        assembling the screen (fetch the listing image and AI-compare the art
REM        for every target), and only ~10 rows survived. None of that needs a
REM        human, so do it here. --dry-run does the same assembly but opens no
REM        browser and writes nothing; both caches (listing image / art match)
REM        are on disk, so the daytime run is then near-instant.
echo [confirm-warm] %date% %time% >> "%LOG%"
python -u psa_hoju_fill.py confirm --dry-run >> "%LOG%" 2>&1

REM --- 6b) mark which unlisted rows can actually be listed (AP column), so the
REM         master sheet stops looking like "plenty of candidates left".
REM         2026-08-17: of 58 rows with a blank itemID and not sold out, only 13
REM         could ever be listed; the other 45 are a second copy of a card that
REM         is already live. The blank itemID read as "candidate", so the call
REM         "no need to restock yet" was made on a false picture. A grey cell in
REM         the itemID column now means "this row will never become a listing".
echo [listable-flag] %date% %time% >> "%LOG%"
python -u sheet_listable_flag.py --write >> "%LOG%" 2>&1

REM --- 6c) refresh the funnel and the analyses that read it. These only read
REM          reports and write spreadsheet tabs, so they are safe unattended.
REM          2026-09-03: doing this at night means the morning buttons (shelf /
REM          cull / restock counts) already have fresh numbers to work from.
echo [funnel] %date% %time% >> "%LOG%"
python -u listing_funnel.py >> "%LOG%" 2>&1
echo [funnel-diff] %date% %time% >> "%LOG%"
python -u funnel_diff.py >> "%LOG%" 2>&1
echo [demand] %date% %time% >> "%LOG%"
python -u demand_winners.py >> "%LOG%" 2>&1
echo [restock-worklist] %date% %time% >> "%LOG%"
python -u restock_worklist.py >> "%LOG%" 2>&1

REM --- 6d) ichibankuji nightly search (was a manual button only; nothing else
REM          ran it, so the daytime press had to do the searching itself).
echo [kuji-night] %date% %time% >> "%LOG%"
python -u run_kuji_night.py >> "%LOG%" 2>&1

REM --- 6e) lists that the daytime buttons only display: price-down candidates
REM          and title-rework candidates. Both write a spreadsheet tab only.
echo [pricedown] %date% %time% >> "%LOG%"
python -u noconvert_pricedown.py >> "%LOG%" 2>&1
echo [title-rework] %date% %time% >> "%LOG%"
python -u noclick_targets.py >> "%LOG%" 2>&1

REM --- 7) write the "no backup URL at all" listings into one tab so they can be
REM        seen at a glance (they are scattered rows in the master sheet).
REM        Writes only that tab; never touches the master sheet.
echo [naked-list] %date% %time% >> "%LOG%"
python -u hoju_naked_sheet.py >> "%LOG%" 2>&1

:done
echo [end] %date% %time% >> "%LOG%"
endlocal
