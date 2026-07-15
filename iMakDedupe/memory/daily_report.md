# 重複くん daily_report

## 2026-06-12

### G-shock 全除外 regression 修正 (= Phase 1)

- 決定: catalog resolver の G-shock dispatch 未実装が真因、 catalog A (= resolver.py) + dedupe B/C (= signals 補完) で並走修正
- 変更: dedupe/resolver_io.py:80-99 (= resolve_csv_row model signals) / dedupe/resolver_io.py:131-156 (= resolve_sheet_row) / dedupe/resolver_io.py:205-213 (= _guess_category G-shock 検出)
- 検証: tests/test_resolver_io_gshock.py 22 件 GREEN + 6/12 CSV 10/10 canonical KEY 取得 verify + HQ ライブ E2E PASS (= 0 → 7 件入稿)

### D列 "DUP" マーカー方式 実装 (= Phase 2)

- 決定: 重複除外行を LOW スプシ D列 (= col 4 「売り切れ」) に "DUP" 書込で抽選キューから除外、 3 downstream (= 出品くん/監視くん/リバイスくん) 全て無害確認
- 変更: dedupe/dup_marker.py (= 新規) / dedupe/csv_check.py:373,398-401 (= removed_canonical_keys 戻り値) / dedupe/checker.py CLI (= --fullscan-dup-mark + --mark-dups + scope1 統合)
- 検証: tests/test_dup_marker.py 11 件 GREEN + scope2 本実行 5/5 PASS + 抽選キュー 151→146 削減

### スプシ内重複対応 (= Phase 3)

- 決定: 内部重複 2 件 + 6/12 14:50 border line 2 件 = 計 4 件 を D列 "DUP" 追加マーク、 ACTIVE 重複 (= itemID あり + sold 空) 15 group は user 側で取下げ完了 → 重複出品ゼロ達成
- 変更: 未実装 (= write_dup_markers 既存 helper の ad-hoc 呼出で完結)
- 検証: 抽選キュー 146→142 削減 + ACTIVE 重複 再集計 0/0 PASS (= 558→537 row)

### extract_gshock_model 出品くん regex 整合 (= Phase 4)

- 決定: prefix 固定 whitelist (= 旧 23 prefix) 廃止 → 出品くん gshock_to_csv.extract_model_from_text と同等の汎用 regex 採用、 GMC/GR/MRG 等取りこぼし解消
- 変更: dedupe/extractors/gshock.py (= 全書換、 `[A-Z]{1,4}-...数字` + YGO EN/JP 形式除外) / tests/test_extractors_gshock.py (= 既存 fail_closed 修正 + 新規 3 class 追加)
- 検証: tests 329 全 GREEN + GMC-B2100Y-1A / GMC-B2100Y-1AJF 抽出 + catalog alias 正規化 verify

### 統合報告 + commit/push

- 決定: 本日 4 phase まとめて HQ に統合報告投入 + 重複くん initial commit (= 過去全期間分まとめて 1 commit) + new branch push
- 変更: iMak_data/dedupe/requests/2026-06-12_dedupe_TODAY_summary_to_HQ.md / git commit 1ef4160 + push origin feature/dedupe-phase1
- 検証: 42 file commit 完了 + GitHub remote push 完了 (= new branch 作成)

---

### 今日の状態 (= 終了時)

| 観点 | Before (= 朝) | After |
|---|---|---|
| G-shock pipeline 入稿件数 | 0 件 (= 全除外 regression) | 7 件 (= ライブ verify) |
| eBay ACTIVE 重複 group | 15 group / 33 listing | **0** ✅ |
| LOW G-shock 抽選キュー | 151 件 | 142 件 (= DUP 9 件除外) |
| pytest | 309 passed | **329 passed** (= +20 件、 regression-free) |
| extract_gshock prefix カバレッジ | 固定 23 whitelist | 汎用 (= GMC 含む全 prefix) |

### HIGH スプシ DUP マーク 追加 (= Phase 5、 夜の追加対応)

- 決定: HIGH (= TCG) 同 canonical KEY × 異 cert で「既出品 ACTIVE あり + 未出品 B空 row」 を DUP マーク (= スプシ＝eBay 整合)
- 変更: 未実装 (= dup_marker 既存 helper の ad-hoc 呼出で完結)
- 検証: 6/6 PASS (= SV9-102 / SV9-105 / M2a-197 ×2 (= 依頼書事例 145954556/142643221) / M2a-202 / OP12-061_p1) + .bak 保存 (= 20260612_121159_dup_mark_HIGH.bak.json)

### PSA cert 単位判定 依頼 → 撤回 (= 方針合意フェーズ)

- 決定: HQ 撤回受領、 「PSA も無在庫 drop-ship」 前提で canonical KEY 単位 現状維持 (= 実装着手なし)
- 変更: なし
- 検証: 撤回理由 = memory `dropshipping_model_premise` 整合、 spec §1 「1 枚 = 1 固有 KEY」 維持

### 次のセッション持越し

- TCG 解決不能 64 件 (= cert 無し 42 + cache 未投入 5 + resolver "" 17) → 別方針 (= cert 補完 / 手動、 HQ 判断)
- `_dummy` 系 2 件 (= row 380/382) HQ 精査
- catalog 未登録 (= GA-V01CMG-6AJF 型) → 現状維持 (= 収録後自然出品)
- HQ 側で `_leader_cost_invariant` test 2 件 fail (= iMakTCG Leader cost logic、 重複くん責務外)

### 本日 DUP マーク 累計 (= スプシ＝eBay 整合の総括)

- LOW G-shock: 9 件 (= scope2 5 + scope3 4)
- HIGH TCG: 6 件 (= Phase 5)
- 合計: **15 件** → スプシ上の冗長 row 整理完了

---

## 2026-07-14

### 起動時: 前セッション未push commit を保全 (= 消失防止・最優先)

- 決定: 位置確認 (C:/dev/iMak_dedupe / feature/dedupe-phase1) OK・working tree clean だが origin 比 2 commit 先行 (da505e1 7/13 live-filter是正 + 7e81fa8) が未 push と判明 → 即 push
- 変更: git push origin feature/dedupe-phase1 (441ca1b..da505e1)、コード変更なし
- 検証: `git status -sb` で ahead 0 確認、push 完了 (前セッションは commit まで完了・push 途中落ちを回収)

### B空+cert 行の cert→KEー backfill feasibility 回答 (= 補URL 実効化)

- 決定: 「新規 resolver 不要・既存 primitive で backfill 可・fail-closed 維持」で回答。ただし歩留まり律速は resolver でなく **PSA cache miss** と実測判明 → cache warming を最優先レバーとして提言
- 変更: iMak_data/dedupe/requests/2026-07-14_dedup_key_backfill_for_hoju_url_feasibility_response.md (= 回答のみ、実装着手なし)
- 検証: HIGH シート read-only 実測 (scratchpad audit_cert_backfill_feasibility.py)。R=TCG/B空/A有/cert有 = 269 行、KEー空 245 行中 **product_id 解決 83 (33%) / unresolved 162 (うち PSA cache miss 147=60%, cache HIT だが未解決 15)**、url_key 0 (product_id 限定確認)。live filter が B基準 (checker.py:1422) のため backfill 行の orphan 混入なしを code 監査で確認

### 既存 primitive 監査結果 (= 実装不要の根拠)

- 決定: cert→KEー は `resolver_io.resolve_sheet_row` + sheet 駆動 backfill `sheet_io.backfill_canonical_key` が既存 → 追加は「B空限定 + url_col=None (product_id限定)」薄い CLI wrapper のみ (小 BUILD、承認後着手)
- 変更: なし (feasibility 段、コード改変なし)
- 検証: resolver_io.py:110-158 / sheet_io.py:885-1013 / iMakeBayAPI_psa_io.py:53-65 を Read 監査、fail-closed (""→無書込)・冪等 (空KEーのみ)・非破壊を確認

### 次フェーズ持越し (= HQ 判断待ち)

- cert backfill CLI (B空限定・product_id限定) の BUILD 承認可否
- PSA cache warming: 補URL 歩留まりの最大レバー。cache miss 147 certs を 出品くん/iMakeBayAPI で fetch させられるか (dedupe 外・要 HQ)。対象 147 certs list は read-only 抽出可
- DON!! カード (cache HIT だが CardNumber 空) は image-hash 経路要・B空行に画像URL無ければ unresolved のまま → 補URL 対象外で良いか

---

## 2026-07-15

### cert→KEー backfill CLI BUILD (= 補URL 実効化・ユーザー承認済)

- 決定: 7/14 feasibility 承認を受け BUILD。既存 primitive `backfill_canonical_key` に「B空限定 + category限定」param 追加 + 薄い CLI runner。product_id 限定 (url封じ)・fail-closed・冪等
- 変更: dedupe/checker.py:1583-1640 (= run_backfill_keys_from_cert) / checker.py:1229-1237 (= --backfill-keys-from-cert flag) / checker.py:1338-1339 (= dispatch) / sheet_io.py:885-940 (= only_item_id_empty + category_col/value param + 新 counts) / tests/test_backfill_from_cert.py (= 新規 10 件)
- 検証: 新規 test 10 件 pass + dedupe 全 suite 347 passed。本実行で **KEー 付与 83 行** (feasibility 見込みと完全一致)・written_url_key=0 (url封じ確認)・再実行 written=0 (冪等、skipped_existing 24→107)

### 147 cache-miss cert list 抽出 (= cache warming 用・read-only)

- 決定: backfill 後 KEー空残の cert を cache miss / cache-hit未解決 で分類、147 cache-miss を HQ に list 提供
- 変更: iMak_data/dedupe/requests/2026-07-15_psa_cache_miss_certs.txt (147 certs plain) / 同 _for_warming.json (詳細) / _build_response.md (完了報告)
- 検証: PSA cache miss 147 + cache-hit未解決 15 (= feasibility 実測と一致)。fetch script 入力用 plain list 出力確認

### 次フェーズ持越し (= HQ 側)

- HQ が 147 certs を PSA fetch → cache warming → 重複くん再 backfill で resolve 率上昇見込み
- 補URL ツール (hoju_url_from_dupes.py) で cert 経由 2枚目↔primary 突合 → 歩留まり再測定
- ③ DON!! (cache HIT だが CardNumber 空) は image-hash 経路・本 BUILD 対象外 (取りこぼし許容)
