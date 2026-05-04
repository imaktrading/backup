-- iMakCatalog 商品マスター SQLite スキーマ
-- 2026-04-26 Phase 0 初版
-- 全カテゴリ (TCG / G-SHOCK / リール / ポーター / モンベル / 一番くじ) を統合管理

-- ============================================================================
-- products: 商品マスター本体
-- ============================================================================
CREATE TABLE IF NOT EXISTS products (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    category          TEXT NOT NULL,    -- 'one_piece_tcg' | 'pokemon_tcg' | 'gundam_tcg'
                                        -- 'dragonball_scg' | 'gshock' | 'reel' | 'porter'
                                        -- 'montbell' | 'ichibankuji'
    product_id        TEXT NOT NULL,    -- カテゴリ内一意の ID (variant suffix 含む)
                                        -- TCG例: 'PRB02-005', 'OP06-022_p', 'OP06-022_ST28'
                                        -- G-SHOCK例: 'GA-2100-1A1'
                                        -- リール例: 'shimano_22stella_4000xg'
    name              TEXT NOT NULL,    -- 表示名 (英語/ローマ字、API原文)
    name_jp           TEXT,             -- 日本語名
    name_en           TEXT,             -- 英語名 (montbell 等で公式英訳を保持、出品 listing で AI 翻訳廃止)
                                        -- NULL OK (未設定 = HQ 側 fallback 動作、品質確認後に埋める運用)
    name_en_source    TEXT,             -- name_en の出典 / 翻訳手段
                                        -- 'montbell_us' (海外公式サイト) | 'montbell_official_en' (国内サイトの英語表記)
                                        -- | 'dict' (辞書 transliteration) | 'claude_translation' (AI 翻訳)
                                        -- | 'manual' (人手) | NULL (未設定)
    set_name          TEXT,             -- 公式原文 (= set_name_official、raw 保存)
                                        -- eBay フィルタ値変換は api.lookup() が ebay_filter_map で実行
    set_name_official TEXT,             -- 公式DB原文 (検証用、ebay_filter_map 引用元)
    card_set_id       INTEGER,          -- 公式 set ID (TCG+ API の card_set_id 等、内部join用)
    language          TEXT,             -- 'en' | 'ja' | 'both' — variant 単位の言語
    specs             TEXT NOT NULL,    -- JSON: フィールド構造はカテゴリ依存
                                        --   TCG: {"Rarity":"SR","Cost/Life":"4","Power":"5000","Color":"Green",
                                        --         "Card Type":"Character","Type":"Supernovas/...",
                                        --         "Counter+":"1000","Attribute":"Strike","Illust Type":"Original",
                                        --         "card_text":"...","regulations":[...],
                                        --         "legality":{"main":1,"extra":1,"extra2":0,"side":1},
                                        --         "illustrator":null}  ← Pokemon 等で値入り
                                        --   G-SHOCK: {"band":"Resin","case_size":48,"water_resist":200,...}
    images            TEXT,             -- JSON 配列: ["https://...", ...]
    source            TEXT NOT NULL,    -- 取得元: 'bandai_jp' | 'bandai_tcg_plus' | 'pokemon_official'
                                        --        | 'casio_official' | 'shimano_official' | 'porter_official' | etc.
    source_url        TEXT,             -- 取得元 URL
    created_at        TEXT NOT NULL,    -- ISO 8601 (例: '2026-04-26T13:14:00')
    updated_at        TEXT NOT NULL,    -- ISO 8601
    UNIQUE(category, product_id)
);

CREATE INDEX IF NOT EXISTS idx_products_category    ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_product_id  ON products(product_id);
CREATE INDEX IF NOT EXISTS idx_products_name        ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_name_jp     ON products(name_jp);
CREATE INDEX IF NOT EXISTS idx_products_updated_at  ON products(updated_at);
CREATE INDEX IF NOT EXISTS idx_products_card_set_id ON products(card_set_id);


-- ============================================================================
-- ebay_filter_map: eBay フィルタ値マッピング
-- ============================================================================
-- 公式DBの値 (例: 'BOOSTER PACK -AWAKENED PULSE- [FB01]') を
-- eBay フィルタ表示値 (例: 'Awakened Pulse') に変換するマップ
CREATE TABLE IF NOT EXISTS ebay_filter_map (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category     TEXT NOT NULL,         -- 'one_piece_tcg' 等
    field        TEXT NOT NULL,         -- 'set' | 'rarity' | 'card_type' | 'manufacturer' 等
    source_value TEXT NOT NULL,         -- 公式DB値
    ebay_value   TEXT NOT NULL,         -- eBay フィルタ表示値
    note         TEXT,                  -- 備考 (確認方法、eBay 公式画面リンク等)
    created_at   TEXT NOT NULL,
    UNIQUE(category, field, source_value)
);

CREATE INDEX IF NOT EXISTS idx_filter_map_lookup ON ebay_filter_map(category, field, source_value);


-- ============================================================================
-- scrape_log: スクレイプ実行履歴
-- ============================================================================
-- 各カテゴリのスクレイプ実行時に1行追加。差分更新の判断材料に使う。
CREATE TABLE IF NOT EXISTS scrape_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL,      -- 'running' | 'success' | 'failed'
    products_added  INTEGER DEFAULT 0,
    products_updated INTEGER DEFAULT 0,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_scrape_log_category ON scrape_log(category, started_at DESC);
