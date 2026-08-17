# iMakHarvest — 商品ソース URL 集約プロジェクト

## 🛡️ Worktree 分離ルール (2026-05-01 制定・絶対厳守)

**この worktree (`C:/dev/iMak_harvest/`) は Harvest Claude 専用**。

- ✅ Harvest Claude: ここで作業
- ❌ Inventory Claude / Catalog Claude / その他: **絶対 touch 禁止**
- ❌ 他 worktree (`C:/dev/iMak/` `C:/dev/iMak_inventory/`) への touch も禁止

詳細は `.PROJECT_LOCKED.md` 参照。グローバル `~/.claude/CLAUDE.md` の Worktree 分離
ルールも厳守。違反は他プロジェクトの自動運用を破壊する致命行為。

---

## 📏 何を集めるか決めるルール (2026-08-18 制定)

**毎回考えない。この順で決める。** 例外を足さない。

### ① 語 (何で検索するか) の作り方

1. **需要実証済を最優先** — ファネル分析スプシの `RESTOCK` (在庫=0 ∩ 需要>0)。
   走行のたびに読み直す (人が写した値を使わない)。実売 > watch > 露出 の順に並べる。
2. **弾コード総当たり** (`psa_search_terms`) は 1 の後ろに足す。網羅の下支え。
3. **カード番号が取れた行だけ語にする**。英語カード名やキャラ名から推測して語を作らない
   (別カードを掴む = 誤出品に直結)。
4. **語は減らさず増やす**。1 語 15 件が検索側の上限なので、語を削るとその枠ごと消える。
   上限に張り付いた語は「カード番号単位」に刻んで増やす。
5. **2 走行連続で 0 件の語だけ落とす**。落とした語は daily_report に残す。

### ② 拾った出品をどう扱うか

| 状態 | 扱い |
|---|---|
| cert が読めた + PSA10 + セラー基準を満たす | 候補 (I列に cert) |
| **cert が読めなかった** | **I列空欄で投入** (目視で確認。出品くんは I列非空しか拾わない) |
| グレードが PSA10 でないと判明 | 捨てる |
| セラー評価 <100 / 本人確認なし / 売切 | 捨てる |
| 本番 (HIGH/LOW) で既に押さえている URL / cert | 捨てる |
| ページ取得に失敗した | **捨てない。⚠️要対応として件数と URL を出す** |

★「読めなかった」(写真の問題 = 正常な reject) と「確認できなかった」(こちらの障害 =
Vision 障害 / 取得失敗) を混ぜない。後者は必ず要対応として表に出す。

### ③ 走行のたびに残すもの

収集数 / 候補数 / I列空欄で入れた数 / 未判定数 (取得失敗) / 語ごとの件数。
未判定が 0 でない走行を「正常」と書かない。

iMak Trading Japan の出品候補商品の **入り口管理**。Mercari いいね /
Amazon お気に入り / 等から商品 URL を収集し、各カテゴリのスプシに転記する。

trabajo の `getMercariUrls / getAmazonUrls / etc` 機能の代替。

---

## 役割

| やる | やらない |
|---|---|
| Mercari いいねから URL 収集 | 出品作業 (各 listing project に任せる) |
| Mercari Shops products から URL 収集 | 在庫監視 (iMakInventory に任せる) |
| Amazon ウィッシュリストから URL 収集 | eBay 取り下げ (iMakInventory に任せる) |
| 各カテゴリのスプシに URL 書込 | リスティング作成 (iMakTCG / iMakG-shock / etc) |
| 重複防止 (item_id デドゥープ) | バイヤー対応 (iMakAdvisor) |
| GUI 操作パネル | コード修正 (iMakHQ) |
| 4h cron 自動巡回 (任意) | |

---

## スコープ (Phase 1)

- Mercari 通常 (`/item/m...`) いいね収集
- Mercari Shops (`/shops/product/...`) 収集
- Amazon ウィッシュリスト (ASIN 抽出)
- スプシ書込 (HIGH/LOW or 任意スプシ指定)

## Phase 2 (任意)

- ヤフオク・ラクマ・PayPay フリマ (現運用に対象無ければ不要)
- いいね削除機能 (収集後の整理)
- 既出品との突合 (eBay 出品中商品は除外)
- 4h cron + GUI

---

## 既存資産流用元

iMakInventory のコード資産を 70% 流用可能:

- Selenium + undetected_chromedriver + cookie 永続化 (`chrome_profile_*`)
- スプシ書込 (gspread + service account)
- 4h cron 統合 (Windows タスクスケジューラ)
- GUI フレームワーク (Tkinter)
- decision_log 記録方式
- トースト通知 (win10toast)
- pre-commit hook + pytest

---

## 関連プロジェクト

- **入力源**: Mercari / Amazon / (Yahoo Auctions / Rakuma / PayPay フリマ)
- **出力先**: 各カテゴリのスプシ (TCG / G-shock / Mercari listing 用 / 一番くじ / etc)
- **下流**: iMakTCG / iMakG-shock / iMakMercari / iMak_ichibankuji が出力スプシを読んで eBay 出品作成
- **並走**: iMakInventory (在庫監視・取り下げ)、iMakHarvest (URL 収集)、両者で trabajo 完全代替

---

## NG (やってはいけないこと)

- 出品作業 (各カテゴリ listing project に任せる)
- 在庫監視・取り下げ (iMakInventory に任せる)
- 重複した URL のスプシ書込 (item_id 単位デドゥープ必須)
- 既出品 (eBay 出品中) 商品の再収集 (将来 Phase 2 で eBay と突合)

---

## セッション開始時の必須読み込み

iMakHarvest は他プロジェクトと連携するため、開始時に以下を読む:

- `C:\Users\imax2\.claude\CLAUDE.md` (グローバル / 全プロジェクト共通ルール)
- `C:\dev\iMak\iMakHQ\CLAUDE.md` (司令塔)
- `C:\dev\iMak\iMakInventory\CLAUDE.md` (姉妹プロジェクト、コード資産流用元)
- このファイル (`CLAUDE.md`)
- 該当時に各 listing project の CLAUDE.md
