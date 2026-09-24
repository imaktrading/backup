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
REM   0b) mirror ads 10% + best offer: mirror_promo_bestoffer.py --write
REM   NOTE: the only eBay write here is 0b (adds an ad / turns on best offer on
REM         UK/AU/CA mirrors that lack them; never removes or changes a price).
REM         Ending, relisting and restoring quantity stay manual buttons on
REM         purpose (they are not reversible).
REM   30 items per run = slow and steady, to keep the BAN risk low.
REM   Google Sheets API can return 503, so step 1 retries up to 3 times.
REM   2026-09-24: each step is guarded by night_step.py (--check / --done).
REM   If the PC crashes, the next run (or night_resume.py at logon) skips the
REM   steps already done. Steps that write to eBay or send mail are --no-retry.
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
python -u night_step.py hoju --begin >> "%LOG%" 2>&1

REM --- 0) fill the canonical KEY of live listings that are still blank.
REM        2026-08-16: KEY was only filled for rows in that day's CSV, so a row
REM        missed at listing time stayed blank forever. A blank KEY makes the
REM        aux-URL search skip the row ("no card number") and disables the
REM        duplicate check. The value comes from the cert (already confirmed by
REM        a human at listing time), so no review is needed. fail-closed: it
REM        writes nothing when the cert cannot be resolved.
echo [keyfill] %date% %time% >> "%LOG%"
python -u night_step.py hoju key_backfill_live --check >> "%LOG%" 2>&1 || goto :skip1
python -u key_backfill_live.py >> "%LOG%" 2>&1
python -u night_step.py hoju key_backfill_live --done %errorlevel% >> "%LOG%" 2>&1
:skip1

REM --- 0b) mirror ads + best offer (2026-09-11 user: "make it nightly").
REM         Same as the Pm/Bo button. About 1 minute: one listing sweep, then it
REM         sends only to mirrors that still lack them; listings that can never
REM         get best offer (category, eBay warning 20135) are skipped for 30 days.
REM         Placed before step 1 because step 1 can jump to :done on failure.
echo [pmbo] %date% %time% >> "%LOG%"
python -u night_step.py hoju mirror_promo_bestoffer.--write --check --no-retry >> "%LOG%" 2>&1 || goto :skip2
python -u -X utf8 mirror_promo_bestoffer.py --write >> "%LOG%" 2>&1
python -u night_step.py hoju mirror_promo_bestoffer.--write --done %errorlevel% >> "%LOG%" 2>&1
:skip2

REM --- 0c) write the canonical KEY on UT rows that are already listed.
REM         2026-09-12: the dedupe tool blocks double listings by KEY. UT rows are
REM         identified by eye (ut_identify) but had no KEY, so the same shirt in the
REM         same colour and size could be listed twice. Only rows with an itemID and
REM         a decided colour/size get a KEY (never a row that is not listed yet:
REM         a KEY on an unlisted row reads as "already listed" and blocks it forever).
echo [ut-key] %date% %time% >> "%LOG%"
python -u night_step.py hoju ut_key_backfill.--write --check >> "%LOG%" 2>&1 || goto :skip3
python -u ut_key_backfill.py --write >> "%LOG%" 2>&1
python -u night_step.py hoju ut_key_backfill.--write --done %errorlevel% >> "%LOG%" 2>&1
:skip3

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
python -u night_step.py hoju psa_hoju_fill.search.--max-backups=5.--limit=130 --check >> "%LOG%" 2>&1 || goto :skip4
python -u psa_hoju_fill.py search --max-backups=5 --limit=130 >> "%LOG%" 2>&1
python -u night_step.py hoju psa_hoju_fill.search.--max-backups=5.--limit=130 --done %errorlevel% >> "%LOG%" 2>&1
:skip4

REM --- 3) prefetch for the RESTOCK gate (shares psa_research_cache, makes the
REM        button answer instantly and cuts re-scraping)
echo [restock] prefetch %date% %time% >> "%LOG%"
python -u night_step.py hoju psa_hoju_fill.search-restock.--limit=0 --check >> "%LOG%" 2>&1 || goto :skip5
python -u psa_hoju_fill.py search-restock --limit=0 >> "%LOG%" 2>&1
python -u night_step.py hoju psa_hoju_fill.search-restock.--limit=0 --done %errorlevel% >> "%LOG%" 2>&1
:skip5

REM --- 3a) read the descriptions of mercari candidates whose title has no card number
REM         2026-09-24 user: "some sellers write the number in the description".
REM         Same-name cards with several numbers hide number-less candidates; a number found
REM         in the description shows (same) or drops (other) them. Login-free pages only.
echo [desc-numbers] %date% %time% >> "%LOG%"
python -u night_step.py hoju mercari_desc_numbers --check >> "%LOG%" 2>&1 || goto :skip5a
python -u mercari_desc_numbers.py --limit=200 >> "%LOG%" 2>&1
python -u night_step.py hoju mercari_desc_numbers --done %errorlevel% >> "%LOG%" 2>&1
:skip5a

REM --- 3b) PSA restock: re-check whether supply came back, for listings whose variant
REM         was already confirmed by eye, and update the waiting ledger.
REM         2026-09-05: the ledger only moved when the daytime button was pressed, so a
REM         listing whose supplier came back stayed "waiting" until someone noticed it.
REM         --nightly opens no browser, writes no catalog request and no RESTOCK
REM         confirmation; it only re-checks stock and updates the ledger.
REM         Unconfirmed variants are left alone (a wrong variant must not be revived).
echo [restock-recheck] %date% %time% >> "%LOG%"
REM         2026-09-13: the mercari re-check used the default batch of 10 per night,
REM         so 34-41 cards were carried over EVERY night and "restockable" stayed at
REM         14-16 of 68 for a week (never converged). Raise the nightly batch to 40
REM         (the per-run safety cap in psa_resource_gate is 60, so this stays inside it).
set RESTOCK_TARGET_NEW=0
set RESTOCK_SCRAPE_BATCH=40
python -u night_step.py hoju psa_resource_gate.--nightly --check >> "%LOG%" 2>&1 || goto :skip6
python -u psa_resource_gate.py --nightly >> "%LOG%" 2>&1
python -u night_step.py hoju psa_resource_gate.--nightly --done %errorlevel% >> "%LOG%" 2>&1
:skip6
set RESTOCK_TARGET_NEW=
set RESTOCK_SCRAPE_BATCH=

REM --- 3c) move the spare supply URLs that a human already identified (the tab
REM         "new listing candidates", rows marked as aux use) into the aux columns
REM         of the matching listing. 2026-09-05: those rows had no destination at
REM         all, so 163 of them were sitting unused while 45 listings had no spare
REM         supplier at all. The card is already confirmed by a human, so no new
REM         judgement is needed here.
REM         2026-09-22: first save the other suppliers of cards that are already
REM         decided (no human judgement needed). This used to happen only when the
REM         daytime button was pressed, so the button showed 387 while only 52 needed eyes.
echo [newcand-autoaux] %date% %time% >> "%LOG%"
python -u night_step.py hoju newcand_confirm.--auto-aux-only --check >> "%LOG%" 2>&1 || goto :skip7
python -u newcand_confirm.py --auto-aux-only >> "%LOG%" 2>&1
python -u night_step.py hoju newcand_confirm.--auto-aux-only --done %errorlevel% >> "%LOG%" 2>&1
:skip7
echo [newcand-aux] %date% %time% >> "%LOG%"
python -u night_step.py hoju psa_hoju_fill.newcand-aux --check >> "%LOG%" 2>&1 || goto :skip8
python -u psa_hoju_fill.py newcand-aux >> "%LOG%" 2>&1
python -u night_step.py hoju psa_hoju_fill.newcand-aux --done %errorlevel% >> "%LOG%" 2>&1
:skip8

REM --- 4) prefetch for ichibankuji aux URLs (candidates only, no UI, no sheet)
echo [ichibankuji] prefetch %date% %time% >> "%LOG%"
python -u night_step.py hoju ichibankuji_restock.prefetch.10 --check >> "%LOG%" 2>&1 || goto :skip9
python -u ichibankuji_restock.py prefetch 10 >> "%LOG%" 2>&1
python -u night_step.py hoju ichibankuji_restock.prefetch.10 --done %errorlevel% >> "%LOG%" 2>&1
:skip9

REM --- 5) prefetch for ichibankuji LIVE listings that are thin on aux URLs
REM        2026-08-16: step 4 fills out-of-stock rows first and there are ~50 of
REM        them, so live listings never got a slot. Aux URLs are insurance and
REM        must be stocked BEFORE the supplier dies, so give live its own step.
echo [ichibankuji] prefetch-live %date% %time% >> "%LOG%"
python -u night_step.py hoju ichibankuji_restock.prefetch-live.10 --check >> "%LOG%" 2>&1 || goto :skip10
python -u ichibankuji_restock.py prefetch-live 10 >> "%LOG%" 2>&1
python -u night_step.py hoju ichibankuji_restock.prefetch-live.10 --done %errorlevel% >> "%LOG%" 2>&1
:skip10

REM --- 5b) pre-open the candidate detail pages (condition / shipping / seller
REM         reviews). 2026-08-16: this was most of the 22 minutes the ichibankuji
REM         restock button took (9 items x 10 candidates, 3s wait each). Those
REM         fields never change, so cache them here and the button only shows.
echo [ichibankuji] prefetch-detail %date% %time% >> "%LOG%"
python -u night_step.py hoju ichibankuji_restock.prefetch-detail.120 --check >> "%LOG%" 2>&1 || goto :skip11
python -u ichibankuji_restock.py prefetch-detail 120 >> "%LOG%" 2>&1
python -u night_step.py hoju ichibankuji_restock.prefetch-detail.120 --done %errorlevel% >> "%LOG%" 2>&1
:skip11

REM --- 5c) UT (Uniqlo/GU collab tee) aux-supply candidates. Collect only; the
REM         sheet is written after a human check in the daytime.
REM         2026-09-03: the tee line stalled because the single supplier sold out
REM         and the listing work was wasted. Same fix as PSA: keep spares.
echo [ut] hoju search %date% %time% >> "%LOG%"
python -u night_step.py hoju ut_hoju_fill.search --check >> "%LOG%" 2>&1 || goto :skip12
python -u ut_hoju_fill.py search >> "%LOG%" 2>&1
python -u night_step.py hoju ut_hoju_fill.search --done %errorlevel% >> "%LOG%" 2>&1
:skip12

REM --- 5d) UT restock: sold-out tees are still Active with qty 0 (verified
REM         2026-09-03), so finding a live supplier is enough to bring them back.
echo [ut] restock search %date% %time% >> "%LOG%"
python -u night_step.py hoju ut_hoju_fill.restock-search --check >> "%LOG%" 2>&1 || goto :skip13
python -u ut_hoju_fill.py restock-search >> "%LOG%" 2>&1
python -u night_step.py hoju ut_hoju_fill.restock-search --done %errorlevel% >> "%LOG%" 2>&1
:skip13

REM --- 6) warm the daytime review screen (candidates -> ref image -> art match).
REM        2026-08-16: pressing the daytime button spent ~7 of its 8 minutes
REM        assembling the screen (fetch the listing image and AI-compare the art
REM        for every target), and only ~10 rows survived. None of that needs a
REM        human, so do it here. --dry-run does the same assembly but opens no
REM        browser and writes nothing; both caches (listing image / art match)
REM        are on disk, so the daytime run is then near-instant.
echo [confirm-warm] %date% %time% >> "%LOG%"
python -u night_step.py hoju psa_hoju_fill.confirm.--dry-run --check >> "%LOG%" 2>&1 || goto :skip14
python -u psa_hoju_fill.py confirm --dry-run >> "%LOG%" 2>&1
python -u night_step.py hoju psa_hoju_fill.confirm.--dry-run --done %errorlevel% >> "%LOG%" 2>&1
:skip14

REM --- 6b) mark which unlisted rows can actually be listed (AP column), so the
REM         master sheet stops looking like "plenty of candidates left".
REM         2026-08-17: of 58 rows with a blank itemID and not sold out, only 13
REM         could ever be listed; the other 45 are a second copy of a card that
REM         is already live. The blank itemID read as "candidate", so the call
REM         "no need to restock yet" was made on a false picture. A grey cell in
REM         the itemID column now means "this row will never become a listing".
echo [listable-flag] %date% %time% >> "%LOG%"
python -u night_step.py hoju sheet_listable_flag.--write --check >> "%LOG%" 2>&1 || goto :skip15
python -u sheet_listable_flag.py --write >> "%LOG%" 2>&1
python -u night_step.py hoju sheet_listable_flag.--write --done %errorlevel% >> "%LOG%" 2>&1
:skip15

REM --- 6c) refresh the funnel and the analyses that read it. These only read
REM          reports and write spreadsheet tabs, so they are safe unattended.
REM          2026-09-03: doing this at night means the morning buttons (shelf /
REM          cull / restock counts) already have fresh numbers to work from.
echo [funnel] %date% %time% >> "%LOG%"
python -u night_step.py hoju listing_funnel --check >> "%LOG%" 2>&1 || goto :skip16
python -u listing_funnel.py >> "%LOG%" 2>&1
python -u night_step.py hoju listing_funnel --done %errorlevel% >> "%LOG%" 2>&1
:skip16
echo [funnel-diff] %date% %time% >> "%LOG%"
python -u night_step.py hoju funnel_diff --check >> "%LOG%" 2>&1 || goto :skip17
python -u funnel_diff.py >> "%LOG%" 2>&1
python -u night_step.py hoju funnel_diff --done %errorlevel% >> "%LOG%" 2>&1
:skip17
echo [demand] %date% %time% >> "%LOG%"
python -u night_step.py hoju demand_winners --check >> "%LOG%" 2>&1 || goto :skip18
python -u demand_winners.py >> "%LOG%" 2>&1
python -u night_step.py hoju demand_winners --done %errorlevel% >> "%LOG%" 2>&1
:skip18
echo [restock-worklist] %date% %time% >> "%LOG%"
python -u night_step.py hoju restock_worklist --check >> "%LOG%" 2>&1 || goto :skip19
python -u restock_worklist.py >> "%LOG%" 2>&1
python -u night_step.py hoju restock_worklist --done %errorlevel% >> "%LOG%" 2>&1
:skip19

REM --- 6c1) sold listings: put the quantity back to 1 at today's cost.
REM          2026-09-14: nothing did this automatically. The monitor only revives when
REM          a supplier goes sold -> in stock, so a listing that sold while its supplier
REM          stayed in stock sat at 0 (4 found). Orders come from the order API so this
REM          does not wait for the weekly report download. Skips: unshipped orders,
REM          supplier sold / crawl older than the shipment, same card already live,
REM          non-US (mirror) listings. At most 10 sends per night; each send is read back.
REM          2026-09-15: switched on (--write) after the 09-14 list-only night matched the
REM          daytime check exactly (3 to put back, Snorlax held for an unshipped order).
echo [sold-restock] %date% %time% >> "%LOG%"
python -u night_step.py hoju sold_restock.--orders-api.--write.--max=10 --check --no-retry >> "%LOG%" 2>&1 || goto :skip20
python -u sold_restock.py --orders-api --write --max=10 >> "%LOG%" 2>&1
python -u night_step.py hoju sold_restock.--orders-api.--write.--max=10 --done %errorlevel% >> "%LOG%" 2>&1
:skip20

REM --- 6c2) cull (take-down) candidates from the live listing list.
REM          2026-09-10: the funnel above stops by itself when the Seller Hub
REM          reports are 4+ days old, and only a human can download them. So the
REM          take-down button stayed at the 09-08 candidates for days. The live
REM          list (about 20 API calls, shared 2h cache) has everything the cull
REM          decision needs. Writes funnel_output\cull_live_YYYYMMDD.csv only;
REM          nothing is ended here (the button checks each item before ending).
echo [cull-live] %date% %time% >> "%LOG%"
python -u night_step.py hoju cull_live --check >> "%LOG%" 2>&1 || goto :skip21
python -u cull_live.py >> "%LOG%" 2>&1
python -u night_step.py hoju cull_live --done %errorlevel% >> "%LOG%" 2>&1
:skip21

REM --- 6c3) UT: which works actually sell -> the order in which Harvest collects.
REM          2026-09-12 (design iMakHQ/UT_FLOW.md, step 12): Harvest was going through the
REM          catalog's sold-out collab names by count. This hands it the demand order
REM          instead (sales x3 + watchers + shown). Writes one json in the shared area.
echo [ut-demand] %date% %time% >> "%LOG%"
python -u night_step.py hoju ut_demand_words.--write --check >> "%LOG%" 2>&1 || goto :skip22
python -u ut_demand_words.py --write >> "%LOG%" 2>&1
python -u night_step.py hoju ut_demand_words.--write --done %errorlevel% >> "%LOG%" 2>&1
:skip22

REM --- 6d) ichibankuji nightly search (was a manual button only; nothing else
REM          ran it, so the daytime press had to do the searching itself).
echo [kuji-night] %date% %time% >> "%LOG%"
python -u night_step.py hoju run_kuji_night --check >> "%LOG%" 2>&1 || goto :skip23
python -u run_kuji_night.py >> "%LOG%" 2>&1
python -u night_step.py hoju run_kuji_night --done %errorlevel% >> "%LOG%" 2>&1
:skip23

REM --- 6e) lists that the daytime buttons only display: price-down candidates
REM          and title-rework candidates. Both write a spreadsheet tab only.
REM   2026-09-22: pricedown MUST NOT write the AL flag at night. Revise reads AL and
REM   lowers the eBay price every morning, so writing it here changed prices without
REM   the user deciding (334 listings -5% since 9/3). List only; the button writes AL.
echo [pricedown] %date% %time% >> "%LOG%"
python -u night_step.py hoju noconvert_pricedown --check >> "%LOG%" 2>&1 || goto :skip24
set NOCONVERT_NO_FLAG_WRITE=1
python -u noconvert_pricedown.py >> "%LOG%" 2>&1
set NOCONVERT_NO_FLAG_WRITE=
python -u night_step.py hoju noconvert_pricedown --done %errorlevel% >> "%LOG%" 2>&1
:skip24
echo [title-rework] %date% %time% >> "%LOG%"
python -u night_step.py hoju noclick_targets --check >> "%LOG%" 2>&1 || goto :skip25
python -u noclick_targets.py >> "%LOG%" 2>&1
python -u night_step.py hoju noclick_targets --done %errorlevel% >> "%LOG%" 2>&1
:skip25

REM --- 6f) find listings whose supplier is a DIFFERENT card.
REM          2026-09-08: found only because a buyer asked. A spare-supply URL pointed at
REM          a different, cheaper card; its price became "cheapest supply now" in the
REM          sheet and the cost-plus price came out at USD 155.98 instead of 405.98.
REM          Nothing else would ever have noticed. Stage 1 only (free, a few seconds):
REM          list the rows whose cost is far below the cheapest number-verified supply.
REM          Stage 2 (opening each supplier page) stays a human-triggered step, because
REM          a low price is often genuine - 2026-09-08: 14 flagged, 0 actually wrong.
REM          --mail sends the result every night, INCLUDING when nothing is wrong:
REM          silence must not be ambiguous between "all clear" and "the job died".
echo [supply-mismatch] %date% %time% >> "%LOG%"
python -u night_step.py hoju supply_card_mismatch.--mail --check --no-retry >> "%LOG%" 2>&1 || goto :skip26
python -u supply_card_mismatch.py --mail >> "%LOG%" 2>&1
python -u night_step.py hoju supply_card_mismatch.--mail --done %errorlevel% >> "%LOG%" 2>&1
:skip26

REM --- 7) write the "no backup URL at all" listings into one tab so they can be
REM        seen at a glance (they are scattered rows in the master sheet).
REM        Writes only that tab; never touches the master sheet.
echo [naked-list] %date% %time% >> "%LOG%"
python -u night_step.py hoju hoju_naked_sheet --check >> "%LOG%" 2>&1 || goto :skip27
python -u hoju_naked_sheet.py >> "%LOG%" 2>&1
python -u night_step.py hoju hoju_naked_sheet --done %errorlevel% >> "%LOG%" 2>&1
:skip27

:done
python -u night_step.py hoju --end >> "%LOG%" 2>&1
echo [end] %date% %time% >> "%LOG%"
endlocal
