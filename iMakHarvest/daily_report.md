# iMakHarvest daily_report

## 2026-08-18 — 鑑定番号が読めなかった出品も I列空欄で投入 (user 指示)

- 決定 (user): 写真から cert が読めなかった分 (前回76件) は捨てずに中間スプシへ入れる。
  **I列は空欄**にしておき、目視で確認する。grade が PSA10 でない等「対象外と分かった」分は従来通り捨てる。
- 安全性: 出品くんの入口は `I列(cert#)非空 AND B列空 AND A列非空`。I列空欄で入れる限り
  自動では出品に回らないので、目視で番号を入れて初めて対象になる。
- 変更 (`run_harvest_mercari_psa10.py`): `unreadable` を候補と別に持ち回り (途中セーブ/再開にも載せる) /
  `build_sheet_items()` を純関数として切り出し、読めなかった分は cert="" で書込 / ログに「番号読めず N件」。
- 検証: offline test 838 passed (+4、うち1本は「読めなかった行に他候補の cert が紛れない」回帰)。
  実機 dry-run (OP01・5件) で新経路の走行を確認。

## 2026-08-17 (続2) — PSA10 ワンピース49語 本走行 完了

- 実行: `python run_harvest_mercari_psa10.py --games onepiece --save-every 10` (19:51-21:36、非headless)。
  途中落ち無し (`item_error` 6件は 1件ずつ隔離されて走行は継続 = 8/17 の crash-safety 修正が効いた)。
- 結果: 収集 487件 → **候補 224件を `mercari_psa10` に投入** (合計230行、H列/I列とも全行充足)。
  reject: grade_not_psa10 60 / cert_unreadable 76 / seller_rating 51 / already_claimed 22 / sold 8 /
  title_cert_conflict 3。vision_error 0 (Vision は事前に実機で読取確認済)。
- ★**残務 (user 判断: 次回でよい)**: **ページ取得に失敗した42件が未判定** (fetch_fail 36 + item_error 6)。
  取りこぼしなので次回走行で拾う。対象 URL は `debug/mercari_psa10_20260817T195108.json` に残っている。
- 残務 (継続): pokemon/dragonball/gundam の本走行は未実施。

## 2026-08-17 (続) — ポーターの H列 (商品説明) 空欄を是正 (user 指摘)

- 事象: `mercari_porter` 76行中 56行の H列が空欄。8/15 19:09 の走行分が全件空 (JSON dump でも 0/61)。
  8/15 18:23 の走行分 (20行) は全件入っている。コードは 5/5 から無変更 = 環境要因。
- 根因: 説明が購入ボタンより遅れて描画されると、`_extract_description` が一発 find で空文字を返し、
  **そのまま空欄で書かれて「正常終了」していた** (silent 空欄 = fail-OPEN)。実測で説明は
  購入ボタンの 0.03〜0.17 秒後に出る (今日の実機3件) ので、負荷が高い時に落ちる。
- 変更: `_extract_description` を出現待ち (5秒 poll) + `.text` が空なら `textContent` で拾う /
  取れなければ `description_missing=True` を返す / porter runner が ⚠️要対応として件数と URL を出す。
  `tools/backfill_mercari_description.py` 新設 (H列空欄の行を URL から埋め直す)。
- 是正: 56行を埋め直して **75/76 に回復**。残り1件 (`m35430690763`) は出品が削除済で取得不能。
- 検証: 実機で headless / 非headless とも説明取得OK。offline test 834 passed (+4)。

## 2026-08-17 — メルカリ PSA10 収集 + 売れたPSA10の再仕入れ を新設 (user 依頼)

### ① メルカリ PSA10 収集 (「ポーターのように PSA10 も」)

- 決定: ポーターと同じ流れ (検索→詳細→セラーフィルタ→中間スプシ) で、**カード特定の段だけ追加**。
  「どのカードか」が確証できない物は通さない (出品正確性原則)。
- 変更: `scrapers/psa_slab_vision.py` (スラブ写真から Vision でラベル読取) /
  `scrapers/psa_cert.py` (psacard.com 照会 + ラベル多信号突合 + 通信不要の `local_gate`) /
  `run_harvest_mercari_psa10.py` 新設。`sheet_writer*.py` に `COL_CERT` (I列) 追加。
- 検証: 実走で ワンピース19件収集 → 候補6件を中間スプシ `mercari_psa10` に投入 (appended=6)。
  6件とも Vision が読んだ英字ラベルと日本語出品名が弾番号込みで一致。offline test 830 passed。

- 決定 (2026-06-24 の PSA cert OCR 保留を解除): **公式照会は出品くん (iMakTCG) に 1本化**。
  user 指摘「PSAの新規出品でもブロック対策しているでしょ」を受けて `psa_to_csv.py` を確認したところ、
  Cloudflare 対策 (`_psa_cloudflare_warmup`: visible 起動→user 手動突破→同driver流用 + 1件15秒) と
  入口 (`I列(cert#)非空 AND B列空 AND A列非空`) が既にあった。同じIPで二重に叩くと制限を食い合う。
- 変更: Harvest 側の PSA 照会は既定 OFF (`--verify` で任意)。Harvest は通信不要の事前ゲート
  (cert桁数 / ラベルのグレード / 出品タイトル末尾4桁 vs cert末尾4桁) までを担当。
- 検証: 生HTTPは 200/404 を返すが数発で 429 (7分待っても復帰せず)、uc.Chrome でも同じ壁 = IP単位。
  公式APIは要トークンで無料枠不明。→ 叩かない方針が正しいことを実測で確認。

### ② 件数の壁の実測とキーワード設計

- 決定: 件数を増やす手は **キーワードを増やすことだけ**。フィルタは緩めても増えないので遠慮なく掛ける。
- 変更: `scrapers/psa_search_terms.py` 新設 (弾コードから自動生成: onepiece 49語 / pokemon 24語 /
  dragonball 12語 / gundam 5語 = 計88語)。`mercari_search` に `shipping_payer_id` /
  `sleep_between_sec` を通せるようにした (既定は従来動作、ポーターの挙動は変えない)。
- 検証 (`debug/probe_psa10_volume.py` / `probe_psa10_keywords.py`): 1語 15件で頭打ち。
  価格帯・送料込みを外しても増えない (21→10件)。一方 弾コード10語 → ユニーク148件 (重複2件のみ)。
  語間8秒なら10語連続でも 15件/語 を維持。

### ③ 重複防止 (user 指摘「既に抽出済と重複もあるんだろうなー」)

- 決定: 中間スプシ内の dedupe だけでは足りない。**本番で既に押さえている仕入元**と突合する。
- 変更: `sheet_writer.load_claimed_supply()` 新設 (HIGH/LOW の A列 + AC-AG列 URL、I列 cert)。
  URL 突合は詳細フェッチの**前** (1件約10秒 + Vision 1回が浮く)、cert 突合は Vision の後
  (同じ現物が別URLで再出品されると URL では捕まらない)。
- 検証: 実測で既知 仕入元URL 3,116件 / cert 1,044件。I列は PSA 専用でない (montbell は型番) ため
  cert 形式のみ採用。test +6。

### ④ 売れた PSA10 の別個体を探す (「売れた商品の補充」)

- 決定: 入力は **eBay 側を SSOT** にする。売れた行は HIGH に残らない (直近90日の注文30件中4件のみ)。
- 変更: `scrapers/ebay_sold.py` (getOrders + GetItem)、`scrapers/psa_restock.py`、
  `run_harvest_restock_psa10.py` 新設。カード名は英語なので日本語出品を引けない →
  **カード番号**を検索軸にする (ポケモンの "310/190" は前半のみ)。
- 検証: 注文取得は既存の user token でそのまま使えた (`sell.fulfillment.readonly`)。
  ★`GetItem` は `DetailLevel=ReturnAll` だけでは ItemSpecifics が返らず `IncludeItemSpecifics=true`
  が必要。実走で 売れたPSA10 3件 → 3件全部に代替個体を発見 (候補6件)。90日実績: 注文30件
  (UNIQLO/GU 15 / PSA10 11 / その他4 / G-SHOCK 1) = 月10件ペース。

- ★**別カードを掴むバグをテストが検出** (`psa_cert.match_signals`): 「Monkey D. Luffy」と
  「Portgas D. Ace」が2系統一致で通っていた。原因は ①1文字トークン "D" を数えていた
  ②ゲーム名 "ONE PIECE" の一致を数えていた。どちらも識別力が無いので除外し回帰テストを追加。
  誤出品に直結する穴だった。

### ⑤ 長時間走行の作業を捨てない (user 指摘・事故対応)

- 事故: ワンピース49語の走行で 収集487件 → 詳細145件まで進んだ時点で chromedriver への
  read timeout。例外が走行全体を殺し、**JSON 保存が全ループ終了後の1回だけ**だったため
  145件分 (Vision 読取111回 = 課金済 約$0.8、所要1.5時間) が全部消えた。
- 決定: 原因は 2つとも設計の欠陥。①保存が最後の1回だけ ②1件の失敗が走行全体を殺す。
- 変更 (両 runner): `--save-every` 件ごとに途中セーブ (収集直後にも1回) / `_dump` を
  tmp→replace の原子的書込 / 1件の失敗はその1件だけ (item_error) / 連続失敗でドライバ再生成 /
  それも失敗なら `truncated=True` で打ち切って保存 (黙って正常終了しない) /
  `--resume-from-json` で再開。`collect()` は継ぎ足し patch で壊れたため書き直し、
  1件処理を `_process_one()` に分離。
- 検証: `tests/test_psa10_crash_safety.py` 8本追加 (途中セーブ/原子性/1件失敗の隔離/
  ドライバ再生成/truncated/再開)。offline 830 passed、pre-commit 945 passed。

### ⑥ Vision 障害を「写真が不鮮明」と混ぜない

- 事故: 実走で12件全部が cert 読取失敗。原因は Anthropic API の残高切れだったが、
  `read_slab` が空 dict を返す実装のため「不鮮明が多い」と見分けられなかった。
- 決定: 「読めなかった」(写真の問題=正常な reject) と「確認できなかった」(こちらの障害) を分ける。
- 変更: `psa_slab_vision` に `error` フィールド。runner は `vision_error` として別枠で数え、
  ⚠️要対応として報告 (silent drop 禁止)。★色判定 (`color_vision`) は同じキーを使うが未対応 = 残務。
- 検証: 残高復活後 既知画像 5/5 読取 (cert/grade/label/番号/年 全項目)、末尾4桁も全件一致。

### 出した依頼書 / 残務

- `iMak_data/hq/requests/2026-08-17_psa_cert_lookup_rate_limit.md` — I列に cert 行が増える件の確認。
- `iMak_data/hq/requests/2026-08-17_backup_url_restock_qty1.md` — **補URLが生きているのに取り下げている**。
  監視くん (`monitor_listings.py:378-388`) が検出して `補URL救済ログ` に999行 (うちPSA 955行) 書いているが
  **測定用シグナルのみで action が無い**。PSA cert行1077件中 補URLあり288件(27%) は在庫1に戻すだけで済む
  (Description に「different certificate number」の開示があり cert 書換不要 — live 3件で実確認)。
  残り789件(73%) が Harvest 担当。
- 残務: ①ワンピース49語の本走行 (未実施、約2時間) ②`color_vision` の障害/不鮮明の切り分け
  ③`--verify` 経路は IP ブロック中で未検証。

## 2026-08-15 (続2) — 色抽出の誤り修正 (漢字色→canonical / Vision ゴミ排除)

- user 指摘: mercari_porter の色が違う (クロ/シブラック/オレンジ等)。根因: `extract_katakana_color_from_text`
  が漢字色(黒/紺等)を拾わず Vision に落ち、 Vision が「クロ」「シブラック」等の非 canonical/ゴミを返す。
- 変更 (`scrapers/color_vision.py`、 共有):
  - `_extract_kanji_color()` 追加: 単漢字色→canonical katakana (黒→ブラック等)。境界厳密
    (抹茶/黒革 は熟語で不採用)、 カタカナ優先。Step1 で確定抽出 → Vision 不要に。
  - whitelist に `セージグリーン` `シルバーグレー` 追加 (Porter TANKER 定番色)。
  - test 更新 (旧 kanji_not_extracted → kanji→canonical / compound安全 / katakana優先)。
- 是正: mercari_porter 76件の S列を title 再判定で修正 (クロ→ブラック 12件、 セージグリーン/
  シルバーグレー 復元、 シブラック/末尾欠け は空欄=fail-closed)。最終: ブラック62/ネイビー3/
  セージグリーン2 等、 空2 (ゴミ除去)、 オレンジ1 (内側色誤認=目視対応)。`pytest tests/` 全緑。

## 2026-08-15 (続) — ポーター抽出を「PORTER タンカー限定」に是正 (user 確定)

- user 確定: 欲しいのは **「PORTER タンカー + カテゴリ」** = TANKER シリーズ限定。ポーターなら
  何でも NG。カテゴリ = ヘルメット/ボディ/ショルダー/ビジネスバッグ。
- 変更:
  - DEFAULT_KEYWORDS を `PORTER タンカー <4カテゴリ>` に再構成 (旧 `PORTER <cat>` + 広すぎる
    PORTER/ポーター単独 を廃止)。
  - `is_tanker()` 追加 (タンカー/TANKER 必須) → runner で not_tanker reject。
  - `_OFFTARGET_RE` に **別ブランド混入** (FADEN/NORTH FACE 等、「検ポーター」タグ付き) を追加。
  - test: is_tanker 5件 + other_brand 2件。
- 是正: `mercari_porter` 52 → (バッグ絞り41) → **タンカー限定20行** に書き直し。全て PORTER TANKER
  バッグ (トート/ショルダー/ボディ/2way・3way)、別ブランド0。

## 2026-08-13 — メルカリ フリマ検索でポーター抽出 新設 (user 依頼)

- 決定: メルカリ フリマをキーワード検索して PORTER を収集 + フィルタ (評価数≥100 / 本人確認済 /
  送料込み / 販売中 / 価格10000-30000)。
- 変更 (新規):
  - `scrapers/mercari_search.py`: 検索URL builder (shipping_payer_id=2/status/price) +
    収集 (mercari_seller の _load_until_enough/_collect_listing_urls_from_page 流用) +
    **セラー品質抽出** (商品ページ aria-label「N件のレビュー/5段階評価中X/本人確認済」を parse) +
    passes_seller_filter (fail-closed: 評価数不明は reject)。
  - `run_harvest_mercari_search.py`: 7クエリ (PORTER 組合せ) 収集 → 詳細フェッチで
    販売中/評価数/本人確認 reject → keep を JSON/スプシ出力。
  - test: `test_mercari_search.py` 9件 (URL/parse/filter)。
- 検証 (POC・実機): 「PORTER ショルダーバッグ」headless で検索収集OK・ブロックなし。
  keep2/reject4 (評価<100=3, 本人確認なし=1)。keep 例: PORTER ショルダーバッグ ¥10,000 評価323
  本人確認✓ / タンカー ¥11,900 評価278 ✓。フィルタ正常。`pytest tests/` = 819 passed。
- 出力先: 中間スプシ `mercari_porter` タブ (sheet_writer_mercari_search.py、item_id dedup)。
- ★件数の壁と解決 (user 指摘「メルカリスクレイプボタン」): 自動scrollは jp.mercari.com フリマの
  anti-bot/仮想化で **~6-15件/キーワード 頭打ち**(mercari-shops.com は緩く759件取れるが別ドメイン、
  PSA10=psacard/一番くじ=1kuji でメルカリ大量抽出の既存実装は無し)。**GUI のメルカリセラーボタンが
  フリマアシスト手動click で壁を破っていた**のが正解 → 検索版に **`--manual` モード追加**
  (`_wait_for_manual_load` 流用、非headless、キーワード毎に手動click)。要フリマアシスト install。
  自動scrollは「少数高品質」、手動は「volume」の2モード。



## 2026-07-28 — snapshot cron の silent失敗を修正 (06:00 が API503 で無flag失敗)

- 事象: 07-28 06:00 の snapshot cron が Google Sheets API **503** で失敗 (Last Result=1)。
  build_yodobashi_snapshot に **API/DNS リトライが無く**、かつ snapshot ラッパーに**失敗flagが無かった**
  ため **silent 失敗**(collect/merge には flag あり、snapshot だけ抜けていた)。
  → snapshot が 22:10(前夜) のまま = 8.6h 古。06:45 LOW cycle は 12h 以内で効いた(fail-closed で無害)。
- 修正:
  - `build_yodobashi_snapshot.py`: `_with_retry`(sheet open/read)追加。
  - `run_snapshot_cron.cmd`: 失敗時 `CRON_FAILED_snapshot.flag` を残す(成功で自動クリア)+ PYTHONIOENCODING=utf-8。
    = 3ラッパー(collect/merge/snapshot)全てで「失敗をsilentに流さない」を統一。
- 検証: 手動再生成 exit0 / flag無し / generated_at 07-28T07:10 に最新化(237型番・在庫236)。

---

## 2026-07-27 (続) — merge/収集を cron 化 (HQ (A) GO)

- 決定: HQ 督促回答で **(A) cron化 GO**。手動放置は「新型番がヨドバシに出ても補URL未載=silentな
  取りこぼし=fail-OPEN」なので自動化が安全側。順序 収集→merge→snapshot→LOW を厳守。
- 変更: 失敗マーカー付きラッパー2本 + Task Scheduler 2タスク:
  - `run_yodobashi_harvest_cron.cmd` → `iMakHarvest_YodobashiHarvest_2100` (毎日21:00 収集)
  - `run_gshock_merge_cron.cmd` → `iMakHarvest_GshockMerge_2130` (毎日21:30 merge)
  - 両ラッパー: PYTHONIOENCODING=utf-8、**失敗時 exit≠0 で `debug\CRON_FAILED_*.flag` を残す**
    (成功で自動クリア)= 「要対応」を silent に流さない (グローバル状態同期原則2項)。
- 検証: merge ラッパー test-run = **exit0 / flag無し / 冪等(追記0・FLG増減0)/ UTF8ログ可読**。
  収集ラッパーは 21:00 予定実行との二重回避のため手動実行せず、今夜が初の全チェーン稼働。
- 依存順: 21:00収集 → 21:30merge → 22:00snapshot → 22:45 LOW cycle。全て22:00前完了(収集~15分)。

---

## 2026-07-27 — snapshot生成 cron を 1日3回に変更 (06/14/22)

- 決定: HQ `..._cadence_3x_daily.md`。LOW巡回が06:45/14:45/22:45に変更 + 監視くん12h staleガードで
  22:20の1本ではstale扱い → 発火せず。生成を **1日3回(06:00/14:00/22:00)** に。
- 変更: 旧タスク `iMakHarvest_YodobashiSnapshot_Daily`(22:20)削除 → `_0600`/`_1400`/`_2200` の3タスク
  (同一ラッパー run_snapshot_cron.cmd)。**コード変更なし**(cron時刻のみ)。
- 検証/判断: 236型番の所要=**約10.5分**(実測)。3回/日=約708アクセス/日だが10分バースト×3・~0.4req/s・
  captcha無 → BANリスク低く許容。45分前生成で12hガード余裕。fail-closed(生成失敗=無害)。
- I/F(型番キー+generated_at)・監視くん12h定数は不触。回答 `_response.md` 投函。



## 2026-07-26 (続6) — マージを設計思想版に修正 (21初弾 → 全236被り + 47新規別出し)

### 決定 (user 指摘)
- 初弾は「取下げ(D=○)∩在庫」21型番だけだったが、**設計思想は「ヨドバシ全型番をLOW突合、
  被る全型番の全行に先回りで補URL冪等追記」**。21はそのサブセットに過ぎない → 恒久版に修正。

### 変更
- `run_gshock_merge.py` 全面改修:
  - 既定 source = **yodobashi_gshock タブ全283型番**(21救済JSON限定を廃止)。
  - **LOW未収載型番 → new_candidates として `yodobashi_new_to_low.json` に別出し**
    (新規出品は listing project 責務、LOW には書かない)。
  - DNS flapping 耐性の `_with_retry`(sheet open/read/batch_update)を追加。

### 検証 (実測)
- 全283投入 → **LOW被り236型番(244行)/ 補URL追記221行(+既存冪等skip23=21救済分)/ 満杯0**、
  **LOW未収載47型番を別出し**。D列不触。
- read-back: LOW で **ヨドバシ補URL保持行 = 244**(21救済23 + 今回221)。
- **冪等性**: 再run で 追記0・冪等skip244 → 完全冪等を実証。
- snapshot も対象が21→236型番に自動拡大(build_yodobashi_snapshot が LOW のヨドバシURL行型番を拾う)。

### FLG 追加 (user 指示: LOW未収載を中間スプシで一目で分かるように)
- `run_gshock_merge` に FLG(Q列)冪等更新を追加: yodobashi_gshock の **LOW未収載型番行に Q="新規"**、
  収載済(=補URL対象)行はクリア。現値一致は書かない(冪等)。
- 実測: Q="新規" **47行** ちょうど(read-back)、値統一。test 1件追加。JSON別出しも併存(listing用)。

---

## 2026-07-26 (続5) — snapshot生成 cron 登録 (毎日22:20)

- 決定: HQ `..._cron_cadence_2220_GO.md` で 22:20 cron GO (LOW cycle 22:30 の10分前)。
- 変更: `run_snapshot_cron.cmd`(ラッパー、無窓pythonw+ログ)+ Task Scheduler タスク
  `iMakHarvest_YodobashiSnapshot_Daily`(毎日22:20)。
- 検証: 初回テスト実行で **Last Result=1**(WindowsApps python シム失敗 + 日本語RENコメント
  文字化けが真因)→ **①実体pythonパス化 ②.cmd を ASCII コメント化** で解消 → **Last Result=0**、
  snapshot generated_at が自動更新(19:36:15、21型番)を実測。Next Run=22:20。
- 教訓: (1) Task Scheduler で WindowsApps python **実行エイリアスのシムは失敗** →
  `PythonSoftwareFoundation.Python.3.11_...\pythonw.exe` の実体パスを使う。
  (2) **.cmd は ASCII のみ**(cmd.exe が UTF-8 日本語 REM を CP932 誤読しspurious error)。

---

## 2026-07-26 (続4) — 複数仕入元マージ 本実装 初弾 (21型番救済 + snapshot)

### 決定
- HQ WRITE_GO (`..._impl_go_WRITE_GO.md`): 21型番救済の補URL実書込 + snapshot生成ランナー。

### 変更 (新規)
- `run_gshock_merge.py`: LOW(1jF9vggb) の AC-AG 補URL に ヨドバシURL を型番キーで冪等追記
  (compute_merge 配線)。**D列不触・AC-AG限定 assert 安全弁**。同型番複数行は各行独立に追記。
- `build_yodobashi_snapshot.py`: LOW でヨドバシURL保持の型番の (在庫,価格,url) を
  `iMak_data/harvest/yodobashi_stock_snapshot.json` に型番キーで生成 (fail-closed・generated_at)。
- test: `test_gshock_merge_runner.py` (AC-AG列マッピング / ヨドバシURL検出)。

### 検証 (実測・完了条件クリア)
- **21型番補URL実書込**: dry-run → 実書込 **AC 23セル** (21型番、同型番複数行で23行)。
  read-back: **AC 23/23 入力 / D列変化 0件** (在庫状態不触を実証)。
- **snapshot初回生成**: 21型番 **全 in_stock=True** + price + url、generated_at=19:14。不備0。
- `pytest tests/` = **798 passed**。
- → 次 LOW cycle で Inventory が「Amazon 3rd化 → ヨドバシ延命 + M最安」を突合予定。報告は `_response.md`。

---

## 2026-07-26 (続3) — 複数仕入元マージ POC (HQ go)

### 決定
- HQ POC go (`..._multisource_merge_feasibility_hq_confirm` / `..._yodobashi_ifce_design_poc`)。
  分界確定: Harvest=型番マージ+補URL(データ)AC-AG冪等追記+在庫I/F提供 / Inventory=D復活・M-min(状態)。

### 変更 (新規)
- `scrapers/yodobashi_search_http.py`: `stock_price_by_model()` I/F 追加 (word=型番 検索タイルから
  在庫bool+価格+URL、 型番完全一致1商品に絞る、 fail-closed=判定不能は ok=False)。
- `gshock_merge.py`: `compute_merge()` 純関数 (型番キー・主/補URL 冪等マージ、 空枠のみ・満杯skip・
  新規別出し、 在庫状態は touch しない = Inventory 責務)。PSA hoju compute_additions の LOW 版。
- test: `test_gshock_merge.py` 9件 + yodobashi I/F 検証。

### 検証 (実測)
- **型番ピンポイント検索精度**: 6/6 型番で `word=型番`→完全一致1商品に絞れた (誤マージなし)。
- **在庫I/F**: 実在4型番=在庫True/価格/URL取得、 非在型番=fail-closed (ok=False, None)。
  ★重要: **素の HTTP で成功** (Inventory の「Akamai=Selenium必須」と食い違い)→ 監視くんに
  Selenium 不要のスナップショット供給が可能。
- `pytest tests/` = **796 passed**。
- POC結果 + I/F提案 (型番キー・HTTPスナップショット・fail-closed) を `_response.md` で HQ に共有。

---

## 2026-07-26 (続2) — 項目Amazon整合 (画像/説明/色/ポイント) + 3RD救済

### 決定
- user: ヨドバシ抽出項目を Amazon に極力揃える + ポイントを両方 K 列に入れる。
- user: Amazon で 3RD 化し取り下げた分を ヨドバシ在庫で救済できないか。

### 変更
- `scrapers/yodobashi_search_http.py`: `fetch_detail()` 追加 (詳細ページから画像8枚/説明/
  色(共通 whitelist・fail-closed)/**ポイント円 直値** `js_scl_pointValue`/clean title)。
- `sheet_writer_amazon.py`: `_build_row` に **K=ポイント(円)** 書込追加 (Amazon/ヨドバシ共有)。
- `run_harvest_yodobashi.py`: Phase 2 詳細fetch追加 → G/H/S/K 書込、title を clean 版に差替。
- `tools/backfill_amazon_points_staging.py`: amazon_<label> の K を backfill (widget anchor 版・
  DNS リトライ付き)。
- test: yodobashi 14件 (points直値/画像scope/clean title 等) + _build_row K 3件。

### 検証 (実測)
- yodobashi_gshock 283行 **全項目再収集**: URL/title/価格/画像/説明/ポイント/型番=283/283、
  色=16/283 (fail-closed、 タイトル色語のみ・推測なし)、K ポイント=**283/283 (全件10%)**。
- amazon_gshock K backfill: **311/327** (残16=ポイントなし)。※ fetch完走後の書込で DNS 一過性
  失敗 (getaddrinfo) → **ログから311値を復元し retry 書込で完走** (再fetchなし)。ツールに
  DNS リトライを恒久追加。
- **3RD救済**: HIGH/LOW の Amazon×D=○ (取下げ) 193型番 ∩ ヨドバシ在庫283 = **21型番**が
  ヨドバシ仕入で復活可 (`_amazon_jp_dumps/yodobashi_rescue_candidates.json`、価格−pt=実質原価付)。
  注: D=○ は理由(3RD/実売)未記録のため「取下げ∩在庫」。3RD厳密化は seller 再確認が要。
- `pytest tests/` = **787 passed**。

---

## 2026-07-26 (続) — ヨドバシ G-shock 収集 新設 (第2の仕入元 + Amazon差分)

### 決定
- user 依頼: ヨドバシ.com から G-shock を収集し中間スプシに出す + Amazon との差分確認。
- feasibility 実機調査: サーバHTML(JSアプリでない)・captcha無・単一直販(merchantId不要)。
  在庫は配送表記で判定 (「…お届けできます」=在庫あり 283 / 廃番・取寄 7)。
  無在庫DS前提で **在庫あり(お届け表記)のみ keep**、取寄/廃番/予約は fail-closed skip。

### 変更 (新規ファイル)
- `scrapers/yodobashi_search_http.py`: カテゴリ検索を `/pN/` パスで全ページ走査、
  `.js_productList .productListTile` から型番/価格/在庫を parse。page1=0件で blocked
  (Amazon と同じ fail-OPEN ガード)。
- `sheet_writer_yodobashi.py`: `yodobashi_<label>` タブに append (product_id dedup、
  列構成は sheet_writer_amazon と共有 → AI列型番で両タブ突合可)。
- `run_harvest_yodobashi.py`: 収集→keep gate(在庫/gshock/gift-pair除外)→append→Amazon差分。
- `tests/test_yodobashi_search.py`: 16件 (URL構築/型番/在庫/container-scoped parse)。

### 検証 (実測)
- 収集290 → keep283 (在庫あり) / reject7 (out_of_stock)。gift_pair 除外は共有関数で0。
- スプシ: `yodobashi_gshock` に **283行 append** (appended=283/skipped=0)。
  read-back: URL不正0 / F価格非数字0 / AI型番空0。
- **Amazon 差分 (型番ベース)**: ヨドバシのみ **51型番** (Amazon未収集の新規候補) /
  両方232 / Amazonのみ95。
- `pytest tests/` = **778 passed**。

---

## 2026-07-26 — Amazon G-shock 差分取得 + fail-OPEN defect 修正

### G-shock 差分 (HQ 手動依頼方式)
- 決定: `run_harvest_amazon_search.py --preset gshock-mens --use-http-prefilter --skip-existing-tab gshock` 実行。
- 検証: **新規30件を amazon_gshock タブに append** (skipped_existing=0 = 全て真の新規)。
  URL収集765 → HTTP直販/brand filter keep18 → variant展開 kept30/reject3、captcha無。
  JSON: `_amazon_jp_dumps/amazon_gshock_20260726T075058.json`。

### ギフトセット/ペアウォッチ 除外 (user 指示)
- 決定: メンズ抽出から **ギフトセット (バンドル SKU) と ペアウォッチ (2型番同梱) を除外**。
  複合 SKU は catalog の ID 完全一致 lookup に写像不能 + 仕入元/価格が単品と別。単品本体のみ残す。
- 変更:
  - `scrapers/amazon_search_http.py`: `is_gift_or_pair_set(title)` 追加 (`ペア\s*ウォッチ|ギフト\s*セット`)、
    `evaluate_detail_for_keep.should_keep` に `and not is_gift_or_pair_set` 追加 (Phase B)。
  - `run_harvest_amazon_search.py`: Phase C REJECT 連鎖に `gift_or_pair_set` 分岐追加。
  - `tools/delete_gift_pair.py`: 既存タブの物理削除ツール新規 (delete_ladies 同型、判定は単一ソース)。
- 検証: フィルタ回帰テスト10件 (`tests/test_amazon_giftpair_filter.py`)。
  スプシ実削除: dry-run 19行 (今回15 + 過去残4) → 全タイトル目視で ペア/ギフト 確認 → 削除19、
  **残存0件 / 327行**を実測。

### fail-OPEN defect 修正 (user 指摘「そんなはずない」が契機)
- 決定: 検索 page1=0件 (captcha無) の**間欠ソフトブロックを「新規なし・正常」と誤報告する
  fail-OPEN を封じる**。1回目 run が silent に0件完了し30件を取りこぼしかけた。
- 変更:
  - `scrapers/amazon_search_http.py:collect_search_asins` — page1 が retry 後も0件なら
    `blocked=True` を返す (page>1 の0件は従来通り正当な末尾)。
  - `run_harvest_amazon_search.py:_http_prefilter_keep_asins` — `search_blocked` 伝播。
  - `run_harvest_amazon_search.py:harvest_amazon_search` — blocked 時は summary に `blocked:True`
    で loud-abort (0件を keep空=正常 と混同しない)。
  - `run_harvest_amazon_search.py:main` — blocked 時 **exit 1** (cron/呼出側に失敗を伝える)。
- 検証: 新規テスト2件 (page1空→blocked=True / page2空→blocked=False) + 統合probeで
  main() exit 1 を実測確認。`pytest tests/` = **752 passed**。

---

## 2026-07-23 (続) — HIGH backfill 完走 (全系統の最終ピース)

- 決定: HQ go (2026-07-23_high_backfill_go.md) を受け、LOW と同一の widget anchor 修正版で
  HIGH の Amazon 行に F=現在価格 + K=pt(円) を backfill。N 不触。
- 変更: `tools/backfill_amazon_points_low.py` に `--sheet {low,high}` 追加 (HIGH_SHEET_ID 切替のみ)。
- 検証: dry-run 5行 → 本適用。HIGH Amazon 行 total=55 (HQ 想定一致)、うち売切44 = 既定 skip、
  現役11行 = K記入10 / ptなし1 (fail-closed "") / fetch失敗0、書込22セル。
  実行後 read-back で TGT 11行の K がログ全一致 + 非対象行 (PSA NO-GO sentinel 含む) の K 変化ゼロを実測。
  pt率分布: 1%帯1 / 10-13.5%帯2 / >13.5%=7 (最大26%)。報告を `_processed.md` に追記済 → HQ 独立検証待ち。

---

## 2026-07-23 — re-backfill 完走 (widget anchor 版、HQ go 案A)

### 決定
- HQ go (サンプル20 目視OK + 高率ポリシー=案A忠実採用、HIGH は別途) を受け全量再適用。

### 検証 (シート実測 = 独立検証)
- ✅ LOW 380行: pt取得331 / ptなし21 / fetch失敗28 (不触)。F=現在価格+K のみ書込 (704セル)。
- ✅ **旧汚染シグネチャ (0.8%未満) = 0件** (defect時136 → 根絶)。
- pt率分布: 1%帯51 / 2-10%帯9 / 10-13.5%帯166 / **>13.5%=105 (最大39.9%、widget実表示の
  ポイントアップ、一覧を response に添付)**。
- 依頼書 (defect / rebackfill_go) processed 化、完了報告を response に追記。
- ✅ 07-23 回収run完走: 失敗重複0(一過性)、最終 K充足352+ptなし22/未充足0 = LOW 完全カバー。HIGH 55行のみ HQ 別 go 待ち。

---

## 2026-07-22 (続) — ポイント抽出 defect 修正 (widget anchor 化)

### 決定

- HQ 実測で backfill の K 半数以上が実勢不整合 (高率48/低率136/不整合34) と判明 → HQ が K 全クリア。
- **真因**: buybox の実表記は「ポイント: 1,831pt (13%)」(pt表記+タグ分断) で旧 regex は
  **buybox に一度もマッチせず**、全マッチが「よく一緒に購入」/カルーセルの**別商品 pt** だった。
  緩い整合 ±(1%+20円) が 1%帯で別商品小額 pt を、 近価格帯で campaign pct を通した。
- **検証の非**: 「N==F−K 全336一致」は自書込値の循環照合で抽出検証になっていなかった。
  以後、抽出系は独立ソース突合を受け入れ条件とする。

### 変更 (commit `3a58a60`)

- `extract_points_jpy` を **widget anchor 化** (`pointsInsideBuyBox`/`points` 断片内のみ、
  tag除去+nbsp正規化 → 「ポイント: Npt (X%)」)。全ページ走査廃止。整合 ±(0.5%+10円)。
- tool: F=現在ページ価格 + K を書く (混成防止、HQ指示)。N 不書込 (関数保護)。
- 回帰テスト 16件 (カルーセル pt を拾わない回帰含む)。

### 検証

- ✅ 不良実例: B07SD7THVK 旧33→**新143 (HQ 予言の 1%=143 と一致)**。良品 1831/1584 正値維持。
- ✅ サンプル20 dry-run: 全行 K=現在価格×1% ちょうど、汚染バラつきなし → response 添付済。
- ⚠️ 要 HQ 裁定: widget 自体が高率表示のケース (B08ZYWDZZB 24%=実在ポイントアップ) の採否。
- 全量 re-backfill は HQ 目視 → go 待ち (先行しない)。

---

## 2026-07-22 — Amazon ポイント込み実質仕入値 (HQ依頼 3通、当日完結)

### 決定

- HQ 依頼 (feasibility → go → formula_switch) を当日で完遂。
  - K列(11)=ポイント(円) 確定 (LOW K 未使用を実機確認: Inventory の K 書込は SKU シート向け)。
  - **formula_switch (同日上書き)**: N はシート関数 =(MあればM、なければF)−K に移行。
    書き手は観測値のみ → Harvest tool は **K のみ書く** (N 書込は関数を壊すため残存ゼロ必須)。

### 変更

- `scrapers/amazon_search_http.py`: `extract_price_jpy` / `extract_points_jpy` 新設
  (price×pct 整合 ±1%+20円 で基本 pt のみ採用、 campaign 分排除、 fail-closed None)。
- `tools/backfill_amazon_points_low.py` 新規 → formula_switch で **K-only** に改修
  (N/F 書込撤去、 grep で N 書込残存ゼロ確認)。 commit `9b28c3d` → `820671b`。
- `tests/test_amazon_points.py` 15件 (整合フィルタ / fail-closed / plan_row K-only 契約)。

### 検証

- ✅ 実ページ 3/3 で pt 抽出一致 (1831/1378/1584)。
- ✅ 本適用 (LOW 380行): **pt取得336 / ptなし11 / fetch失敗33 (不触)**、 K1 ヘッダ改名済。
- ✅ 実機全件照合: **K非空336 / N==F−K 全336一致 / 不一致0 / 欠落0** (全角￥書式込)。
- ✅ pt率 1〜13% 帯、 20% 超の異常値なし。 依頼書 3通 processed 化 + 最終報告を response に追記。
- 残: fetch失敗33行は tool 再実行で回収 (K-only なので ARRAYFORMULA 後も安全)。

---

## 2026-07-13 — メルカリセラー手動待機: button 併用時の 15s 早期完了を修正

### 決定

- user 報告「seller 623636774 が 0件」を調査 → **DOM 破損でも出品ゼロでもなく under-collection**。
  ログ `出現 10 / 既知 skip 10 / 取得 0` + スクショで **セラーは大量出品ありなのに初期10件で
  早期完了**を確認。 原因 = `_wait_for_manual_load` の **15s stable 自動完了が「click 完了!」
  button (done_event) 併用時も生きており、 user が「もっと見る」 を押し切る前に打ち切っていた**。
  (done_event は 6/3 に早期完了対策で追加されたが、 stable 判定を無効化しておらず修正が不完全)。

### 変更

- `scrapers/mercari_seller.py`: `DEFAULT_MANUAL_BUTTON_STABLE_SEC=120` 新設。
  `_wait_for_manual_load` の stable 判定を、 **done_event あり時のみ `max(stable_sec, 120s)`**
  に緩和 (= button 押下で即完了が本筋、 押し忘れ時のみ 2分 idle fallback)。 done_event 無し時
  は従来 15s 維持 (= 既存挙動保持、 [[mercari_scraper_freeze]] 準拠)。
- `tests/test_mercari_seller.py`: 回帰テスト 2件 (button無=15s完了 / button有=15sで完了せず)。

### 検証

- ✅ `tests/test_mercari_seller.py` = 53 passed (新2件含む)。
- ⚠️ 運用: 再実行時は Chrome で **「もっと見る」 を押して件数を増やし → 「click 完了!」 button**
  で明示完了。 15s では切れなくなった。 もし click しても件数が増えない場合はフリマアシスト
  load-more 不具合 (= 別調査)。

---

## 2026-07-03 — Amazon G-shock 抽出: 部品除外フィルタ + 新着sortパス (= 精度/網羅 是正)

### 決定

- user 指摘の 2 精度問題を是正:
  1. **ベゼル/部品混入**: MTG-B3000「交換用バンド」単体が is_gshock (ブランド一致) で keep 通過
     → 時計本体でない部品を keep gate で除外。
  2. **新作取りこぼし** (DW-6900CMG-3JF): 広い「G-Shock」既定sort検索は Amazon 表示上限
     (~400-500件) で頭打ち → 新作が圏外に埋もれる。 narrow検索/新着sortなら到達可 (実測)。
- 対策方針: (a) 部品除外フィルタ (b) 新着sortパス併設。 いずれも user 承認 (両方実装)。

### 変更

- `scrapers/amazon_search_http.py`: `is_accessory_part(title)` 新規 + `should_keep` に
  `and not is_accessory_part` 追加、 return に `accessory_part`。 判定 = 明示 part marker
  (交換用/保護フィルム/BAND-SKU 等) or (腕時計/watch 表記なし かつ アクセサリ名詞)。
  本体型番名の "メタルベゼル・バンドモデル" 等は誤除外しない設計。
- `run_harvest_amazon_search.py`: (1) selenium fetch 側にも `accessory_part` reject 追加。
  (2) PRESETS 各 preset に **新着sortパス** (`-new`, `s=date-desc-rank`) 併設。 新着パスは
  merchantId URL フィルタ (p_6) を外し Phase B の per-ASIN merchantId 検証に委ねる
  (= search段 merchantId 絞込が直販でも稀に落とすため。 ASIN dedup で既定sortと重複吸収)。
- `tests/test_amazon_parts_filter.py` 新規 10 件。

### データ是正 (中間スプシ amazon_gshock タブ)

- 差分抽出 +12 → 型番重複2 + 部品1 を削除 → CMG系(DW-6900CMG-3JF 等)5件を narrow検索で回収
  → 既存 legacy 型番重複 7組を整理。 **309 → 最終 316 行 (重複0/部品0/列ズレ0 実機検証済)**。

### 検証

- ✅ `test_amazon_parts_filter.py`(10) + `test_amazon_ladies_filter.py`(8) = 18 passed。
- ✅ amazon 関連 5 ファイル = **72 passed**。 PRESETS = all:4/mens:2/ladies:2 パス。
- ✅ 実機: CMG系 append 後 DW-6900CMG-3JF 存在確認、 部品/列ズレ/型番重複なし。
- ⚠️ 未対応: HTTP検索の一過性ブロックで page1=0 → false-0 abort する silent bug
  (`amazon_search_http.collect_search_asins` の `new_added==0 break`) は別途対応候補。

---

## 2026-06-17 — sheet_writer append の列ズレ事故修正 (= HIGH Porter 7行が U列起点に +20列ずれ)

### 決定

- user 指摘「HIGH へのメルカリ/Porter 書込が U列に URL を書いている」を是正。
- 真因: `append_new_urls` の `ws.append_rows()` が **table_range 未指定 (既定 None)** のため、
  Sheets API の表検出が col A 本表でなく **出品日列(U)のスパースブロック** (legit な U列日付 +
  stray な U1057="2026-06-16") を表と誤認 → 新7行を **U列起点・+20列ずれ** (A→U/C→W/F→Z/S→AM)
  で row1058 に着地させた。snkrdunk_op の同型事故 (A列空タブで append が遠方列に誤書込) と同根。
- 対処方針: **append の検索起点を A1 に固定** (`table_range="A1"`) して col A 本表末尾へ左詰め強制。
  破損済データは再スクレイプ不要・既存シフト値から決定的に復元。

### 変更

- `sheet_writer.py:263` — `ws.append_rows(new_rows, value_input_option=..., table_range="A1")`
  (table_range 追加 + 事故経緯コメント)。
- `tests/test_sheet_writer_dedupe.py` — mock append_rows に table_range 受領 + `append_kwargs` 記録、
  回帰テスト `test_append_anchors_table_range_at_a1` 追加 (= table_range=="A1" を担保)。
- HIGH スプシ実データ修復: シフト済 7行(src 1058-1064 の U-AN)を A1054:T1060 に復元書込、
  stray U1057 + 旧シフト領域 U1057:AN1064 を batch_clear。backup =
  `debug/high_porter_shift_backup_20260617.json`。

### 検証

- ✅ 修復後 実機照合: last col-A row=1060、シフト行(no-A かつ U-AN data)=0件。
  1054-1060 の 7 Porter が A=URL/C=タイトル/F=価格/S=色 で正列着地を確認。
- ✅ 別 anomaly 行 [115,119,120,149,728] は **列ズレでなく** A列空の正常既存行 (C列にタイトル、
  E/F/G 正列) と確認 → 今回バグ無関係、不触。
- ✅ `tests/test_sheet_writer_dedupe.py` + `test_sheet_writer_snkrdunk_aux.py` = **73 passed** (-s)。
  (全体 pytest は online/selenium テストの capture teardown で末尾クラッシュ＝既存環境ノイズ、本変更無関係)

---

## 2026-06-14 (= 続) — スニダン ワンピPSA10 抽出を正URL化 (= 17→233カード、 販売中網羅)

### 決定

- user 指摘「売切混入 / 在庫がもっとあるはず」を是正。 2 つの根本原因を解消:
  1. **列挙の keyword/brandId (単数) が無視されていた** → 正解は **複数形 `keywords`/`brandIds`
     + `isSaleOnly=true`** (= user 提供 URL 2026-06-14)。 旧方式は keyword 無視でトレカ人気上位の
     One Piece 分 (152頭打ち) しか取れず。
  2. **累積 dedup で売切listingが陳腐化** → リフレッシュ書込 (毎回クリア+最新で全置換) に変更。
- 抽出スコープ: **販売中 (isSaleOnly + status==0) × One Piece (brandIds) × PSA10**、 価格 cap OFF
  (= 価格はスプシ後処理、 user 方針)。 productNumber gate は brandIds 保証により撤廃。

### 変更

- `scrapers/snkrdunk_op_catalog.py`:
  - `enumerate_candidate_model_ids` を `keywords/brandIds=onepiece/isSaleOnly=true` URL に修正。
  - `extract_psa10_under` price_cap 既定 None (= 上限なし)。 HTTP fetch retry (既存)。
- `run_harvest_snkrdunk_op.py`:
  - `write_cards_to_tab` リフレッシュ化 (clear+rewrite, price昇順)。
  - productNumber gate 撤廃 (= OPCD/OP-P/CS25 variant 取りこぼし防止)、 --price-cap 既定0(無制限)。

### 検証

- ✅ 新URL動作確認: 3頁69件 / 純度25/25 One Piece (旧は Pokemon 混在)。
- ✅ 本実行 (user CMD): 候補233 → 販売中PSA10カード **233** (総出品3850) → 新タブ233行
  (補仕入31 / 新規202)、 価格帯 ¥4,100〜2250万。 旧16カードから13.7倍に網羅。
- ✅ 全 pytest 緑 (snkrdunk_op 16件含む)。
- ✅ orphan chrome 7個 (失敗probe残骸) を kill して起動失敗を回復。

---

## 2026-06-14 — Chrome version_main 全scraper 自動検出化 (= 横断展開、 版ズレ事故の構造的防止)

### 決定

- グローバル CLAUDE.md 新ルール (2026-06-14, Inventory caa659b 先行 + 全worktree展開)
  「version_main を数値ハードコードするな・Chrome 実バージョンを自動検出せよ」に Harvest 対応。
- 契機: スニダン run が Chrome 149 実機に対し `version_main=148` 固定で、 uc が起動時に
  正しいドライバを fetch しに行き DNS 断で死亡 / 不安定化 (= 2026-06 の 2 日間事故と同型)。

### 変更

- `scrapers/_chrome_util.py` 新規 = `detect_chrome_major()` (registry BLBeacon → chrome.exe)。
  iMakInventory/scrapers/_chrome_util.py:detect_chrome_major() と同方式。
- 全 6 create_driver を `version_main = detect_chrome_major() or <fallback>` に変更:
  - snkrdunk_official.py (= 共有 util に集約、 detect_chrome_major_version は後方互換 re-export)
  - amazon_wishlist.py / mercari_likes.py / mercari_shops_likes.py / casio_official.py
  - run_harvest_amazon_search.py (attach_to_existing_chrome)
- `tests/test_chrome_util.py` 新規 2件。

### 検証

- ✅ detect_chrome_major() = **149** (実機一致)。 全 scraper import OK。
- ✅ 全 pytest **719件 pass** (= 717 + chrome_util 2)。
- ✅ 今後 Chrome が 150,151… に自動更新されても追従し、 版ズレエラーは構造的に出ない。
- note: orphan chrome 一掃は Harvest は手動実行ツール + enumeration 硬化で driver.quit が確実に走る
  ため、 ユーザーブラウザ巻込みリスクを避け自動kill は入れない (= Inventory cron とは事情が異なる)。

---

## 2026-06-13 — スニダン ワンピPSA10 全件抽出 本実装 (= 新タブ snkrdunk_op_psa10、 16件)

### 決定

- **スニダンのワンピPSA10・price<10万 を catalog 横断で全件抽出** する新パイプラインを実装 (= user 指示)。
  既存 snkrdunk_official.py (= 補仕入 lookup, card単位) と別物の「カタログ列挙」型。
- 抽出方式 (= 2026-06-12 調査で確立):
  - 列挙 = 検索結果ページ (CSR) を Selenium DOM scrape → /apparels/<model_id>
  - One Piece 限定 = model 詳細 productNumber が OP/ST/EB/PRB/P (= Pokemon 等を fail-closed 除外)
  - 出品 = `GET /v1/apparels/{id}/used?perPage=30` → PSA10 + status0 + price<cap (純HTTP)
- 既存 iMakTCG 出品 (HIGH) と同 card_id = **補仕入扱い (Q列="補")**、 それ以外 = 新規候補。

### 変更

- `scrapers/snkrdunk_op_catalog.py` 新規 (= is_one_piece_pn / fetch_model_detail / fetch_used_items /
  extract_psa10_under / enumerate_candidate_model_ids、 HTTP fetch に retry)。
- `run_harvest_snkrdunk_op.py` 新規 (= 列挙→One Piece判定→PSA10<cap抽出→新タブ書込 + 補仕入flag、
  --dry-run / --price-cap / --keywords / --max-pages / --write-from-json)。
- `tests/test_snkrdunk_op.py` 新規 16件。
- ★ 書込バグ修正: `_create_from_template`(duplicate) は テンプレ遠方列(CS)ジャンクを引継ぎ、
  A列データ無し時 append_rows がCS列起点に誤書込 → `add_worksheet(cols=37)` + `ws.update("A..")` に。

### 検証

- ✅ 全 pytest **717件 pass** (= 701 + snkrdunk_op 16)。
- ✅ dry-run (40 model): One Piece19 / PSA10<10万 4件 で end-to-end 動作確認。
- ✅ 本実行 (keyword「ワンピース」25頁): 候補347 → One Piece model **159** → PSA10<10万 **カード16**
  (総出品321) → 新タブ `snkrdunk_op_psa10` に16行書込、 A-AK列に正常着地を実機確認。
- ✅ 補仕入照合: HIGH既出 62 card_id と照合 → **補仕入2 / 新規14**。
- ⚠️ 環境 DNS が断続失敗 (getaddrinfo)。 HTTP/書込 retry + cards 先行保存 + --write-from-json で対処。
  完全性は keyword「ワンピース」単独で159 model (= 末端カードは未surface)。 弾別keyword追加で拡張余地。

### 次のアクション

- 完全性向上 (= 弾別 keyword / 検索完全列挙) は別 task。 現状でも主要ワンピPSA10<10万 16件を抽出済。
- DNS 安定時に再実行すれば差分追加 (= card_id dedup で重複しない)。

---

## 2026-06-12 (= 続2) — staging amazon_gshock → LOW へ重複しない分を転記 (= ASIN dedup 136件)

### 決定

- **staging amazon_gshock (309件) のうち LOW 未登録分を LOW に追記** (= user 指示)。
- **重複判定は ASIN** (= URL から抽出)。 URL 完全一致は不可と判明:
  LOW は Amazon を wishlist 形式 (`/dp/ASIN/?coliid=...&ref_=list_c_wl_...`) で保持するため、
  staging のクリーン `/dp/ASIN` と文字列不一致 → URL 一致だと同一 ASIN 109件を二重登録してしまう。
  - URL 完全一致 dedup → 245件 (= 109件が二重登録) ❌
  - ASIN dedup → **136件** (= 正、 二重出品防止) ✅

### 変更

- `tools/transfer_amazon_gshock_to_low.py` 新規 (= staging→LOW 転記、 ASIN dedup、 37列行コピー)。

### 検証

- ✅ 転記実機: LOW 756→**892行** (+136)。 dup skip 173 / ASIN無し 0。
- ✅ 私の追記 136件は **全て新規 ASIN、 二重登録 0件** (= collide 検証で確認)。
- ⚠️ LOW には **元々 48 ASIN が重複登録** (= 転記前から存在、 本件と別の既存データ品質問題)。

### LOW 重複 cleanup (= user 指示「お願いします」)

- **48 ASIN 重複を安全解消** (= `tools/dedupe_low_sheet.py`)。
  - ルール: 重複グループ内で **eBay item ID (B列) 空の行のみ削除**、 ID 行 (= 出品中) は絶対残す。
  - 47 行削除 (= 全て空 ID の untracked 重複)。 LOW 892→**845行**、 ASIN 重複 48→**3**。
- **残 3 件 = eBay 上で二重出品 (両行に live item ID)**。 シート削除では解消不可、 eBay 側 end が必要:
  - B098D3TSYP (GW-M5610U-1JF): id 356980160947 / 356980160959
  - B0CJJ5PMCZ (DW-6900NNJ-1JR): id 358556999744 / 358276567493
  - B0F9K5ZP1R (G-5600SFJ-9JR): id 357173500721 / 358422162572
  - → Inventory/出品側で片方 end 推奨 (= Harvest 責務外、 報告のみ)。

---

## 2026-06-12 (= 続) — メンズ scope にレディース50件混入を是正 (= 性別フィルタ追加 + 削除)

### 決定

- **メンズ preset にレディース専用 50件が混入** していた (= 6/11「レディース skip」決定と矛盾)。
  user 指示「削除してメンズのみに戻す」。
  - 混入経路: メンズ検索で拾った midsize モデル起点に variant 展開が色違い family
    (= GMA-P2100 29色 等) を丸ごと取込。 `is_gshock_item` に性別フィルタが無く素通り。
- **keep gate に性別フィルタ追加** (= レディース専用 title を除外、 メンズ scope 維持)。
  兼用 (= メンズ/男性 併記) と ユニセックス は除外しない (= fail-safe で keep)。

### 変更

- `scrapers/amazon_search_http.py`: `LADIES_ONLY_RE` / `MENS_MARKER_RE` / `is_ladies_only(title)` 追加。
  `evaluate_detail_for_keep` の `should_keep` に `and not is_ladies_only(title)` 追加 (= HTTP keep gate)。
- `run_harvest_amazon_search.py:_fetch_details`: seller/brand gate の後に `is_ladies_only` reject 追加
  (= selenium keep gate、 reason="ladies_only")。
- `tools/delete_ladies.py` 新規 (= 同 `is_ladies_only` 基準で既存行削除、 単一ソース)。
- `tests/test_amazon_ladies_filter.py` 新規 8件 (= 純レディース除外 / 兼用・ユニセックス・メンズは keep)。

### 検証

- ✅ 全 pytest **701件 pass** (= 693 + ladies8、 regression なし)
- ✅ レディース 50件 削除実機完走: 359→**309行**。 削除後検証: レディース明示 **0**。
- ✅ fail-safe 確認: GMA-S2100-1AJF (= "ユニセックス・大人" 表記) は残存 (= 男性装用可で正しく keep)。
- ✅ 性別フィルタは HTTP/selenium 両 keep gate に入ったため、 **今後の差分実行でレディース再混入しない**。

### 次のアクション

- catalog dump のレディース **51 ASIN** を Catalog へ依頼書投入済 (= 完全除外でなく gender タグ/scope外認識。
  `catalog/requests/2026-06-12_amazon_gshock_dump_ladies_tagging.md`)。 Catalog `_response.md` 待ち。
- 定期差分実行 (= `--use-http-prefilter --skip-existing-tab gshock`) の運用方式 (auto/手動) は user 判断保留。

---

## 2026-06-12 — Amazon seller 判定 FBA 誤検出バグ修正 + 376件 merchantId 再精査 + KEY空欄是正

### 決定

- **そもそもの抽出方針は「Amazon.co.jp 直販のみ keep」が正** (= 国内 third-party / Amazon US は両方除外)。
  user 指摘で再確認。 旧 flag_amazon_us_in_sheet.py の 'AMAZON_US' ラベルは誤り
  (= merchantId≠直販 を一律 US 扱い、 実体は国内 third-party の国内正規品が多数)。
- **selenium `_extract_seller` の FBA 誤検出が混入の根本原因** と特定。
  発送元(Ships from / 発送元) marker + body 全文マッチで、 第三者販売+Amazon発送(FBA) の
  国内 third-party を直販と誤判定 → run_harvest の seller!="Amazon.co.jp" gate をすり抜け。
  → 販売元 = buybox merchantId="AN1VRQENFRJN5" を authoritative signal に統一 (= HTTP 経路と同一)。
- **buybox rotation を新たに確認** (= Amazon の販売者は時間で入れ替わる)。
  旧 39 flag のうち 25件は rotation による誤flag (= 今は直販)、 真の非直販は 15件のみ。
  → 単発 snapshot flag は不安定。 再精査は merchantId + 非直販候補は確認 fetch 1回 で安定化。
- **KEY 空欄 12件の根本原因 = 型番の日本語直結** ("GWG-B1000-1AJFメンズ")。
  `\b` 境界が カタカナ/漢字も word 文字扱いで消え抽出漏れ。 → KEY抽出を ASCII境界+digit必須 に修正。
- **Q列 FLG 値は '非直販'** に統一 (= 'AMAZON_US' 誤称を廃し、 国内third-party/US を区別せず除外マーク)。

### 変更

- `scrapers/amazon_item_detail.py:520-536` SELLER_AMAZON_JP_MARKERS から発送系(Ships from/発送元)削除。
  `SELLER_AMAZON_MERCHANT_MARKER = '"merchantId":"AN1VRQENFRJN5"'` 追加。
- `scrapers/amazon_item_detail.py:645` `_extract_seller` 全面改修
  - step1: page_source の merchantId で直販判定 (= authoritative、 発送元に左右されない)
  - 旧 step2 (body 全文マッチ) を削除 (= FBA 誤検出の元凶)
  - fallback は buybox block 内「販売」marker のみ (= 発送 marker 除外済)
- `scrapers/amazon_item_detail.py:867` `_extract_product_id_estimated_from_title` 改修
  - `_KEY_MODEL_HYPHEN_RE` / `_KEY_MODEL_NOHYPHEN_RE` 新規 (= ASCII境界、 \b 非依存、 digit必須で series語除外)
- `tests/test_amazon_seller.py` 新規 8件 (= FBA 誤検出回帰防止)
- `tests/test_amazon_key_extract.py` 新規 11件 (= 日本語直結型番 / series語除外)
- `tools/reaudit_amazon_seller.py` 新規 (= 376行 merchantId 再精査 + Q列是正、 rotation 確認fetch付)
- `tools/backfill_key_from_title.py` 新規 (= 空欄KEY を修正済抽出で backfill、 Amazon fetch なし)
- `tools/flag_amazon_us_in_sheet.py` は旧版 (= 'AMAZON_US' 誤ラベル)、 reaudit が上書き是正済。

### 検証

- ✅ 全 pytest **693件 pass** (= 旧674 + seller8 + key11、 regression なし)
- ✅ 376件 再精査実機完走 (06:00-06:16): direct=361 / nondirect=15 / fetch失敗0 / captcha0
  - Q列書込 40件 = 旧誤flagクリア 25 + 非直販マーク 15
  - 非直販 15件の merchantId: A1EJGP084HULR(=真Amazon US: row74,83,91,92) + 国内third-party各種
- ✅ buybox rotation 実証: B0H2CLW4T2 / B0F9K112T9 が 05:15非直販 → 05:40以降 3回連続 direct
- ✅ KEY backfill 6件書込 (= row66 GWG-B1000-1AJF / 71 GWG-B1000-1A4JF / 87 GWA11001A3JF /
  189 MTG-B3000-1AJF / 228 GWG-B1000-3AJF / 356 DW-6900NNJ-1JR)。 KEY空欄 12→6 に。

### 物理削除 (= user 指示 2026-06-12「1,2 は削除」)

- **非直販 + バンド類 17行を物理削除** (= `tools/delete_nondirect_and_bands.py`)。
  - 非直販時計 13 + バンド類 4 (= 85,89,93,208)。 削除直前 rotation 再確認で直販復帰 0件 (= 全件安定)。
  - 削除後 実機検証: データ 376→**359行**、 残 非直販 0 / 残 バンド 0 / 残 KEY空欄 0。
  - → 中間スプシは「Amazon.co.jp 直販 G-shock 時計・全件KEYあり」のクリーン状態に。

### 下流是正 (= catalog dump、 user 指示 2026-06-12「そうした方がいい」)

- **catalog dump 4 file (375件)** に混入の非直販/バンド 17 ASIN 除外を Catalog Claude へ依頼。
  - 依頼書投入: `catalog/requests/2026-06-12_amazon_gshock_dump_nondirect_exclusion.md`
  - 17 ASIN を A(バンド4)/B(真Amazon US 4)/C(国内third-party 9) に分類し dump file map 付きで提示。
  - **Catalog 回答受領 (`_response.md`)・本件クローズ** (2026-06-12):
    - Amazon dump は未 merge (= catalog に 17 ASIN 0 hit、 amazon_available 列も無し) → 遡及是正不要。
    - `_amazon_jp_dumps/exclude_asins.json` 恒久リスト化で対応 (= 完全除外8 / 直販フラグ抑止9)。
    - dump JSON は seller-bug 証跡として温存 (= 非破壊・可逆を採用、 user 同意でクローズ)。

### 残・別 task

- レディース skip (= user 判断保留、 6/11)
- 他カテゴリ展開時の `is_gshock_item` プラガブル化 refactor

---

## 2026-06-11 (= 後半) — Amazon G-shock メンズ全網羅完了 (= HTTP filter + variant 補完 + monthly_sales)

### 決定

- **Amazon メンズ G-shock 全抽出 完了** (= 中間スプシ 376 行、 catalog dump 4 file 375 件)
  - 根拠: 6/11 終日 5 session 通し、 selenium / 拡張機能 / URL filter / attach / HTTP filter を順次検証 → 最終 HTTP filter で 100% 精度確立
- **HTTP filter 戦略採用** (= Gemini 助言 + merchantId AN1VRQENFRJN5 検証で 100% 精度確認)
  - selenium 環境では URL filter / 拡張機能ともに無効化される (= Amazon bot 検出) ことを実証
  - `requests + bs4` + `merchantId="AN1VRQENFRJN5"` grep で代替実装、 selenium 介さず Amazon 直販判定
- **拡張機能 (Amazon 3rd Party Seller Filter) 対応 + attach 方式** = 検証の結果 selenium 自動 navigate で効かないと判明 → HTTP に転換
- **AI 列 (= col 35、 KEY 型番)** に生 verbatim (= HQ 規約 2026-06-11)
- **V 列 (= col 22、 Amazon 月販売数)** に生 verbatim 「過去 1 ヶ月で N 点以上購入」 (= user 指示 2026-06-11)
- **Amazon US 並行輸入 1 件 (= B000FPVUJA)** reject (= merchantId 検証で 国内仕入不可商品除外)
- **variant 全展開 採用** (= 既存 119 ASIN seed → HTTP で variant 子 ASIN 取得 → 既存 dedup 後 selenium で 14 field 抽出)
- **catalog 投入 schema 確定** (= 14 field + variant_asins、 catalog は identity/在庫hint/画像のみ使用、 動的データは sourcing 層 = 中間スプシ責務)

### 変更

- `scrapers/amazon_search_http.py` 新規作成 (= HTTP-based URL 収集 + seller/brand/variant filter)
  - `create_session` / `fetch_search_page` / `parse_search_asins` / `collect_search_asins`
  - `fetch_detail_page` / `detect_seller_amazon_jp` (= merchantId AN1VRQENFRJN5 100% 精度)
  - `extract_brand_text` / `extract_title` / `extract_monthly_sales_text`
  - `extract_variant_asins_http` (= regex `</ul>` end pattern で section 切り出し、 入れ子 div 問題回避)
  - `is_gshock_brand_text` / `evaluate_detail_for_keep` (= 1 ASIN total 評価)
  - `SELLER_AMAZON_PRIMARY_MARKER = '"merchantId":"AN1VRQENFRJN5"'` (= Amazon.co.jp 公式 ID)
- `scrapers/amazon_search.py:_collect_asin_urls_from_search_page` 拡張
  - `brand_prefilter=True` (= G-SHOCK title 含む card のみ採用)
  - `card.is_displayed()` チェック追加 (= 拡張機能で hide された card 除外用、 ただし selenium で効かず判明)
- `scrapers/amazon_item_detail.py` 拡張
  - `_extract_seller` 強化 (= merchant block 内 厳格判定 + fallback)
  - `_extract_rating` 修正 (= "5つ星のうち X.X" pattern 優先で 5.0 誤抽出 fix)
  - `_extract_monthly_sales` 追加 (= V 列用、 「過去 1 ヶ月で N 点以上購入」 grep)
  - `extract_variant_asins` / `extract_variant_count` (= inline-twister 新 UI 対応)
  - `fetch_detail_full` に variant + monthly_sales 統合
- `sheet_writer_amazon.py`
  - `COL_MONTHLY_SALES = 22` (= V 列、 月販売数) 追加
  - `_build_row` で V 列書込 logic 追加
  - `append_amazon_search_items` を `ws.update(range_name)` pattern で fail-safe (= 既存)
- `run_harvest_amazon_search.py` 大幅拡張
  - `is_gshock_item` (= brand + title AND filter、 Baby-G / Edifice 除外)
  - `_collect_urls_for_paths` / `_fetch_details` (= queue ベース + variant 展開 + pre_visited)
  - `_load_existing_asins_from_tab` / `_http_prefilter_keep_asins`
  - `_http_variant_supplement` (= seed ASIN → variant 子 ASIN 補完 + Amazon US 除外)
  - `setup_extension_mode` / `launch_attach_chrome_mode` / `attach_to_existing_chrome`
  - 新 options: `--use-http-prefilter` / `--supplement-variants-from-tab` /
    `--skip-existing-tab` / `--launch-attach-chrome` / `--attach-port` / `--setup-extension`
- 全 pytest **674 件 pass** (= regression なし)

### 検証

- ✅ session 1 (= 11:34-13:08): selenium 直、 200 scanned → 49→75 件 keep (= bug fix 後再 append)、 captcha 0
- ✅ session 2' (= 14:50): brand pre-filter + 拡張機能、 200 scanned → 17 件 keep (= Amazon US 1 件混入後 16 件)、 captcha 0
- ✅ session 4 (= 18:37-19:11): HTTP pre-filter + variant、 28 scanned → 27 件 keep (= 歩留り 96%)、 captcha 0
- ✅ session 5 (= 19:54-22:07): variant supplement、 287 scanned → 257 件 keep、 captcha 0
- ✅ Gemini 助言検証: merchantId AN1VRQENFRJN5 = 既存 keep 3 + reject 5 で **100% 精度** 実証
- ✅ HTTP variant regex 修正: B0D9Y4QZQT で 6 件取得確認 (= 親 + 5 色 variant)
- ✅ 中間スプシ実機: 376 行、 AI 列 96.8%、 V 列 9 件 (= Amazon 売れ筋表示の仕様通り)
- ✅ catalog merge pre-flight: 119 件 → 既収録 97% (= 新規 catalog 追加 3 件)
- ✅ Amazon US 並行輸入 B000FPVUJA: merchantId 検証で `A1EJGP084HULR` (= Amazon US) と判明 → reject
- ✅ 完成報告投入: `harvest/requests/2026-06-01_amazon_gshock_full_scrape_processed.md`

### 次のアクション

- レディース 着手 (= user 判断「skip」 で保留)
- Catalog Claude による catalog merge (= dump 4 file 受領済、 Catalog スケジュール)
- 他カテゴリ展開 (= フィギュア / ねんどろ / 一番くじ) 時の `is_gshock_item` プラガブル化 refactor (= 30 分)
- selenium 環境での Amazon URL filter / 拡張機能 有効化 (= Playwright / CDP 直接利用 / 別 task)

---

## 2026-06-11 (= 終夜) — Amazon US (= 並行輸入) cleanup tooling + 39 件 flag

### 決定

- **中間スプシ既存 376 件 を全件 merchantId 検証 → Amazon US 商品 39 件 (= 10.4%) を Q 列 FLG=AMAZON_US で識別** (= user 後で削除 / 別タブ移動可能化)
  - 根拠: session 1 / 2' (= selenium 直 + brand pre-filter) で selenium が seller="Amazon.co.jp" と誤判定し Amazon US 並行輸入が keep されていた
  - HTTP merchantId 検証 (= AN1VRQENFRJN5 一致) を真実値として retroactive cleanup

### 変更

- `tools/flag_amazon_us_in_sheet.py` 新規作成 (= 中間スプシ全行を HTTP detail で merchantId 検証 + Q 列に FLG 書込)
  - rate limit 2-3s (= Amazon ブロック対策)
  - 既存 Q 列値あり 行は skip (= 上書き禁止、 安全)
  - 完走 376 件、 captcha 0

### 検証

- ✅ 全 376 件 fetch 完走 (= captcha 0)
- ✅ Amazon.co.jp 確定: **337 件** (= 89.6%)
- ✅ Amazon US 検出 + Q 列書込: **39 件** (= 10.4%)
- ✅ fetch_failed: 0 件
- ✅ session 4 / 5 (= HTTP filter で keep した分) には Amazon US 混入 **0 件** (= merchantId 100% 精度実証通り)
- ✅ 結果 dump: `debug/flag_amazon_us_result.json` (= 39 ASIN list + 行番号)

### 次のアクション

- user 手動で Q 列 = "AMAZON_US" 39 行の削除 / 別タブ移動 / 出品候補から除外
- 国内 Amazon 直販 実質 **337 件** が catalog 投入 / listing 候補化対象

---

## 2026-06-11 (= 前半) — Amazon G-shock 全件 scrape 新規実装 (= 4 番目 catalog source)

### 決定

- **Amazon G-shock 全件 scrape を 4 番目 catalog source として実装** (= 元 6/1 依頼書 GO 発火)
  - 根拠: ユーザー Takaaki さんの「Amazon retry GO」 (= 6/1 Amazon bot mark expire 後)
  - 規模: メンズ 推定 200-300 弱 (= 6/11 実機 sniff、 captcha なし)
- **「一石二鳥」 案採用** (= JSON dump + 中間スプシ append、 catalog 投入 + listing 候補化 両方)
  - 根拠: Catalog 回答 (= `_amazon_gshock_two_birds_confirmation_response.md`) で C 案 賛成
- **brand filter 追加** (= CITIZEN 完全除外、 5/11 5 件 sample で混入課題判明 → fix)
- **variant 全展開 fetch 採用** (= 各色違いの子 ASIN を別 detail fetch、 ユーザー指摘「全部取らないとね」)
- **AI 列 (= 型番) 生 verbatim で中間スプシ 列追加** (= HQ 規約 `_amazon_gshock_raw_model_in_sheet.md`)
  - canonical 化・正規化は Harvest でやらない (= catalog 側 lookup_gshock で resolve)
- **拡張機能 (Amazon 3rd Party Seller Filter) 組込** (= 検索 page で第三者除外、 user 提案)
  - chrome_profile_amazon に install、 setup-extension mode で setup 一度のみ
- **append bug fix** (= 5/26 mercari_seller 同型事故、 ws.append_rows で AC 列から書込発生 → ws.update(range_name) pattern に修正)
- **skip-existing-tab option** 追加 (= session 跨ぎで既存 ASIN 重複 fetch 防止)
- **brand pre-filter** 追加 (= 検索 page card で G-shock title 含むもののみ URL 収集)

### 変更

- `scrapers/amazon_search.py` 新規作成 (= 検索 page URL 収集 + pagination + brand pre-filter)
  - `parse_search_url` / `build_search_url_with_page` / `parse_asin_from_url`
  - `_collect_asin_urls_from_search_page(brand_prefilter=True)` (= card 単位 + G-SHOCK title filter + fallback)
  - `collect_search_listing_urls` (= 最大 25 page 走査、 hard cap 1000)
  - `SEARCH_RESULT_CARD_SELECTORS` / `GSHOCK_TITLE_PREFILTER_RE`
- `scrapers/amazon_item_detail.py:514-617` `fetch_detail_full` 新規追加 (= 14 field 拡張)
  - `_extract_seller` (= block + body marker、 6/11 fix で `merchantInfo` block 内 「販売 + Amazon」 strong signal 採用)
  - `_extract_brand` / `_extract_model_number` / `_extract_release_date_amazon` (= spec_pairs から key:value)
  - `_extract_review_count` / `_extract_rating` (= "5つ星のうち X.X" pattern 優先)
  - `_extract_product_id_estimated_from_title` (= G-shock model regex)
  - `extract_variant_asins` / `extract_variant_count` (= inline-twister + variation_color_name、 子 ASIN list 抽出)
- `sheet_writer_amazon.py` 拡張
  - `DEFAULT_COLUMN_COUNT`: 20 → **35** (= AI 列 KEY まで含む format)
  - `COL_KEY = 35` (= AI 列、 model_number / product_id_estimated 優先で生 verbatim)
  - `_build_row` に AI 列書込 logic 追加
  - `build_amazon_tab_name` / `_get_or_create_amazon_search_tab` / `append_amazon_search_items` (= 中間スプシ append)
  - **append bug fix**: `ws.append_rows()` → `ws.update(range_name=A{next}:T{end})` 明示範囲指定
- `run_harvest_amazon_search.py` 新規作成 (= entrypoint)
  - `PRESETS = {gshock-all, gshock-mens, gshock-ladies}`
  - `is_gshock_item` (= brand + title AND filter、 Baby-G / Edifice / Pro Trek 除外)
  - `_collect_urls_for_paths` / `_fetch_details(queue ベース + variant 展開 + pre_visited_asins)`
  - `harvest_amazon_search` / `_load_existing_asins_from_tab`
  - `setup_extension_mode` (= chrome 起動 + 拡張機能 install URL navigate + 30 分 sleep)
  - `--skip-existing-tab` / `--setup-extension` option
- `tests/test_amazon_search.py` 新規 24 件 (= URL parse / brand filter / dedup / regex / tab name / is_gshock_item)
- `tests/test_sheet_writer_amazon_dedupe.py` `len(r) == 20` → `35`
- `tests/test_mercari_size_extract.py` 同様 `len(row) == 20` → `35`
- `.gitignore` debug/dry_run / sniff / verify / probe / *.log 追加除外

### 検証

- ✅ `pytest` 全体 = **674 件 pass** (= regression なし)
- ✅ 6/11 sniff dry-run (= verify_extension_filter): 拡張機能 install 後 1 page URL 46 件 (= 前 60 件、 23% 削減)
- ✅ variant dry-run (= dry_run_amazon_variant): B0D9Y4QZQT 起点 6 色 variant 全取得確認
  - GD-010-4JF (オレンジ) / -1A1JF (オールブラック) / -3JF (カーキ) / -1JF (ブラック) / -010BEG-1JF / -010GB-1A9JF
- ✅ session 1 本実行 (= 13:34-14:50、 約 1 時間 16 分):
  - メンズ URL 398 件、 scanned 200 件、 **keep 49 件 (= bug fix 前) → 75 件 (= bug fix 後再 append)**
  - captcha 0 件
  - 中間スプシ amazon_gshock タブ append 75 件、 **AI 列 (= 型番) 値あり率 97.3% (73/75)**
- ✅ append bug 修正検証: row 2 col 1 = URL / col 3 = title / col 5 = "New" / col 6 = "10780" 正常書込確認
- ✅ brand filter 検証: 75 件中 「Baby-G / Edifice / Pro Trek / CITIZEN 等」 hit **0 件**、 title G-SHOCK 表記 75/75
- ✅ Catalog 依頼書 2 件 + 回答受領済 (= 6/11 13:00-13:39):
  - `_amazon_gshock_two_birds_confirmation.md` + `_response.md`
  - `_amazon_gshock_intermediate_sheet_format_check.md` + `_response.md`
- ✅ HQ 依頼書受領 (= 6/11):
  - `_amazon_gshock_raw_model_in_sheet.md` (= 型番は生 verbatim、 AI 列に格納)
  - `_gshock_ingestion_suffix_normalize.md` (= 別 task、 casio_official.py 投入時 alias 整合)
- ⏸ session 2' 進行中 (= 拡張機能 + brand pre-filter 込み、 max_per_session 200、 既存 75 ASIN skip)

### 次のアクション

- session 2' 完走 → 拡張機能 + brand pre-filter 効果実測 (= 歩留り 75-90% 期待)
- 完了報告 投入 (`harvest/requests/2026-06-01_amazon_gshock_full_scrape_processed.md`)
- 別 task: `_gshock_ingestion_suffix_normalize.md` (= casio_official.py 投入時 alias 整合、 緊急度低)
- フィギュア等他カテゴリ展開時の brand filter プラガブル化 (= refactor 30 分相当)

---

## 2026-06-03 — メルカリセラー 接続切断対策 + 差分 fetch mode 追加 / Casio 391 件 中断

### 決定

- メルカリセラー rate limit を **2-4s → 5-10s に緩和** (= IP 評判低下下での接続切断対策)
  - 根拠: 6/3 朝、 seller 803732659 で 15-25 件目に Read timed out / ConnectionResetError 連続発生
  - 直前 Casio 大量 fetch (= 累計 1200 request) で IP 評判低下、 mercari 側 bot 検出 threshold 同期厳格化と推定
- **「✓ click 完了!」 button mode 追加** (= manual click 早期完了 fix)
  - 根拠: stable_sec=15s 自動判定が user click 前に発火 → 10 件で完了とみなされる症状確認
  - user 明示 signal で stable_sec より優先 即完了
- **chrome profile fresh reset + フリマアシスト 再 install** (= profile 累積 odd state 疑い)
  - 旧 profile rename 退避 (= legacy_20260603)、 setup_anonymous mode で再 install
- **「差分のみ詳細取得」 mode 追加** (= 再実行高速化、 default ON)
  - 根拠: 同 seller 再実行時、 既存タブ row の詳細取得が 50 分 無駄 → 差分のみで 数分化
  - 既存挙動 (= checkbox OFF) は維持 = backwards compatible
- Casio 公式 391 件 fetch は **204/391 取得時点で Akamai 認定** → 数時間待ち + 全技 reset で後日 retry 方針
  - profile + IP + instance fingerprint 全て track 確認、 attach 方式 (= port 9222) も 1-2 件で再 block

### 変更

- `scrapers/mercari_seller.py:92-94`
  ```python
  DEFAULT_DETAIL_RATE_LIMIT_MIN_SEC = 5.0  # 旧 2.0
  DEFAULT_DETAIL_RATE_LIMIT_MAX_SEC = 10.0  # 旧 4.0
  ```
  commit `d74f5a1`
- `scrapers/mercari_seller.py:334-378` `_wait_for_manual_load`
  - `done_event` (= threading.Event) 引数追加、 set で即完了
  - 既存 stable_sec 判定は fallback として維持
- `scrapers/mercari_seller.py:394-406` `collect_seller_listing_urls`
  - `manual_done_event` 引数追加 → `_wait_for_manual_load` に pass-through
- `scrapers/mercari_seller.py:487-503` `collect_seller_with_details`
  - `manual_done_event` 引数追加 → `collect_seller_listing_urls` に pass-through
  - `known_item_ids: Optional[set] = None` 引数追加 → URL 収集後 詳細取得 phase 前に filter
  - 返却 dict に `skipped_known` 追加 (= 効果計測用)
  commit `babf5ba` / `a19754c`
- `control_panel.py:279-300`
  - 「差分のみ詳細取得」 checkbox 追加 (= default ON、 `self.mercari_seller_skip_known_var`)
  - 「✓ click 完了!」 緑 button 追加 (= `self.mercari_seller_manual_done_btn`)
  - `self.mercari_seller_manual_done_event = threading.Event()` 保持
- `control_panel.py:993-1057` `_run_mercari_seller_thread`
  - manual_mode 実行時 button enable + event reset
  - skip_known ON 時 既存タブから `read_existing_dedupe_keys_in_tab` で dedup key set 取得
  - mercari_seller 呼出に `known_item_ids` + `manual_done_event` を pass
  - 終了処理で button disable + text reset
- `control_panel.py:1180-1194` `_on_mercari_seller_manual_done`
  - button 押下 callback、 event.set() + button text 更新
- 退避済: `C:\Users\imax2\local_data\iMakHarvest\chrome_profile_mercari_seller_anon_legacy_20260603` (= rename)
- 退避済 (= Casio 別 task): `chrome_profile_casio_anon_blocked_20260601` / `chrome_profile_casio_attach_blocked_20260601`

### 検証

- ✅ `pytest tests/test_mercari_seller.py` = 51 件 pass (= 各 commit 前 pre-commit hook)
- ✅ `pytest` 全体 = 115 件 pass (= 各 commit)
- ✅ 6/3 17:19-18:11 実機完走: seller 803732659
  - URL 収集 222 件 (= 「click 完了」 button で 11s で signal 送信、 stable_sec 15s 待ち不要)
  - 詳細取得 222/222 (= rate 5-10s、 接続切断 0 件)
  - group 化 221 rows (= aux 1 件)
  - Vision calls=213 hits=5 disagree=0
  - スプシ書込 appended=211 + skipped_existing=10
  - 所要時間 約 50 分
  - bot 検出 / 429 / timeout / ConnectionResetError = **すべて 0**
- ✅ git push: feature/harvest-phase1 = origin と同期 (= commit d74f5a1 / babf5ba / a19754c 全 push 済)
- ✅ フリマアシスト install verify (= PowerShell): `chrome_profile_mercari_seller_anon\Default\Extensions\jcbljdgnpcckiamdgmnfhijgkkaogmgg\3.68.1_0`
- ✅ 報告書投入:
  - `requests/2026-06-03_mercari_seller_click_done_button_release.md` (= 完成報告)
  - `requests/2026-06-01_casio_official_391_detail_fetch_interim.md` (= Casio 中断報告)
- ✅ memory 更新: `mercari_seller_phase3_anonymous_furima.md` (= click 完了 button / rate 5-10s / 6/3 実機実績 追記)
- ⏸ 差分 fetch mode の実機検証は 次回 同 seller 再実行時 (= 効果値は実機で確定)

### 次のアクション

- 差分 fetch mode 実機検証 (= user が 同 seller 再実行で skipped_known 件数報告)
- Casio 391 件 retry (= 数時間〜半日 待機 + user 指示で発火、 fresh profile で再 try)
- 共有 dir `2026-06-01_amazon_gshock_full_scrape.md` (= 30 分前 投入の新依頼) 未着手 = 次セッションで対応
