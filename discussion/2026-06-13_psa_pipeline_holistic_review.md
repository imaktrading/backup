# PSA TCG 出品くん パイプライン 網羅レビュー (順番/速度/精度)

- 日付: 2026-06-13 / レビュー: HQ Claude + Gemini(gemini-2.5-flash, 独立)
- 動機: ユーザー指摘「継ぎ足し・修正の産物が現状。ボタン押下→CSV生成の流れを網羅的に見直せ」
- 実コードで処理順を確定 (Explore agent map + run log 一致確認)。憶測でなく file ベース。

## 現状フロー (ボタン→入稿CSV)
後処理が **psa_to_csv 本体** と **control_panel(GUI)フック** に分裂している = 継ぎ足しの痕跡。

```
[psa_to_csv subprocess]
 A 抽出: スプシHIGH cert#(B列空) → shuffle → 10件だけ
 B scrape(per cert/直列): Cloudflare warmup(uc.Chrome) → psacard.com Selenium(~15s,+30s retry) → 表裏画像 → cert cache
 C 特定(per cert/直列): Vision API → PSA補正 → catalog lookup → Item Specifics決定
 D 価格(per cert): eBay OAuth(1) → 市場API(cache600s) → 利益/GATE → market_log追記
 E 生成: 行をメモリ追記 → 送料postprocess(rw) → decision_log → CSV出力 → _cost.json
 F selfcheck → check_csv.main()(禁止field空欄化(rw)/validate/eBay競合API(per cert)/GATE/Claude AI総合レビュー)
[control_panel フック (subprocess完了後)]
 G excluder(check_csv stdout文字列parse→NO-GO物理削除) → post_title_fix(rw) → dedupe --check-csv(重複物理削除) →
   dedupe --write-keys → post_psa_review(cert目視HTML=人間が初めてidentity確認) → post_no_go_sentinel
 H 完了通知
※CSVを 6〜7回 破壊的 read/write。市場APIは psa_to_csv と check_csv で per-cert 2系統(cache共有)。10件で約5分。
```

## 3軸の問題 (Claude+Gemini 一致)

### 順番
1. **単一オーケストレータ不在** = 後処理が本体とGUIに二分。excluder が check_csv の **stdout を文字列parse** する脆い結合。
2. **「作ってから消す」**: 全certをCSV化→市場NO-GO/重複を後段で物理削除。弾く前に scrape/Vision/タイトル/API を無駄打ち(=金と時間)。
3. **cert目視(identity=出す根幹)が最後尾**。本来 identity確定→価格/CSV の順。ユーザー指摘の「順番違う」はこれ。
4. **dedupe check と write-keys が順序依存**(同cycルで書いたKEYを誤認するリスクをコード自身がコメント)。
5. CSV 6〜7回破壊書換 = デバッグ困難・破損リスク(Gemini補強)。

### 速度
1. **per-cert 完全直列・I/Oバウンド**(Selenium 15s+retry30s / Vision / 市場API)→10件約5分。待ち時間が大半。
2. **Cloudflare warmup 毎回**、cache済cert も再scrape の可能性 → 永続cache+skipで即効改善。
3. **check_csv の Claude AI総合レビューが毎回**(重いAPI・従量課金)。入稿必須でないSEOメモ=ノイズかつ無駄コスト。
4. 無駄打ち = API従量コスト直撃(Gemini補強)。

### 精度
1. **catalog(SSOT)を正にしていない**: set名/character/rarity を LLM・推測で生成 → 誤出品(VMAX Climax→"Brilliant Stars"が素通り)。
2. **チェックが catalog照合をしない**(内部整合+英語名ヒューリスティックのみ)→ 構造的に誤りを捕まえられない。selfcheck/validate があるのに根本誤りを見逃す=表面整合しか見ていない証拠。
3. **Vision が catalog hit 時も常時呼ばれる**(gap-fill専用のはず)= ハルシネーション混入経路 + 無駄コスト。

## あるべき姿 (target)
- **単一オーケストレータ** (GUIから切出し)。各処理は CSVでなく **メモリ上 List[Dict]** を受け渡し、CSVは**最後に1回だけ**書く。
- **「確定してから作る」**: 重複(cert単位,scrape前) → catalog解決 → identity確定(低信頼のみ目視) → 市場ゲート → **確定行だけ生成**。
- **catalog 決定論生成** + **チェックは catalog照合1本** + SEOノイズ分離 + Claude AIレビュー任意化。
- 速度: **永続scrape cache+skip** を先に。並列化は後 (API先・Selenium最後・rate limit/レース対策必須)。

### target フロー (順番の入替え)
```
抽出 → 重複除外(cert単位/scrape前) → scrape(cache優先) → catalog解決 → identity確定(低信頼のみ目視) →
catalog決定論で行データ作成(メモリ) → 価格/市場ゲート → 確定行だけ CSV 1回書込 → catalog照合チェック → sentinel/write-keys
```

## 実装優先順位 (継ぎ足しを減らす方向)

### P0 (誤出品を止める + 速度即効)
1. **catalog SSOT 決定論生成** + **catalog照合チェック1本**(set名は静的JP→英語マップ, 未マップ=空欄, Character=キャラ名のみ, Language=Japanese追加)。← 誤出品の根治。
2. **PSA scrape 永続cache + skip**(cache済certは再取得しない, Cloudflare warmup無駄排除)。← 速度即効・低リスク。
3. **「確定してから作る」へ第一歩**: 行をメモリ保持しCSV書込は最終1回。重複/NO-GO/目視を生成前に前倒し。

### P1 (速度・堅牢性)
1. **Claude AI総合レビュー 削除/任意化**(重い・必須でない)。
2. **stdout parse 廃止 → 構造化(JSON/メモリ)受け渡し**(excluder↔check_csv の脆い結合解消)。
3. **dedupe の check↔write-keys 順序リスク解消**(オーケストレータ内で安全順序に統合)。

### P2 (最適化・将来)
1. per-cert 並列化(API先, スロットリング, 共有書込はロックor最後に集約)。
2. Selenium → Playwright 等軽量化。
3. decision_log 構造化・監査証跡強化。

## 注意 (リスク)
- これは**稼働中の本番パイプラインの再設計**。一気に作り替えるとデグレ確率が高い。**P0を小さく刻んで**(まず生成のcatalog決定論化→次にcache→次にwrite-once)、各段で E2E verify。
- ユーザー目標は「毎日 正しい出品をたくさん→売上」。Recallより Precision、ただし検索性(英語セット名)は **静的マップで両立**(Geminiの強い指摘=日本版名のみは売上壊滅)。
```
```
