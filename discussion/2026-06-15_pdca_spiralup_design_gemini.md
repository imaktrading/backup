承知いたしました。iMak Trading Japan のシニアアーキテクトとして、忖度なく、具体的かつ実装可能な設計を提案します。現状の「やって終わり」の Check を、回すほどに精度が向上する「Spiral-up」な PDCA サイクルへと進化させましょう。

---

### 設計提案: 真のPDCAを実現する出品パイプライン

#### 1. PDCA のマッピング
パイプラインの各機能を PDCA に明確にマッピングし、責務を定義します。

-   **Plan (計画):**
    -   **実体:** `catalog` (SSOT), `competitor_intel.db` (後述), `improvement_queue.db` (後述)
    -   **責務:** 「何を・どのように出品するか」の全ての情報源。`catalog` は確定情報、DB群は改善のためのインテリジェンスと課題リスト。
-   **Do (実行):**
    -   **実体:** 生成コア (`psa_to_csv`, `tcg_listing_fields`)
    -   **責務:** **Plan (特に `catalog`) のみ**をインプットとし、決定論的に出品CSVを生成する。推測や自己判断を一切含まない。
-   **Check (監査):**
    -   **実体:** `check_csv`, `competitor_gap_finder.py`
    -   **責務:** Do の生成物と外部情報(競合データ)を比較し、**ギャップと改善候補を構造化データとしてDBに永続化する**。表示して終わり、は廃止。
-   **Act (改善):**
    -   **実体:** **新設する `Improvement Review UI` と `Catalog Updater` バッチ**
    -   **責務:** Check が生成した改善候補を人間がレビューし、承認されたものを **Plan (`catalog`) に反映する**。このループを閉じるのが最重要。

---

#### 2. Check結果の蓄積層設計
使い捨ての情報を、クエリ可能で再利用可能なインテリジェンス資産に変えます。

-   **技術選定:** **SQLite** を採用。ファイルベースで導入が容易、かつ強力なSQLクエリが可能。`pandas.DataFrame.to_sql` で容易に書き込めます。
-   **DB設計:** 以下の2つのDBファイルを新設します。

    1.  **`competitor_intel.db` (競合インテリジェンスDB)**
        -   **`gap_keywords` テーブル:** 競合が使うが自社タイトルにないキーワード
            -   `card_id` (TEXT, PK): カード識別子
            -   `keyword` (TEXT, PK): 候補キーワード (例: "treasure")
            -   `competitor_usage_rate` (REAL): 競合TOP20での使用率
            -   `last_seen_ts` (INTEGER): 最終確認タイムスタンプ
        -   **`aspect_intelligence` テーブル:** TOPセラーのAspect値の分布
            -   `category_id` (INTEGER, PK)
            -   `aspect_name` (TEXT, PK): "Features", "Rarity" 等
            -   `aspect_value` (TEXT, PK): "Full Art", "Secret Rare" 等
            -   `usage_rate` (REAL): 当該カテゴリでの使用率
            -   `last_calculated_ts` (INTEGER)

    2.  **`findings_and_queue.db` (監査指摘・改善キューDB)**
        -   **`findings_log` テーブル:** `ledger.jsonl` の構造化版
            -   `finding_id` (INTEGER, PK)
            -   `run_id` (TEXT): 実行ID
            -   `item_id` (TEXT): 対象アイテム
            -   `finding_type` (TEXT): "seo_weak", "short_title" 等
            -   `details` (TEXT): 詳細
            -   `is_recurrent` (BOOLEAN): 再発フラグ
            -   `created_ts` (INTEGER)
        -   **`improvement_queue` テーブル:** **本設計の心臓部**
            -   `queue_id` (INTEGER, PK)
            -   `item_id` (TEXT): 対象アイテム (NULL許容: 全体への提案)
            -   `target_field` (TEXT): `catalog` の修正対象フィールド
            -   `suggested_value` (TEXT): 提案値
            -   `evidence` (TEXT): 提案の根拠 (例: "Top sellers use 'Full Art' with 80% frequency in this category.")
            -   `priority` (INTEGER): 優先度スコア
            -   `status` (TEXT): "pending", "approved", "rejected"
            -   `created_ts` (INTEGER)
            -   `reviewed_by` (TEXT)
            -   `reviewed_ts` (INTEGER)

---

#### 3. Act(還元)の自動化設計 (Fail-Closed厳守)

##### (a) タイトル生成(キーワード)への還元経路
1.  `check_csv` は `competitor_intel.db` の `gap_keywords` を参照。
2.  タイトルにない有力なキーワードを見つけたら、**`improvement_queue` に `target_field='title_keyword_suggestion'` としてレコードをINSERT**する。`evidence` には競合使用率を記載。
3.  Catalog担当者が `Improvement Review UI` でこの提案をレビューし `approved` にする。
4.  承認された提案は、`Catalog Updater` バッチが `catalog` の **`suggested_keywords`** (新設フィールド) に追記する。
5.  生成コアは、既存のタイトル生成ロジックに加え、`suggested_keywords` の単語も使ってタイトルを構築するよう改修する。

##### (b) catalog充填候補の裏取り待ちキュー経路
1.  `check_csv` は `competitor_intel.db` の `aspect_intelligence` を参照。
2.  `catalog` で未設定だが、競合の使用率が高いAspect値 (例: `Features`=`Full Art`) を見つけたら、**`improvement_queue` にレコードをINSERT**する。
3.  Catalog担当者が `Improvement Review UI` でレビューし `approved` にする。
4.  `Catalog Updater` バッチが、承認された `target_field` と `suggested_value` を `catalog` の該当レコードに**自動で書き込む**。

##### 3.5. 証拠付き候補と閾値
-   **妥当です。** 「TOPセラーの85%が使用」は、人間が判断する上で極めて強力な証拠となります。
-   **閾値:** 最初は **`usage_rate >= 0.5` (50%)** でキューに積むことを推奨。運用しながら、キューの量を見て動的に調整します。カテゴリ毎に閾値を変えられる設計が理想です。

---

#### 4. 滞留依頼244件の撲滅作戦
`.md` ファイルは即時廃止し、DBに一元化します。

1.  **スクリプト開発:** 全ての `.md` ファイルをパースし、`improvement_queue` テーブルのスキーマに沿ったデータに変換して一括INSERTするワンタイムスクリプトを作成・実行します。
2.  **重複排除と優先度付け:**
    -   `GROUP BY item_id, target_field` で重複を特定。重複件数を `priority` の計算要素とします。
    -   `priority` を `(影響アイテム数) * (指摘の重要度係数) * (再発回数)` のような式でスコアリングし、キューを優先度順に表示します。
3.  **可視化と処理:** **Streamlit** を用いて `improvement_queue` を表示・編集するシンプルなWeb UI (`Improvement Review UI`) を構築します。これにより、担当者は優先度順に効率的に棚卸しできます。

---

#### 5. 「Spiral-up」を測るKPI
ダッシュボードで以下の指標を定点観測します。

-   **先行指標 (プロセスの健全性):**
    -   **Catalog充足率 (%):** `Features`, `Finish` 等の重要Aspectが埋まっている割合。**これが向上すれば、生成品質の土台が強固になっている証拠。**
    -   **改善キュー滞留件数 (件):** `status='pending'` のレコード数。これが高止まりしていればループが詰まっている。
    -   **改善キュー平均処理時間 (日):** `AVG(reviewed_ts - created_ts)`。
-   **遅行指標 (結果としての品質):**
    -   **SEO指摘/NO-GO率 (%):** `check_csv` が出す `seo_weak` 等の指摘件数の、全生成数に対する割合。**これが逓減していくことが Spiral-up の直接的な証明。**
    -   **指摘再発率 (%):** `is_recurrent=true` の指摘の割合。

---

#### 6. MVP(最小価値製品)の順序
過剰設計を避け、最短で価値を出すための3ステップ。

1.  **Phase 1: 蓄積と可視化 (現状把握)**
    -   **SQLite DB (2つ) を作成**し、`check_csv` が分析結果を**書き込むだけ**の実装を行う。
    -   滞留 `.md` をDBにインポートする。
    -   DBの中身を**表示するだけ**の超シンプルな `Streamlit` ビューアを構築。
    *→ これだけで、捨てられていた知見と滞留課題が可視化され、次のアクションが明確になる。*

2.  **Phase 2: 半自動の改善ループ (人間支援)**
    -   `Streamlit` ビューアに**ステータス更新機能**を追加。人間がレビューし、`approved`/`rejected` を記録できるようにする。
    -   Catalog担当者は、このUIを見て `catalog` を**手動で**修正する運用を開始する。
    *→ これで、不完全ながらも改善のループが回り始める。*

3.  **Phase 3: Actの自動化 (ループ高速化)**
    -   `approved` された提案を `catalog` に自動反映する `Catalog Updater` バッチを開発。
    -   生成コアを改修し、`catalog` の新フィールド (`suggested_keywords` 等) を参照させる。
    -   KPIダッシュボードを構築。
    *→ これで、人間は「最終判断」に集中でき、Spiral-upが加速する。*

---

#### 7. アンチパターン (警告)
-   **推測のSSOTへの自動反映:** 競合分析結果を人間のレビューなしに `catalog` に書き込むことは、**fail-closed 原則に反する最大の禁忌**です。必ず `improvement_queue` を介し、人間の承認を必須とします。
-   **ブラックボックス化:** 「AIによる自動最適化」のような説明不能なロジックは避けてください。全ての変更は、`improvement_queue` の `queue_id` と `catalog` の変更履歴によって追跡可能であるべきです。
-   **同期処理:** 競合分析やDB書き込みは、出品生成パイプライン本体とは非同期（例: 夜間バッチ）で実行し、本体のパフォーマンスを維持してください。