# iMakInventory daily_report

## 2026-06-30 — 過去数日ログ点検: 在庫適正 (取下げ漏れゼロ) + cron silent crash 穴を hardening

### 在庫整合性確認 (user「過去数日分のログで在庫に問題ないか」) — 問題なし
- 決定: 06-27〜30 の全 cycle (31本) + 公式監視くんを点検。**履行不能リスクの取下げ漏れゼロ = 在庫適正**。
- 検証:
  - 本体 cycle 31本: **up_ng=0 / action_required=0 / pending_stuck=0** を全 cycle で確認
    (= 取下げ upload 全成功・未対応ゼロ・滞留ゼロ)。`skipped_lock_held` は cycle 重複時の正常 skip。
    各 cycle の scrape error 3〜25件/1247 は transient (network)、 fail-closed で誤取下げ化せず。
  - reverse_audit heartbeat: 06-28/29/30 とも **OK_ACK_ONLY (未承認乖離 0)** = D=○ 系の漏れゼロ
    (承認済み row728 のみ)。
  - **固着 scrape error (盲点リスク) を深掘り**: persistent_err_rows に PSA10 カード 5件
    (358632857689/694/701/703, 358637511019) が連続 None (fail-closed)。**D≠○ なので reverse_audit
    の死角** → 源が実売切なら fail-OPEN 漏れになり得る。本体 scraper で各 3回 scrape して実機判定 →
    **5件とも 3/3 ON_SALE (在庫あり) × eBay qty=1 = 全て正しく漏れなし**。固着は PSA10 ページへの
    anti-bot で transient、 fail-closed が正しく機能していた (誤取下げも漏れも無し)。
  - 公式監視くん (iMakeBayAPI/inventory_monitor): mail_send.log 全 OK、 audit_and_heal の
    **pending:0** が連日 (= 未解決の漏れゼロ・乖離自動補正稼働)。

### reverse_audit daily cron の silent crash 穴を hardening (commit 予定)
- 決定: 点検中に **06-30 10:00 の reverse_audit cron が exit 1 + heartbeat 無記録で落ちていた**
  のを発見 (手動再実行は exit 0 = 真因は transient)。問題は失敗そのものより **silent だったこと**:
  pythonw は stderr 破棄、 かつ `_run_daily_audit` より外で例外が起きると heartbeat/alert コードに
  到達せず = 「audit が走らなかった」を誰も気づけない (安全原則「audit 不能は非-silent」違反)。
- 変更: `reverse_audit.py` `--mode all` を最外周 try で捕捉し、 想定外クラッシュ時も
  `_emit_crash_alert()` で **heartbeat(AUDIT_CRASH) + AUDIT_ALERT.log + toast + email** を必ず残す。
- 検証: `tests/test_reverse_audit_daily.py` に crash-guard test 追加 (7件)。offline 159 pass。

## 2026-06-27 — daily cron 初回自動実行を確認 + reverse_audit 承認済み allowlist 新設 (alert 疲労対策)

### reverse_audit daily cron 初回自動実行 = 稼働実証 + SHOPS 自動是正の確認
- 決定: 昨日復旧した `iMakInventory_ReverseAudit_Daily` が **06-27 10:00 に初回自動実行**され、
  乖離1件を検知して alert 発報 = **cron が設計通り稼働している実証**。
- 検知乖離は row728 (トゲキッス V) のみ = 既知偽陽性。**row949 SHOPS は乖離リストから消滅**
  = 昨日の SHOPS skip 修正 (commit 6ea4cfe) が予告通り D=○ を自動是正したことを実機確認。

### row728 が毎日同じ偽 critical alert → 承認済み allowlist で抑制 (commit 予定)
- 決定: row728 (item 358645217419, PSA10トゲキッス V) は url 空で源 scrape 不能なまま eBay live
  (qty=1)。user が物理確保済の 1点物 PSA10 鑑定品 (無在庫向かない商材) を意図的に出品継続中で
  **取下げ漏れではない** (履行可能、過去 user 確認済 [[ended_listing_not_failopen]])。だが D=○ が恒久
  stale のため **毎日同じ critical alert を出し続ける → 本物の取下げ漏れ alert が埋もれる (alert 疲労)**。
  安全原則「DLQ/要対応リストは墓場にせず…」と裏腹に、 既知ノイズの常時発報は真の警告の visibility を
  下げる → **承認済み既知偽陽性 allowlist で alert のみ抑制** (データ・heartbeat は温存)。
- 変更:
  - `reverse_audit_acknowledged.json` 新設 (git 追跡 = 人手レビュー可能): item_id + reason +
    acknowledged_at を明記。row728 を登録。
  - `reverse_audit.py` `_run_daily_audit()`: 乖離を承認済み/未承認に分離。**critical alert (toast/
    email/AUDIT_ALERT.log) は未承認分のみ**で発火。承認済みは **heartbeat に reverse_ack /
    acknowledged_ids として毎回記録** (= silent drop 禁止・安全原則準拠)。**fail-closed**: allowlist に
    無い item_id は従来通り必ず alert、 ファイル不在/破損時も全件 alert に倒す。status に OK_ACK_ONLY 新設。
- 検証: `tests/test_reverse_audit_daily.py` を 4→6 件に拡張 (承認済みのみ→alert 抑制+heartbeat 記録 /
  承認+未承認混在→未承認件数だけで alert)。offline 159 pass。**ライブ実証**: `--mode all` exit 0、
  status=OK_ACK_ONLY (未承認 0 / 承認済 1)、heartbeat に ack 記録 + AUDIT_ALERT.log に新規追記なし
  = 抑制成功。未承認の本物乖離は従来通り 3 チャネル発火 (前回 06-25 実証済)。

## 2026-06-26 — 陳腐化テスト2件修正 + 在庫適正 再確認 (取下げ漏れ実害ゼロ)

### 陳腐化していた既存テスト2件を現行コード仕様に追従 (commit cec28cc)
- 決定: full suite で fail していた非-live 2件は **コードが正しく、テストの期待値が機能追加前のまま
  固定** されていた陳腐化バグ → テスト側を現仕様に追従。
- 変更:
  - `tests/test_run_cycle.py`: email ヘッダ「⚠️ 要対応」に 2026-06-11 追加の「送信失敗」bit が
    併記される現仕様へ期待文字列を更新 (`売切検知 4 → 完了 2 / 未取下げ 2` → `… / 送信失敗 1`)。
  - `tests/test_n_col_price_now.py`: `update_listings_sold_marks` の返り値に追加された `err_writes`
    キーを期待 dict に追加。
- 検証: 非-live テスト **414 全 pass** (残 11 deselected は network 依存の live smoke のみ)。
  pre-commit 115 + offline 159 pass。

### 在庫適正 再確認 (user「在庫は適正なの/問題なし?」) — 取下げ漏れ実害ゼロ
- 決定: 履行不能リスクのある取下げ漏れ (= 在庫切れ D=○ なのに eBay で買える) は **ゼロ = 問題なし**。
- 検証 (実機 06-26):
  - pending_revise (取下げ滞留): **0 件**。
  - action_required.jsonl: 累積 892 行だが **最新エントリ 06-22T08:10** = sold-out 単品 verify 修正
    (commit 0b7f566) 以降 新規ゼロ (3日以上クリーン)。内訳 886=過去 burst guard holdout / 6=旧 verify giveup。
  - reverse_audit (06-25 11:10 daily, HIGH 2件) は **両方 既知偽陽性**:
    row949 SHOPS PSA10ミラーピカチュウ = 源在庫あり (eBay qty=1 が正、D=○ が stale)、HIGH=SHEET cycle
    6x/日 再 scrape + SHOPS skip 修正で自動是正。row728 トゲキッス V = user 手動再買 (qty=1, url空) で意図的。
  - 公式監視くん (iMakeBayAPI/inventory_monitor) は audit_and_heal が毎 cycle 乖離自動補正で稼働中。
- 補足: 専用 daily cron `iMakInventory_ReverseAudit_Daily` は 2026-06-26 10:00 から自動実行開始
  (継続証跡 heartbeat 積上げ)。

## 2026-06-25 — amazon driver 自動再起動 + 昨日ログ点検 + 在庫整合性確認 (reverse_audit 偽乖離2件 + SHOPS skip 修正) + reverse_audit 専用 daily cron 復旧

### 在庫整合性確認 (user 指示「在庫は問題ないの」) — 実害ゼロ、構造ギャップ2件
- 決定: pending=0 / action_required=0。reverse_audit 手動実行 (06-16 以降 自動停止のため) で乖離2件検出 →
  **両方とも偽陽性 = 取下げ漏れ実害ゼロ**と確定。
  - HIGH row728 (トゲキッスV): 既知正当 (user 手動再買 qty=1、url空) [[ended_listing_not_failopen]]。
  - HIGH row949 (PSA10ミラーピカチュウex SHOPS, iid=358705341664): eBay qty=1 live × D=○。
    源を clean 環境で 5/5 再 scrape → **ON_SALE qty=1 ¥38,280 = 在庫あり** → eBay qty=1 は正しい (取下げ不要)。
    ※ 初回 scrape は orphan chrome 競合で flip-flop した。即取下げせず源確認した判断が正解 ([[dont_act_on_audit_alert_without_human_review]])。
- 変更(1) mercari SHOPS skip 除外 (commit 6ea4cfe): `monitor_listings.py` — URL が /shops/ = SHOPS は
  D=○ skip せず毎 cycle 再 scrape (restock 検知)。SHOPS は業者出品で復活するのに 1点もの前提 skip が
  誤適用され、 売切→D=○ 後の復活を検知できず D=○ が stale 化していた (row949 の真因)。通常 item(/item/) は
  skip 維持。test_mercari_shops_no_skip.py。
- 検証: 次 cycle で row949 再 scrape→ON_SALE→D=○ 自動是正される見込み。offline 159 + pre-commit 115 pass。
- 残課題(2) **reverse_audit が 06-16 のスケジュール再編以降 自動実行されていない** → ✅ **本日復旧** (下記)。

### reverse_audit 自動実行の復旧 — 専用 daily cron に切出 (commit 予定)
- 決定: 06-16 再編で Phase 5 起動条件 `sheet=="both" and not sheet_id` を満たす cycle が消滅
  (旧 _Cycle_BothDaily0930 削除、 現タスクは SHEET=--sheet-id 指定 6x/日 と LOW=--sheet low 3x/日 のみ)
  → reverse_audit (取下げ漏れ reconciliation) が 9 日間自動実行ゼロ = 安全原則「定期 reconciliation で
  乖離ゼロ継続証跡」が本体側で途切れ = fail-OPEN 検出網の穴。**user 裁定: 専用 daily タスクで復旧**
  (run_cycle 改修・source 再スキャン不要。 reverse_audit は HIGH/LOW シートを eBay と直接突合し monitor
  scan 移行と独立なため)。
- 変更:
  - `reverse_audit.py`: `_run_daily_audit()` 新設 + `--mode all` CLI 追加。reverse + ebay_down を共有
    eBay active map で両方実行。 (1) 乖離 0 でも heartbeat 証跡 (`decision_log/reverse_audit_daily.log`)
    を必ず append = 継続 reconciliation の客観証跡。 (2) reverse mismatch>0 (取下げ漏れ疑い) /
    mismatch==-1 (eBay取得/sheet読込失敗で audit 不能) は **alert ログ + desktop toast + email の
    3 チャネル非-silent 通知** ([[koshiki_mail_silent_fail_fixed]] 同型の多重防御)。 ebay_down orphan は
    review シート書出済で自動無害 → heartbeat のみ (alert しない)。
  - `tools/register_reverse_audit_daily_task.ps1` 新設 → タスク `iMakInventory_ReverseAudit_Daily`
    を **10:00 daily** で登録済 (cycle と非重複、 reverse_audit は chrome 不使用で 一括kill 制約外、
    09:30 SHEET cycle との eBay API 負荷集中を回避)。次回 2026-06-26 10:00。
- 検証: `tests/test_reverse_audit_daily.py` 4件 (乖離0=heartbeat のみ/mismatch>0=3チャネル発火/
  audit不能(-1)=非-silent/ebay_down orphan単独=alert せず) pass。offline 159 pass、 既存 full suite に
  対し regression ゼロ (残 13 fail は全て network 依存 live test + 私の変更前から fail の既存 2 件)。
  **ライブ実証**: `python reverse_audit.py --mode all` exit 0、 reverse 乖離 2 / ebay_down orphan 230、
  alert 3 チャネル全発火 (email=sent 実送確認)、 heartbeat=MISMATCH 記録。乖離 2 件は今朝確認済の
  既知偽陽性のみ (row728 トゲキッス V=user手動再買url空 / row949 SHOPS=源在庫あり D=○ stale、
  SHOPS skip 修正で次 cycle 自動是正) = 新規取下げ漏れゼロ。
- 公式側 (iMakeBayAPI/inventory_monitor) は audit_and_heal が毎 cycle 稼働で乖離自動補正中=元から問題なし。

### ログ点検 (user 指示「昨日のログで不具合ないか」)
- 決定: 本体監視 06-24 はクリーン。06-23 に一過性2件 (いずれも可視化済・翌 cycle 回復) を検出 →
  うち1件 (amazon driver 無再起動) は構造ギャップにつき修正。公式監視くん (iMakeBayAPI/inventory_monitor)
  は全 cycle 正常・mail 全 OK・audit_and_heal が乖離自動補正・scrape 精度 10/10 で不具合なし。
- 検出した一過性2件 (06-23):
  - 02:16 SHEET cycle: スプシ書込 DNS失敗 (scrape は全成功・売切14検知)。eBay 取下げは scrape queue
    起点でスプシ書込から独立 ([[ebay_update_independent_from_sheet]]) = 安全、 [NG] 計上=silent でない。
  - 06:30 LOW cycle: amazon driver セッション死 (InvalidSessionId 394件)、 row418〜831(396行)が6秒で
    全滅=1 cycle 盲目。err_writes=396 で AK列計上=silent でない。翌 06-24 は 0件で回復。
  - 公式 06-24 11:00: Trading API DNS失敗 → Selenium fallback 作動で全78 listing 正常処理 (silent skip 無し)。

### amazon driver 無再起動ギャップ修正 (commit 67dc192)
- 決定: driver auto-restart が mercari 専用で amazon は driver死後に残り全行盲目化していた
  (06-23 の396行盲目の真因)。一過性なら自己回復するが持続したら mercari 297連続失敗事故と同型の fail-OPEN。
- 変更: `monitor_listings.py process_sheet` — (1) driver-dead 検知 (mercari_driver_dead→driver_dead) に
  "invalid session id"/"InvalidSessionId" 追加。(2) AMAZON_RESTART_THRESHOLD=3 新設、 amazon 連続 crash で
  create_amazon_driver 再起動 (mercari と同型、 失敗時 None で続行=残り行 error 計上で次 cycle 再試行、
  fail-closed で偽 OOS 化しない)。(3) amazon 成功で counter リセット。
- 検証: `tests/test_amazon_driver_restart.py` 3件 (閾値定数 / invalid session id 検知 / 連続
  InvalidSessionId→create_amazon_driver 2回以上=再起動発火・全行処理しきる、 修正前は create 1回で fail)。
  offline 159 + pre-commit 115 pass。



### sold-out 単品 verify が QuantitySold 取りこぼし → 偽「滞留」⚠️要対応 (commit 0b7f566)
- 決定: 09:30 HIGH cycle が iid=358251931733 (LOW row131) を「19.6h 取下げ滞留=要対応」と誤報。
  実機調査で **危険なし=偽陽性** と確定 → 根因修正。GetItemTransactions で当該 listing は
  **2026-05-13 に売却済 (CompleteStatus=Complete, available=0)** = 履行リスク皆無、直近売却でもない。
- 変更: `ebay_actions/trading_api_uploader.py` `_verify_qty_zero` の単品 GetItem を raw_xml_cap=2000→None。
  真因: `<QuantitySold>` が SellingStatus 内で 2000字より後ろ (実測 pos≈3669) に来るため cap=2000 で
  取りこぼし → sold=0 と誤算 → available=Quantity(1)-0=1 と過大評価 → sold-out 単品 (Qty=1/Sold=1,
  実 available=0) を永久に qty_gt0 と誤判定 → verify_qty_gt0_giveup で drain 不能=永久 spam。
  variation 経路は既に cap 解除済だったが単品が漏れていた。fail-OPEN は導入せず (verify がより正確化=安全側)。
- 検証: `tests/test_single_soldout_verify.py` 2件 (cap 尊重 mock で sold-out→verified=True / 在庫残→False)。
  ライブ実証: 実 revise(21917092 redundant/success) + verify(cap=None)→available=0→verified qty=0、
  pending から drain 完了 (processed_revise.jsonl に consumed_at 記録=silent でない)。pre-commit 115 +
  offline 159 pass。2026-06-17 ended-listing fix (bb11fae) と同型の偽滞留撲滅。



### ★最重大: HIGH/LOW 巡回が 06-17夕〜06-20 の3日間 silent 停止していた
- 決定: 真因は「私の amazon 修正(a12b776, 残りN点を在庫マーカー追加)が run_cycle 起動時の
  pytest precheck の中古品検体テストを fail させ → precheck=失敗で巡回 abort」。 さらに abort 通知が
  toast のみ(Task Scheduler の pythonw 下で不可視・メール無し)で **完全 silent** だった二重欠陥。
  タスクは定刻 0x0 で発火し続けたが起動直後に自己中止していた。
- 変更: (f88d9f1) `_detect_stock(html, rendered=False)` を追加し「残りN点/通常発送」は
  rendered=True(Selenium新DOM)限定に → 旧DOM中古検体の誤判定解消・precheck 通過。
  (d7cad31) precheck 失敗時の abort を desktop ALERT + メール発報で loud 化(silent 再発防止)。
- 検証: `pytest tests/ -m offline` = 159 passed(中古検体 fail 解消)。 タスク発火 0x0 だがログ皆無 →
  precheck-abort が真因と特定。 修正後 HIGH 09:30 = 売切1→取下げ1、 LOW 06:30 = 売切3→取下げ3 で正常復帰確認。

### 在庫メンテ(3日バックログ清算)
- 決定: 停止中に溜まった売切れを全取下げ。 burst guard(閾値30)が HIGH 44件/LOW 221件の spike を HOLD。
  LOW 220件は amazon が第三者販売化(実セラー POP/コメカミジャパン等を4件実機確認、 glitch でなく Rule 0 取下げ対象)。
- 変更(運用、 コード変更なし): HIGH holdout 19件取下げ / LOW 219件取下げ(215成功) / 公式 ✕×eBay live 7件取下げ。
  手動取下げが cycle 経由でなく pending queue 未 drain → burst 高止まり再発 → pending 270件を drain(qty=0 確認/取下げ34)。
- 検証: reverse_audit 反復で「✕(売切)×eBay qty>0」= **0件**(残1=正当 row728)を確定。 次 cycle 正常復帰(no_upload 解消)。

### CI 穴クローズ(commit が通る ⟺ cycle が起動できる を構造保証)
- 決定: pre-commit(115件)と cycle-precheck(offline 159件)が別物で、 検体不在テストが silent SKIP
  (`pytest -m offline` は全 skip でも exit 0)→ 壊れた変更が commit を素通り。 HQ と分担して根治。
- 変更: (5e6c79d/601d03a) amazon/mercari/fril の `samples_available` fixture を「検体不在=SKIP→FAIL」化(土台)。
  HQ(6aff500, 本元)が pre-commit に cycle 同一 offline ゲートを worktree 判定で追加。
- 検証: 失敗注入で commit 拒否を実証(`❌ Inventory offline gate FAILED`、 HEAD 不変)。 検体退避→赤も確認(amazon16/mercari21/fril11 errors)。

### item_id 空欄(未出品)も巡回対象に(2026-06-10 方針を反転)
- 決定: user 指示。 出品くんが CSV 作成→出品 後に「実は仕入元売切」 発覚を防ぐため、 出品前に源在庫を D 列へ反映。
- 変更: (be674ab) monitor_listings の item_id 空欄 skip を除去 → 未出品も scrape。 取下げ対象は無いので
  revise/pending/要対応 には入れない(既存の「newly_sold && item_id空欄 → 検知のみ」分岐が処理)。 巡回件数 ~290/cycle 増。
- 検証: test_blank_itemid_skip.py を新挙動に書換(未出品も scrape / 売切でも pending・action_required 無し)2件 pass。 offline gate 159 pass。

## 2026-06-19 — 公式 silent fail 群 + DNS 耐性 + 取下げ verify 化

- 決定/変更/検証:
  - (71ef8eb) 公式メール送信を retry + mail_send.log 永続記録 + desktop ALERT + 本文保存 → pythonw で結果破棄され
    DNS/SMTP blip で silent 欠落し得た穴を撲滅。 test 5件。
  - (e9a7ec6) 公式取下げを「K列に目標値0を楽観書込」から「実 eBay GetItem verify ベース」に → 取下げ未反映でも
    完了扱いだった silent fail-OPEN を撲滅(montbell M 5件 実害を手動解消)。 test 5件。
  - (d4e16a9) 公式 open_sheet に transient(DNS) backoff retry / (3f9c944) uniqlo/gu scraper に同 retry → cycle 時刻の
    getaddrinfo failed 頻発で全体❌/⚠️noise になる穴を吸収。

## 2026-06-17 — Multi-SKU 取下げ fallback + 終了済 listing verify + LOW/公式 8h 化

- 決定/変更/検証:
  - (61e5a93) 単行 Revise が 21916736(Multi-SKU)で失敗→永久滞留 fail-OPEN を、 GetItem→qty>0 variation 全 qty=0 化
    fallback で救済。 失敗注入 test 5件。 row55 鬼滅UT XXL の 8.5h 滞留で発覚。
  - (bb11fae) 終了済(Completed)listing は残存 Quantity を持つが購入不可 → verify を safe_failure(ended)通過扱いに(偽滞留 spam 撲滅)。
  - (運用) LOW/公式 巡回を日1回→8h毎に頻度UP(Windows タスク、 全 cycle 時刻 非重複)。

## 2026-06-14 — mercari ReadTimeout に再取得リトライ (「エラー除外」= fail-OPEN を回避)

### 決定
- driver version 修正後、 通信エラーは 0〜1件/cycle で安定。 残る間欠 ReadTimeout
  (row729/m42155119753 等、 特定の重いページで driver コマンドが localhost timeout) について
  ユーザーが「在庫あるのに読めなかっただけならエラーから外せないか」と提案。
- **回答 = 除外は NG (fail-OPEN)**: ReadTimeout は「読めなかった=在庫不明」であって「在庫あり確定」
  ではない。 除外すると "本当に売切れた行がたまたま ReadTimeout" を silent 見逃す → 取下げ漏れ
  → Defect/BAN ([[indeterminate_means_investigate_root_cause]] / 状態同期の安全原則)。
- **代替 = 再取得リトライ**: 同 row を間隔空けて再取得。 読めれば確定 (= noise 減)、 読めなければ
  依然 error (= 漏れにしない)。 fril/snkrdunk と同思想。 ユーザー承認。

### 変更
- `scrapers/mercari_scraper.py:fetch_product_inventory` に max_retries=2 追加。
  `_detect_via_selenium` が ReadTimeout/ProtocolError/ConnectionReset/MaxRetryError/
  「Connection aborted」/「timed out」を投げたら 2/4s 空けて再取得。 transient でない例外
  (DOM構造変更等) は即 raise (retry しない)。 全滅も raise (= 呼出元で error 化、 除外しない)。
- `tests/test_mercari_readtimeout_retry.py` 3件 (回復 / 全滅raise / 非transient即raise)。

### 検証
- ✅ モックで 2回ReadTimeout→3回目確定 / 全滅raise / 非transient即raise。 offline 153 pass。
- 漏れ安全性: 「除外でなく再取得」なので、 読めない行は依然 error に残り silent drop しない。

## 2026-06-13 — driver「cannot connect to chrome」真因 = version_main=148 ハードコード陳腐化

### 決定 (Gemini 相談 + コード調査で真因確定)
- 05:30 cycle でも driver crash 継続 (mercari/amazon 10行 blind、 `MaxRetryError`/
  `ConnectionReset(10054)` on localhost)。 ユーザー指示で Gemini (gemini-2.5-flash) に相談
  → 「version mismatch が最有力」。 コード調査で **真因確定**:
  - `mercari_scraper.py:170` / `amazon_scraper.py:361` が **`version_main=148` ハードコード**
    (コメントも「2026-05-21 v148対策」のまま)。 だが **Chrome 本体は自動更新で v149**。
  - → uc が chromedriver 148 を取得 → chrome 149 に接続できず
    「SessionNotCreatedException: cannot connect to chrome」 を頻発。
  - uc は 3.5.5 が PyPI 最新で更新不可 (uc 更新は手詰まり)。 真の問題は version 固定の陳腐化。

### 変更 (Chrome 実 version を自動検出 → 自動追従で再発防止)
- `scrapers/_chrome_util.py` 新規: `detect_chrome_major()` = レジストリ
  `HKCU/HKLM\Software\Google\Chrome\BLBeacon\version` から Chrome major を検出 (キャッシュ、
  失敗時 None=uc 自動検出)。
- `mercari_scraper.py` / `amazon_scraper.py`: `version_main=148` →
  `version_main=detect_chrome_major()`。 Chrome 自動更新 (149→150...) に構造的に追従。
- `tests/test_chrome_util.py` 3件 (int/None・キャッシュ・例外fallback)。

### 検証
- ✅ `detect_chrome_major()` → 149 (Chrome 本体と一致)
- ✅ mercari driver 起動成功 + scrape 成功 (version 一致で「cannot connect」解消)
- ✅ offline 計 150 pass
- 09:30 both-cycle が真の live proof (driver crash が消えるか)

### Gemini 助言の他項目 (今回不採用/保留)
- 画像読込OFF 等の chrome flag (リソース削減) = 低リスク高効果、 次の改善候補
- driver 50-100件ごと再生成 = mercari は既に 150件ごと実装済
- chrome downgrade = Gemini は「149はベータ」と誤認 (知識2024)、 2026 では安定版 → 不採用

## 2026-06-12 — mercari driver「chrome not reachable」事故 → orphan chrome 一掃で再発防止

### 事故
21:30 cycle で mercari driver が 22:04 にクラッシュ → 再起動を3回試みるも
`SessionNotCreatedException: cannot connect to chrome` で失敗 → 約6分(22:04-22:10) mercari
全 None → row519-541 等 19行が blind。 その後 isolation でも driver 起動不能に悪化。

### 根本原因 (調査で確定)
- driver 再起動失敗のたびに **headless chrome が orphan として残留・累積** (cycle中 + 手動test
  で 23→38→50)。 累積で新規 chrome 起動が「chrome not reachable」になり driver 完全不動。
- 既存の kill 処理 (`monitor_listings.py:456`) は **二重バグで orphan を一つも kill できていなかった**:
  (a) `taskkill /IM chromedriver.exe` ← uc は `undetected_chromedriver.exe` で名前不一致
  (b) `taskkill /IM chrome.exe /FI "WINDOWTITLE eq *iMakInventory*"` ← headless chrome は
      window title 無しで 0 ヒット。
- Wi-Fi 無関係 (localhost の chrome 接続失敗)。 Chrome v149 / uc 3.5.5。

### 対処
- **即時**: scraper の orphan chrome (--headless で識別、 ユーザーブラウザ温存) + driver を
  手動 kill → driver 即復活 (単発 scrape OK 確認、 再起動不要)。
- **再発防止 (commit)**: `monitor_listings.py` に `_kill_stale_scraper_chrome()` 追加、
  **process_sheet 開始時 (driver 生成前 = 並走 driver 皆無の安全点) に orphan を一掃**。
  PowerShell で `undetected_chromedriver` + `--headless` chrome を kill (非headless=
  ユーザーブラウザは温存)。 cycle 途中の kill は並走 driver を巻き込むため startup のみ。
- test_kill_stale_chrome.py 3件 (非win32 no-op / powershell+headless filter / 例外 fail-safe)。

### 漏れ検証
- 19 blind 行: 404=0 (削除なし) + row729 実機 ON_SALE + **ユーザーが HIGH AK 全行を目視確認
  → スプシ整合・漏れなし**。 売切で返った行ゼロ。 **取下げ漏れ: なし**。

## 2026-06-11 (続々々々) — snkrdunk「uncertain N/M candidates」誤アラート → 接続リトライ

### 決定 → 変更 → 検証
- **決定 (+ 自己反省)**: 21:30 cycle で snkrdunk row595「uncertain: 1/6 candidates errored」。
  当初「様子見」と誤って軽視 → ユーザー指摘「仕入元売切 + eBay 出品中やぞ」。 調査で判明:
  - 主URL(45481844) は 404 売切だが、 **補#4(45635003) が在庫あり (¥35,000 PSA10 レベッカ)**。
    multi-sourcing で在庫あり = 取下げ不要が正解 (= 漏れではなかった)。
  - cycle で uncertain になったのは、 **その在庫あり補#4 が transient 接続例外で None** に
    なり「在庫あるのに見えず uncertain」 になったため。 = fril と同型の transient。
  - snkrdunk が None を返すのは `requests.get` 例外時のみ ([snkrdunk_scraper.py:84])、
    = 接続瞬断/rate-limit。 cycle 中は多数行×最大6候補で大量 fetch するため発生。
- **変更**: `scrapers/snkrdunk_scraper.py:fetch_product_inventory` に http_status=None
  (=接続例外) 時のリトライ (2/4/6s 間隔、 max_retries=3) を追加。 404/sold/in_stock の
  確定結果は即採用 (retry しない)。 fril と同型。
- **検証**: `test_snkrdunk_retry.py` 3件 (transient回復 / 全滅None / 404即確定)。 offline 143 pass。
- **教訓**: 「uncertain」 を様子見にするのは取下げ軸では fail-OPEN 寄り。 transient 候補エラーは
  retry で潰すのが正。 在庫ある補欠が transient で落ちると「在庫あるのに uncertain」 になり、
  逆に「売切なのに見落とし」 とも誤認させる両刃。 → retry で根治。

## 2026-06-11 (続々々) — fril「scraper returned None」反復 → no_signal リトライ

### 決定 → 変更 → 検証
- **決定**: 17:30 cycle 等で fril 行 (row542 は 01:50/05:49/17:48 と 1日3回) が
  「scraper returned None (fail-closed)」を反復。 調査で判明: 失敗 URL は HTTP200 の
  実在商品ページ (UNIQLO UT、 在庫あり) だが、 cycle 中は負荷で **marker 無しページ
  (anti-bot/rate-limit/部分ロード) を間欠返し** → `_detect_stock` が no_signal=None。
  単独 re-fetch では 8/8 正常判定 (buy_button + JSON-LD availability=InStock) = 検出
  ロジックは健全、 transient なページ不良が原因。
- **変更**: `scrapers/fril_scraper.py:fetch_product_inventory` に no_signal/接続失敗
  (=None) 時の再 fetch リトライ (2/4/6s 間隔、 max_retries=3) を追加。 404/sold/in_stock
  の確定 dict は即 break (retry しない)。 eBay の network retry と同思想。
- **検証**: offline test 3件 (`test_fril_retry.py`: transient回復 / 全滅fail-closed /
  確定即break)。 offline 計 140 pass。 実 URL 連続 fetch 8/8 正常も確認。
- **未対応 (別件)**: snkrdunk row575 「uncertain 1/3 candidates errored」は別 scraper の
  partial。 単発なので今回は様子見 (反復したら同型 retry 検討)。

## 2026-06-11 (続々) — DNS瞬断起点の取下げ漏れ事故 → 多層防御4本 + 公式横断確認

### 事故の経緯
09:30 both cycle で api.ebay.com への **DNS 瞬断 (getaddrinfo failed)** が発生。
取下げ4件中1件 (G-SHOCK DW-6900 / itemID 356901158380 / LOW row214 / D=○売切) が
送信失敗 → pending に 6-10 16:46 から **約19h silent 滞留**。 ユーザー手動UPで qty=0 化・解消。
深掘りで以下の fail-OPEN を芋づる発見。

### 決定 → 変更 → 検証 (4本)
- **① 決定**: API client が network 瞬断で即諦め (DNS失敗は全uploadの~12%=105中13で発生)。
  - **変更**: `ebay_actions/trading_api_client.py:_call_trading` に指数backoff(1/2/4/8s)
    リトライ追加 (max_net_retries=4)。 commit **440c66a**。
  - **検証**: モックで2回瞬断→3回目成功 / 全滅→False+明示。 offline 134 pass。
- **② 決定**: `run_reverse_audit` に空map fail-closed ガード無し → eBay取得失敗時に
  偽「✅乖離0件」を継続証跡に積む fail-OPEN (sibling にはあった)。
  - **変更**: `reverse_audit.py` 空map→`mismatch_count=-1/error` で返し email の
    「❌突合不能・嘘の安心排除・即時」path に乗せる。 commit **e835e9a**。
  - **検証**: 空map注入→-1/error 確認。 ※調査で判明: 実 reconciliation fetch
    (iMakeBayAPI download) は元々堅牢(_post_with_retry+raise+HasMoreItems)で、 先の
    「✅0件は偽」断定は過剰だった = 多層防御として有効だが今回の主因ではない。
- **③ 決定**: network失敗(qty不明)の取下げ失敗は action_required(verify_qty>0判明分のみ)
  を素通り → pending に silent 滞留 (= 356901158380 が19h無通知の真因)。
  - **変更**: `revise_csv_generator.get_stuck_pending_items()` (8h超pending検出) +
    run_cycle で検知 + email「★取下げ滞留 要対応」別掲。 commit **083326d**。
  - **検証**: offline test 3件 (境界/parse不能/空) + email レンダリング確認。
- **④ 決定**: メール冒頭「✅全件取下げ完了」と本文「失敗・全断・全BAN risk」が矛盾
  (header が upload_ng/滞留を無視 + 本文が success=False で無条件全断表記)。
  - **変更**: `email_notifier.py` header に upload_ng/stuck算入(→⚠️)、 本文を
    全断/部分失敗/action-needed で出し分け。 commit **fee3af4**。
  - **検証**: 実09:30=「⚠️要対応(送信失敗1)」+「部分失敗3/4・監視」一致 / 全断=「即時」。

### 公式監視くん 横断確認 (ユーザー指摘「公式も同様に修正できたの？」)
公式 (iMakeBayAPI/inventory_monitor) は **追加修正不要**。実機確認の根拠:
- ① retry: 公式取下げは iMakInventory の `trading_api_client` を流用(auto_qty_zero.py:188)
  → retry を自動共有。
- ② 監査: 公式の eBay取得は失敗時 raise(`_post_with_retry`+Ack chk) = 設計上 fail-closed。
- ③ 滞留: 公式は pending queue でなく毎cycle「対処要+未対処済」をシート再導出 → 失敗は
  次cycleで再surface + ng毎回計上 = silent 化しない。
- ④ メール: run_daily は元々 `total_ng>0→⚠️`(164-177行) = 矛盾なし。 件名も整合済み。
→ 今回の穴は HIGH/LOW 固有 (pending queue方式 + reverse_audit 空ガード欠落)。

## 2026-06-11 (続) — エラー重複の原因究明 + 構文 smoke テスト(A) + driver 堅牢化(B)

### 決定
- 01:30 / 05:30 cycle でエラー対象が重複する件を調査 → **localhost ReadTimeout (= 手元
  chromedriver のハング) が巡回深度 ~740行で cluster** と判明。 mercari ブロックではない。
  失敗5行 (747/751/753/756/757) は item_id 空欄 skip を除くと**実 scrape 5連続**で、 これが
  「連続None5件→driver再起動」トリガーになり ~10分 + 5行 unknown を浪費していた。
  シート順固定なので毎 cycle 同じ位置で再現 (= ユーザーの「シート順影響」の勘が正しい)。
- 対策2本 (ユーザー承認「ABともに」):
  - **A**: 全モジュール構文 smoke テスト追加 (= cda4126 型バグ再発防止)
  - **B**: driver 堅牢化 (反応閾値 5→3 + 予防的再起動 150件ごと)

### 変更
- **A**: `tests/test_syntax_all_modules.py` 新規。 iMakInventory + 公式 inventory_monitor の
  全 .py を py_compile (doraise) で検査。 run_daily.py / main.py 等 **どのテストも import
  しないモジュール**の構文エラーを検出。 54 ファイル検査。
  - ★ ゲート位置 (調査で判明・要注意): git commit フック (`tools/hooks/pre-commit`) は
    モノレポ root の `pytest tests/ iMakHQ/tests/` を回すだけで **iMakInventory/tests/ は
    走らせない**。 よって A が効くのは **commit 時ではなく run_cycle の Phase 0 pre-flight**
    (`pytest tests/ -m offline`、 HIGH cycle 4h ごと、 失敗で cycle abort+通知: run_cycle.py:463)。
  - 本テストは公式 .py も compile するので、 cda4126 型バグは **次 HIGH cycle pre-flight
    (例 05:30) で abort+通知** = 公式 08:00 cron クラッシュ前に検知できる構図。
  - commit 時ブロックが欲しければ共有フック改修が要るが、 これは HQ 管轄 (worktree 跨ぎ
    共有 infra) なので requests/ 経由で提案する事項。 本 worktree から単独改変はしない。
- **B**: `monitor_listings.py`
  - `MERCARI_RESTART_THRESHOLD` 5→3 (反応的再起動を速め、 浪費を ~4分 + 2行に圧縮)
  - `MERCARI_PREVENTIVE_RESTART_EVERY = 150` 新設 + loop 内に予防再起動ブロック
    (mercari 実 scrape 150件ごとに driver refresh = 疲弊前リサイクル、 0で無効化)
  - per-item Selenium timeout は誤判定(fail-closed)リスクのため**触らない**

### 検証
- ✅ offline 134件 pass (= 旧80 + 構文 smoke 54)、 回帰なし
- ✅ test_syntax_all_modules が run_daily.py / main.py を検査対象に含むこと自体も assert
- ⚠️ B は本番 scraper 挙動変更。 次 HIGH cycle 13:30 が初 live。 restart コスト ~10-20s ×
  予防2回/cycle = 微小。 効果は cluster 解消の実 log で次 cycle 確認予定。

## 2026-06-11 — 巡回ERR FLG 列導入 (3スプシ) + run_daily.py 致命 SyntaxError 修正

### 決定
- メール本文のエラー row 表示が上位10件 cap で、11件以上だと残り URL が拾えない取りこぼし
  が判明 (Takaaki さん指摘)。→ **スプシに専用「巡回ERR」列を設け、件数無制限で全 error 行を
  filter 可能にする**方針を採用。
- 対象は **HIGH / LOW / 公式 の 3 スプシ全部** (Takaaki さん指示「公式にも追加を」)。
  公式は別系統「公式監視くん」(iMakeBayAPI/inventory_monitor/run_daily.py, 毎日08:00) が巡回。
- 書込先の列 (Takaaki さん確定):
  - HIGH/LOW = 商品管理シート **AK 列** (per-listing、 D=売り切れの隣系統)
  - 公式 = **SKU詳細シート T 列** (per-SKU)。理由: 公式の在庫ステータス(I=仕入元在庫)は
    SKU詳細にあり、シート1は入力リストに過ぎない。scrape は listing 単位失敗なので
    該当 listing の全 SKU 行 (D=listing_id 逆引き) を同 count でマーク。
- marker は **連続エラー回数つき** (`⚠ ReadTimeout ×2 06/11 06:03`)。成功で自動 clear (自己修復)。
  連続3回以上 = 持続エラーとしてメール別掲 (transient と区別、 手動 chk 促し)。
- 関連 row747 (m48307094591): 22:08 / 02:03 と 2 cycle 連続 localhost ReadTimeout だが
  在庫あり (Takaaki さん確認)。本機構はこの type の blind spot を炙り出すのが狙い。

### 変更
- 新規: `err_flag.py` (HIGH/LOW 側) / `iMakeBayAPI/inventory_monitor/err_flag.py` (公式側、同一複製)
  - marker 生成/解析: build_err_marker / marker_count / is_persistent / PERSISTENT_THRESHOLD=3
- HIGH/LOW 側:
  - `sheet_updater.py`: LISTINGS_COL_ERR_FLG=37(AK) 追加、read_listings_rows に err_flag_prev、
    update_listings_sold_marks に err_flag 書込、ensure_listings_err_header / _col_letter 追加
  - `monitor_listings.py:686付近`: エラー行→連続回数 marker / 成功行(前marker有時のみ)→clear、
    persistent_err_rows 集計、process_sheet start で AK ヘッダ ensure
  - `run_cycle.py:226,248付近`: grand に persistent_err_rows 集約
  - `email_notifier.py:347付近`: AK列誘導行 + 持続エラー別掲ブロック
- 公式側 (SKU詳細 T 列、 per-SKU):
  - `sheet_updater.py`: SKU_COL_ERR_FLG=20(T) / SKU_COL_LISTING_ID=4(D) 追加、
    build_sku_listing_map (listing_id→SKU行逆引き) / write_sku_err_flags /
    ensure_sku_err_header (grid 19→20 拡張込み) / _col_letter 追加
  - `main.py:740付近`: cycle_sku_rows から listing_map 構築、 loop で listing 失敗時に
    全 SKU 行を同 count マーク / 成功時 clear、 persistent 集計 + 「持続エラー : N」出力、
    SKU status 書込後に T列書込 (独立 fail-safe)
  - `run_daily.py:55,212付近`: _parse_monitor_output に persistent_errors (「持続エラー」を
    「エラー」より先に判定し continue で衝突回避)、report に H列誘導 + 持続別掲
- **致命バグ修正①**: `run_daily.py:254` `lines.extend([...]` が `])` でなく `]` で閉じられて
  おり **SyntaxError** (commit cda4126 2026-06-10 16:18 で混入)。→ `])` に修正。
- **件名を HIGH/LOW に整合 + バグ修正②**: `run_daily.py:182` 公式 subject の `overall` 判定が
  `err_rate >= 0.1` (旧「N%以下なら正常」思想の残骸) → `scrape_errors > 0` に変更
  (= 1件でもerror→要対応、 本文冒頭2行と一致、 HIGH/LOW と同思想)。同時に **`err_rate` は
  scrape_errors=0 時 未定義** = error0・ng0 の clean cycle で件名生成が **NameError クラッシュ**
  する潜在バグも解消 (render test で clean cycle 正常確認)。

### 検証
- ✅ `py_compile` 9ファイル全 OK (修正前は run_daily.py が SyntaxError)
- ✅ HEAD の run_daily.py も SyntaxError 確認 (= 本番 08:00 cron は **今日 6/11 08:00 に初発火で
  クラッシュ予定だった**。最後の成功 run は 6/10 15:59 = 混入 commit 16:18 の前)。
- ✅ offline テスト: `tests/test_err_flag.py` 新規13件 pass + 既存80件 pass (回帰なし)
- ✅ _col_letter(37)=AK / _col_letter(8)=H 確認
- ✅ email_notifier 持続ブロック描画確認 (row747 ×3回 + AK列誘導行が出力)
- ✅ 公式 _parse_monitor_output: errors=5/persistent=2/listings=100 を正しく分離 (衝突なし)
- ⚠️ 未検証: 実 gspread への AK/H 列書込 (= 走行中 cycle と profile 競合回避のため live 実行は
  次 cycle に委ねる。dry-run も selenium 起動で競合するため未実施)


## 2026-04-30 — Phase 4 Live smoke Step 1 (最小スコープ)

### 決定

- Phase 4 Live smoke は段階的に進める方針確定 (Takaaki さん指示)
- Step 1 = test listing 1 件で **CSV 生成 + eBay login** のみ。**アップロード未実行**
- 推奨候補は TEST_HIGH 行 82 (item 358454087573 UNIQLO ヒロアカ 1年A組 UT XLサイズ)
  - 選定理由: 出品 $22.58 (最安)、Mercari DELETED (仕入不可確定)
  - Takaaki さん「どれでもいい」で承認

### 変更

- **CSV 生成**: c:/dev/iMak/iMakInventory/csv_output/revise_smoke_step1_20260430_071008.csv
  ```
  *Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8),ItemID,*Quantity
  Revise,358454087573,0
  ```
- **eBay login profile 作成**: C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay\
  - Takaaki さん手動 login 実行
  - Cookies file: 68KB 保存
  - profile total: 125.47 MB

### 検証

- ✅ CSV 形式 トラバホ delete*.csv と一致 (header / Action=Revise / Quantity=0 / 列順序)
- ✅ encoding UTF-8 BOM なし (グローバル CLAUDE.md 仕様遵守)
  - 注: トラバホは BOM 付きで実績あり、eBay は両対応の見込み
- ✅ eBay login cookie 保存成功 (Default/Network/Cookies = 68KB)
- ✅ **headless driver で login 状態認識成功**
  - is_logged_in() = True
  - current_url = https://www.ebay.com/mye/myebay/summary (login 必須ページ到達)
- ✅ Amazon と異なり eBay は headless detection 緩い
- ❌ アップロード未実行 (Step 2 待ち、Takaaki さん次の指示まで実行禁止)

### 次のアクション (Takaaki さん指示待ち)

Step 2 アップロード実行 GO / NOT-YET の判断:

```bash
# Step 2 で実行する想定コマンド (現在は実行しない)
python -m ebay_actions.sell_feed_uploader upload \
  csv_output/revise_smoke_step1_20260430_071008.csv \
  --dry-run    # まずは dry-run でフォーム到達確認
```

その後 `--dry-run` 外して実 upload で qty=0 反映確認。

---

## 2026-04-30 (続き) — Phase 4 Live smoke Step 2 (2段階アプローチ)

### 決定

- Step 2a (現 URL での dry-run) と Step 2b (トラバホ同等補強実装) を別工程で進める
- Step 2c (本番 upload) は別指示で待つ (Step 2 内では実行しない)

### Step 2a 結果 (k2b-bulk URL)

旧 URL `k2b-bulk.ebay.com/...` を `driver.get()` した結果、eBay 側が自動 redirect:
- 到達 page: `https://www.ebay.com/sh/reports/uploads` (= トラバホ解析の新 URL)
- ログイン OK (cookie で persist)
- file input 要素発見、ファイル選択完了
- success: true (dry-run、Submit せず)

→ **k2b-bulk → sh/reports/uploads は eBay 側で自動 redirect される** ことが判明。
   明示的な URL 切替も依然として推奨 (再 redirect 削減)。

### Step 2b 補強実装

トラバホ `__UploadCSVwithSolded` / `__UploadCSVwithSoldedWithRetry` を踏襲した補強:

| # | 項目 | 実装 |
|---|---|---|
| 1 | URL 切替 | `EBAY_FILEEXCHANGE_UPLOAD_URL = "https://www.ebay.com/sh/reports/uploads"` |
| 2 | 3回リトライ層 (upload 全体) | `for attempt in range(1, UPLOAD_RETRY_MAX+1=3)` + 3s sleep |
| 3 | login 3回リトライ層 | `for li in range(1, LOGIN_RETRY_MAX+1=3)` + driver.refresh |
| 4 | file input 可視化 | `driver.execute_script("...style.display='block'...")` |
| 5 | ポップアップ監視 (2分) | `#shui-upload-file__pop-up` を 2 秒おきポーリング、"Download results"/"ダウンロード" で成功判定 |
| 6 | 履歴ページ refresh (3回) | popup 不確定時 results URL に遷移、5s sleep、ファイル名 + "-" 含むか確認、session 切れ検知で再 refresh |
| 7 | NoSuchElement/StaleElement | popup 監視 / 履歴ループ内で `continue` で吸収 |

### 変更

- `ebay_actions/sell_feed_uploader.py`:
  - URL 定数を `https://www.ebay.com/sh/reports/uploads` に変更
  - 新規定数: `UPLOAD_RETRY_MAX=3`, `LOGIN_RETRY_MAX=3`, `POPUP_MONITOR_TIMEOUT_SEC=120`, `POPUP_POLL_INTERVAL=2`, `HISTORY_REFRESH_MAX=3`, `HISTORY_REFRESH_SLEEP_SEC=5`
  - `upload_csv_via_form`: 旧 alert ベース監視を `#shui-upload-file__pop-up` ポーリング + 履歴 refresh に置換、file input 強制可視化 JS 追加
  - `upload_one_csv`: 3 回リトライ層 + login 3 回リトライ層追加

### 検証

- ✅ pre-commit 既存 115 tests pass
- ✅ Step 2b 修正後 dry-run 再実行成功:
  ```
  upload attempt 1/3 (3回リトライ層動作確認)
  ✅ ログイン状態 OK
  page_url: https://www.ebay.com/sh/reports/uploads
  success: true (ファイル選択まで OK、Submit せず)
  ```
- ❌ 本番 upload 未実行 (Takaaki さん次の指示まで実行禁止)

### Step 2 完了基準

- ✅ Step 2a: 現 URL での dry-run 結果報告
- ✅ Step 2b: トラバホ補強 1-7 実装 + pre-commit pass

### 次のアクション (Takaaki さん指示待ち)

Step 2c 本番 upload 実行 GO / NOT-YET 判断:

```bash
# Step 2c で実行する想定 (現在は実行しない)
python -m ebay_actions.sell_feed_uploader upload \
  csv_output/revise_smoke_step1_20260430_071008.csv
# ↑ --dry-run なし = 実 Submit + popup 監視 + 履歴 refresh で結果確認
```

実 upload 後の確認項目:
- eBay 側 listing 358454087573 (UNIQLO ヒロアカ) の qty が 0 になる
- decision_log/upload_*.jsonl に成否記録
- 不具合あれば履歴ページから人手で復旧

---

## 2026-04-30 (続き) — Phase 4 Live smoke Step 2c (本番 upload 実行)

### 決定

Takaaki さん「Step 2c GO」を受けて本番 upload 実行 (item 358454087573 の qty=0 化)。

### 実行結果 (success: true)

```
job: by7cwpvmc
csv: csv_output/revise_smoke_step1_20260430_071008.csv (Revise,358454087573,0)

upload attempt 1/3: 失敗 — "popup + history both inconclusive"
                         (popup 出る前にタイムアウト、3s sleep)
upload attempt 2/3: ✅ 成功
  popup_text: "アップロード完了\nrevise_smoke_step1_20260430_071008.csv\n結果をダウンロード"
  result_text: "popup: Download results link found"
  page_url: https://www.ebay.com/sh/reports/uploads
  success: true
```

### 検証

- ✅ **3 回リトライ層が機能した実例**: attempt 1 失敗 → 3s sleep → attempt 2 成功
- ✅ popup 監視が "ダウンロード" (Japanese) で hit (英語 "download results" にも対応)
- ✅ decision_log: `decision_log/upload_20260430_073541.jsonl` に success: true 記録
- ⏳ eBay 側反映確認 (qty=0): Takaaki さん管理画面で目視確認お願い
  (公開 itemID URL は 403 Bot block のため scraper では確認不可)

### NG 確認

- ❌ Step 3 (qty=1 復活) 未実行 (Takaaki さん次の指示まで実行禁止)
- ❌ 自動的に Step 3 進まない

### 完了基準

- ✅ decision_log success: true
- ⏳ eBay 側 listing qty=0 反映 = Takaaki さん管理画面確認

### Takaaki さん次のアクション

1. eBay seller hub (`https://www.ebay.com/sh/lst/active`) で listing 358454087573 の qty 確認
2. qty=0 反映済 → Step 2c 完了確定
3. 復活希望なら Step 3 (qty=1 化) を別 CSV 生成 + 同じ仕組みで upload

---

## 2026-05-01 — Phase 9c 並走突合 (trabajo vs inventory)

### 決定

- **DELETED → ○ → auto revise の現行ロジックを維持** (Takaaki さん判断)
- 「在庫あり → 在庫なし誤判定 (過剰)」は許容。理由: 機会損失のみで Defect Rate 影響なし
- 「在庫なし → 在庫あり誤判定 (漏れ)」は致命 (キャンセル直結 = Defect Rate 直撃)、ゼロ維持優先

### 変更

- `tools/compare_sheets.py`: 売切判定文字を `{"○", "〇"}` 両対応化
  - `SOLD_MARKS = {"○", "〇"}` 定数追加
  - `_is_sold(v)` ヘルパー追加
  - `diff_sheets` 内の `== "○"` → `_is_sold()` に置換
  - **Why:** 突合初回 (`sheet_diff_20260501_115901.md`) で「全件 0/120」の偽情報が出た真因 = trabajo 側 `〇` (U+3007 IDEOGRAPHIC NUMBER ZERO) と inventory 側 `○` (U+25CB WHITE CIRCLE) の文字コード差。判定 `== "○"` が片方のみ拾っていた。`monitor_listings.py:164` は既に両対応済 (`in ("○", "〇")`)、突合ツールだけ取りこぼしていた

### 検証

- 突合対象: trabajo `19kj8N...` (統合Hight_商品管理シート20260420) vs inventory `1oDjQC8WN_3...` (TEST_統合Hight_商品管理シート)
- 共通 URL: 421 件
- 結果 (修正後 `sheet_diff_20260501_120229.md`):
  - 一致 ○○: **115**
  - 一致 --: 299
  - inventory 漏れ (致命): **0**
  - inventory 過剰: 6 → ユーザー目視確認後 **真の過剰 1 件のみ** (行 413 ポーター ブリーフケース)、残り 5 件は inventory 先回り正解 (trabajo 取りこぼし)
  - trabajo 誤検知 (inventory 正解): 1 (行 66 鬼滅 UT)
- inventory 正答率: **419/421 ≈ 99.5%**、漏れ 0、真の誤検知 1 (0.24%)
- 真の誤検知 1 件 (行 413) の原因: scraper が `raw_status=DELETED` を売切扱い → 出品者一時取下げ等で実際は他で在庫ありの可能性。Defect Rate には無影響のため許容
- pytest 146 passed / 1 failed (`test_live_known_sold_urls[row118-m14968932238]`、live Mercari アクセスの environmental issue で本修正と無関係)

### 次のアクション

- なし (現行ロジック維持)。次回 cycle 後に再突合して傾向継続確認


## 2026-06-03 — Trading API 統一 + amazon scraper 構造修正

5 commit 集約 (d23ad99 / 7b20adc / 2f5a268 / 7663102 / 4351d8e)。 朝の dry-run で
LOW amazon 152 件 偽 OOS が判明 → 順次潰し込み + HQ § 統一指示で監視くん全体を
Selenium FileExchange UI から Trading API direct に統一。

### 決定

- **(d23ad99) amazon scraper fail-closed 致命バグ 2 重 safety net**:
  scrape 失敗 / no_signal → False=取下げ に倒れる構造 (= LOW 152 件 偽 OOS の真因) を
  「raw に in_stock 無し / None → 強制 skip」 + 「Amazon driver 起動失敗 → cycle 即 abort」
  の 2 重 safety net で 構造的再発防止 (Takaaki さん § dont_declare_complete_after_one_cycle)
- **(7b20adc) HIGH/LOW 監視くん の取下げ path = Trading API 統一**:
  sell_feed_uploader (Selenium FileExchange UI) は chromedriver DevTools 2GB
  JSONDecodeError 等で 13:30 cycle 6 件 upload 失敗 = 構造的脆弱性。
  ReviseInventoryStatus direct call に切替、 sell_feed_uploader は緊急時 fallback 残置
- **(2f5a268) 公式監視くん (inventory_monitor) も同じく Trading API 化**:
  HQ § Trading API 統一を scope 拡張。 variation listing 対応のため
  `revise_inventory_status_variation` (= 当初 ReviseInventoryStatus 経路で実装) +
  CSV 自動判定 (3 col single / 6 col variation) を追加
- **(7663102) variation revise は ReviseFixedPriceItem の `<Variations>` 構造**:
  ReviseInventoryStatus は SKU 文字列ベースで VariationSpecifics 不可
  (= err 21916736 "Cannot revise a Multi-SKU item when ItemID alone is supplied")。
  ReviseFixedPriceItem の `<Item><Variations><Variation>` 経路 に修正
- **(4351d8e) 巡回レポート 集計 + DNS 自動 retry**:
  Trading API stdout が旧 sell_feed_uploader 文言と integrated せず
  「variation Revise: 0 件 なし/失敗」 誤表示 (= 実際は eBay 上 反映済)。
  result_text に Success / Transient 追加 + CSV 行数 + ok/ng 件数 明示出力 +
  run_daily 集計 logic 拡張 + DNS/Timeout 系は 同 cycle 内 1 回 自動 retry
- **(運用) cron 全 3 task Enable + LOW スプシ自動化 復活**:
  iMakInventory_Cycle / Cycle_BothDaily0930 / Monitor_Daily を Enable。
  memory `low_sheet_manual_only.md` は事実誤認のため削除
- **(運用) スプシ D=○ 一括同期 291 件 (片方向)**:
  D=空欄 + eBay qty=0/ended の不整合を D=○ 化 (= HIGH 79 + LOW 212)。
  逆方向 audit (D=○ + eBay active qty>0) は DNS fail で pending
- **(運用) ユーザー目視 force_revise 18 件**:
  G-SHOCK 第三者 FBA 11 件 + HIGH mercari/snkrdunk 7 件 = 計 18 件 qty=0 化 (HQ upload)
- **(運用) Profile 復旧 (Amazon + eBay)**:
  Amazon 7.7GB / eBay 2.34GB 巨大化で driver 起動不能。 rename 退避 + 新 profile +
  手動 re-login で復旧。 旧 profile は `*.broken_20260603` に保持 (rollback 用)

### 変更

- `scrapers/amazon_scraper.py:62-89,100-138` (= 販売元 identity gate + fail-closed)
- `monitor_listings.py:141-160,378-410` (= None ハンドリング + driver 起動 retry/abort)
- `ebay_actions/trading_api_client.py` 新規 (= self-contained、 token + revise + variation + GetSellerList)
- `ebay_actions/trading_api_uploader.py` 新規 (= CSV 自動判定 + DNS retry + result_text 拡張)
- `run_cycle.py:51,303-321` (= _phase_upload を Trading API に切替、 sell_feed_uploader は fallback 残置)
- `../iMakeBayAPI/inventory_monitor/auto_qty_zero.py:187,304-309` (= upload_one_csv → trading_api_uploader、 件数 log 追加)
- `../iMakeBayAPI/inventory_monitor/audit_and_heal.py:158-162` (= upload_csv wrapper を Trading API 化)
- `../iMakeBayAPI/inventory_monitor/run_daily.py:73-118,160-185` (= _parse_qty_output + _detail() helper)
- `tests/test_amazon_stock_detection.py:117-148,149-210` (= 販売元 gate 5 検体 + fail-closed 3 件)
- `tests/test_trading_api_client.py` 新規 (= 11 件: Ack 解析 / IAF expired / CSV parse / DNS retry / result_text format)
- スプシ HIGH 79 + LOW 212 行 D=○ batch_update (= 永続)
- cron: iMakInventory_Cycle / Cycle_BothDaily0930 / Monitor_Daily Enable

### 検証

- amazon fail-closed bug fix:
  - HIGH/LOW dry-run pre-fix: LOW newly_sold 152 件 (= 主力 G-SHOCK 多数の偽 OOS)
  - post-fix LOW 再 scan: **newly_sold 152→7 (= -95%)** / 判定不能 (skip) 4/603 = 0.7% (= mass-skip 否)
  - 在庫あり 4 ASIN (B0BQHK77MZ/B0CQP1J8MD/B07VHSZ17W/B0CLR9NNJL) GetItem で in_stock=True ¥12K-32K 確認
- token refresh:
  - mtime 6/2 17:01:51 (HQ findings の 21h 停止) → 6/3 14:56:20 (= IAF expired 自動 retry で 更新)
- HIGH/LOW Trading API 化 E2E:
  - 13:30 cycle 失敗 6 件 CSV を ReviseInventoryStatus で再実行 → 5/6 ack=Warning redundant + 1/6 safe failure 231 = 全 OK
  - GetItem で status=Active available_qty=0 確認
- 公式監視くん variation E2E:
  - 16:42 cycle 全 31 件 失敗 (err 21916736) → 17:34 retry script で 28 件 即 OK + DNS fail 3 件 個別 retry で 全 OK = **31/31 ack=Success**
  - eBay 実機 GetItem 6 検体 (取下げ 4 + 補充 2): variation 単位 qty 全件 期待通り (`Sizes` 単軸 / `Sizes × Color` 多軸 両方)
  - 17:34 単独実行 5/5 ack=Success + result_text "Success 5 + Warning 0 + Transient 0" 出力確認
- 回帰テスト: pre-commit 全 115 件 / commit 別 検体 17→20 件 / Trading API client 6→11 件 全 pass
- スプシ D=○ 同期: ws.batch_update 2 call (HIGH 79 + LOW 212) で 「✓ done」 log 確認
- 18 件 force_revise: HQ upload で Warning 5 + safe Failure 1 + Warning 7 (= 朝 G-SHOCK 11 + HIGH 7) 確認

### 次のアクション

- **明朝 8:00 公式 cycle (= 自動)**: 集計表示 「variation Revise: N 件 (成功) (ok=N / ng=M)」
  へ format 整合確認 + DNS retry 自動発火確認 (= cycle 内 1 件でも fail があれば log で見える)
- **17:30 HIGH cycle (= 自動)**: Trading API path 経由 で qty=0 化が走るか確認、
  巡回レポート format 確認
- **逆方向 audit (= D=○ + eBay active qty>0)** pending: DNS resolver fail で延期、
  `c:/tmp/reverse_audit.py` script 残置、 次回 DNS 復旧後実行
- **HQ 依頼 2 フィギュア棚卸し** pending: amazon scraper bug fix 終結後着手、
  販売元抽出 logic 再利用 (= commit 24a6699 朝の販売元 identity gate + d23ad99 の `_detect_seller`)
- **process 反省**: 7663102 (= variation API 間違い) は memory `reuse_existing_proven_solution.md` 違反 = リバイス君の sell_feed_uploader 経由 variation_upload.py を 先に確認していれば API 仕様検討の trigger になっていた。 次回 worktree 跨ぎ logic 実装時は **既存 worktree で 同種実装の有無を 必ず先に grep** する

## 2026-06-04..05 — 公式監視くん 修復 + Active Listing 取得を Trading API 化

### 決定

- **6/4 朝 cycle 補完を即実行**: 8:00 cycle が 3 step NG (restore / audit_heal / scrape_audit) で
  終わったため、 取下げ未反映 7 件 (= 仕入元切れ × eBay qty>0、 Defect Rate 直撃) を放置
  しないため uuid_sync / K 列同期 / audit_and_heal / scrape_audit を手動再実行で補完。
  Trading API 経由で 12 件 (取下げ 7 + 復活 5) を heal、 GetItem 8 variation で qty 直接確認
- **`_schedule_new_report` UI 失敗時の既存 link fallback 実装** (= 5/29 以降 7 日連続失敗の
  延命): 真因 = eBay reports/schedule の DOM 構造変更で XPath 当たらず。 fallback で
  6/3 dated 既存 link を再利用、 「永遠に DL ゼロ」 を回避
- **SKU シート全行 cycle 内 1 回 cache 化** (= Sheets API 429 防止): 6/4 08:00 cycle 末尾
  8 listing が `Read requests per minute per user` quota 超で取りこぼし発覚。 process_listing
  毎の `read_sku_rows` 連発を main loop 前 1 回読込に集約 (= API read 74 → 1)
- **ErrorCode 21916750 (FixedPrice item ended) を safe_failure 化**: 6/4 09:30 メルカリ
  cycle で ng=1 → 3 cycle 連続 (= 6/2 ConnectionError, 6/3 JSONDecodeError, 6/4 21916750) で
  generic_failure_threshold アラート発火。 sold/expired listing への qty=0 化は dropshipping
  前提では「目的達成済」、 safe codes に追加
- **Active Listing CSV 取得を Trading API GetSellerList Fine に置換** (= 根本対策):
  上記 fallback は短期延命、 根本問題 = Selenium UI scrape の脆弱性 + 「fallback で同 CSV を
  使い続け → 新規 listing が監視対象外になる」 構造。 GetSellerList Fine + IncludeVariations
  で全 active listing を取得 + 既存 CSV column 互換で出力 → 既存 sync_from_csv / audit_and_heal
  無修正で動く。 Selenium 経路は safety net 残置 (= memory `reuse_existing_proven_solution`)
- **17:30 メルカリ cycle DNS failure を手動 Revise で即解消**: 1 件 (358571988843) が
  DNS resolver 一時失敗で transient retry 1 回でも復活せず ng=1。 4h 待たず手動 revise で
  qty=0 化 (= memory `ebay_first_always` Defect Rate 防衛)
- **「正式完了」 宣言を引込め、 145 件大量復活を verify**: 6/5 08:00 cycle で 145 件
  qty=1 復活が走った時、 サンプル 1 件 verify のみで「健全」 と断言したのは
  memory `full_check_before_report` 違反。 10 listing × 28 variation を仕入元 API で再 verify
  → 100% in_stock=True で復活妥当性確定

### 変更

- `iMakeBayAPI/inventory_monitor/ebay_active_listing_dl.py:248-267`
  (= `_schedule_new_report` 失敗時の既存 link fallback、 commit f07788c)
- `iMakeBayAPI/inventory_monitor/main.py:215-235,706-714` (= SKU シート全行 cycle 内
  cache + process_listing の all_sku_rows 引数追加、 commit a891745)
- `iMakInventory/ebay_actions/trading_api_uploader.py:178` (= safe codes に "21916750"
  追加、 commit 292b297)
- `iMakInventory/tests/test_trading_api_client.py:87-95` 新規 (= 21916750 source 検査
  test、 commit 292b297)
- `iMakeBayAPI/inventory_monitor/ebay_active_listing_via_trading_api.py` **新規**
  (= GetSellerList Fine paging + Active Listing CSV 互換 8 column 出力 + DNS retry 5 回
  + IAF auto refresh、 commit 8711aa3)
- `iMakeBayAPI/inventory_monitor/main.py:608-643` (= --ebay-report auto 分岐を Trading
  API 優先 + Selenium fallback に、 commit 8711aa3)

### 検証

- **6/4 補完 cycle**: uuid_sync 70 cells 書換、 K 列同期 159 件補正 (= 5/29 以降ずっと
  古かった K)、 audit_heal Trading API で取下げ 7 + 復活 5 = 12 件全件 ack=Success
- **8/8 variation direct verify (GetItem)**: 取下げ済 7 件 (358381852914 L/XL,
  358359355028 S, 358359565422 XL, 358275199203 BL/S, 358560250231 XXS, 358278977272
  Brown/L) + 復活 5 件 (358275199203 DGN-XL, NV/OG/TQ/YL-S) = 100% qty 期待値一致
- **6/5 08:00 公式 cycle 全 step OK**: monitor (= Sheets 429 エラー 0 件、 a891745 効果)
  / uuid_sync / zero (11 件) / restore (141+4=145 件) / audit_heal (zero 9 + restore 11)
  / scrape_audit (100%、 昨日 90% アラート解消)
- **6/5 13:30 メルカリ cycle 正常**: 取下げ 2 件 ack=Success、 streak 0 維持
  (= 292b297 効果、 21916750 → safe 扱いで ng 化されない)
- **大量復活 sample verify**: random 10 listing (= 50 中 20%) × 28 variation を
  uniqlo / gu API で実 fetch → 100% in_stock=True qty=11 (= scraper 判定 健全)
- **昨日朝 heal_zero 7 件 巻き戻し非発生 verify**: 6/5 08:00 cycle 後に再度 GetItem、
  全 7 件 qty=0 維持確認 (= 復活 145 件に巻き込まれてない)
- **Trading API CSV 互換性 verify**: 19:53 全 24 page fetch (7500 rows)、 既存 6/3 dated CSV
  と diff = 共通 290 variation listings (互換 100%) / 削除 0 / **新規 3 listings
  (358639572937, 358639652237, 358640199261 = 計 21 variations) が 6/3 以降 監視対象外
  だった事実確定**
- **手動 Revise (17:30 救済)**: 358571988843 qty=0 化 ack=Warning (= 23015 Best Offer 警告
  だが qty=0 化 success)
- **pre-commit**: 4 commits 全て 115 tests pass

### 次のアクション

- **明日 8:00 公式 cycle (= 自動)**: Trading API path (= 8711aa3 効果) の log 確認、
  「[Active Listing DL] Trading API (GetSellerList Fine) 開始」 が出るはず + 監視対象に
  新規 3 listings (358639572937 等) が含まれることを確認
- **#7 監査 (= Claude implementation-auditor + Gemini 二次)**: 本セッション 4 commits
  + 実 eBay Revise ~201 件 + スプシ書込 (UUID 70 + K 列 159) の 独立検証。
  HQ 自己申告との乖離 chk
- **DNS retry 増強 (trading_api_uploader)**: 17:30 cycle failure の根本対策。 現状
  retry 1 回 → ebay_active_listing_via_trading_api._post_with_retry と同じ 5 回 + 10s sleep
  パターン展開 (= memory `reuse_existing_proven_solution`)
- **過去 restore NG 真因調査** (緊急度低): 6/2 6/3 6/4 で connectionError / JSONDecodeError /
  21916750 ng と毎回違う原因、 今は self-correct 済
- **K 列同期 「dry-run」 ログ表示** (cosmetic): execute=True で乖離 0 件のとき
  「乖離 0 件、 dry-run」 と紛らわしい文言、 後で確認
- **process 教訓**: Selenium UI scrape は eBay UI 構造変更で永続的に壊れる。 Trading API
  で代替可能なところは API 化 を優先する (= 今回 GetSellerList Fine で完全代替できた)

---

## 2026-06-06 — pending drain 後置化 (transient failure sliver loss bug 修正)

### 決定

- `drain_pending_queue` の呼出位置を **CSV 生成時 → upload 完了後** に移動
- 成功 item (= ack=Success/Warning or safe_failure) のみ drain、 失敗 item は pending 残置
- 失敗 item は次 cycle で sheet D=○ verify を経て自動 re-enqueue (= 構造的に retry)
- 17:30 cycle の 1 件 sliver loss は **手動 revise (358624006440 qty=0、 ack=Warning err=23015) で復旧済**

### 変更

- `ebay_actions/revise_csv_generator.py:538`: drain call 削除 + 説明 comment
- `ebay_actions/revise_csv_generator.py:567` return dict に `mode` / `allowed_item_ids` 追加
- `run_cycle.py:50` import に `drain_pending_queue` 追加
- `run_cycle.py:586` 付近 upload 完了後に `successful_ids = [r["item_id"] for r in u["results"] if r["success"]]`
  → `drain_pending_queue(successful_ids)` 呼出 + 失敗件数 log 出力
- `tests/test_run_cycle.py` に `test_drain_pending_only_on_success` 追加 (Regression guard)

### 検証

- ✅ 全 282 tests pass (新規 1 件含む)
- ✅ Grep 確認: `drain_pending_queue` 呼出は 2 箇所 (`revise_csv_generator.py:260` def + `run_cycle.py` の post-upload call) のみ
- ✅ revise_csv_generator return に新 field 追加、 既存 caller (`run_cycle.py`) は `mode == "pending"` で gating
- ✅ 旧 bug の再現条件 (transient failure → pending から即消滅) は新実装で発生不能
  - new test で `[iid_ok, iid_safe]` の 2 件のみ drain、 `iid_fail` は pending に残る ことを物理担保
- ✅ 手動 revise 実行: `358624006440` qty=0 ack=Warning success=True (err 23015 = informational Best Offer 警告)

### 次のアクション

- **明日 cycle 観察**: 17:30 cycle 後の `decision_log/trading_api_upload_*.jsonl` で
  ng>0 のとき pending に該当 item が残ってるか実機確認
- **DNS retry 増強 (元 TODO)**: trading_api_uploader._is_transient_failure 用 1-時 retry を
  ebay_active_listing_via_trading_api._post_with_retry と同等 (5 回 + 10s) に展開
  → 今回の drain 後置 化で sliver loss 不能化したため緊急度は下がった、 別 turn で着手
- **reverse_audit (memory `reverse_audit_pending`)**: 別系統の補完監査として残置、 D=○ +
  eBay active qty>0 検出 logic は cycle 末尾 phase 化検討

---

## 2026-06-09 — pending queue auto-prune (肥大化防止)

### 決定

- `collect_from_pending_queue` の verify で `no_longer_sold_or_id_changed` 判定された
  entry を pending file から物理削除し、 `discarded_revise.jsonl` に archive する
  構造修正 (= 「2026-06-02 amazon scraper bug 由来の 158 件等が永続蓄積」 問題)
- 削除は **sheet verify 成功** 時のみ。 sheet 読込失敗 (skip_reason 無し) / 別 sheet の
  filter_* skip は誤削除しない安全側設計

### 変更

- `ebay_actions/revise_csv_generator.py:79` `DISCARDED_REVISE_FILE` 定数追加
- `ebay_actions/revise_csv_generator.py:260` `prune_discarded_entries(skipped)` 追加
  - skip_reason="no_longer_sold_or_id_changed" のみ対象、 archive に
    `discarded_at` / `discard_reason` field 付与
- `ebay_actions/revise_csv_generator.py:485` `run()` 内、 `collect_from_pending_queue` 直後で
  prune 呼出 + 件数 log 出力
- `tests/test_run_cycle.py::test_prune_discarded_entries_only_no_longer_sold` 追加
- 既存 167 件 (LOW 166 + SHEET 1) を実機 sheet verify 経由で全件 archive 実行 →
  pending file 0 件 / discarded file 167 件

### 検証

- ✅ 全 283 tests pass (新規 1 件含む)
- ✅ 4 種の skip 状況 (no_longer_sold / filter_low / sheet_read_fail / valid) で
  no_longer_sold のみ削除されることを test で物理担保
- ✅ live sheet verify 実走で 167 件全てが `no_longer_sold_or_id_changed` と判定 →
  全件 archive 安全と確認 (sheet 上で ○ 残存ゼロ)
- ✅ 実機 prune 実行: pending 167 → 0、 discarded 0 → 167
- ✅ 主因 (158 件) は 2026-06-02 amazon scraper fail-closed bug 由来 (= memory
  `amazon_scraper_fail_closed_bug` で 解決済の偽 OOS 残骸)

### 次のアクション

- **明日 09:30 `--sheet both` cycle 観察**: 新 prune 経路の log
  「pending prune (sheet で ○ 解除済): N 件 → discarded_revise.jsonl」 が 0 件出力
  (= 新規蓄積なし) になっているか確認
- **discarded_revise.jsonl size 監視**: 蓄積 file なので backup_inventory.ps1 の
  rotation 対象に含めるか検討 (= 緊急度低、 当面 167 件で size 微小)

---

## 2026-06-10 — sliver loss 根絶 Phase 1 (HQ FINAL 確定指示 A/B/C 実装)

### 決定

- 過去 5 週間に 156 件規模の silent sliver loss が発生していた事実発覚
  (= ユーザーが 358596670518 を指摘 → reverse_audit で 11 件発見 + 全件 qty=0 化救済)
- 真因 = (i) 旧 Selenium FileExchange UI 経路の脆性 (6/3 commit 8711aa3 で Trading API 化済)
  + (ii) drain-before-upload bug (6/6 commit 5716879 で drain 後置化済)
  + (iii) **私の 6/9 commit b4c238d の prune_discarded_entries が sheet D=空 だけで** archive
  → 6/10 09:30 で sheet 書込 DNS fail 由来の偽 D=空 で 2 件 silent drop 発生
- HQ FINAL 設計指示 (= `_FINAL_design_directive`) 確定:
  - 「取り下げるべきもの」 はそのサイクル内で eBay qty=0 を確認するまで閉じる
  - 「除外」 を silent でなく「未取下げ=要対応」 として明示
  - 「正常」 は全件 qty=0 確認できた時のみ

### 変更

- `ebay_actions/revise_csv_generator.py:263` `prune_discarded_entries` を fail-CLOSED 改修
  - sheet D=空 だけでは discard しない、 **eBay GetItem qty=0 確認後にのみ** discard
  - eBay qty>0 残存 entry は pending 残置 + **再 include 候補に格上げ** (= sheet 状態誤と判定、 silent loss を逆に救済)
  - GetItem 失敗時は保守的に pending 残置
  - return 値: `int` → `{"discarded": N, "kept_qty_gt0": M, "reincluded": [..]}`
- `ebay_actions/revise_csv_generator.py:619` 付近 `run()` で reincluded 候補を CSV 対象に追加
- `ebay_actions/trading_api_uploader.py:96` `INCYCLE_RETRY_INTERVALS_SEC = [5.0, 15.0, 45.0]`
  module-level 追加
- `ebay_actions/trading_api_uploader.py:170` `_verify_qty_zero(item)` 関数追加
  (= revise 後 GetItem で qty=0 確認、 err 17 は qty=0 同等扱い)
- `ebay_actions/trading_api_uploader.py:175` 付近 in-cycle short retry loop 実装
  (revise → verify → NG なら 5s/15s/45s で再 revise + 再 verify、 最大 4 試行 = 65s 上限)
- 失敗時 entry に `verified` / `verify_qty` / `verify_msg` / `verify_attempts` field 追加
- `monitor_listings.py:304` `ACTION_REQUIRED_FILE` + `append_action_required` 追加
  (HQ 原則 B、 silent 除外禁止)
- `monitor_listings.py:533` 付近 newly_sold + item_id 空欄 → silent 除外せず action_required 化
- `run_cycle.py:50` `drain_pending_queue` import 修正
- `run_cycle.py:610` 付近 upload 完了後 verify-failed item を action_required.jsonl に記録
- `run_cycle.py:689` 付近 cycle 末尾で action_required の cycle 内集計 →
  `cycle_log["phases"]["action_required_summary"]` 格納
- `email_notifier.py:204` 付近 メール冒頭 1 行に
  `取下げ: 売切検知 N → 完了 X / 未取下げ Y` + `結果: ⚠️ 要対応 (取下げ漏れ Y件)` or
  `結果: ✅ 全件取下げ完了` (= HQ 原則 C)
- 旧 cycle_log 形式との後方互換性確保 (= action_required_summary 未投入時は status_jp fallback)
- `tests/test_run_cycle.py` 既存 test 1 件改修 (`test_prune_discarded_entries_requires_ebay_qty_zero`)
  + 新規 2 件追加 (`test_email_header_shows_untaken_count_when_action_required` /
  `test_in_cycle_verify_blocks_silent_success`)
- HQ 依頼書 2 本 `_processed` リネーム + iMakRevise feasibility 依頼書投入
  (`c:/dev/iMak_data/revise/requests/2026-06-10_price_revise_sliver_loss_feasibility.md`)

### 検証

- ✅ 全 185 tests pass (新規 2 件 + 既存改修 1 件含む、 live scraper test 除く)
- ✅ Email format 模擬 cycle_log で動作確認:
  - 要対応 2 件 → `売切検知 4 → 完了 2 / 未取下げ 2` + `⚠️ 要対応 (取下げ漏れ 2 件)` ヘッダ
  - 全件完了 → `売切検知 3 → 完了 3 / 未取下げ 0` + `✅ 全件取下げ完了` ヘッダ
- ✅ Regression test `test_in_cycle_verify_blocks_silent_success`:
  revise が Ack=Success でも GetItem qty=5 なら success=False / verified=False / verify_attempts>=3
- ✅ Regression test `test_prune_discarded_entries_requires_ebay_qty_zero`:
  qty=0 → discard / qty>0 → 再 include / API 失敗 → 保守的に保持 / filter skip → 触らない
- ✅ Reverse audit 6/10 実行で発見した 11 件全件 qty=0 化済 (= 156 件型の事後収束)
- ✅ HQ 信頼回復 5 点 のうち 1 (失敗注入回帰テスト) 完了

### 残課題 (= Phase 2 候補)

- 案 B 自動 re-enqueue (= 定期 reverse_audit を cycle phase に組込) — Phase 1 効果観察後
- Bulk Change Circuit Breaker (newly_sold 率異常検知) — commit d23ad99 既存実装の調査先行
- グローバル CLAUDE.md 原則追記 (「1 回失敗 = 永久放置 禁止」) — HQ 側で別セッション
- DLQ resurrection CLI (`cli.py resurrect-dlq <iid>`) — action_required.jsonl からの戻し経路
- 公式監視くん audit_and_heal の reconciliation 網羅性 再監査 (HQ 横断指示)
- iMakRevise feasibility 回答待ち (= 価格 revise の sliver loss 有無)

### 次のアクション

- 次 cycle (= 13:30 SHEET 単一 cycle) で新 logic 実走、 ログ + メール冒頭 1 行を実機確認
- 明日 09:30 `--sheet both` cycle で 6/10 同型 (= sheet 書込 fail 発生時) の動作確認
- iMakRevise 回答 / Phase 2 着手判断は 1-2 週間運用後

---

## 2026-06-10 (続き) — Phase 1.5: 急増ガード + reverse_audit + HQ 3 条件反映

### 決定

HQ confirm 指示 (= `requests/2026-06-10_phase1_review_burstguard_and_reconciliation_deadline_processed.md`)
の 3 条件を反映して Phase 1.5 着手:
- **条件 A**: 急増ガード閾値 「20 件」 を盲決めせず実機データで校正、 env var で configurable 化
- **条件 B**: reverse_audit 「6/12 乖離 0 件」 を成功条件にせず、 初回乖離鳥瞰を 「audit 動作の証拠」 と
  位置付け。 0 件目標は隠ぺい圧力 = fail-OPEN 再発リスク
- **条件 C**: auto-fix defer 中も検知→alert→人手 loop を回す、 手動 SLA 明記

### 変更

1. **急増ガード (`revise_csv_generator.py:99`)**:
   - `DEFAULT_REINCLUDE_BURST_THRESHOLD = int(os.environ.get("INVENTORY_REINCLUDE_BURST_THRESHOLD", "10"))`
   - 実機 校正データ: 通常 cycle 0-2 件 / 6/10 09:30 sheet 書込 fail 2 件 / 6/9 sweep 167 件 (= 一回限り)
   - デフォルト 10 件 = 通常の 5 倍マージン
2. **HOLD 経路 (`revise_csv_generator.py:644`)**:
   - reinclude > 閾値 → 全件 HOLD + `action_required.jsonl` に reason=`reinclude_burst_guard_holdout` で記録
   - silent化禁止 = HQ A 条件遵守
3. **reverse_audit (`reverse_audit.py` 新規)**:
   - `run_reverse_audit()`: HIGH/LOW sheet D=○ vs eBay GetSellerList qty>0 突合
   - read-only 検知 + `decision_log/reverse_audit_<ts>.jsonl` 機械可読 log 出力
   - sheet 読込失敗時は fail-CLOSED 中断 (= 「乖離 0 件」 と誤読される partial result を出さない)
4. **cycle 統合 (`run_cycle.py:686`)**:
   - Phase 5 として組込、 `--sheet both` cycle のみ実行 (= 4h 単一 cycle は API quota 考慮で skip)
5. **email 文言 (`email_notifier.py`)**:
   - reconciliation セクション追加: 乖離 > 0 → 「初回 = 既存乖離鳥瞰、 audit 機能の証拠 / 当日内に件数を減らす目標は不要、 人手で順次潰す」
   - 乖離 = 0 → 「✅ 乖離 0 件 (継続証跡を 1 件積上げ)」
   - action_required ブロックに対応期限明記: 通常 `4 時間以内` / 急増ガード発火時 `即時`
6. **regression test (`tests/test_run_cycle.py`)**:
   - `test_burst_guard_holds_mass_reinclude_to_action_required`: 閾値超で全件 HOLD + action_required 記録
   - `test_reverse_audit_email_uses_hq_b_wording`: 「0 件目標」 文言禁止 + audit 機能の証拠表現確認

### 検証

- ✅ 全 187 tests pass (新規 2 件 + 既存全件)
- ✅ 急増ガード閾値が env var INVENTORY_REINCLUDE_BURST_THRESHOLD で override 可能
- ✅ HOLD entry が action_required.jsonl に記録される (= silent 化禁止条件遵守)
- ✅ reverse_audit logic は sheet 読込失敗時 fail-CLOSED 中断 (= 「乖離 0」 と誤判定しない)
- ✅ メール本文に対応期限明記 (HQ C 手動 SLA)

### 信頼回復 5 点 進捗

| # | 項目 | 状態 |
|---|---|---|
| 1 | 失敗注入回帰テスト | ✅ 完了 (commit 300dc8f + 本 commit で計 5 件) |
| 2 | アラート実送テスト | ❌ 未実施 (6/11 中に手動発火実証予定) |
| 3 | reverse_audit 継続乖離なしレポート | 🟡 phase 実装完了、 6/12 09:30 初回出力 (= 初回は既存乖離が出る前提) |
| 4 | 156 件 qty=0 化証跡保全 | ✅ 完了 (6/10 sweep + reverse_audit xlsx 保全) |
| 5 | 「動く証拠で示す」 | 🟡 #2/#3 で達成見込 (6/12 完了予定) |

### 次のアクション

- 13:30 SHEET 単一 cycle で Phase 1 logic 実走確認 (= ログ + メール冒頭 1 行)
- 17:30 / 21:30 / 6/11 01:30 / 05:30 順次確認
- **6/11 09:30 `--sheet both` cycle で reverse_audit phase 初回実走**
  - 既存乖離 (= 5 週間分の積残 + 6/10 sweep で qty=0 化済の 11 件 + ユーザー手動 fix 済 145 件相当) が
    出る想定、 HQ B 条件通り 「audit 動作の証拠」 として表示される
- **6/12 09:30 cycle で 「継続乖離なし」 の初回証跡記録** (人手で 6/11 中に既存乖離を潰した前提)
- 信頼回復 #2 (アラート実送テスト) を 6/11 中に並行実施
- iMakRevise feasibility 回答待ち
- Phase 2 (auto-re-enqueue / Bulk Change Circuit Breaker / DLQ resurrect CLI) は 1-2 週運用観察後判断

---

## 2026-06-10 (続続) — Phase 1.6: 取下げ側急増ガード + release CLI (HQ affirm 2 点)

### 決定

HQ confirm 指示 (= `_phase1_5_metrics_alignment_response`) で承認、 HQ Phase 1.6 GO 投入指示
(= `_phase1_review_burstguard_and_reconciliation_deadline_processed` の続報) の 2 affirm 反映:
- **affirm #1**: burst HOLD が新 fail-OPEN にならないこと、 即時 SLA + release 経路が load-bearing
- **affirm #2**: 22-29 件帯の隙間は reverse_audit が backstop、 newly_sold 乖離も突合対象に含む

加えて、 Phase 1.5 daily_report の **校正データ訂正**:
- 私の記述 「実機校正データ: 通常 cycle 0-2 件」 は no_longer_sold (= prune 親集合) 分布で、
  急増ガード発火メトリクス reincluded (= 子集合 = eBay qty>0 と判定された subset) ではなかった
- 正しい reincluded 実機分布は 過去全て 0 件 (= 6/9 167 件も 6/10 2 件も全件 qty=0 で discard)
- 閾値 10 件 は conservative マージンとして維持、 透明性確保のため明示訂正

### 変更

1. **取下げ側急増ガード (`revise_csv_generator.py:106`)**:
   - `DEFAULT_NEWLY_SOLD_BURST_THRESHOLD = int(os.environ.get("INVENTORY_NEWLY_SOLD_BURST_THRESHOLD", "30"))`
   - 実機 newly_sold 分布校正 (= 189 cycle 集計): 中央 2 / 平均 4.4 / 90 %tile 6 / 95 %tile 10 / 通常 max 21
     / 偽 OOS incident 50/95/152 件
   - 閾値 30 件 = 95 %tile の 3 倍、 通常 max 21 + 50% マージン、 偽 OOS 100% catch
2. **HOLD 経路 (`revise_csv_generator.py:729`)**:
   - candidates 件数 > 閾値 → 全件 `action_required.jsonl` に reason=`newly_sold_burst_guard_holdout` 記録
   - candidates を空にして以降 CSV 生成 / upload を skip
3. **release CLI (`tools/release_holdouts.py` 新規 ~250 行)**:
   - `--reason` / `--item-id` でフィルタ、 `--execute` で本実行 (default dry-run)
   - eBay 現状 qty 確認 → revise qty=0 投入 → verify → ledger 記録 (released_revise.jsonl + processed_revise.jsonl)
   - action_required.jsonl から release 済 entry 物理削除
4. **reverse_audit (`reverse_audit.py` 冒頭 docstring)**:
   - HQ affirm #2 backstop 機能を明示: 22-29 件帯通過分 + burst HOLD 放置分も
     「sheet D=○ vs eBay qty>0」 で必ず検出される relationship を 物理担保
5. **email (`email_notifier.py`)**:
   - burst HOLD (newly_sold/reinclude いずれか) 検出時:
     - 「load-bearing: HOLD のまま放置 = 出品継続 → 無在庫履行不能」 警告
     - release CLI コマンド (dry-run + execute) を本文記載
     - 対応期限 「即時」
6. **regression test (`tests/test_run_cycle.py`)**:
   - `test_newly_sold_burst_guard_holds_to_action_required`: 6 件 candidates > 閾値 5 → 全件 HOLD
   - `test_email_includes_release_cli_for_burst_holdouts`: release_holdouts CLI / `--execute` / 「即時」 が本文出現

### 検証

- ✅ 全 189 tests pass (新規 2 件)
- ✅ release CLI が `--help` で help 表示、 dry-run 動作確認
- ✅ 3 系統独立防護構造完成:

| ガード | 検知対象 | 閾値 | env var |
|---|---|---|---|
| per_run_cap | CSV 行数 | 100 (--force 解除可) | --max-per-run |
| **newly_sold burst** (Phase 1.6) | **scraper 系異常 (= 偽 OOS、 6/3 95件型)** | **30** | `INVENTORY_NEWLY_SOLD_BURST_THRESHOLD` |
| reinclude burst (Phase 1.5) | sheet 書込系異常 (= 6/10 09:30 型) | 10 | `INVENTORY_REINCLUDE_BURST_THRESHOLD` |

### Phase 1.5 校正データ訂正

> 校正データの母集団 訂正: 「通常 cycle 0-2 件」 は no_longer_sold (= 親集合 = prune 入口) 分布で、
> 急増ガード発火メトリクス reincluded (= 子集合 = eBay qty>0 と判定された entry) ではなかった。
> reincluded 実機分布は 過去全て 0 件、 閾値 10 件は transient/レース由来 false positive 用 conservative
> マージンとして維持。

### 次のアクション

- 13:30 SHEET 単一 cycle で Phase 1 logic 実走確認 (= Phase 1.5/1.6 のガード自体は両 sheet cycle 専用)
- **17:30 / 21:30 / 6/11 01:30 / 05:30** 順次確認、 異常なしのまま継続
- **6/11 09:30 `--sheet both` cycle で Phase 1.5/1.6 + reverse_audit phase 全部実走**
- **6/12 09:30 cycle で 「継続乖離なし」 の初回証跡記録** (人手で 6/11 中に既存乖離を潰した前提)
- 信頼回復 #2 (アラート実送テスト) を 6/11 中に並行実施
- iMakRevise feasibility 回答待ち
- Phase 2 (auto-re-enqueue / DLQ resurrect CLI) は 1-2 週運用観察後判断

13:30 実走 + 6/12 初回 reverse_audit レポート まで 「対策進行中 (未解決)」 スタンス 維持 (= HQ 指示)。

---

## 2026-06-10 (続続続) — 3 sheet manual 巡回 残課題 (= BAN risk 残存)

### 巡回結果

- 公式監視くん (= variation 系) 15:39-15:59 完了
- iMakInventory cycle (= --sheet both) 15:39-18:05 完了 (2h 26 min)

### メール 2 行ステータス (= ユーザー要件 2026-06-10、 commit `5693dc8` 効果)

```
仕入元在庫監視 : ⚠️ 要対応 (1708 件中 通信エラー 23 件 (1.3%))
eBay 在庫調整  : ⚠️ 要対応 (売切検知 14 → 完了 5 / 未取下げ 9)
```

### 既解決 case (= 今 session 内で対応完了)

- LOW row 548 (= A 列 URL 不正 + ended listing) → ✅ 削除済
- 356901158380 (verify NG) → ✅ false positive (= 私の verify ロジック bug、 commit `9d4794b`
  で `available = Quantity - QuantitySold` 修正)、 release ledger 整理済
- 8 件 PSA10 ポケモン (item_id 空欄) → ✅ 未出品扱い (= ユーザー指示、 commit `5ef4554`
  で action_required 化やめる)

### **★残課題 (= BAN risk 残存、 user 判断要)**

| # | 件数 | 種別 | 状態 | BAN risk |
|---|---|---|---|---|
| 1 | 16 件 | **amazon fail-closed (= scraper returned None)** | **profile 由来の常態的失敗** | **顕在化前提** |
| 2 | 1 件 | fril fail-closed (HIGH row 9) | 未着手 | 単発、 次 cycle 動向次第 |
| 3 | 5 件 | mercari chromedriver ReadTimeout | 未着手 | chromedriver 状態次第 (= 半 transient) |

### 最重要 — amazon 16 件

amazon 16 件は **scraper returned None (= 判定不能)**。 真因 = **amazon login profile 由来の
常態的失敗** (= memory `amazon_scraper_fail_closed_bug` 同型再発の疑い)。

**profile 修復しない限り、 次 cycle も同じ row で再失敗** = 「scrape 不能 + eBay qty>0 維持」
が継続 = **BAN risk 顕在化前提**。

判定不能 17 件 (amazon 16 + fril 1) の扱いは memory `dont_make_my_own_judgment.md` 制定により
私 (Claude) が indirect 推論で決めない。 ルール直接 citation できない grey zone:
- memory `precision_priority_over_recall.md` は 「判定誤差」 を対象 (= 判定不能はカバー外)
- グローバル CLAUDE.md L201-205 「fail-OPEN を許さない」 は取下げ失敗 (= revise 投げて失敗) が
  対象、 「判定不能で revise 試行すらしてない」 状態は直接 cover してない

→ **user 判断仰ぐ**:
- A. 17 件全件 qty=0 化 (= 過剰検知扱い、 在庫戻ったら復活、 BAN risk 即排除)
- B. amazon profile 修復先行 (= scraper を信頼可能にしてから判定)
- C. 17 件 manual 1 件ずつ確認

### 該当 row 詳細 (= user 判断用)

**fril 1 件**:
- HIGH row 9 iid=356740464475 supplier=fril
  URL: https://item.fril.jp/ff877496fe231fb8abec03d5c0f1eb50
  title: ONEPIECE Tシャツ

**amazon 16 件**:
- LOW row 519 iid=357019640381 (TAMASHII 仮面ライダードライブ)
- LOW row 520 iid=357019640383 (TAMASHII アイカツスターズ! 桜)
- LOW row 533 iid=357026358233 (TAMASHII 仮面ライダーエグゼイド)
- LOW row 535 iid=357026358239 (TAMASHII アベンジャーズ ドクター)
- LOW row 537 iid=357056658663 (TAMASHII 仮面ライダーマッハ)
- LOW row 539 iid=357056658669 (TAMASHII アイアンマン マーク4)
- LOW row 547 iid=357063698234 (TAMASHII アントマン&ワスプ)
- LOW row 549 iid=357063698239 (TAMASHII ウルトラマンオーブ)
- LOW row 550 iid=357063698240 (S.H.Figuarts 仮面ライダー鎧武 バロン)
- LOW row 557 iid=357106027062 (TAMASHII アベンジャーズ ドクター)
- LOW row 559 iid=357106027065 (TAMASHII スター・ウォーズ)
- LOW row 561 iid=357106066458 (TAMASHII ウルトラマンジード)
- LOW row 610 iid=356777776711 (TAMASHII ドラゴンボールZ セル)
- (+ 他 3 件、 詳細 logs/listings_LOW_20260610_180304.jsonl)

### mercari chromedriver timeout 5 件 (= 半 transient、 次 cycle で動向確認)

- HIGH row 731-733, 737 (PSA10 系)
- LOW row 155

### 構造的気づき (= 別 turn 着手候補)

- amazon scraper 「判定不能 = 触らない」 設計が fail-OPEN になる case (= 取下げ漏れ) の判定基準が
  ルールに未明示 = grey zone。 ルール拡充 (= 「判定不能 = 取下げ実行」 or 「判定不能 N 回連続で
  アラート」 等) 要検討
- amazon profile 復旧手順の標準化 (= 6/3 commit d23ad99 で fail-closed bug は修正済だが、 profile
  自体の脆弱性は構造的)
- 「次 cycle 待ち」 が grey zone の場合の暫定 SLA を rule 化 (= 何 cycle 持続したら escalate するか)

### 次のアクション

- amazon profile 修復 → 別 session or 手動 (= 私が指示せず、 user 判断 / 別 session 起動次第)
- 17 件の扱い (qty=0 化 vs profile 修復先行 vs manual chk) は user 判断待ち
- スケジュール再有効化は本 17 件の扱い確定後に判断



---

## 2026-06-10 (続続続続) — 判定不能23件 再調査 + 3構造修正 + variation verify 修正

### 判定不能23件 再調査 (= reflex/丸投げ禁止、再調査主義確立)

- 決定: scraper None は「売れた」でない。実URL再scrape/WebFetchで真因分類してから処置。
- 変更: <方針>（memory indeterminate_means_investigate_root_cause.md 制定）
- 検証: 23件内訳 = mercari 6 在庫あり(transient) / mercari 2 auction / amazon 13 第三者のみ /
  fril 1 OOS / 未出品 1。 17件は eBay取下げ確認済(active CSV照合)、6件正常。

### 構造修正3点 (commit 3324cb7)

- 決定/変更/検証 (1) mercari auction化 → 取下げ対象:
  - scrapers/mercari_scraper.py _detect_via_selenium に bid-button検知追加 → AUCTION/in_stock=False
  - 旧: container 30s timeout→None で取下げされず fail-OPEN。 live 2件で AUCTION/False 確認。
- 決定/変更/検証 (2) item_id空欄 = 未出品 skip:
  - monitor_listings.py process_sheet 冒頭で空欄行 skip (skipped_no_item_id、 sheet書込も触らない)
  - scraper None/error でも errors計上しない。 test_blank_itemid_skip.py 追加。
- 決定/変更/検証 (3) eBay取下げ済×sheet未売切 → review シート:
  - reverse_audit.py run_ebay_down_sheet_active_audit 新設。 active map空=fail-closed。
  - run_cycle.py 09:30 both cycle に Phase 5b 組込(qty_map共有)。
  - 初回 live orphan 239件(qty=0:74/ended:165) を HIGH/LOW タブに書出済。 test 追加。

### variation verify per-SKU化 (commit f0eb3a3)

- 決定: 多variation listing の qty=0 verify は対象SKUの available(Quantity-QuantitySold)で判定。
- 変更: trading_api_client.py _call_trading に raw_xml_cap引数(None=cap解除)。
  trading_api_uploader.py _extract_variation_available新設 + _verify_qty_zero variation対応。
- 検証: 公式の「qty=0失敗3件」は実は取下げ成功済。 verifyが listing合計(22/41/3)を読む false-NG。
  実3件で per-SKU available=0 → verified=True 確認。 test_variation_verify.py 5件。 全293 pass。

### reverse_audit 取下げ漏れ 0件 確認

- 検証: sheet D=○ + eBay qty>0 = 0件 (= BAN risk 方向クリア、 最重要証跡)。

### スケジュール再開

- 決定: 全系統クリア確認後、 4タスク再有効化。
- 変更: iMakInventory_Cycle(SHEET 4h, 次21:30) / _Backup(04:00) / _Monitor_Daily(公式 08:00) /
  _Cycle_BothDaily0930(HIGH/LOW+audit 09:30) を Enable。
- 検証: Get-ScheduledTask で State=Ready / NextRun 確認済。

### 残課題 (user 対応 / 別タスク)

- ebay_down orphan 239件 → 「在庫あり・eBay取下げ済」シートで user レビュー。
- amazon 第三者のみ化 自動検知 → user 指示「今はいい」で見送り (検知シグナル=他の出品者あり+buybox無し は特定済)。

## 2026-06-16 — mercari ReadTimeout 真因解消 + AK巡回ERR 自己修復バグ修正

### mercari driver eager 化 (commit bc91e03)

- 決定: mercari driver を page_load_strategy=eager + set_page_load_timeout(45) 化。
- 変更: scrapers/mercari_scraper.py create_driver。
- 検証: 重い PORTER ページ(row754/757)が 3 cycle 連続 localhost ReadTimeout していた真因 =
  既定 strategy="normal" が load イベント(画像/サブリソース全部)待ち。eager(DOMContentLoaded返却)で
  load 依存除去、状態判定は WebDriverWait(30s)が担保。新 test 37件 pass + live ON_SALE 2/SOLD_OUT 2 確認。
  本番効果: 翌日以降 mercari ReadTimeout 0件継続、HIGH cycle 43分→33分。

### row728 reverse_audit 誤検知 → 過剰処置の反省 (コード変更なし)

- 決定: reverse_audit 乖離 1件(row728 トゲキッスV: D=○ + eBay qty=1)を fail-OPEN と誤認し qty=0 化したが、
  実態は user のキャンセル後 手動再販(正当な qty=1)。qty=1 に復元。コード修正は不要と確定。
- 変更: <未実装> (row728 は巡回前に URL クリアし忘れ→cycle が D=○ 付与→手動 qty=1 と乖離しただけ)。
- 検証: eBay GetItem で qty=1/Active 復元確認。reverse_audit は read-only 人手レビュー用で自動処置しない方針を再確認。
  memory dont_act_on_audit_alert_without_human_review.md 制定。

### AK巡回ERR 自己修復クリア + 連続カウント 永久不発火バグ修正 (commit 9e67374)

- 決定: _build_row_result が結果 dict に err_flag_prev を含めていなかった真因を修正(1行追加)。
- 変更: monitor_listings.py _build_row_result に "err_flag_prev": row.get("err_flag_prev","") 追加。
- 検証: 旧バグで clear_err が常に False → (1)成功 scrape しても AK 列が永久にクリアされない(06/11からの×1 marker
  48件堆積) (2)error 再mark の count が常に×1 → PERSISTENT_THRESHOLD「要手動chk」永久不発火。
  新 test_err_flag_prev_propagation.py 5件(失敗注入で fix無し時 4件 fail 確認)、pre-commit 115件 pass。
  公式監視くん(iMakeBayAPI/inventory_monitor/main.py)は別実装で err_flag_prev 直接使用=影響なしを確認。
- 後処理: 堆積していた古い marker を一括クリア(HIGH 48件→0 / LOW 18件→0、verify 残0)。
