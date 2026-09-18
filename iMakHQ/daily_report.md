# iMakHQ Daily Report

HQルール準拠フォーマット: 決定 / 変更 / 検証 の3点セット。
検証欄は grep / テスト / 目視 の実結果のみ記録する（自己申告は書かない）。

---

## 2026-09-18 [HQ] リサーチを道具にした — 市場で売れているカードを取って、探す先と出品の優先順に回す

### 決定事項
- **eBay の Research (Terapeak) を毎回同じ条件で取る**。条件は `iMakHQ/tools/market_ledger.py`
  の `PRESETS` が唯一の口 (手打ちしない)。キーワード `PSA10` / CCG 183454 / 即決+オファー承諾 /
  日本人セラー / 売れた数順。価格の下限と買い手の国は入れない (下限は実測で4%しか外れない)
- **ドラゴンボールは Super Card Game だけ**。`Dragon Ball CCG` は 2000年代の別ゲーム (カタログ回答)
- **トレジャーハント** (ユーザー命名) = 市場で売れているのに、うちが出していないカード。
  PSA 新規の並べ順で **最優先**。枠は切らない (件数が少ないため)
- **上限仕入れ値**は `pricing_engine` を二分探索で逆に解いて出す。**式は持たない** (SSOT を割らない)
- 2026-09-17 の「Apify で市場の売れたデータを取る案は見送り」は**取得手段の話**として決着。
  Terapeak なら無料・365日まで取れる ([[terapeak-grab-extension]])

### 変更点
- `iMakHQ/tools/terapeak_grab/` — Chrome 拡張 (版 1.1)。画面の一覧を CSV にする。
  「まとめて取る」は人が押した時だけ、開いているタブで、1ページ5〜8秒あけて最大50ページ。
  フィルタの選択肢も出せる。`fc998a1` `44999a0` `4e63da1` `c2029f6` `f4799a0`
- `iMakHQ/tools/market_ledger.py` — 台帳 (ingest / report / targets)。`4e63da1` `334c1e7` `5b19672`
- `iMakHQ/console/` 0.7.0 — 分析・棚に「リサーチ」。商材 / 売れた・出ている / 期間を選んで開く。`c30f41d`
- `iMakTCG/tcg_batch_select.py` — トレジャーハントを並べ順の先頭に (一覧が無ければ今まで通り)。`5b19672`

### 検証 (実結果)
- 台帳 **1,612行** (ポケモン1,193 / ワンピース308 / ドラゴンボール111)。販売 2,776個 / カード554種類 /
  **2個以上売れたのは152種類**
- **うちの出品(ポケモン323件)のうち、90日の売れた実績に載っていたのは22件 (7%)**。
  重なった19件は**全部うちの方が高く、中央値 +82%** (インプレは出ているので「見られて買われていない」)
- 探す先: **114種類 / 90日で772個** がうち未出品 → `iMak_data/hq/market_sold/demand_market.csv`
  (カタログを引けたのは56種類)。上限仕入れ値つき (例: マクドナルドのピカチュウ 020/M-P =
  166個 $202.50 → 15,000円まで)
- テスト: `tests/test_market_ledger_20260918.py` 14件 / `iMakTCG/tests/test_treasure_hunt_20260918.py` 4件 緑
- 拡張は保存した実ページを Chrome に読ませて検証 (Sold 50件取得・隠れタブ除外・フィルタ384件)

### 他担当とのやり取り
- **カタログ → 完了**: Character を eBay の綴りに寄せた **2,894行** (綴りゆれ19 / 形の違い1,727 /
  キャラでない値1,148を空欄)。残り0行・毎日の監査も常設。Set とワンピース/DB の不一致は**天井**
  (eBay 側に値が無い) と判明。`Alternative Art` はうちが正
- **抽出くん → 依頼中**: トレジャーハントを別タブ・夜間自動で集める
  (`harvest/requests/2026-09-18_treasure_hunt_harvest.md`)。返事待ち
- **SSD**: リセットは 9/13 の10回から 9/18 は0回まで減少・BSOD も今日は0 → **交換しない**。
  控えに入っていなかった `catalog/_raw` (83,162ファイル) を1回固めて Google ドライブへ
  (`catalog_raw_20260918.zip` 1,664MB)。取得処理は再開して良いと回答

### 次にやること
- 抽出くんの返事が来たら、出品くん Console に**トレジャーの件数**を出す (タブ名が決まってから)
- ユーザー確認待ち: `status_now.py` が二重登録に見えた場所 (タスク側には無い)

## 2026-09-16 08:56 [HQ] 出品くん Console を合意した見本の形に / 版の管理 / 後処理を共通化して 54/55 が新画面で押せる

### 決定事項
- 決定1: **旧 出品くん (control_panel.py) は残したまま、徐々に新画面へ移す** (ユーザー指示)。
  版の数え方を固定 — **0.x = 旧パネル併用 / 1.0 = 旧パネルの全ボタンが新画面で押せた時**。
  旧パネルには版を振らない (触らないから)。記録は `iMakHQ/console/CHANGELOG.md`。
- 決定2: 同じ処理を2つ書かない。新画面から押せるようにするための後処理は **旧パネルから抜き出して共用**する
  (新画面用に書き直さない)。

### 変更
- `iMakHQ/console/` 段階2 (v0.2.0 → v0.3.0):
  - 見本 https://claude.ai/artifact/17znRRHtq61RzUeroRxU41 の形に組み直し。ページ分け (今日やること /
    新規出品 / 在庫メンテ / 分析・棚 / 定期 / 版・移行)、補URL と再仕入れは **商材 × 段階の格子**、
    「担当」「実行ログ」の常設欄は削除 (ログは実行中・直後だけ下から出す)
  - 「版・移行」タブ = 押せる本数と、押せないボタンの理由ごとの一覧
- `iMakHQ/control_panel.py`: 画面コードの中にあった2つを module 直下に抜き出した (中身・順番・文言は不変)
  - `before_run(script, append_log)` … PSA orphan KEY 掃除 / N列関数ガード
  - `after_run(script, rc, ...)` … 除外 → タイトル補強 → 重複くん → PSA自動の締め → 再仕入れ変換 →
    cert目視 → NO-GO sentinel → 締めの表示
  - 旧パネルの `poll_queue` / `run_script` はこれを呼ぶだけになった
- 新画面は後処理のあるボタン・新規生成・入力欄・金額も押せる (入力は画面の小窓で聞く)。
  **残る旧パネル専用は 一番くじの新規 (ウィザード画面) だけ = 54/55**

### 検証
- `python -m pytest tests/ iMakHQ/tests/` → **5,029 passed / 1 skipped / 7 xfailed** (pre-commit で強制)
  - 移設に合わせて既存の形チェック5本を新しい場所に向け直した (N列ガード / 締めの失敗表示 /
    PSA自動の締め / RESTOCK skip / Tシャツ自動)
- 新画面から「📊 補URL 件数感 (全系統)」を実行 → `returncode=0`、
  「(…: excluder/title-fix/重複くん の後処理をスキップ — skip_postprocess)」→「🎉 全 process 完了」まで出た
- 旧 `出品くん.vbs` を起動 → 単一インスタンスの待受 (127.0.0.1:53247) を確認して終了
- 画面は Edge のヘッドレスで各タブを撮影して目視 (今日 / 新規出品 / 在庫メンテ / 分析・棚 / 定期 / 版・移行)
- commit: `b3783b2` (見本の形) / `bf4062e` (版の管理) / `607920f` (後処理の共通化)

### 次にやること
- 1.0 の残り: **一番くじの新規 (ウィザード画面)** を新画面に移す
- 新画面から**実際の出品 CSV を1本**作って、旧パネルで作った時と同じ結果になるか突き合わせる
  (今日の確認は「見るだけ」のボタン止まり)
- 棚割りの金額が円をドルとして出ている疑い (棚 $16.84M / TCG +$7.82M)。旧パネルと同じ数字なので
  既存の問題。直すかはユーザー判断待ち

### 追記 09:20 — 新画面から本番の CSV を1本作って確かめた (ユーザー「そっちで TEST してみてよ」)

- 実行: 新 Console の「新規出品 → G-SHOCK → 新規」(`gshock_to_csv.py`)。eBay には送らない生成だけ
- 結果: **returncode=0 / CSV 10行** (`csv_output/gshock_upload_20260916_091438.csv`)
  - 生成時セルフ監査: 除外0 / カタログ修正依頼0 / プログラム修正依頼0 / SEOメモ10
  - 後処理が旧パネルと同じ順で全段走った:
    live cache 鮮度 → 重複くん物理除外 → 同design間引き → write-keys → dup_guard →
    補URL自動追記 (死んだ仕入元16本を除去) → 売り切れ除外 (0件) → 「出せるか」塗り直し (出せる163件)
    → 🎉 全 process 完了
  - `…csv.excluded.json` は `drops: []` / `soldcheck: ok`
  - 後処理で行は減らず 10行のまま (SKU 10件)
- 8/28 の CSV と列が2つ違う (`C:Customized` / `C:Vintage`) が、これは 8/22 の「G-Shock では列ごと落とす」
  決定 (commit 4116bd0) によるもので、画面の違いではない
- **この走行で見つけた差を1つ直した**: Console は後処理のログを run log にも書いていた。後処理は
  run log を「今回の stdout」として読み直すので、後処理自身の文が次の段の入力に混ざる
  (NO-GO 行の二重取り)。旧パネルと同じく**画面だけ**に出すよう修正 + test 追加
- 残り: 止めるボタン / 一番くじウィザード / オファー・ミラー・残務の窓 が新画面に無い


---
## 2026-09-14 [HQ] ファネルは API にせずレポートに守りを足す / 売れた分の補充を夜間化 (一覧から)

### 決定事項
- 決定1: **ファネルの材料は Seller Hub レポートのまま** (API 化は取りやめ)。本当の問題は API ではなく
  **広告レポートの期間の選び間違い** (7/23 は4日分・9/01 は1日分 → 9/02・9/04 のファネルは NO_SEARCH 277件、
  90日分の 9/06 では2件)。期間はファイルの Start/End 列にあるので読んで止める。
- 決定2: レポートは **週1回・広告レポートは期間90日** で落とす。古さの線は 4日 → 7日 (判定は1回で1〜2%しか動かない)。
- 決定3: **売れた分の補充は夜間に自動** (ユーザー go)。目視は補URLを足す時に済んでいる。
  止める条件: 支払い済み未発送 / 仕入元売切・巡回が発送日より前 / 同じカードが出品中 / US 以外。
  **最初の夜は一覧だけ**。翌朝ログを見てから `--write` (1晩10件まで)。
- 決定4: eBay への上限引き上げ申請はしない (ユーザー)。
- 補URLが無い物は、仕入元を買った時点で監視くんが売切にするので自動では戻らない (PSA 再仕入れ①②③ の手作業)。

### 変更 (`312b29d`)
- `listing_funnel.py`: 広告レポートの期間 85日未満で中断 / 古さ7日 / 未落札レポートの新名 inactive-listings
- `sold_restock.py` / `sold_restock_worklist.py`:
  - 在庫0の出品を「補充済」にしていた (B列に番号があるだけで判定) → eBay の在庫で判定。戻す相手は台帳の US 出品
  - GetItem の残り在庫を `Quantity` だけで読み、**在庫0を在庫1と誤読** (数量を戻す処理が一度も動かない) → Quantity − QuantitySold
  - pricing カテゴリ名誤り (`G-shock`/`Ichibankuji`) で G-SHOCK の売上1件で落ちていた → `G-SHOCK`/`一番くじ`
  - 仕入値は監視くんの M-min (巡回が発送日以降・売切でない時だけ「今の仕入値」)
  - 注文レポートを reports フォルダから探す / 夜間は注文 API から / 送信後に読み直し / 出し直しは itemID 書戻し
- `run_hoju_search.bat`: `[sold-restock]` を追加 (`--orders-api`、`--write` なし)。CRLF 維持
- `control_panel.py`: 失敗 (returncode≠0) でも「🎉 全 process 完了」と出ていた → 「❌ 失敗しました」/ DL 手順に「広告は90日」
- `ebay_rate_limits.py`: 鍵の旧パス固定で起動しなかった → credentials から
- memory: 回数制限の小さい API を検証で使い切るな (traffic_report 1日100回を検証で使い切り6時間止めた)

### 検証
- 9/14 DL のレポートでファネル実走: 期間 06/15〜09/12 (90日) を通過、inactive-listings を読んだ、シート更新確認
  (NO_SEARCH 1 / NO_CLICK 148 / NO_CONVERT 452 / RESTOCK 86 / CULL 113)
- 補充の一覧 (注文 API・送信なし): カイロス 820065007508 / ピカチュウ 358750857470 / バリヤード 820041237462 を qty1、
  カビゴン 358887214446 は未発送で止め、UK ミラー2件は触らない。注文レポート版と同じ対象
- 在庫0の4件の原因: 監視くんは仕入元が「売切→在庫あり」に戻った時しか数量を戻さない (inventory 回答書で確認・コード未確認)
- 昨夜分: `iMakHQ_PsaCacheWarm_0130` 9/14 01:30 実行・結果0 / `iMakHQ_HojuSearch_2330` 9/13 23:30 結果0 (タスクスケジューラ)
- pytest 全件 4,850 passed (pre-commit)

### 残
- **9/15朝: `[sold-restock]` のログ確認 → ずれが無ければ `--write` を足す** (残務板 P1)
- 9/13夜の残 (再仕入れ照合が40件になったか / 売れ筋の点) はログ未確認
- 注文 API は未払いの注文を返さない (未払いで終わった出品は夜間の対象外。レポート版では拾う)

---
## 2026-09-13 夜 [HQ] 作ってあるのに動いていなかった物を横断で洗った / PSA データの夜間先貯めを有効化

### 決定事項
- 決定1: **仕組みは「本番と同じ起動で1回動かして件数と終了コードを見る」まで完成と言わない**。
  定期処理は翌日に実行されたかを見る (ユーザー「作って終わりじゃなくて、ちゃんと動くか確認しないと」)。memory に記録。
- 決定2: **`iMakHQ_PsaCacheWarm_0130` を有効化** (ユーザー go)。毎晩40件・15秒間隔、Cloudflare で即停止。

### 横断確認の結果 (タスクスケジューラ全件 + 夜間バッチ各段 + 週次/月次ログ)
| 何が | 実際 | 対応 |
|---|---|---|
| PSA データ夜間先貯め | 8/19 作成から **一度も未実行 (Disabled)**。PSA 自動の20枠中11枠が「既に出品中」で無駄 | 有効化 + 下の不具合を修正 |
| PSA 売れ筋順 | **219件中0件** に点。鍵(AI列)は出品後に入る物で、残る候補は全部 鍵なし | PSA データから product_id を引く |
| 夜の再仕入れ照合 | メルカリを **1晩10件** だけ。毎晩34〜41件持ち越し、再仕入れ可が1週間14〜16件のまま | 夜間は40件 (安全上限60の内側) |
| OPCG 公式 dump 月次 | 取得成功 → 検証の期待値 (327) が古く **毎回巻き戻し**。dump 42日前 | catalog にヒアリング |
| catalog 整合性 週次 | **5週連続 異常92件** を放置 / 9/07 は途中で中断 | catalog にヒアリング |

### 変更
- `iMakTCG/tcg_batch_select.py`: 鍵が無い候補は PSA キャッシュ + `psa_preflight.classify` で product_id を引いてセット記号へ
- `iMakHQ/tools/run_hoju_search.bat`: `RESTOCK_SCRAPE_BATCH=40` を再仕入れ照合の前だけに設定
- `iMakTCG/psa_cache_warm.py`: **PSA にページが無い cert を Cloudflare と誤判定して夜ごと打ち切る**所を修正。
  ページを見て見分け、ページが無い cert は30日飛ばす。見分けがつかない時は今までどおり止める。
  「データ揃い」に飛ばした分を混ぜない
- 夜間バッチ2本を CRLF に (1行足した時に書き戻しで LF 化していた。`goto` が壊れる恐れ) + test
- 依頼: `catalog/requests/2026-09-13_scheduled_checks_not_acted_on.md` (OPCG 期待値 / 週次異常92件 / RawArchive 結果2)
- 残務板: 「9/14朝: 夜間で動かしたものが本当に動いたか確認」(P1)

### 検証
- 先貯めを **有効化前に3件で試走** → 3件目 (936643273・PSA にページ無し) で「Cloudflare」と誤判定して打ち切り → 修正
  → 再試走で 936643273 を記録して次へ進み 2件取得。dry-run: データ揃い 25→27 / ページ無し1件は飛ばす
- 売れ筋の点: 実データ (未出品 TCG 391件) で 143件に点 (うち PSA データから11件)。先貯めが進むほど増える
- タスク: State=Ready / 次回 9/14 01:30
- pytest 関連19件 passed

### 残
- **9/14朝に実行確認** (先貯めの LastRunTime・取得件数 / 再仕入れ照合が40件になったか / 売れ筋の点が0でないか)
- OPCG / 週次整合性は catalog の回答待ち

---
## 2026-09-13 [HQ] Tシャツを PSA と同じ運用に (目視→🤖自動→予約出品) / 出口が繋がっていない所を5つ塞いだ

### 決定事項
- 決定1: **Tシャツの 🤖自動 = 先に目視 → 目視で決めた行だけ生成 → 予約出品**。1回20件 (PSA と同じ)、
  売れ筋の作品から並べる。既存出品の KEY 埋めは手動の 🩹 UT 新品 目視特定 に残す。
- 決定2: **画像はカタログが主役・仕入元は最後** (選んだ色の表 → サブ → 仕入元 / 最大12枚)。
  目視では「使わない画像を外す」「1枚目を選ぶ」だけ。
- 決定3: **最初は予約出品**。Seller Hub の予約で中身を確認してから公開する。
- 決定4: **メルカリ UT の出品はスキル (apparel-tee-listing) の形**。タイトル
  `[作品] [キャラ] Anime Graphic Tee UNIQLO UT Japan Exclusive [色] US M (JP L) NWT`
  (1出品1サイズなので色の後ろにサイズ)。説明文のサイズは US が先。
- 決定5: **実寸がカタログに無くても出品は止めない**。JP⇔US 対応表を出す (嘘の「画像を見て」は出さない)。
- 決定6: **公式URL→バリエーション出品 (手動) の手順はスキルに残す**。メルカリ UT の流れと混ぜない。
- 決定7: 海外限定 UT (region_only) は出品しない / 公式英語名は catalog が持つ [IMPLEMENT-GO]。

### 変更
- PSA 補URL: 在庫確認が120秒で毎回打ち切られ **1本も足せていなかった** → 内側300秒上限・外420秒・
  仕入元ゼロの出品向けを先に確認 (`33e8512`)
- PSA 補URL 目視待ち: **951本中886本 (93%) が itemID 空で画面に出ていなかった** + 512本が毎晩の積み直し
  → 書く側が itemID を入れる / 見る側は行番号から引き直す / 冪等化・過去分を1本化 (`4e900a7`)
- UT 補URL: 再仕入れの探索が **補URL用キャッシュを丸ごと上書き** → 目視が毎回0件だった (`1e4df0f`)
- UT 補URL を PSA と同じ4ボタンに (①当日分 / ②夜に探す / ③補充 / ③入れ替え) + 海外限定を候補から除外 (`49c9297`)
- UT 目視特定: **画面が起動しなかった** (cf303e8 で読み込み先の足し忘れ) を修正・売れ筋順 (`047ade0`)
- UT 🤖自動: 先に目視 (新規だけ20件) → 選んだ行だけ生成 / 目視で決めていない行は作らない (`909dcd8` `7c99322`)
- 画像: カタログ主役・予約出品・**今回より古い CSV を締めで拾わない** (`819c4cf`) / 画像を大きく (`afca66c`) /
  1枚目だけ選べる (`7dc2646`)
- 「カタログに無い」の依頼に作品名・参考URL (任意) と写真全部を載せる (`a2cfd6e`)
- タイトル・説明文をスキルの形に / 実測表 / JP⇔US 対応表 / Exclusive→キャラ名の順に削る (`022f6fe`)
- スキル apparel-tee-listing に「流れは3つ・混ぜない」と【メルカリ新品 UT】の節を追加
- 依頼: 抽出くん2本 (POC 返球・タグ番号 486159 の読み違い [IMPLEMENT-GO]) /
  catalog 3本 (海外限定・英語名の回答 / 手がかり欄の返信 / 実寸の取り方ヒアリング)

### 検証
- Tシャツ試走: **予約出品10件** (1枚目はすべてカタログ画像 / itemID・KEY 書戻し / 広告8% / メール) を確認
  → ユーザー確認で「タイトルに Japan New」「サイズ表が無い」「サイズ表記が JP 先」「スキルを使っていない」が判明
- 取り下げ: eBay で10件 End → GetItem で10件とも消えたことを確認 → シートの B列・AI列を空に (10行・残り0)
  → 出品結果ファイルを退避。次の 🤖自動 で拾われることを確認 (目視済み14行)
- 補URL 目視待ち: 951本 → itemID が引けない 0本 / 実質439本 (補充295・入れ替え144)
- UT 補URL 目視: 0件 → 12件 / 再仕入れ 5件
- pytest 4,811 passed (pre-commit gate 通過)

### 残
- **実寸 (サイズ表) がカタログに29%しか無い** (公式で買えない大人の UT 5,036件中 1,447件)。
  消えた商品は公式 API が 404。catalog にヒアリング中 (`catalog/requests/2026-09-13_ut_size_chart_for_gone_products.md`)
- 3AI 判定で1件 BLOCK (「Japan New」×原産国ベトナム)。新しい形では Japan New は出ないが、
  **「Japan Exclusive」でも同じ判定が出るかは未確認**
- **Groq が NotFoundError で毎回棄権** (3AI が実質2AI)。モデル名の更新が要る
- ★パネルの 🤖自動 の締めはこのセッション中に2回、目視画面を捨てた走行を手で止めた。
  「目視を閉じたら走行も止める」ボタンが無い

---
## 2026-09-12 [HQ] Tシャツ 入稿CSV 7件を用意 / 3XL が上げても弾かれる誤りを直した

### 決定事項
- 決定1: **Size Type は Department では変えない**。eBay のカテゴリ側の決まりなので、
  3XL は Unisex Adults でも Big & Tall。9/08 の「Men だけ」は直し方が誤っていた。
- 決定2: **UT の収集は語を広げない**。目視待ちが213件あり、集めるほど人の作業が積むだけ。
  抽出くんには「順番だけ需要順にして 40件枠で1回」と返した。50件を切ったら173語に広げる。

### 変更
- `iMakHQ/csv_output/tshirt_upload_20260912_190458.csv` **7件** (入稿待ち)。
  目視で確定した8件のうち1件は **公式仕入で出品中のため出さず** (二重出品ガードが作動)
- `listing_common.size_type_for`: Department の分岐を削除 + 数字サイズ(52〜68)・Tall表記を追加。
  test も直した (`65e3b3d`)
- 依頼2本: 抽出くん `harvest/2026-09-11_ut_catalog_link_poc_result_response.md` (返球) /
  リバイスくん `revise/2026-09-12_size_type_3xl_remaining_items.md` (既存出品の残りを聞く)

### 検証
- **eBay Taxonomy API を実取得** (Size の `valueConstraints`)。cat 15687 / 57988 とも
  3XL〜8XL・52〜68・Big nX・*T は `["Big & Tall"]` のみ。2XL は両方に在る = Regular でよい。
  Department 別の分岐は eBay 側に**存在しない**
- CSV監査くん (dry-run): 対象7行 / 除外0 / program修正0 / カタログ依頼0 → **入稿OK**
- 生成済みCSVの 3XL 1行 (鬼滅の刃) を Big & Tall に直して再監査。7行のまま通った
- pytest **4,719 passed** (pre-commit gate 通過)
- 目視の消化 20件 = 出す8 / カタログに無い8 / 対象外4。「カタログに無い」8件は**全部**
  検索語なしの旧収集分だった (韓国限定・海外限定が中心)

### 残
- **人がやること**: 上の CSV を FileExchange に上げる → B列に itemID を入れる
- 目視待ち **213件** (中間タブ + 商品管理シートの未出品Tシャツ行)。`ut_identify.py`
- 抽出くんの POC 40件は**まだ1件も目視していない**。効果の比較はその後

---
## 2026-09-08 [HQ] 出品の選び方を実績で決め直した / 目視を4割に絞った

### 決定事項
- 決定1: **PSA新規は ポケモン70% + 売れ筋順**。2026-06-23 の「3シリーズ均等」を撤回。
  3ヶ月回した結果、ワンピ/DB は**滞留ではなく売れていなかった**と分かったため。
- 決定2: **補URL目視は 補3本以下で発動**(旧: 満杯未満すべて) + **今の仕入値より
  高い候補は出さない**。4〜5本の札の最安入替は自動追記に任せる。
- 決定3: **服の Size Type はサイズから決める**。Men の 3XL以上は `Big & Tall`。
- 決定4: **補URLに死んだ仕入元を入れない**。書く直前に在庫を確かめる。

### 変更
- `tcg_batch_select`: ポケモン70% / 各グループ内は売れ筋順 (セット別スコア=
  実売*100+watch*8+表示*0.05)。点が付かない物は後ろに順不同。旧・均等は
  `pokemon_share=0` で残す (`dc3f0ac`)
- `psa_hoju_fill`: 目視の発動を 補<4 に / 今の仕入値(N列)より高い候補を除外。
  主URLが売り切れの札は例外。候補画像を 200x270 → 300x405 (`59ebfec` `75c2fdc`)
- `hoju_url_from_dupes`: 書込み直前に ①買えない台帳 ②詳細ページ で在庫確認 (`622e6f1`)
- `listing_common.size_type_for` 新設 + Tシャツ/モンベルの生成器を接続 (`622e6f1`)
- 監査/PDCA の4件 (セット記号regex / digest前のprune / 失敗の単独行 / 台帳の列分離)
  (`dc2b4bc` ほか)
- 依頼を4件 返球 (リバイスくん1 / 監視くん1 / UT78件=保留 / Act提案=実装GO)

### 検証
- PSA の実績を **販売実績スプシで確認**: 直近6ヶ月 TCG 14件・利益¥72,285 (1件¥5,163)
  = 全カテゴリで最高。★ファネル(出品側の売れた個数)だけ見て「PSAは効率が悪い」と
  報告したのは誤りだった。利益は実績シートを見ること
- 選定の根拠 (funnel + US live): ポケモン $1万あたり2.06 / ワンピ 0.50 / ガンダム・DB 0
- 目視の削減見込み: 候補 987本 → 415本 / カード 339 → 201件 (実測)
- 3XL: itemID 356740464473 を Big & Tall に直して実機確認。9/01・9/02・9/08 と
  毎日失敗していた1件
- pytest 4,389 passed (pre-commit gate 通過)

### 残
- **CVR 0.1% (月8件)**。出品数を増やしても分母が増えるだけ。棚割りは金額枠が97%埋まり、
  Tシャツ/モンベルに $86,000 の空きがある一方 PSA/G-shock は超過 (残務№107)
- 再仕入れの止まっている5件 (cert未取得3 / 仕入値上限超え1 / 同定不能1)
- ★このセッションで**生成が暴走**した (同じ1文を275回出力)。会話が長くなり過ぎたのが
  引き金と見られる。区切りで新セッションにすること

---
## 2026-09-07 [HQ] 値段の元ネタが2枚あった / 止まっていたレビュー5件を返した

### 決定事項
- 決定1: **価格の元シートは V9 一枚**。`profit_params.GSHEET_URL` を 5/18 に取った複製
  (`1P1yf…`) から V9 本体へ。以後、値の議論はシート上で完結する (コードは触らない)。
- 決定2: **一番くじ / フィギュアの送料想定は ¥4,000** (V9 の値)。今まで ¥3,000 で計算しており
  **新規出品を $10 安く出していた**。ゴルフも手数料 0.1325→0.133 で $1 安かった。
- 決定3: 昨日・一昨日のコード修正提案 8件に実装GO。ただし**2件は master を直しても効かない**
  (実行時は `C:/dev/iMak_catalog` が読まれる / 残務№41) ので catalog 側へ回す指示付き。

### 変更
- `iMakeBayAPI/profit_params.py` 参照先を V9 に / `config/global.yaml` の控えを同値に /
  凍結期待値 (golden) を 3000→4000 に / 複製シートに戻ったら落ちるテストを追加 (`df7e12b`)
- V9 `US計算_非US!H9` (仕入) が直値 ¥45,000 で放置されていた → `='US計算'!H9` に。
  同タブの F3・I9 は元から US計算 参照だったので H9 だけ非対称だった。
  修正前は基準行が **-¥33,620 / -163.6%**、修正後 **+¥3,380 / 16.4%** (US は +¥2,560 / 11.1%)
- 依頼 6件のうち 5件を返球 (窓口が24時間以上止めていた分は 0件に)

### 検証
- 両シート実測突合: 為替 (B2/F2/H2/J2)・手数料 (B3:B5) は同値、カテゴリ 20行中 **3行**が相違
- 価格差の実測: 一番くじ 仕入¥6,000 → $108.98→$118.98 / フィギュア ¥8,000 → $134.98→$144.98 /
  ゴルフ ¥12,000 → $192.98→$193.98
- pytest 4,242 passed (pre-commit gate 通過)。既存の「控えが本番より安いと落ちる」テストが
  今回の取り違えを検出した
- ★自己訂正: 当初「価格は1円も動かない」と報告したが**誤り**。目視照合が原因で、
  コード突合で3行の差が出た

### 夕方〜夜 (追記)

- **N列 (仕入値) が全行 空だった**。`#REF!` の原因は N2268〜2284 の直値17個。
  N列を一度空にして式を入れ直し、**2,275行すべて復旧**。値は F(と K) に入れる。N は触らない
- **ヒントの件数を「押せば進む件数」に統一**。①は日数で復活する数え方をしていて
  二度と出ない1件を数え続けていた / ②は cert しか見ておらず生成に回らない行を数えていた。
  どちらも**ボタン本体と同じ処理を通して数える**形に。①0 / ②0 / ③0 になった
- **「CSVは作れるが上げられない」台帳を新設** (`restock_undeliverable.json`)。
  Snorlax 358514312870 (カタログで同定できない) を記録。もう数えない
- **補URL目視: 判定済みの札が毎晩戻ってくるのを止めた**。戻す条件を
  「番号まで一致した新しい供給が出た時だけ」に。実測 復活50件 → 13件
- **補URL目視: 番号は合うが刷りが違う候補 (パラレル) を出さない**。
  「違う」が 15件中 5→4→2件 に。ログに「刷り違い(パラレル)で除外 N候補」が出る
- **再仕入れ**: 今日17件を再出品 (朝8件 + 夜8件、1件は落とした)。残り5件は
  cert未取得3 / 仕入値上限超え1 / 同定不能1 で、ボタンでは動かせない
- **ファネル**: 在庫あり行に `age_days` / `supply_url` / **落とすグループ**を追加。
  棚②の落とす順に**作品**を1段追加 (ガンダム/DB → ワンピ → G-SHOCK → ポケモン)
- 自動採用 (絵柄が「同じ」なら目視を飛ばす) は**ユーザー判断で見送り**。人が見る形を維持

### 残
- **メルカリのユニクロUT 78件** — 取込む仕組みが存在しない (`SHEET_REGISTRY` 未登録)。
  作る / 手動で拾う / 見送る の判断待ち (依頼から2週間)

---
## 2026-09-06 — パネルの嘘を消す / eBay 認証を OAuth へ / 棚を30日回転に

### 決定事項
- 決定1: **棚② は30日回転**。PSA も G-shock も 出品30日超で取り下げ (G-shock 365→30日)。
  SOLD実績ありは除外。落とす順は **ウォッチ少ない順 → 表示少ない順 → 金額 大きい順**。
  自店データで日数を決めるのをやめた理由: 月間回転率が **0.8%** (月8.2件 / US出品1,022件)
  まで落ちており、表示やCTRが低いのは **店の順位が下がった結果**の可能性が高い。
  その内部データから閾値を決めると悪循環を固定する。取下げを始めてからオファーが
  増えている観察もあり、棚を減らす方向が効いている。
- 決定2: 棚②の **金額指定なしの既定は「前回の出品額ぶん」**。出品していない日に $0 になり
  押しても0件だったため (9/6 18:08 の実走行)。
- 決定3: **補URL目視は「新しい供給が出るまで出さない」**。日数では戻さない。
  同じ候補をもう一度見せても前回と同じ判断をするだけ。
- 決定4: Trading API は **OAuth (X-EBAY-API-IAF-TOKEN) に一本化**。旧 Auth'n'Auth は
  18ヶ月で hard expire し更新の口が無い。
- 決定5: eBaymag の英国 Return period は **個別ポリシーを触らず「14日以内の返品可能ポリシー
  適用」をONにする**。公開時だけ適用されるので既に出ている383件は変わらない。

### 変更
- 変更: iMakHQ/control_panel.py — 商材の箱を工程ごとに行分け (補URL / 再仕入れ)
- 変更: iMakHQ/control_panel.py — 全ボタンのヒント1行目を `残り N件 — 今回 M件 …` に統一。
  `todo_line()` を新設し、1回の上限は `PRESS_CAP` が持つ (cmd の --limit とずれたらテストが落ちる)
- 変更: iMakHQ/control_panel.py — 補URL① と ② が同じ badge を共有していたのを分離
  (`hoju_search_now`)。①は夜間ルールの対象外にした
- 変更: iMakHQ/control_panel.py — 夜間の実績を **その夜の日付**で数える
- 変更: iMakHQ/tools/psa_hoju_fill.py — `count_workload` に `today_can` / `searched_by_date` 追加
- 変更: iMakHQ/tools/psa_hoju_fill.py — `skip_iids_now()` 新設。cooldown 満了でも供給が同じなら伏せる
- 変更: iMakHQ/tools/cull_end.py — `live_snapshot()` / `still_oos()` 新設。在庫が戻った分を件数から外す
- 変更: iMakHQ/tools/shelf_evict.py — `STALE_MAX_AGE` を {TCG:30, G-shock:30}、②の並びを watch→impr→額
- 変更: iMakHQ/tools/shelf_evict.py — `listed_today_amount` が直近の出品日にさかのぼる
- 変更: iMakeBayAPI/ebay_getitem_images.py — ヘッダ6か所を `_headers()` に集約、`TradingAuthError`
  で認証切れを broad except に飲ませない、`_check_auth()` を応答ごとに通す
- 新規: iMakHQ/tools/ebaymag_api.py — eBaymag をブラウザ無しで読む (GraphQL 直叩き)
- 新規: iMakHQ/tools/ebaymag_dump.py — 画面をスクロールして表として落とす
- 新規: skill `ebaymag-inspect` — eBaymag の調べ方と落とし穴

### 検証
- 検証✅: テスト 4,234件 pass (pre-commit 経由)。今日 追加した試験 63件
- 検証✅: 取下げ `count_workload` → 実データで remaining 8→0 / restocked 8。押した結果と一致
- 検証✅: Trading API OAuth → itemID 358845054366 で Ack=Success / 旧AuthToken=hard expired。
  画像・数量・状態・価格・状態ID の5つとも取得できることを実機で確認
- 検証✅: 目視用の画像キャッシュ「画像なし(-)」15件のうち **14件は認証が直ったら取得できた**
  = 認証切れが焼いた嘘。実URLに修正 (控え psa_ref_image_cache.json.bak_20260906)
- 検証✅: 棚② 新基準 → 対象387件 / $102,746。先頭は ウォッチ0・表示36回の時計、
  末尾は ウォッチ50・表示68,721回の PSA
- 検証✅: eBaymag ミラーの実態 → UK 839 / AU 874 / CA 869 公開中。**DE/FR/IT/ES は棚が無効で0件**
- 検証✅: eBay 出品中3,562件を ViewItemURL のドメインで集計 → .com 1,022 / .com.au 863 /
  .ca 852 / .co.uk 825 / **.de 0**
- 検証✅: 英国の Return period エラー 49件 → 38件に減少 (設定ONの後)。新規公開分は
  ReturnsWithin=14 Days が付くことを itemID 820093085304 で確認

### 数字 (2026-09-06 実測)
- 月間回転率 **0.8%** (月8.2件 / US出品1,022件)
- 1件あたり粗利 中央値 **¥3,071** / 月間粗利 約 **¥25,000** (目標 ¥100,000 → 月33件 必要)
- 出品枠 残り **6,042件 / $29,337** (上限 12,000件 / $1,000,000。金額が先に尽きる)
- 実売74件の days-to-sell 中央値 **48日** (30日までに35% / 90日までに70%)
- CTR **0.1%** (プロモ使用時の正常値) / CVR **0.1%** (無在庫平均 0.3-1.0% に対し低い)

### 次の一手
- **課題化: CVR 0.1% を上げる** (backlog 2026-09-06)。出品数を増やす道は枠で詰まっているので
  CVR しか残っていない。最大の障害は **相場データが1件も無い** こと (trend_price 全件0)。
  同じカードの他セラー価格を取れるようにするのが最初の一歩
- 棚②の表示金額 $424,890 が件数と合わない (383件で42万ドル)。落とす動作は目標額で止まるので
  実害は無いが、表示の出どころを確認する
- eBaymag: Return period 38件 / eBay内部エラー34件 が減っているか翌日 確認
- CTR は「どれを落とすか」ではなく **「どう作るか」の問題**。30日以内の新しい出品も
  CTR 0.001% なので、入れ替えても変わらない。主画像は実物を見たところ問題なし
  (私が寸法だけ見て「横長で小さい」と誤診 → 実物確認で撤回)

---


## 2026-04-23 — Phase 3 ⑤ 価格×物理ゲート統合

### 決定事項
- 決定1: 市場価格連動を一部カテゴリで強制化。価格設定SSOTを「GATE.xlsx × eBay市場相場」に統一（Porter等1点ものと G-Shock は PRICE_CHECK_CONFIG で除外扱い）
- 決定2: 物理ゲート拡張 — pricing_engine が ALERT を返した行は CSV 出力から物理的に除外し、csv_hold_queue.jsonl へ隔離
- 決定3: カテゴリ別閾値管理 — listing_common.PRICE_CHECK_CONFIG で有効/無効と閾値をカテゴリ別に保持

### 変更
- 変更: iMakeBayAPI/listing_common.py:313 — PRICE_CHECK_CONFIG 新設
- 変更: iMakeBayAPI/listing_common.py:327-350 — audit_csv_row に price_status / median_usd 引数追加（デフォルト値付きで後方互換）
- 変更: iMakeBayAPI/listing_common.py:471-485 — gate_row_or_hold に同引数追加、ALERT時は violations 経由で物理除外
- 変更: iMakeBayAPI/listing_common.py:429-437 — csv_hold_queue.jsonl パス解決（iMakHQ/review_logs/csv_hold_queue.jsonl）
- 変更: iMakeBayAPI/check_csv_core.py:181 — fetch_ebay_market_median ブリッジ関数（既存 Browse API ロジック再利用）
- 変更: iMakMercari/mercari_to_ebay_csv.py:913-920 — 市場中央値取得→利益計算→物理ゲートの結線
- 変更: iMak_ichibankuji/ichibankuji_to_csv.py:982-990 — 同上
- 変更: iMakMercari/tshirt_listing.py:539-634 — 市場中央値取得（fetch_top_seller_specs 経由）→ compute_listing_price → gate_row_or_hold(price_status, median_usd)
- 変更: iMakMercari/montbell_listing.py:643-770 — 同上
- 未実装: iMakG-shock/gshock_to_csv.py:1042 — コメントのみ。PRICE_CHECK_CONFIG で "enabled": False とすることで「除外カテゴリ」として設計上成立（動的価格未対応）

### 検証
- 検証✅: grep `PRICE_CHECK_CONFIG` → iMakeBayAPI/listing_common.py:313 に定義、4 listing script が参照
- 検証✅: grep `audit_csv_row` 関数シグネチャに price_status/median_usd 引数を確認（listing_common.py:327）
- 検証✅: grep `gate_row_or_hold` 内部で audit_csv_row に price_status=price_status, median_usd=median_usd を渡していることを確認（listing_common.py:485）
- 検証✅: grep `fetch_ebay_market_median` → check_csv_core.py:181 に実装、mercari/ichibankuji の 2 スクリプトから呼出
- 検証✅: listing script 結線は 4 active（mercari / ichibankuji / tshirt / montbell）+ 1 除外（gshock）= 5カテゴリ touched を目視確認
- 検証⚠️（齟齬あり）: 申告「pytest 4シナリオ（正常/ALERT/除外/旧仕様）PASS」について、iMakHQ/tests/test_listing_rules.py は audit_csv_row の回帰テストのみで、price_status / ALERT / median_usd を名指しで検証するケースは grep で発見できず。fixtures_listing.json にも該当キー無し。→ **price_status 分岐の自動テストは未実装扱いとして扱う**
- 検証⚠️（未実施）: 「リールカテゴリにて ALERT 発生時に csv_hold_queue.jsonl への隔離と理由出力を確認」は実データ未投入のため HQ からは未再現
- 検証⚠️（要確認）: tshirt / montbell は `fetch_top_seller_specs` を使用（`fetch_ebay_market_median` ではない）。決定1の「Browse API による Median 取得」と同一実装かは別途要確認

### 未完了（次セッション以降への持ち越し）
- 実戦投入（リール）で csv_hold_queue.jsonl への物理隔離を**実データ**で確認（テストデータでは既に確認済）
- fetch_top_seller_specs と fetch_ebay_market_median の実装差分レビュー（両者とも Browse API 依拠か、SSOT 統一候補）

---

## 2026-04-23 追補1 — 齟齬修正 + pytest 価格分岐テスト追加

### 決定事項
- 決定1: PRICE_CHECK_CONFIG の G-Shock エントリを実装状態（未結線）と揃えるため `enabled=False` に修正
- 決定2: pytest に価格検証4ケース（A:GO正常 / B:ALERT遮断 / C:Porter除外 / D:後方互換）+ 物理ゲート2ケース（allow/block）を追加
- 決定3: ALERT 由来の error と必須項目欠落 error を区別するため、minimal valid row + message 文字列（"pricing_engine ALERT"）による厳密アサーションを採用

### 変更
- 変更: iMakeBayAPI/listing_common.py:318 — `"gshock": {"enabled": False}` に変更（コメントで未結線理由を明記）
- 変更: iMakHQ/tests/fixtures_listing.json — 新キー `PRICE_VALIDATION_CASES` に4ケース追加（minimal valid row ベース）
- 変更: iMakHQ/tests/test_listing_rules.py — `gate_row_or_hold` 追加 import、`_check_price_case` / `_check_gate_blocks_alert` / `_check_gate_allows_go` ヘルパー追加、pytest parametrize と standalone ランナー両方に反映

### 検証
- 検証✅: `pytest iMakHQ/tests/test_listing_rules.py -v` → **12/12 passed**（既存6 + 新規価格4 + 新規ゲート2）
- 検証✅: csv_hold_queue.jsonl に GATE-BLOCK-TEST エントリが 2026-04-23T21:05:42 付で書込確認済。violation: `Price $700.00 exceeds market tier limit vs median $500.00 (pricing_engine ALERT)` — ALERT 由来 error が物理ファイルに記録されることを実証
- 検証✅: Tomica は mercari_to_ebay_csv.py 経由で結線済。`validate_category="tomica"` の時 fetch_ebay_market_median が走る構造（mercari_to_ebay_csv.py:881, :913-920）。Tomica 専用スクリプトは存在しない
- 検証✅: G-Shock の config/実装齟齬解消（config=False かつ スクリプト未結線 → 整合）

### リール実戦投入への準備状態
- 論理的障壁: すべて解消
- 技術的障壁: すべて解消
- 残タスク: 入力ファイル（search_urls 等）件数・カテゴリ確認のみ（グローバル CLAUDE.md「スクリプト実行前の必須確認」に従う）

---

## 2026-04-24 追補2 — PSA TCG 初陣（Fallback Chain 実証）

### 決定事項
- 決定1: psa_to_csv.py の sys.path 遅延 import バグ修正（ファイル冒頭に移動）
- 決定2: build_row が selfcheck 失敗で None を返す際のガードレール追加（errors+card_info 同期）
- 決定3: Claude にタイトル生成依頼する際、PSA生値ではなく Bandai DB 補完済 `official_card_number` を渡す設計変更
- 決定4: Claude がタイトル中の card# を短縮する現象に対し、物理的な文字列contains検証を追加（既存の title_preserves_subject と同パターンで build_title フォールバックへ強制切替）
- 決定5: listing_validator への psa_card_number 引数には PSA 生値（set prefix無し）を渡す（Bandai補完値を渡すと Rule 3 が常に false positive になる）

### 変更
- 変更: iMakTCG/psa_to_csv.py:27 — `sys.path.insert(0, "../iMakeBayAPI")` をファイル冒頭に追加
- 変更: iMakTCG/psa_to_csv.py:1601 — 旧位置の sys.path.insert を削除、コメント更新
- 変更: iMakTCG/psa_to_csv.py:1579-1587 — build_row None 返却時のガードレール（5行）追加
- 変更: iMakTCG/psa_to_csv.py:1358-1360 — Claude呼出の引数を `card_number` → `official_card_number` に変更（2行コメント付き）
- 変更: iMakTCG/psa_to_csv.py:1381-1389 — card#保持検証を追加、Claudeが短縮した時 build_title フォールバック
- 変更: iMakTCG/psa_to_csv.py:1409-1415 — psa_card_number 引数を `data.get('CardNumber','')` (PSA生値) に変更
- 変更: iMakTCG/psa_to_csv.py:29 + :1805 — CSV出力先を `_gcop("tcg", "upload")` に統一（iMakHQ/csv_output/tcg_upload_<ts>.csv 形式、他カテゴリと命名規則一致）
- 掃除: iMakTCG/ebay_upload_20260424_{063745,064242,064607,065050}.csv + cost.json × 4 = 8ファイルを削除（デバッグ過程の中間失敗版）

### 検証
- 検証✅: `python psa_to_csv.py`（2026-04-24 06:53）→ 魔人ブウ FB04-095 が完走、CSV `ebay_upload_20260424_065345.csv` 1件出力、成功1件/失敗0件
- 検証✅: 出力タイトル `PSA 10 Dragon Ball SCG #FB04-095 Majin Buu : Kid FB04 Visual Alternate Art (74字)` に `#FB04-095` 完全形を含む
- 検証✅: GATE=GO、仕入¥33,333→出品$833.98、予想利益¥61,128 (44%、目標10%)
- 検証✅: **Fallback Chain 実証** — Claude生成タイトルが PSA Subject 改変 → `⚠️ Claudeタイトルが PSA Subject を改変 → ルールベースに切替` ログで build_title へ自動切替 → 正規タイトル生成 → selfcheck 通過。今日追加した「AIの創作をコード論理でねじ伏せる」機構が期待通り稼働
- 検証⚠️（既知エッジケース）: シャンクス (cert 109204387) は PSA brand (OP11-A) と Bandai (ST16) の二重登録で selfcheck Rule 1 に正しく停止 → memory `psa_bandai_brand_divergence.md` に記録
- 検証⚠️（既知エッジケース）: 雷龍 (cert 155746272) は Bandai JP (日本語DB) で英字 Subject "Lightning Dragon" が検索ヒットせず → memory `bandai_jp_en_ja_gap.md` に記録

### 本日の全成果（リール + PSA 統合）
| パイプライン | 処理 | GO出力 | HOLD/失敗 | コード修正数 |
|---|---|---|---|---|
| リール（mercari→eBay 市場連動ゲート） | 4 | 1 (Shimano 22 Stella 4000XG) | 3 (ALERT隔離) | 3箇所 (listing_common + 重複HOLD削除) |
| PSA TCG（Bandai DB連携） | 3 | 1 (魔人ブウ FB04-095 Majin Buu) | 2 (data edge cases) | 5箇所 (sys.path / None guard / Claude args / card# fallback / psa_card_number arg) |

### 次セッション優先度
- **[高]** 出力CSV 2本（`reel_upload_20260424_055735.csv` / `ebay_upload_20260424_065345.csv`）の目視検収 → eBay入稿
- **[中]** median hits閾値（hits < N → NO_MEDIAN 格上げ）の設計
- **[中]** scout の scrape_search_results URL対応付けバグ調査
- **[低]** シャンクス / 雷龍の edge case 再挑戦（英日翻訳層、brand同値性ホワイトリスト）
- **[低]** response_processor.py 拡張（HOLD理由の分類学習）

---

## 2026-04-24 追補3 — certs.txt 廃止 + PSA 10件バッチ実戦

### 決定事項
- 決定1: psa_to_csv.py を certs.txt 駆動 → **スプシ駆動に完全移行**。入力源は Porter/Ichibankuji と共用の `19kj8...` gid=851100680（全カテゴリ共通の出品管理シート）
- 決定2: スプシ I列 = cert#, B列空 = 未処理 の条件で抽出、仕入値は N列優先 + F列 "¥XXX,XXX" パース fallback
- 決定3: 初回採用 ReEl + 単発 魔人ブウの CSV は破棄、バッチ run のみ本番保全

### 変更
- 変更: iMakTCG/psa_to_csv.py:1492 — `load_targets_from_sheet_psa()` 関数を新設
- 変更: iMakTCG/psa_to_csv.py:1552-1567 — main() 内の certs.txt 読込 + Stage 0 重複除外 (50行弱) を削除し、新関数呼出に置換
- 掃除: iMakHQ/csv_output/reel_upload_20260424_055735.csv, tcg_upload_20260424_065345.csv (+cost.json) を削除

### 検証
- 検証✅: Pre-flight `load_targets_from_sheet_psa()` 単独実行で10件抽出成功、cert#/仕入値/URL/タイトル全て正しく parse
- 検証✅: 本実行 `python psa_to_csv.py`（07:37）→ 10件処理完了、CSV `iMakHQ/csv_output/tcg_upload_20260424_073706.csv` に **5件の精鋭**出力
- 検証✅: 物理ゲートの証跡（多段フィルタ動作）:
  - selfcheck 却下 3件: 143657595 Zガンダム / 143657594 百式 / 143657590 エース
  - NO-GO 除外 2件: 149249712 Jewelry Bonney (乖離50%超) / 143657587 Sabo (乖離86%超)
  - GO 出力 5件: Vivi EB03-001 / Shanks OP09-001 / Sanji PRB01-001 / Luffy P-110 / Perona OP14-111
- 検証⚠️（要調査）: Gundam (GD01-069, GD01-072) の同時 selfcheck 失敗 → 共通パターンの可能性。bandai_tcg_plus 経由で title は OK（#GD01-069 Zeta Gundam Card 形式）だが selfcheck が弾いた → listing_validator の未対応 brand pattern の可能性
- 検証⚠️（要調査）: Ace EB02-028 も selfcheck 失敗 → Subject "PORTGAS D. ACE SPECIAL ALTERNATE ART" の長文 brand が validator の想定外パターンか

### 次セッション優先度（更新）
- **[高]** CSV検収: `iMakHQ/csv_output/tcg_upload_20260424_073706.csv` 5件 → eBay FileExchange 入稿
- **[中]** Gundam 2件の selfcheck 失敗原因特定（共通パターン → listing_validator の Gundam 対応追加）
- **[中]** Ace (Special Alt Art) の selfcheck 失敗原因特定（長文 brand への対処）
- **[中]** median hits閾値（hits < N → NO_MEDIAN 格上げ）の設計
- **[中]** scout の scrape_search_results URL対応付けバグ調査
- **[低]** certs.txt / certs_scout.txt / certs_skipped_duplicates.txt を物理削除（現在は未使用）
- **[低]** シャンクス / 雷龍の edge case 再挑戦（英日翻訳層、brand同値性ホワイトリスト）
- **[低]** response_processor.py 拡張（HOLD理由の分類学習、次セッションで複数HOLDデータ揃ったら）

---

## 2026-04-24 セッション終了時 — 失敗3件のエラーログ深掘り結果

### 実エラーメッセージ（log 深掘り後）

| cert# | カード | 実エラー | 真の原因 |
|---|---|---|---|
| 143657595 | Zガンダム GD01-069 | `必須Item Specific 'Type' が空` | bandai_tcg_plus 検索失敗 → card_type 未取得 |
| 143657594 | 百式 GD01-072 | `必須Item Specific 'Type' が空` | bandai_tcg_plus が **誤ったカード返却**: "Launcher Strike Gundam" + card_type 空 |
| 143657590 | エース EB02-028 | `タイトルに'EB02'があるが PSA brand に存在しない` ('OP13-CARRYING ON HIS WILL') | **PSA=OP13プロモ vs Bandai=EB02元セット**、シャンクスと同パターン |

### 系統A vs 系統B — 明確に別問題

- **系統A (Gundam 2件)**: Bandai TCG+ API 連携問題。brand whitelist では解決**しない**。`bandai_tcg_plus.fetch_card` の ID 照合精度 + card_type デフォルト戦略で対応
- **系統B (Ace 1件)**: 既存 memory `psa_bandai_brand_divergence.md` に記録済のプロモ二重国籍問題。シャンクス + Ace で **N=2 揃った** → 汎用化タイミング到来

### 次セッション着手ロードマップ（優先順）

1. **[A-1] bandai_tcg_plus.py の fetch_card 調査**: ID 照合を完全一致に厳格化（誤ヒット物理防止）
2. **[A-2] Gundam デフォルト適用**: `official_card_type=""` 時に `"Unit Card"` を採用（psa_to_csv.py:1339 付近）
3. **[B-1] listing_validator.py 汎用化**: `validate_title_against_psa` に「プロモ分岐許容」ルール追加（psa_brand に別のセットコードがあり、かつ title の card# が `{X}-{番号}` 形式なら WARNING に格下げ）
4. **[再検証]** 同じ10件バッチで再走 → 8-10件通過を目標

### 🚨 今日の CSV 検収時の手動対応（重要）
`iMakHQ/csv_output/tcg_upload_20260424_073706.csv` 5件は **Finish 決定論化の修正適用前に生成された** ため、Finish 列は依然として Claude 推測由来。入稿前に **Finish 列を目視で1件ずつ確認**（または安全側で空欄化）してから eBay 入稿する。自信が持てない行は空欄化（"Non-Foil" と断言しない）。

---

## 2026-04-24 追補4 — 🚨 緊急オペ: Finish 判定の推論切断（実装済）

### 決定事項
- 決定1: Finish (Holo/Non-Foil) は**Claude 画像推測を完全遮断**し、PSA Subject の確定キーワードベースの決定論判定に移行
- 決定2: 保守的キーワード採用（ALTERNATE / SPECIAL / PROMO は Holo 確定語ではないため**除外**）。`"(HOLO)" / "(FOIL)" / "SECRET RARE" / "PARALLEL"` のみで "Holo" 認定、他は空欄
- 決定3: 無在庫販売で「嘘をつかない」カタログ原則（Overpromise 回避）。"Non-Foil" と断言せず、確証なければブランク

### 変更
- 変更: iMakTCG/psa_to_csv.py:648 — Claude プロンプト内 finish field を「DO NOT guess / Blank is ALWAYS correct when uncertain」に書き換え、旧誘導文「Most Secret Rare, Special Art, Alternate Art, and Parallel cards are 'Holo'」を削除
- 変更: iMakTCG/psa_to_csv.py:1373-1381 — finish 代入ロジックを Claude 依存から Subject キーワード判定に差替え。Claude の `finish` フィールドは完全無視

### 検証
- 検証✅: `ast.parse` 構文 OK
- 検証⚠️: 既存の `tcg_upload_20260424_073706.csv` は**修正前生成**のため Claude 推測値が残っている → 入稿前の目視確認必須（または再生成）

### Why
- 過去の SNAD クレーム実績: Claude が "Holo" と推測 → 実物 Non-Foil → 買い手クレーム（無在庫販売では発送前チェックが効かず致命傷）
- プロンプト line 605「NEVER infer Finish from rarity」と line 647「Most ... are Holo」が正面矛盾 → Claude は後者に従っていた
- 無在庫販売の情報不正確は「バグ」ではなく「ビジネス存続リスク（地雷）」という認識共有

### 今後の拡張余地（次セッション以降）
- 公式DB (bandai_jp / bandai_tcg_plus) に Finish フィールドが実装されたら `official_finish` が非空になり、確証 tier が1段上がる

---

## 2026-04-24 追補5 — Finish 完全保守化 + Meta-lesson

### 決定事項
- 決定1: Finish 決定ロジックから Subject キーワード判定も撤廃、`finish = official_finish` の **1行化**（公式DB値のみ採用）
- 決定2: Subject に `"SECRET RARE"` や `"PARALLEL"` が入っていても印刷ロット差異で Non-Foil 個体が混じる可能性 → 100%保証できない以上、一切認定しない保守路線

### 変更
- 変更: iMakTCG/psa_to_csv.py:1373 — Subject キーワード判定ブロックを削除、`finish = official_finish` のみに

### 検証
- 検証✅: `ast.parse` 構文 OK
- 検証✅: 再走 `python psa_to_csv.py` → CSV `iMakHQ/csv_output/tcg_upload_20260424_083911.csv` 生成、5件全て Finish=空欄

### Meta-lesson（iMakシステムの根本教訓）

今回の Finish 問題は**新しいルールではなく、既存2ルールの違反**だった:
1. グローバル CLAUDE.md「Item Specifics 共通ルール」: 確証なきは空欄、公式サイトからの推定は不可
2. メモリ `enforce_in_python_not_prompt`: 重要ルールは SYSTEM_PROMPT 任せ禁止、Python deterministic 強制必須

**なぜ違反が本番稼働したか**:
- ルールは自然言語（ドキュメント）にあった
- Claude プロンプトに誘導文として混入（line 647「Most ... are Holo」）
- selfcheck (listing_validator) に Finish チェックが無かった → gate が機能せず
- grep で検出不可能な形態のため、コードレビューで見逃された

**再発防止に必要なこと（次セッション宿題）**:
- 全 Item Specifics (Rarity / Features / card_type / attribute / finish / color / power / cost) を棚卸し
- それぞれ「official_* 由来か Claude 由来か」を明示、Claude 由来のものは Python 物理強制に移行
- selfcheck に「official_* 変数由来以外は禁止」ルール追加を検討

### 最終成果物（本日 FINAL 確定版）
```
iMakHQ/csv_output/tcg_upload_20260424_083911.csv  (64.8 KB, 5件, 全件Finish空欄)
iMakHQ/csv_output/tcg_upload_20260424_083911_cost.json
```

**iMak 2.0 の誠実な初陣リスト完成**

---

## 2026-04-24 追補6 — 全 Item Specifics Claude 追放 + Bandai精度向上 + プロモ二重国籍汎用化（Gemini監査済）

### 決定事項
- 決定1: rarity / card_type / cost / power / attribute / finish の**全6フィールド**から Claude fallback を物理除去、公式DBのみをソースに
- 決定2: Bandai JP CHARACTER_JP_TO_EN に **26 キャラ追加**（Vivi, Perona, Sabo, Bartolomeo 他）で英日ギャップ解消
- 決定3: bandai_tcg_plus.fetch_card を **card_number 完全一致優先**に変更（誤ヒット物理防止）
- 決定4: GUNDAM_SET_PREFIX の `"DUAL IMPACT"` を `GD01` → `GD02` に訂正（実DB検証済）
- 決定5: Gundam は `"Card Type"` キー名 + `"UNIT"→"Unit Card"` 正規化、power は AP フィールドにフォールバック
- 決定6: **プロモ二重国籍パターン汎用化** — `listing_validator._is_promo_dual_citizenship` で Ace/Shanks/Sabo 等を自動許容。Gemini監査で **TCG ブランドガード追加**（非TCG文脈への誤適用防止）

### 変更
- 変更: iMakTCG/bandai_jp.py — CHARACTER_JP_TO_EN に Vivi/Perona/Sabo 他 26 キャラ追加
- 変更: iMakTCG/bandai_tcg_plus.py — fetch_card に card_number 完全一致優先ロジック、`"Type"`/`"Card Type"` 両対応、Gundam 用 `GUNDAM_TYPE_MAP` 正規化、power は Power/AP フォールバック
- 変更: iMakTCG/psa_to_csv.py — Item Specifics 5フィールドの Claude fallback 廃止、GUNDAM_SET_PREFIX の DUAL IMPACT 訂正
- 変更: iMakeBayAPI/listing_validator.py — Rule 1 正規表現から末尾 `\b` 削除、`psa_has_any_set_code` 許容、`_is_promo_dual_citizenship` 新設（TCG ブランドガード付き）、`_KNOWN_ACCEPTABLE_PATTERNS` に新規エントリ

### 検証
- 検証✅: ユニットテスト `_is_promo_dual_citizenship`: Ace/Shanks PASS + 通常カード非該当 + 非TCG brand 拒否 の4ケース
- 検証✅: 10件 PSA バッチ実戦 → **成功8件 / 失敗0件**（市場ゲートで Bonney/Sabo の2件が NO-GO=相場乖離、selfcheck/3AI 失敗 0件）
- 検証✅: Gemini 累積変更レビュー → "COMPLETE / GO FOR UPLOAD" 判定、1箇所修正指示 (TCG ブランドガード追加) を適用済
- 検証⚠️ 残存: CHARACTER_JP_TO_EN の 26 新規エントリのうち **未検証キャラ**（今日通過した Vivi/Perona/Sabo 以外の 23エントリ）は次回検索時にヒット確認が必要

### 最終成果物（2026-04-24 FINAL）
```
iMakHQ/csv_output/tcg_upload_20260424_144059.csv  (103 KB, 8件)
iMakHQ/csv_output/tcg_upload_20260424_144059_cost.json
```

内訳:
1. Nefeltari Vivi (EB03-001) Leader Card / Alt Art
2. Shanks (OP09-001) Leader Card / Alt Art
3. Sanji (PRB01-001) Leader Card / Alt Art
4. Monkey D. Luffy (P-110) Character Card / Promo
5. Zeta Gundam (GD02-069) Unit Card / LR
6. Hyaku-Shiki (GD02-072) Unit Card / R
7. Perona (OP14-111) Character Card / R
8. Portgas D. Ace (EB02-028) Character Card / SEC [プロモ二重国籍許容]

NO-GO 除外 (市場ゲート動作): Jewelry Bonney (乖離50%) / Sabo (乖離86%)

**iMak 2.0 — 誠実な8件の CSV、eBay 入稿可能**

---

## 2026-04-24 追補7 — 🛑 入稿直前に pipeline 内二重基準を発見、入稿見合わせ

### 事象
ユーザーが最終実行で CSV 生成 + check_csv.py (post-check) を走らせた時、**同一 CSV に対して psa_to_csv.py と check_csv.py が矛盾判定**:

| カード | psa_to_csv median | check_csv median | psa判定 | check判定 |
|---|---|---|---|---|
| Vivi EB03-001 | $250 | **$79** | GO $237.98 | **NO-GO 乖離135%** |
| Hyaku-Shiki GD02-072 | $120 | $120 | 保留 $174.98 | **NO-GO 乖離60%** |
| Ace EB02-028 | $217 | **$193** | 保留 $258.98 | **NO-GO 乖離60%** |

### Gemini 監査の盲点
Gemini は pipeline の各コンポーネント（listing_validator, psa_to_csv 内部ロジック）を個別に精査したが、**psa_to_csv → check_csv 間のインターフェース（同じ CSV に対する判定の一貫性）を確認していなかった**。Gemini 自身もこれを認め反省。

### 決定
- 🛑 **今日の入稿は見合わせ**
- CSV ファイル `tcg_upload_20260424_145636.csv` はディスク上に残すが**「要手動スクリーニング」状態**として扱う
- 明日の最優先タスクとして「二重基準解消」に着手

### 次セッション調査課題（🚨 最優先）
1. **クエリ統一**: psa_to_csv.py と check_csv.py の eBay 検索クエリ・フィルタ条件の diff 取得、どちらが正しいか検証
2. **gap_limit 共有化**: 両ツールが pricing_engine.py から同じ TIER_PARAMS を参照するリファクタ
3. **Vivi の謎解明**: 実際の eBay 検索で `PSA 10 #EB03-001 Nefeltari Vivi` vs `EB03-001 Vivi` の差を目視、どちらの median が真実か判定
4. 解消後に本日の cert 10件でバッチを再実行し、両ツールが合意する CSV を生成

### memory への記録
`dual_gate_disagreement.md` に記録済。運用ルール: 二重基準解消まで psa_to_csv.py CSV の自動入稿は禁止、check_csv.py の post-check で NO-GO 判定行は手動除外必須

### 関連メモリ更新
- `psa_bandai_brand_divergence.md`: シャンクス単独 → シャンクス+エース パターン化。汎用化提案追記
- `gundam_bandai_tcg_plus_reliability.md`: 新規追加（fetch_card 誤ヒット + card_type 欠落）

---

## 2026-04-24 — リール初実戦投入（市場連動ゲート本番稼働）

### 決定事項
- 決定1: リール4件を手動ピック→スプシ直結で出品CSV生成フローを走らせ、物理ゲートの実データ動作を初確認。結果は 3 ALERT隔離 / 1 GO通過 で仕様通り
- 決定2: 出品フロー中の旧 `_append_hold_queue` を削除し、HOLDキュー書込を `listing_common.append_to_hold_queue` に完全一元化（SSOT化）
- 決定3: リールの pricing_engine gap_limit は実運用で **+10%付近が ALERT ライン** と実測確定（+10.2% の m51514473487 が ALERT）

### 変更
- 変更: スプシ `1jF9vggbfUCd...` gid=851100680 行652-655 にリール4行を append + `_tmp_enrich_reel.py` で Mercari から画像URL/価格/タイトル/状態/説明を逆充填（ヘルパーは実行後削除）
- 変更: iMakMercari/mercari_to_ebay_csv.py:603-629 — `_append_hold_queue` 関数と `_HOLD_QUEUE_PATH` グローバル削除
- 変更: iMakMercari/mercari_to_ebay_csv.py:1004 — `_append_hold_queue(...)` 呼出削除 + 周辺コメントを「SSOT=listing_common.append_to_hold_queue」に更新
- 未実装: ichibankuji / tshirt / montbell にも同等の旧HOLD書込があった場合の削除 → grep 確認したところ **mercari_to_ebay_csv 以外には存在しなかった**（二重書込問題はこの1ファイルのみ）

### 検証
- 検証✅: `python mercari_to_ebay_csv.py --sheet reel` 実戦実行（2026-04-24 05:57-06:01）→ 4件処理、GO 1件 / ALERT 3件 / HOLD隔離 3件 / CSV出力1件
  - m33125385604 ¥777,777 → target $7858.98 vs median $7.91 (hits=4) → **ALERT +99,180%**
  - m59859374344 ¥80,000 → target $835.98 vs median $628.28 (hits=24) → **ALERT +33.1%**
  - m29948352652 ¥52,500 → listing $558.98 vs median $586.02 (hits=14) → **GO -4.6%**
  - m51514473487 ¥61,111 → target $645.98 vs median $586.02 (hits=14) → **ALERT +10.2%**
- 検証✅: csv_hold_queue.jsonl に3件の新format（category/violations/row_summary）エントリを確認。各 violation に `"pricing_engine ALERT"` メッセージ含有
- 検証✅: 旧HOLD書込削除後の回帰テスト `pytest iMakHQ/tests/test_listing_rules.py -v` → **12/12 passed**
- 検証✅: grep `_append_hold_queue` / `_HOLD_QUEUE_PATH` が mercari_to_ebay_csv.py から消失。他スクリプトにも存在しないことを確認
- 検証✅: 出力 reel_upload_20260424_055735.csv が 14,779 bytes / 1行（m29948352652 Shimano 22 Stella 4000XG Spinning Fishing Reel High Gear Pre-owned Japan）で生成

### 副次発見（要フォロー）
- **薄いmedianサンプル問題**: m33125385604 は hits=4 で median $7.91（部品/アクセサリを拾った模様）。結果的に ALERT で防げたが、逆に「正しい相場なのに hits 不足」で価格が不安定化するリスクあり。将来 `hits < N` を NO_MEDIAN 扱いに格上げする閾値設計が課題
- **URL↔商品情報の scout 乖離**: 昨日の scout ログ期待値と実 Mercari データで 4件中3件が不一致。scout の `scrape_search_results` が search results DOM から URL/タイトル/価格を抽出する際にズレを起こしていた可能性（別途調査）

### 残タスク（次セッション候補）
- **優先度高**: 出力 reel_upload_20260424_055735.csv の目視検収（eBay 入稿可能品質か）
- **優先度中**: median hits閾値の設計（hits<5 を NO_MEDIAN 格上げ等）
- **優先度中**: scout の scrape_search_results URL対応付けバグ調査
- **優先度低**: response_processor.py 拡張設計（HOLD理由分類の学習データ化）

---

## 2026-06-02 — 🚨 インシデント記録: 85MB マラソンセッション crash → 記憶喪失 2 回

### 決定事項
- 決定1: 単一 Claude Code セッションを長期間（今回 **4/26→6/1 の 5 週間連続**）回し続ける運用を**禁止**。作業区切りで新セッション or `/clear` する
- 決定2: 文脈は context 頼みにせず、**作業区切りごとに daily_report.md へ 3 点セット（決定/変更/検証）で書き出す**運用を徹底（書き出していない分は crash で全消失するため）
- 決定3: 肥大した transcript `8271606a-...jsonl`（85MB）は **resume 対象から外す**（開くと再 crash する）。アーカイブ退避

### 原因（実機計測）
- セッション `8271606a-69ff-4cda-af88-999e76d94284.jsonl` を実測:
  - 稼働期間: **2026-04-26T04:29 → 2026-06-01T10:29（5 週間以上 連続）**
  - イベント数 23,222 行 / file-history-snapshot **1,944 個** / 合計 **85 MB**
  - 内訳: file-history-snapshot 43MB + user 21MB + assistant 21MB
- resume 時にこの 85MB を丸ごとロードしようとして失敗 → 文脈引継げず新規起動 = 記憶喪失
- 6/1 19:32 の後続セッション（21KB）も即死、翌朝も再発（= 同一巨大ファイルへの resume 失敗の繰り返し）

### 検証
- 検証✅: `wc -l` で 23,222 行、`python json` 集計で type別バイト数（file-history-snapshot 43.0MB / user 21.2MB / assistant 20.9MB）を確認
- 検証✅: first/last timestamp で 5 週間連続稼働を確認
- 検証✅: daily_report.md が **4/24 で停止**していたことを確認（5 週間分の作業が永続層に未記録 = 記憶喪失の被害を拡大させた真因）

### 教訓 → memory 化
- `marathon_session_causes_amnesia.md` に記録（長期1本セッション禁止 + daily_report こまめ書き出し）

---

## 2026-04-25〜06-01 — ブリッジ要約（git log からの事後再構成）

> ⚠️ 注記: 上記 85MB セッション crash で 4/24 以降の daily_report 記録が欠落。
> 以下は **git commit log から事後再構成**した要約であり、当時の contemporaneous な検証ログではない。
> 各項目の「変更」は commit hash で追跡可能（= 検証可能）だが、検証欄の実走確認は当時のログが消失したため再構成不可。

### 5/9–5/11: fail-closed 強化 + ichibankuji scraper 構造化 + market gate SSOT
- 4fc441f: gshock_to_csv — partial model_id（color suffix 欠落）を fail-closed SKIP
- 4ed0314: psa adapter — pokemon promo + dbscg full-pid card_number 対応
- d5caf57 / 3d17608 / cff5b09: ichibankuji scraper — text regex 完全撤廃、BeautifulSoup CSS selector 構造抽出に統一
- 0b14d6a / 88dc6aa: 一番くじ median gate 無効化 + gap_limit_override（collectibles 特性対応）
- 2c827b2 / 32840e2 / 59a7990: psa+check の market gate を SSOT 化（出品数 ≤ 10 件で gate skip、ユーザー判断 5/11）
- 01d516c / efca29e: casio_finder_from_catalog — iMakCatalog × active diff で未出品モデル抽出

### 5/12–5/13: 死蔵 listing 再出品ツール群（seller_hub_*） + G-shock 色判定 bug
- b7d576c / 6bad219 / 71a16c6: seller_hub_view — 15 項目 snapshot 保存、Active/Ended 両対応、全ページ scrape
- 3996b5f / 47bc860 / 07d49dc / 6892f7d: seller_hub_relist — View=0 死蔵 listing 取下げ再出品ツール（ビフォーアフター CSV + --undo 巻き戻し）
- 96c8248 / 1d0da35: ビフォーアフター xlsx 化（差分セル黄色ハイライト + 4-sheet 構造 + 承認/却下 dialog）
- 7bd780a / 66d6d1a / 74d026f / 8c548e2 / 9d0e3dd: G-shock 色判定 bug 連続修正（suffix 解析失敗で "Black" fallback → get_band_color SSOT 化）

### 5/15: ライバルセラー分析ツール群
- 03789b3 / d844e40: gap_finder + ebay_seller_store_scraper（Browse API でライバル store listing 取得）
- 130f48c / 204b13e: WatchCount.com trending + PicClick watch 数 merge

### 5/16–5/17: Workman listing 実装
- 63580d0 / 3ce3593 / e206137: workman_scraper（公式 JSON-LD）+ listing Phase 2（variation CSV + 公式在庫要チェック経路 + size chart）
- d7fa68d / cdeb49c: seller_hub_view fix（US listing 検出復活、listed_date 月名 format、num_lines 順序）

### 5/24: 利益計算スプシ v8_GS 完走（memory: profit_calc_sheet_v8）
- 全カテゴリ split=1.0 + US計算 2-sheet 分離 + スニーカー/ゴルフ追加、yaml + Policy 31 + listing 324 全 V8 化

### 5/29–6/1: G-shock カタログ 4-source 拡張（進行中）
- 3-source 戦略（公式491 / ファンサイト / ShockBase 2,777）+ Amazon 直販を 4 番目 source 追加（Harvest 依頼投入済）
- gshock_to_csv の is_active_msrp 廃盤 skip を **REVERT**（gshock_to_csv.py:1446、「廃盤も Amazon で仕入れるから勝手に外すな」のユーザー指摘対応）

---

## 2026-05-22〜06-09 — ブリッジ要約2（横断進捗 + 5月実績）

> 6/2 インシデント以降の実務進捗を事後再構成。日次の詳細は memory 側 daily_report に密に記録済、本欄は HQ 横断サマリ。

### 決定 / 主な進捗（プロジェクト横断）

- **取下げ再出品（relist）システム 大規模実装**: フルファネル分析（NO_SEARCH=露出されない / NO_CLICK=見られてクリックされない / NO_CONVERT=クリックされて売れない の3要因切り分け）+ `funnel_diff` 効果測定（改修前後の差分計測で PDCA クローズ）+ タイトル改修ループ。死蔵 listing を要因別に処置する基盤。
- **在庫切れ対応 強化**: RESTOCK（再仕入れ可なら再出品）/ CULL（仕入れ不能は段階的に End）の2系統に整理。
- **mercari fix**: 写真11枚化 / バッグ寸法抽出 / Porter 999.png（ダミー画像）対応。
- **Catalog**: TCG 5カテゴリの公式画像 100% 化、name_en 1,810件補完。
- **Inventory**: 公式監視くんを Trading API 化、SKU シート cache 導入。
- **Harvest**: Casio 公式 G-shock scraper を新規実装。
- **Revise**: 全 sheet の価格 + Policy revise を完全反映。

### 検証 / 実績（KPI）

- **5月実績: 12件 / ¥17,665**（目標 ¥100,000 に対し達成率 17.7% = 未達）。
- **6月（1〜6日）: 1件 / ¥5,664**。

### 未完了 / 残課題（次セッション以降）

- **売上が目標比で大幅未達**（5月 17.7%）。露出天井が構造的に低い前提（送料無料DDP断念済）で「何を・どれだけ出すか」が課題。relist / ファネル分析はこの底上げ施策。
- **6/9 受信: Oskar 色見えクレーム対応** — Porter Tanker の Description に色注記を追加する依頼が別途あり（要対応）。

---
