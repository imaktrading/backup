# PSA出品 Check の PDCA(spiral-up)設計 — HQ 統合版 (2026-06-15)

発端: ユーザー「チェック結果を今後に活かす仕組みは? ないなら、やって終わりはもったいない」。
現状(実機): PDCA台帳は記録のみ / catalog依頼 244件滞留 / 競合TOPセラー分析を毎回捨てる /
生成コアは還元を一切読まない。= Check→レポート→終わり。Gemini 相談 + HQ判断で合理化。

## PDCA マッピング(このパイプライン)
- **Plan = catalog (SSOT)**: 出品の正は catalog にある。生成を良くする = catalog を良くする。
- **Do = 新コア生成**: catalog の eBay正規化フィールドを決定論コピー。
- **Check = 監査 + 競合分析**: check_csv / CSV監査くん。NO-GO・SEO・競合TOPセラー値分布。
- **Act = improvement_queue → Catalog依頼**: Check で得た「証拠付き改善候補」を貯め、人が承認 →
  **Catalog に依頼**(HQ 自動書込しない=SSOT所有権を Catalog に残す/fail-closed)。
  catalog が更新 → 次の Do(生成)が自動で良くなる → 次の Check で指摘が減る = spiral-up。

## 蓄積層 (1 SQLite: `C:/dev/iMak_data/audit/pdca.db`)
毎回捨てている知見を「クエリ可能な資産」に。
- **aspect_intel**(category_id, aspect_name, aspect_value, usage_rate, last_calc_ts):
  TOPセラーの Features/Finish/Rarity/Color 等の値分布(例: cat183454 Features=Full Art 使用率0.8)。
- **gap_keywords**(card_id, keyword, competitor_usage_rate, last_seen_ts):
  競合頻出だが自社タイトルに無い語(treasure/sar/shiny 等)。
- **findings_log**(run_id, item_id, finding_type, details, is_recurrent, ts): ledger.jsonl の構造化版。
- **improvement_queue**(queue_id, item_id|NULL, target_field, suggested_value, evidence, priority,
  status[pending/approved/rejected], created_ts, reviewed_ts): ★心臓部。証拠付き改善候補。

## Act(還元)経路 — カタログ依頼を全自動発行 / fail-closed 厳守
★依頼の「発行」は全自動(HQ 手書き禁止)。catalog への「反映」は Catalog が裏取りして実施(SSOT所有権=Catalog)。
依頼書は非破壊(提案)なので自動発行して安全。改善キューが dedup/優先度/再発を捌くので Catalog はクリーンな
1本を受け取る(244スパムにならない)。

- **層A 客観ギャップ(=事実)**: 未収録 / set誤マップ / catalog値とCSV不一致 等、**catalog 事実と突合して機械判定できるもの**。
  → improvement_queue 経由で **承認ゲート無しで自動的に Catalog 依頼発行**(今日も auto_catalog_add_request が
  やっている。これを dedup+優先度+1本集約に強化)。
- **層B 競合intel候補(=推測)**: aspect_intel で「catalog 未設定だが TOP 使用率高」(例 Features=Full Art 80%)、
  gap_keywords の有力語。→ improvement_queue に evidence+confidence 付きで積み、**閾値(usage_rate≥0.5)超を
  自動で Catalog 依頼に発行**(「候補・要裏取り」と明示タグ)。catalog 書込は Catalog が裏取り後に判断。
  ※ HQ は推測値を catalog に**自動書込しない**(最大の禁忌)。発行する依頼に「確信度」を載せ Catalog が取捨。
- 生成への還元: catalog 更新(by Catalog)→ 新コアが `suggested_keywords` / `*_ebay` を自動参照 → タイトル/specs 改善。
- 閾値・confidence はカテゴリ別に調整可。低確信は依頼せず queue 保留(Catalog を低品質候補で溢れさせない)。

### 依頼自動発行のループ閉じ(滞留させない)
- 依頼は **queue を source of truth** にし、Catalog が `_processed` にしたら queue status=done に同期。
- 未処理が滞留したら PDCA で可視化(KPI: queue滞留件数)。再発(直したのにまた出た)も検知して再発行。

## 滞留244件の棚卸し
- 全 `.md` を improvement_queue にインポート(ワンタイム)。`GROUP BY item_id,target_field` で重複排除。
- priority = (影響item数) × (重要度係数) × (再発回数)。優先度順に処理。
- 以後 auditor は **.md を毎回新規生成せず queue に upsert**(=滞留スパム停止・重複抑制)。

## レビュー UI
新依存(Streamlit)は入れず、**既存の local HTML + http.server 方式(post_psa_review と同型)を流用**。
queue を優先度順表示 → 承認/却下クリック → status 更新。承認分は Catalog 依頼に集約出力。

## spiral-up KPI(回って良くなってる証拠)
- 先行: catalog充足率(Features/Finish 等の充填%↑) / queue滞留件数 / 平均処理日数。
- 遅行: SEO指摘率(全生成比)逓減 / NO-GO率 / 指摘再発率↓ / avg_title_len。
- ダッシュボードで定点観測(spiral-up の客観証跡 = `pdca_spiral_up_expectation` 充足)。

## MVP 順序(過剰設計回避)
- **Phase 1(蓄積+棚卸し)**: pdca.db 作成 → check_csv/CSV監査くんが aspect_intel/gap_keywords/findings を
  **書くだけ** + 244 .md を queue にインポート(dedup+優先度)+ 中身を見る簡易 HTML ビューア。
- **Phase 2(カタログ依頼 自動発行)**: queue から **層A(客観ギャップ)を承認ゲート無しで自動 Catalog 依頼**
  (dedup+1本集約=滞留スパム停止)。Catalog が `_processed` → queue done 同期(ループを閉じる)。
- **Phase 3(競合intel 還元)**: 層B(競合intel候補)を閾値超で「候補・要裏取り」タグ付き自動依頼。
  catalog 更新後、生成コアが `suggested_keywords`/`*_ebay` を参照(=タイトル/specs 自動改善)+ KPI ダッシュボード。

※ 人手は「Catalog 側の裏取り判断」だけに集約。HQ の依頼手書きはゼロ(全自動発行)。

## アンチパターン(禁止)
- 競合分析を人レビュー無しに catalog 自動書込(fail-closed 違反・最大の禁忌)。
- 説明不能な「AI自動最適化」(全変更は queue_id + catalog 変更履歴で追跡可能に)。
- 競合分析/DB書込を出品本体に同期実行(遅くなる)→ **夜間バッチ等で非同期**。
