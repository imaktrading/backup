#!/usr/bin/env python3
# iMak Trading Japan - 一番くじ → eBay FileExchange CSV 自動生成
# 必要: pip install anthropic undetected-chromedriver beautifulsoup4

import csv
import re
import json
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import anthropic
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# ===== 設定 =====
# API key.txt から読み込む（同じフォルダに置いてください）
try:
    with open("API key.txt", "r", encoding="utf-8") as f:
        ANTHROPIC_API_KEY = f.read().strip()
except FileNotFoundError:
    print("エラー: 'API key.txt' が見つかりません。スクリプトと同じフォルダに置いてください。")
    input("Enterで終了...")
    exit()
URLS_FILE = "kuji_urls.txt"
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"))
from listing_core import get_csv_output_path as _gcop
# 共通リスティング処理ライブラリ (2026-04-23 統合)
from listing_common import (
    normalize_title, audit_csv_row, determine_condition_id,
    is_new_condition, get_default_condition_description,
    fetch_amazon_title, extract_sku_from_url as _extract_sku,
    CONDITION_MASTER,
)
OUTPUT_CSV = _gcop("ichibankuji", "upload")
MODEL = "claude-sonnet-4-20250514"
SCHEDULE_WEEKS = 2
DEFAULT_PRICE = 50.00  # 仕入不明時のフォールバック
PROFIT_CATEGORY = "一番くじ"  # pricing_engine 用カテゴリ

# eBay固定値
EBAY_CATEGORY = 261055  # Collectibles > Animation Art & Merchandise > Animation Merchandise > Collectible Animation Figures & Statues
CONDITION_ID = 1000     # New
LOCATION = "Osaka"
PIC_WATERMARK = "https://raw.githubusercontent.com/imaktrading/imaktrading.github.io/main/999.png"

# ストアカテゴリ2（Figures > Franchise別）
STORE_CATEGORY2 = {
    "dragon ball":      41829920010,
    "one piece":        41830031010,
    "my hero academia": 41830032010,
    "demon slayer":     41833121010,
    "sailor moon":      41834947010,
    "jujutsu kaisen":   41834948010,
    "precure":          41834949010,
    "gundam":           41834950010,
}
STORE_CATEGORY2_DEFAULT = 41861579010  # Figures > others

# DDP送料テーブル（米国向け）
SHIPPING_POLICIES = [
    (39, "<39"), (60, "40-60"), (100, "60-100"), (200, "100-200"),
    (300, "200-300"), (400, "300-400"), (500, "400-500"),
    (600, "500-600"), (800, "600-800"), (1000, "800-1000"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9",
}

def get_schedule_time():
    future = datetime.utcnow() + timedelta(weeks=SCHEDULE_WEEKS)
    return future.strftime("%Y-%m-%d %H:%M:%S")

def get_shipping_policy(price):
    for threshold, policy in SHIPPING_POLICIES:
        if price <= threshold:
            return policy
    return "800-1000"

def scrape_1kuji(driver, url):
    """1kuji.comから賞別データをSeleniumで取得"""
    try:
        driver.get(url)
        time.sleep(5)  # JS読み込み待機

        # スクロールして遅延ロードを発火
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)

        body = driver.find_element(By.TAG_NAME, "body").text
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        page_text = body  # Seleniumで取得したテキスト（JS描画済み）

        # シリーズ名取得
        series_name = ""
        h1 = soup.find('h1')
        if h1:
            series_name = h1.get_text(strip=True)
        if not series_name:
            title = soup.find('title')
            if title:
                series_name = title.get_text(strip=True).replace('｜一番くじ倶楽部｜BANDAI SPIRITS公式 一番くじ情報サイト', '').strip()

        # 発売年・価格取得
        release_date = ""
        price_jpy = ""
        date_m = re.search(r'(\d{4})年(\d{1,2})月', page_text)
        if date_m:
            release_date = date_m.group(1)
        price_m = re.search(r'1回(\d+)円', page_text)
        if price_m:
            price_jpy = price_m.group(1)

        # 賞別データ取得
        current_prizes = []

        # 「各等賞一覧」セクションから賞を抽出
        # パターン：「賞名 アイテム名\n■全X種\n■サイズ：約XXcm」
        prize_pattern = re.compile(
            r'([^\n]+?賞)\s+([^\n]+?)\n■全(\d+)種.*?■サイズ：約([\d.]+)cm',
            re.DOTALL
        )
        for match in prize_pattern.finditer(page_text):
            prize_label = match.group(1).strip()
            item_name = match.group(2).strip()
            varieties = match.group(3)
            size_cm = match.group(4)
            # ダブルチャンスキャンペーンの重複を除外
            if '■当選数' in page_text[match.start():match.start()+200]:
                continue
            current_prizes.append({
                'prize': prize_label,
                'name': item_name,
                'varieties': varieties,
                'size_cm': size_cm,
            })
            print(f"    {prize_label}: {item_name[:35]} / {size_cm}cm")

        # ラストワン賞（■全N種パターンに乗らないケース別途処理）
        if 'ラストワン賞' in page_text:
            if not any(p['prize'] == 'ラストワン賞' for p in current_prizes):
                m = re.search(r'ラストワン賞\s+([^\n]+)', page_text)
                if m:
                    last_one_name = m.group(1).strip()
                    # 近傍500字内で「約XXcm」を探す
                    start = m.start()
                    nearby = page_text[start:start+500]
                    size_m = re.search(r'■?サイズ[：:]\s*約([\d.]+)\s*cm', nearby)
                    if not size_m:
                        size_m = re.search(r'約([\d.]+)\s*cm', nearby)
                    size_cm = size_m.group(1) if size_m else ""
                    current_prizes.append({
                        'prize': 'ラストワン賞',
                        'name': last_one_name,
                        'varieties': "1",
                        'size_cm': size_cm,
                    })
                    print(f"    ラストワン賞: {last_one_name[:35]} / {size_cm or 'サイズ不明'}cm")

        # OGP画像取得
        main_image = ""
        og_img = soup.find('meta', property='og:image')
        if og_img:
            main_image = og_img.get('content', '')

        return {
            'series_name': series_name,
            'release_year': release_date,
            'price_jpy': price_jpy,
            'prizes': current_prizes,
            'main_image': main_image,
            'url': url,
        }

    except Exception as e:
        print(f"  スクレイピングエラー: {e}")
        return None

_CACHED_COLLECTIBLES_KEYWORDS = None

# Collectibles_2026Q1.pdf の top30 を埋め込み（pdftotext失敗時のフォールバック）
# 四半期ごとに更新: 最後に更新したQ = 2026Q1
_EMBEDDED_COLLECTIBLES_KEYWORDS_2026Q1 = [
    (1, "anime figure"), (2, "nendoroid"), (3, "one piece"), (4, "hello kitty"),
    (5, "pokemon plush"), (6, "pikachu"), (7, "super sonico figure"),
    (8, "jujutsu kaisen"), (9, "chainsaw man"), (10, "vintage sanrio"),
    (11, "hetalia"), (12, "my orders status"), (13, "chiikawa"), (14, "miku figure"),
    (15, "jojo s bizarre adventure"), (16, "sh figuarts dragon ball"), (17, "sanrio"),
    (18, "monchhichi"), (19, "super sonico"), (20, "alpha station"), (21, "miku"),
    (22, "hatsune miku"), (23, "pokedoll"), (24, "hatsune miku figure"),
    (25, "sailor moon"), (26, "one piece figure"), (27, "twisted wonderland"),
    (28, "hazbin hotel"), (29, "snoopy"), (30, "dragon ball"),
]


def _load_collectibles_keywords(top_n=30):
    """iMakKeywords/Collectibles_2026Q1.pdf の上位キーワードを読込（起動時1回のみキャッシュ）
    pdftotext が使えない環境では埋め込みリストにフォールバック"""
    global _CACHED_COLLECTIBLES_KEYWORDS
    if _CACHED_COLLECTIBLES_KEYWORDS is not None:
        return _CACHED_COLLECTIBLES_KEYWORDS
    pdf_path = r"C:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMakKeywords\Collectibles_2026Q1.pdf"
    kws = []
    err = None
    try:
        import subprocess as _sp
        import shutil as _shutil
        if not _shutil.which("pdftotext"):
            raise RuntimeError("pdftotext not in PATH")
        r = _sp.run(["pdftotext", "-layout", pdf_path, "-"],
                    capture_output=True, text=True, encoding="utf-8", timeout=10)
        if r.returncode != 0:
            raise RuntimeError(f"pdftotext returncode={r.returncode}: {r.stderr[:200]}")
        for line in r.stdout.split("\n"):
            m = re.match(r'^\s*(\d+)\s+\S+\s+\S+\s+(.+?)\s*$', line)
            if m:
                rank = int(m.group(1))
                kw = m.group(2).strip()
                if rank <= top_n:
                    kws.append((rank, kw))
        kws = sorted(set(kws))[:top_n]
        if kws:
            print(f"✅ Collectibles_2026Q1.pdf 動的読込: 上位{len(kws)}件")
        else:
            raise RuntimeError("PDFパース結果0件")
    except Exception as e:
        err = e

    if not kws:
        # フォールバック: 埋め込み済キーワード使用
        kws = _EMBEDDED_COLLECTIBLES_KEYWORDS_2026Q1[:top_n]
        print(f"⚠️ PDF動的読込失敗({err}) → 埋め込み2026Q1 top{len(kws)} にフォールバック")

    _CACHED_COLLECTIBLES_KEYWORDS = kws
    return kws


def analyze_with_claude(series_data, prize_data):
    """Claude APIで各賞のeBayタイトル・Item Specificsを生成"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 日本語テキストをUTF-8で安全に処理
    series_name = series_data['series_name']
    prize = prize_data['prize']
    item_name = prize_data['name']
    size_cm = prize_data.get('size_cm', 'unknown')
    release_year = series_data.get('release_year', '')
    price_jpy = series_data.get('price_jpy', '')

    # キーワードPDF（Collectibles_2026Q1.pdf）上位を動的挿入
    kws = _load_collectibles_keywords(top_n=30)
    kw_list = "\n".join([f"  #{r} {k}" for r, k in kws]) if kws else "  (PDF読込失敗)"

    prompt = f"""Ichiban Kuji product information:
Series: {series_name}
Prize: {prize}
Item Name: {item_name}
Size: {size_cm} cm
Release Year: {release_year}
Kuji Price: {price_jpy} JPY per draw

Generate an eBay listing for iMak Trading Japan following these rules.

=== eBay 2026Q1 TOP KEYWORDS (Collectibles > Animation Art & Merchandise) ===
これらが buyers が実際に検索する語。タイトルに盛り込めるものは積極的に使う。
{kw_list}
=== KEYWORDS END ===

TITLE RULES (厳守):
- Format: Ichiban Kuji [IP/Series] [Prize] [Character] [Figure Type] Bandai New
- Max 79 characters STRICTLY
- AIM 70-79 characters (詰めるほど検索ヒット増)
- MANDATORY keywords:
  - "Figure" 必須（#1 anime figure の部分マッチ）
  - Franchise 必須: **Series欄に書かれている IP 名から英語名を抽出**（例: "呪術廻戦"→"Jujutsu Kaisen"）
    ※ キャラの流派名・組織名・作中派閥名を Franchise に入れない。あくまで IP 名
  - Character 必須（買い手はキャラ名で検索）
- "Bandai" は文字数に余裕があれば入れる（ブランド検索する人もいる）
- figure_type が prize name にあれば必ず入れる（Masterlise / EXPIECE / Gracemaster 等）
- **「Japan」は入れない**（出品者の調査語であり買い手の検索語ではない）
- 79字超過時は "Bandai" → "New" の順に削る
- Example: "Ichiban Kuji My Hero Academia A Prize Izuku Midoriya Masterlise Figure New"
- Example: "Ichiban Kuji One Piece A Prize Monkey D Luffy Masterlise Figure Bandai New"
- Example: "Ichiban Kuji Dragon Ball B Prize Vegeta Figure New"

FRANCHISE 抽出ルール（最重要・厳守）:
**Franchise は必ず Series 欄の「一番くじ」直後のIP名を英訳して返す。絶対に "Unknown" "N/A" "-" "none" を返すな。**

手順:
1. Series欄から「一番くじ 」プレフィックスを除去
2. 残った部分を英訳（カタカナ→ヘボン式、漢字→意訳、メジャーIPは公式英語名）
3. それを Franchise に入れる（全賞で共通、個別判断はしない）

例:
- Series「一番くじ 呪術廻戦 死滅回游 ～弐～」→ Franchise: "Jujutsu Kaisen"
- Series「一番くじ ワンピース ワノ国編」→ Franchise: "One Piece"
- Series「一番くじ 鬼滅の刃 柱稽古編」→ Franchise: "Demon Slayer"
- Series「一番くじ 歌川一門」→ Franchise: "Utagawa Ichimon"（公式IPなし、そのまま翻字）
- Series「一番くじ モンスターストライク 2026」→ Franchise: "Monster Strike"
- Series「一番くじ WIND BREAKER -原作5周年-」→ Franchise: "Wind Breaker"

注意:
- 一度決めた Franchise は同シリーズの全賞で同一にする
- 作中の組織名・派閥名（海軍/鬼殺隊/呪術高専等）は Franchise に入れない（IP名のみ）
- 歴史的概念・浮世絵・伝統工芸等がシリーズ名に来る場合、そのまま翻字で使用（ex. 歌川一門→Utagawa Ichimon）

ITEM SPECIFICS — TOPセラー(fb>900) 標準構成 (2026-04-22調査:nippon_japan/hiro_shop_japan/quarry_japan):
必須:
- Brand: **Bandai** (22K件主流。BANPRESTOは6.9K件で別有効値だが少数派)
- Franchise: [IP name in English、上記ルール準拠]
  ※ 表記厳格: "Pokémon"(é付き必須) / "Demon Slayer: Kimetsu no Yaiba"(正式長名) / "JoJo's Bizarre Adventure"(JJ大文字) / "Yu-Gi-Oh!"(!付き) / "K-On!"(!付き) / "Hunter x Hunter"(小文字 x)
- TV Show: [Franchise と同じだが表記異なる場合あり]
  ※ TV Show別表記: "Jojo's Bizarre Adventure"(j小文字) / "Hunter X Hunter"(大文字 X) / "Card Captor Sakura"(スペース有) / "Pokémon"(é)
- Character: [Character name in English]
  ※ ホワイトリスト一致時は完全表記（例 "Tanjiro Kamado"、"Naruto Uzumaki"、"Izuku Midoriya"）。リスト外（"Goku"等主要アニメキャラ含む）でもそのまま記入
- Type: Figure
- Theme: **Anime & Manga** (16K件主流。cat 261055では正規値、Anime単独は無効)
- Material: **Plastic** (eBayフィルタ正規値。"PVC, ABS"/"PVC, MABS"はリストに無いので無効)
  ※ Plushの場合は"Plush"、Acrylicの場合は"Acrylic"等、フィギュア素材で適切なものを選択
- Color: Multicolor (17K件主流)
- Country of Origin: Japan (24K件主流)
- Year Manufactured: [series release year]
- Item Height: "X.X in" (TOPセラーは inch表記、cm併記不要)
推奨:
- Series: "Ichiban Kuji [Full Series Name]" (例: "Ichiban Kuji My Hero Academia Held Cultural Festival")
- Features: figure_type名 (例: "MASTERLISE", "EXPIECE")
- Animation Studio: **eBay公式13値のみ使用**
  有効値: "20th Century Animation" / "Blue Sky Studios" / "Bones Animation Studio" / "Disney" / "Illumination" / "Kyoto Animation" / "Nippon Animation" / "Pixar" / "Studio Pierrot" / "Toei Animation" / "Universal Animation Studios" / "Warner Bros. Animation" / "Wit Studio"
  ※ Suffix付け方は値ごとに違う: "Bones Animation Studio"(suffix有) vs "Pixar"(無) vs "Kyoto Animation"(短) vs "Studio Pierrot"(短)
  ※ Mappa/Ufotable/Madhouse/A-1 Pictures/Sunrise/Trigger 等はリストに無い → "Does Not Apply" を入れる
- Movie: 該当アニメシリーズ名 - TV Showと同じでもOK
- Language: Japanese (17K件主流、Japan限定品の差別化)
固定:
- Original/Licensed Reproduction: Original
- Signed: No
- Vintage: No

Return ONLY valid JSON:
{{
  "is_figure": true or false (false if item is stationery, plushie, towel, mug, acrylic, keychain, or any non-figure goods),
  "title": "eBay title max 79 chars",
  "franchise": "IP name in English",
  "tv_show": "Full TV/anime series name (e.g. 'My Hero Academia Held Cultural Festival', 'Jujutsu Kaisen The Culling Game') - or same as franchise if no specific arc",
  "animation_studio": "Animation studio name + 'Animation Studio' suffix (e.g. 'Bones Animation Studio', 'Mappa Animation Studio') or 'Does Not Apply' if unknown/non-anime",
  "series_name_en": "Full series name in English INCLUDING subtitle (e.g. 'Ichiban Kuji My Hero Academia Held Cultural Festival') - TOPセラーは詳細サブタイトル含めて記載",
  "prize_en": "Prize name in English (e.g. A Prize, Shirakami Fubuki Prize, Last One Prize)",
  "character": "character name in English",
  "figure_type": "Masterlise/EXPIECE/Gracemaster/etc - これがC:Featuresに入る。Figureだけなら空文字に",
  "year": "year",
  "item_height_cm": "height in cm",
  "item_height_in": "height in inches (1 decimal)",
  "notes": "any warnings (VERO risk etc)"
}}"""

    # ホワイトリスト検証関数を読込
    try:
        _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"))
        from whitelist_registry import validate_and_normalize as _validate, build_retry_feedback as _feedback
    except Exception:
        _validate = None
        _feedback = None

    messages = [{"role": "user", "content": prompt}]
    last_result = None
    max_retries = 2 if _validate else 0

    for attempt in range(max_retries + 1):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=800,
                messages=messages,
            )
            text = message.content[0].text.strip()
            text = re.sub(r'^```json\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            result = json.loads(text)
        except Exception as e:
            print(f"    Claude APIエラー (attempt {attempt+1}): {e}")
            return last_result

        # 検証無しなら即返却
        if not _validate:
            print(f"    series_name_en: {result.get('series_name_en', '(なし)')}")
            return result

        # Claude フィールド名 → eBay Item Specifics キーにマッピングして検証
        specs_to_check = {
            "Franchise": result.get("franchise", ""),
            "TV Show": result.get("tv_show", ""),
            "Character": result.get("character", ""),
            "Animation Studio": result.get("animation_studio", ""),
        }
        normalized, violations = _validate(specs_to_check, "ichibankuji")

        # 正規化結果を Claude のフィールド名にバック適用
        if normalized.get("Franchise"):
            result["franchise"] = normalized["Franchise"]
        if normalized.get("TV Show"):
            result["tv_show"] = normalized["TV Show"]
        if normalized.get("Character"):
            result["character"] = normalized["Character"]
        if normalized.get("Animation Studio"):
            result["animation_studio"] = normalized["Animation Studio"]

        last_result = result

        if not violations:
            if attempt > 0:
                print(f"    ✓ ホワイトリスト合格 (attempt {attempt+1})")
            print(f"    series_name_en: {result.get('series_name_en', '(なし)')}")
            return result

        if attempt >= max_retries:
            print(f"    ⚠️ {max_retries+1}回試行後も違反{len(violations)}件、正規化値で進行:")
            for f, o, _e, r in violations:
                print(f"       - {f}: '{o}' ({r})")
            print(f"    series_name_en: {result.get('series_name_en', '(なし)')}")
            return result

        # フィードバック生成（eBayキー名 → Claudeフィールド名に変換）
        fb = _feedback(violations)
        fb = fb.replace("【Franchise】", "【franchise】")
        fb = fb.replace("【TV Show】", "【tv_show】")
        fb = fb.replace("【Character】", "【character】")
        fb = fb.replace("【Animation Studio】", "【animation_studio】")
        print(f"    ↻ ホワイトリスト違反{len(violations)}件、再試行 {attempt+1}/{max_retries}")
        for vf, vo, _ve, vr in violations:
            print(f"       - {vf}: '{vo}' ({vr})")
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": fb})

    return last_result

def load_base_description():
    """ICHIBANKUJI.txtを読み込む"""
    try:
        with open("ICHIBANKUJI.txt", "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None

def build_description(data, base_html):
    """Specificationsブロックを挿入"""
    specs = []
    specs.append(f"<li><b>Series:</b> {data.get('series_name_en','')}</li>")
    specs.append(f"<li><b>Prize:</b> {data.get('prize_en','')}</li>")
    specs.append(f"<li><b>Character:</b> {data.get('character','')}</li>")
    specs.append(f"<li><b>Figure Type:</b> {data.get('figure_type','Figure')}</li>")
    if data.get('size_cm'): specs.append(f"<li><b>Size:</b> Approx. {data.get('size_cm')} cm ({data.get('height_in','')} in)</li>")
    specs.append(f"<li><b>Material:</b> PVC</li>")
    specs.append(f"<li><b>Brand:</b> Bandai</li>")
    if data.get('year'): specs.append(f"<li><b>Year:</b> {data.get('year')}</li>")

    specs_html = f"""<p><span style="text-decoration: underline;"><strong>Specifications</strong></span></p>
<ul>
{chr(10).join(specs)}
</ul>"""

    if not base_html:
        return f"<html><body>{specs_html}</body></html>"

    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    if marker in base_html:
        return base_html.replace(marker, specs_html + '\n' + marker, 1)
    return base_html

def build_row(series_data, prize_data, claude_result, price, base_desc):
    """FileExchange CSV行を生成"""
    title = claude_result.get('title', '')
    # 安全策：80字を超えた場合は単語区切りで強制カット
    if len(title) > 80:
        title = title[:80].rsplit(' ', 1)[0]

    # === Title整合性 + 70字パディング (listing_common.normalize_title) ===
    # 一番くじは新品扱い (ConditionID=1000)
    _is_specs = {  # build_row 内で参照可能な item_specifics 雛形
        'Character': claude_result.get('character', ''),
        'Theme': 'Anime & Manga',
        'Type': 'Figure',
        'Franchise': claude_result.get('franchise', ''),
    }
    title = normalize_title(
        title, is_new=True, item_specifics=_is_specs,
        category="ichibankuji", target_min=70, max_chars=80,
    )
    franchise = claude_result.get('franchise', '')
    character = claude_result.get('character', '')
    figure_type = claude_result.get('figure_type', 'Figure')
    year = claude_result.get('year', series_data.get('release_year', ''))
    height_in = claude_result.get('item_height_in', '')
    # フォールバック：Claudeが返せない場合はsize_cmから計算
    if not height_in and prize_data.get('size_cm'):
        try:
            height_in = str(round(float(prize_data['size_cm']) / 2.54, 1))
        except:
            pass
    prize_en = claude_result.get('prize_en', '')
    series_name_en = claude_result.get('series_name_en', '')

    # 画像URL（公式画像 + ウォーターマーク画像）
    pic_url = series_data.get('main_image', '')
    if pic_url and PIC_WATERMARK:
        pic_urls = f"{pic_url}|{PIC_WATERMARK}"
    else:
        pic_urls = PIC_WATERMARK

    # CustomLabel: メルカリURLの m-id を SKU に使う（Porter/Tomica/Tシャツと同じ規約）
    # series_data['mercari_url'] が無い場合は従来のKUJI形式にフォールバック
    custom_label = ""
    merc_url = series_data.get('mercari_url', '')
    if merc_url:
        m = re.search(r'/item/(m\w+)', merc_url)
        if m:
            custom_label = m.group(1)
    if not custom_label:
        franchise_code = re.sub(r'[^A-Z0-9]', '', franchise.upper())[:8]
        char_code = re.sub(r'[^A-Z0-9]', '', character.upper().replace(' ', ''))[:6]
        prize_raw = str(prize_data.get('prize', '')).upper()
        prize_code = ""
        m_last = re.search(r'LAST', prize_raw)
        if m_last:
            prize_code = "LAST"
        else:
            m_prize = re.search(r'([A-Z])\s*賞|([A-Z])\s*PRIZE', prize_raw)
            if m_prize:
                prize_code = (m_prize.group(1) or m_prize.group(2))
        from datetime import datetime as _dt
        ts_suffix = _dt.now().strftime('%m%d')
        parts = ["KUJI", franchise_code, char_code]
        if prize_code:
            parts.append(prize_code)
        parts.append(ts_suffix)
        custom_label = "-".join(parts)

    # C:Prize：英語のみ
    if not prize_en:
        prize_en = re.sub(r'[^\x00-\x7F]', '', prize_data['prize']).strip() + ' Prize'
        if prize_en.strip() == ' Prize':
            prize_en = character + ' Prize'

    # C:Series：Claudeの結果を優先、なければフォールバック
    if not series_name_en:
        series_name_en = f"Ichiban Kuji {franchise}"
    print(f"    → C:Series に設定: {series_name_en}")

    # Description生成
    height_cm = claude_result.get('item_height_cm', prize_data.get('size_cm', ''))
    desc_data = {
        'series_name_en': series_name_en,
        'prize_en': prize_en,
        'character': character,
        'figure_type': figure_type,
        'size_cm': height_cm,
        'height_in': height_in,
        'year': year,
    }
    description = build_description(desc_data, base_desc)

    return {
        "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)": "Add",
        "*Category": EBAY_CATEGORY,
        "*Title": title,
        "*Description": description,
        "PicURL": pic_urls,
        "*StartPrice": price,
        "ConditionID": CONDITION_ID,
        "CustomLabel": custom_label,
        "ScheduleTime": get_schedule_time(),
        "*Format": "FixedPrice",
        "*Duration": "GTC",
        "*Quantity": 1,
        "*Location": LOCATION,
        "BestOfferEnabled": 1,
        "ShippingProfileName": get_shipping_policy(price),
        "ReturnProfileName": "customer1",
        "PaymentProfileName": "SALE",
        "Product:UPC": "Does not apply",
        # Item Specifics — TOPセラー(fb>900)構成準拠
        "C:Franchise": franchise,
        "C:TV Show": claude_result.get('tv_show', franchise),
        "C:Movie": claude_result.get('tv_show', franchise),
        "C:Brand": "Bandai",
        "C:Language": "Japanese",
        "C:Material": "Plastic",  # eBayフィルタ正規値（"PVC, ABS"はリスト無し）
        "C:Character": character,
        "C:Color": "Multicolor",
        "C:Theme": "Anime & Manga",
        "C:MPN": "Does Not Apply",
        "C:Animation Studio": claude_result.get('animation_studio', "Does Not Apply"),
        "C:Country of Origin": "Japan",
        "C:Year Manufactured": year,
        "C:Type": "Figure",
        "C:Features": figure_type if figure_type and figure_type.upper() not in ('FIGURE','') else "",
        "C:Original/Licensed Reproduction": "Original",
        "C:Signed": "No",
        "C:Vintage": "No",
        "C:Item Height": f"{height_in} in" if height_in else "",
        "C:Series": series_name_en,
        "StoreCategoryID": 42133037010,
        "StoreCategoryID2": STORE_CATEGORY2.get(franchise.lower(), STORE_CATEGORY2_DEFAULT),
    }

# ===== Phase 1: 1kuji.com → 中間CSV =====
SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
PENDING_DIR = _os.path.join(SCRIPT_DIR, "pending")

# 非フィギュアキーワード (早期フィルタ用)
NON_FIGURE_KEYWORDS = [
    'タオル', 'マグカップ', 'トートバッグ', 'アクリル', 'ラバー',
    'キーチェーン', 'コースター', 'ポーチ', 'ハンカチ', 'ボード',
    'チャーム', 'プレート', 'シート', 'テープ', 'ストラップ',
    '缶バッジ', 'ステッカー', 'ノート', 'クリアファイル', 'ブックレット',
    'クッション', 'ブランケット', '巾着', '湯呑', 'ポストカード',
    'アソート', 'セット賞', 'イラスト', 'ガラス', 'メタル',
    '小物入れ', '急須', '小皿', 'ビジュアル', 'ぬいぐるみ',
    'Plushie', 'Plush', 'Stuffed', 'Stationery', 'Towel', 'Mug',
    'Tote', 'Acrylic', 'Rubber', 'Keychain', 'Coaster', 'Pouch',
    'Handkerchief', 'Badge', 'Sticker', 'Notebook', 'Clear File',
    'Cushion', 'Blanket', 'Postcard', 'Illustration', 'Glass',
    'Metal', 'Sound', 'Teapot', 'Plate', 'Strap',
]


INTERMEDIATE_FIELDS = ['kuji_url','series_name','prize','prize_title','size_cm','image_url','release_year','kuji_price_jpy','mercari_url','cost_jpy']

def phase1_extract_intermediate(driver, urls):
    """1kuji.com スクレイプ → 中間CSV (タイトル日本語、Mercari URL/cost空欄)"""
    rows = []
    for ui, url in enumerate(urls):
        print(f"\n[Phase1 {ui+1}/{len(urls)}] {url}")
        series_data = scrape_1kuji(driver, url)
        if not series_data:
            print("  スクレイピング失敗→スキップ")
            continue
        series_name = series_data.get('series_name', '')
        image_url = series_data.get('main_image', '')
        release_year = series_data.get('release_year', '')
        kuji_price_jpy = series_data.get('price_jpy', '')
        print(f"  シリーズ: {series_name} ({len(series_data.get('prizes', []))}賞)")
        for prize in series_data.get('prizes', []):
            prize_name = prize.get('name', '')
            prize_code = prize.get('prize', '')
            # 非フィギュア早期フィルタ
            if any(kw in prize_name for kw in NON_FIGURE_KEYWORDS):
                print(f"    {prize_code} 非フィギュア→スキップ: {prize_name[:30]}")
                continue
            # サイズチェック
            size_cm = prize.get('size_cm', '')
            if size_cm:
                try:
                    if float(size_cm) < 10:
                        print(f"    {prize_code} {size_cm}cm(10cm未満)→スキップ")
                        continue
                except:
                    pass
            rows.append({
                'kuji_url': url,
                'series_name': series_name,
                'prize': prize_code,
                'prize_title': prize_name,
                'size_cm': size_cm,
                'image_url': image_url,
                'release_year': release_year,
                'kuji_price_jpy': kuji_price_jpy,
                'mercari_url': '',
                'cost_jpy': '',
            })
    # 書出
    _os.makedirs(PENDING_DIR, exist_ok=True)
    out_path = _os.path.join(PENDING_DIR, f"intermediate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    import csv as _csv
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=INTERMEDIATE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"\n✅ 中間CSV書出: {out_path}")
    print(f"  {len(rows)}行（フィギュアのみ）")
    print(f"\n次のステップ: この中間CSVを開いて、各行のmercari_url列にメルカリURLを貼り付けてください")
    print(f"  完了後: python ichibankuji_to_csv.py --phase 2 {out_path}")
    return out_path


def fetch_mercari_price(mercari_url):
    """メルカリ商品URLから価格をスクレイプ"""
    import requests, re as _re
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(mercari_url, headers=headers, timeout=15)
        if r.status_code != 200:
            return 0
        # og:price or __NEXT_DATA__ 等から抽出
        m = _re.search(r'"price":(\d+)', r.text)
        if m:
            return int(m.group(1))
        m = _re.search(r'¥([\d,]+)', r.text)
        if m:
            return int(m.group(1).replace(',', ''))
    except Exception:
        pass
    return 0


def phase2_transfer_to_sheet(intermediate_path):
    """中間CSV (Mercari URL入力済) → 統合Hightスプシに追記
    G=image_url, I=kuji_url, J=series_name, K=prize_code, L=prize_name_jp,
    M=release_year, N=kuji_price_jpy も書き込む（▶実行で再構成できるように）
    既存A列URLとの重複は自動スキップ。
    """
    import csv as _csv
    import gspread
    from google.oauth2.service_account import Credentials

    if not _os.path.exists(intermediate_path):
        print(f"エラー: {intermediate_path} が見つかりません")
        return

    rows = _read_intermediate_csv(intermediate_path)

    # Mercari URL 入力済の行のみ
    filled = [r for r in rows if r.get('mercari_url', '').strip()]
    if not filled:
        print("Mercari URL入力済み行なし。中間CSV開いて mercari_url列 に貼付してください")
        return

    # 統合Hight 接続
    creds_path = _os.path.join(SCRIPT_DIR, "..", "double-hold-421922-7c0d38d3f73d.json")
    creds = Credentials.from_service_account_file(creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key("19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk")
    ws = sh.get_worksheet_by_id(851100680)

    # 既存URL重複検知
    existing_urls = {u.strip() for u in ws.col_values(1) if u.strip()}
    print(f"📋 統合Hight 既存URL: {len(existing_urls)}件")
    before = len(filled)
    filled = [r for r in filled if r['mercari_url'].strip() not in existing_urls]
    skipped = before - len(filled)
    if skipped:
        print(f"⏭ 既存URL {skipped}件 スキップ")
    if not filled:
        print("転記対象なし")
        return

    print(f"\n転記対象: {len(filled)}件\n")

    all_values = ws.get_all_values()
    next_row = len(all_values) + 1

    # 28列まで書く（A-AB）。A-R=既存スキーマ、U=追加日(全スクリプト共通)、V-AB=一番くじメタデータ
    today_str = datetime.now().strftime('%Y-%m-%d')
    new_rows = []
    for r in filled:
        title_jp = f"{r.get('prize','')} {r.get('prize_title','')}".strip()
        row_26 = [''] * 28
        row_26[0]  = r.get('mercari_url', '').strip()                       # A: URL
        row_26[2]  = title_jp                                                # C: タイトル
        row_26[4]  = '新品、未使用'                                          # E: 状態
        row_26[5]  = f"¥{r.get('cost_jpy','')}" if r.get('cost_jpy','').strip() else ''  # F: 価格
        row_26[6]  = r.get('image_url', '')                                  # G: 写真URL (1kuji OGP)
        row_26[17] = '一番くじ'                                              # R: カテゴリ
        row_26[20] = today_str                                               # U: 追加日 (全スクリプト共通)
        # V-AB: 一番くじ専用メタデータ（▶実行で Claude プロンプト再構成に使用）
        row_26[21] = r.get('kuji_url', '')                                   # V: kuji_url
        row_26[22] = r.get('series_name', '')                                # W: series_name
        row_26[23] = r.get('prize', '')                                      # X: prize_code
        row_26[24] = r.get('prize_title', '')                                # Y: prize_title
        row_26[25] = r.get('release_year', '')                               # Z: release_year
        row_26[26] = r.get('kuji_price_jpy', '')                             # AA: kuji_price_jpy
        row_26[27] = r.get('size_cm', '')                                    # AB: size_cm (Item Height計算用)
        new_rows.append(row_26)
        print(f"  {r.get('prize','')} {r.get('prize_title','')[:25]} → 価格 ¥{r.get('cost_jpy','-')}")

    ws.update(
        range_name=f"A{next_row}:AB{next_row + len(new_rows) - 1}",
        values=new_rows,
        value_input_option='USER_ENTERED',
    )
    print(f"\n✅ 統合Hight に {len(new_rows)}行 追記 (行 {next_row}〜)")
    print(f"次のステップ: ▶実行 で 統合Hight (R=一番くじ, ItemID空) → eBay CSV生成")


def _read_intermediate_csv(path):
    """中間CSV読込（複数encoding対応）"""
    import csv as _csv
    last_err = None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                rows = list(_csv.DictReader(f))
            print(f"📖 中間CSV読込: encoding={enc}")
            return rows
        except UnicodeDecodeError as e:
            last_err = e
    raise last_err


def _process_sheet_to_ebay_csv():
    """統合Hight (R=一番くじ, B=ItemID空, D=売り切れ空) → eBay CSV
    Z列までの A-Z 列を読込み、U-Z の一番くじメタデータで Claude を叩く。
    成功してもスプシは触らない（B=ItemIDは出品後にユーザーが手入力）。
    """
    import gspread
    from google.oauth2.service_account import Credentials
    creds_path = _os.path.join(SCRIPT_DIR, "..", "double-hold-421922-7c0d38d3f73d.json")
    creds = Credentials.from_service_account_file(creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key("19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk")
    ws = sh.get_worksheet_by_id(851100680)

    # A-AB 全列取得（U=追加日, V-AB=一番くじメタも含めるため広めに）
    all_values = ws.get('A1:AB' + str(ws.row_count))

    # クリーンアップ: B列(ItemID)が入った行の V-AB をクリア（U=追加日は残す）
    cleanup_rows = []
    for i, row in enumerate(all_values[1:], start=2):
        row = list(row) + [''] * (28 - len(row))
        url = row[0].strip()
        item_id = row[1].strip()
        category = row[17].strip()
        if url and item_id and category == "一番くじ":
            # V-AB のいずれかに値が残っていれば削除対象
            if any(row[c].strip() for c in range(21, 28)):
                cleanup_rows.append(i)
    if cleanup_rows:
        try:
            batch_data = []
            for row_num in cleanup_rows:
                batch_data.append({
                    'range': f'V{row_num}:AB{row_num}',
                    'values': [['', '', '', '', '', '', '']],
                })
            ws.batch_update(batch_data, value_input_option='USER_ENTERED')
            print(f"🧹 ItemID入済の行から V-AB メタデータをクリア: {len(cleanup_rows)}件")
        except Exception as e:
            print(f"⚠️ V-AB クリア失敗（続行）: {e}")

    targets = []
    for i, row in enumerate(all_values[1:], start=2):
        # 列が足りない場合は空で埋める
        row = list(row) + [''] * (28 - len(row))
        url       = row[0].strip()
        item_id   = row[1].strip()
        sold      = row[3].strip()
        category  = row[17].strip()
        if not url or item_id or sold:
            continue
        if category != "一番くじ":
            continue
        targets.append({
            'sheet_row': i,
            'mercari_url': url,
            'cost_jpy': re.sub(r'[^0-9]', '', row[5]) if row[5] else '',
            'image_url': row[6],
            # V-AB (index 21-27) ※ U(20)は追加日で metadata ではない
            'kuji_url': row[21],
            'series_name': row[22],
            'prize_code': row[23],
            'prize_title': row[24],
            'release_year': row[25],
            'kuji_price_jpy': row[26],
            'size_cm': row[27],
        })

    if not targets:
        print("処理対象なし（統合Hight に R=一番くじ かつ B=ItemID空 の行なし）")
        print("→ 先に ③スプシ転記 で中間CSVを統合Hightへ追記してください")
        return

    # 修復レイヤ1: size_cm が空の行 → pending/ 内の中間CSV を逆引きして補完
    missing_size = [t for t in targets if not t.get('size_cm')]
    if missing_size:
        import glob as _glob
        csv_files = sorted(_glob.glob(_os.path.join(PENDING_DIR, "intermediate_*.csv")))
        csv_lookup = {}
        for p in csv_files:
            try:
                rows = _read_intermediate_csv(p)
                for r in rows:
                    k = (r.get('kuji_url','').strip(), r.get('prize','').strip())
                    if r.get('size_cm'):
                        csv_lookup[k] = r['size_cm']
            except Exception:
                continue
        repaired = 0
        for t in missing_size:
            key = (t['kuji_url'].strip(), t['prize_code'].strip())
            if key in csv_lookup:
                t['size_cm'] = csv_lookup[key]
                repaired += 1
        if repaired:
            print(f"🔧 size_cm 修復(中間CSV逆引き): {repaired}件")

    # 修復レイヤ2: それでも size_cm 空 → 1kuji を再スクレイプ（最新 scrape_1kuji 使用）
    still_missing = [t for t in targets if not t.get('size_cm') and t.get('kuji_url')]
    if still_missing:
        print(f"🔧 size_cm 再スクレイプ: {len(still_missing)}件（1kuji 再訪）")
        # URL 単位でグループ化（同URLは1回で済む）
        by_url = {}
        for t in still_missing:
            by_url.setdefault(t['kuji_url'], []).append(t)
        try:
            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            driver = uc.Chrome(options=options, version_main=146)
            try:
                for url, ts in by_url.items():
                    sd = scrape_1kuji(driver, url)
                    if not sd:
                        continue
                    by_prize = {p['prize']: p for p in sd.get('prizes', [])}
                    for t in ts:
                        p = by_prize.get(t['prize_code'])
                        if p and p.get('size_cm'):
                            t['size_cm'] = p['size_cm']
                            # 統合Hight AB列(size_cm)も更新
                            try:
                                ws.update_acell(f"AB{t['sheet_row']}", p['size_cm'])
                            except Exception:
                                pass
                            print(f"   ✓ 行{t['sheet_row']} {t['prize_code']} size_cm={p['size_cm']}")
            finally:
                driver.quit()
        except Exception as e:
            print(f"⚠️ 再スクレイプ失敗: {e}")

    print(f"\n処理対象: {len(targets)}件（統合Hight, R=一番くじ, ItemID空）\n")

    base_desc = load_base_description()
    if base_desc:
        print("✅ ICHIBANKUJI.txt 読み込み済み")
    else:
        print("⚠️ ICHIBANKUJI.txt なし。シンプルDescription使用")

    all_rows = []

    for idx, t in enumerate(targets):
        prize_code = t['prize_code']
        prize_name = t['prize_title']
        print(f"\n[{idx+1}/{len(targets)}] sheet行{t['sheet_row']} {prize_code} {prize_name[:40]}")

        if not t['kuji_url'] or not t['series_name'] or not prize_code:
            print(f"    ⚠️ メタデータ不足（U-W列空） → スキップ。③スプシ転記からやり直してください")
            continue

        series_data = {
            'series_name': t['series_name'],
            'release_year': t['release_year'],
            'price_jpy': t['kuji_price_jpy'],
            'main_image': t['image_url'],
            'url': t['kuji_url'],
            'mercari_url': t['mercari_url'],
            'prizes': [],
        }
        prize_data = {'prize': prize_code, 'name': prize_name, 'size_cm': t.get('size_cm', '')}

        claude_result = analyze_with_claude(series_data, prize_data)
        if not claude_result:
            print(f"    Claude失敗→スキップ")
            continue
        if not claude_result.get('is_figure', True):
            print(f"    非フィギュア（Claude判定）→スキップ")
            continue

        title = claude_result.get('title', '')
        t_ok = "✅" if len(title) <= 80 else f"⚠️{len(title)}字"
        print(f"    {t_ok} ({len(title)}字) {title}")

        listing_price = DEFAULT_PRICE
        _ebay_median = 0.0
        _price_status = "GO"
        try:
            cost_str = t['cost_jpy'] or t['kuji_price_jpy']
            _cost = int(re.sub(r'[^0-9]', '', str(cost_str))) if cost_str else 0
            if _cost > 0:
                _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"))
                from pricing_engine import compute_listing_price
                # 市場中央値取得（PRICE_CHECK_CONFIG.enabled なら）
                try:
                    from listing_common import PRICE_CHECK_CONFIG
                    if PRICE_CHECK_CONFIG.get("ichibankuji", {}).get("enabled"):
                        from check_csv_core import fetch_ebay_market_median
                        _kw = " ".join((title or "").split()[:5])
                        _ebay_median, _hits = fetch_ebay_market_median(
                            keywords=_kw, category_ids=str(EBAY_CATEGORY),
                            condition_id=str(CONDITION_ID), limit=30,
                        )
                        if _ebay_median > 0:
                            print(f"    📊 eBay median ${_ebay_median:.2f} (hits={_hits})")
                except Exception as _me:
                    pass
                pricing = compute_listing_price(_cost, _ebay_median, PROFIT_CATEGORY)
                listing_price = max(pricing.get('price', DEFAULT_PRICE), 9.98)
                _price_status = pricing.get('status', 'GO')
                print(f"    💰 cost ¥{_cost} → eBay ${listing_price} [{_price_status}]")
        except Exception as e:
            print(f"    ⚠️ pricing_engine失敗: {e}")

        ebay_row = build_row(series_data, prize_data, claude_result, listing_price, base_desc)
        # === 物理ゲート: audit_csv_row error なら HOLDキューへ隔離 ===
        from listing_common import gate_row_or_hold as _gate
        _allowed, _viol = _gate(ebay_row, category="ichibankuji",
                                 sku=ebay_row.get("CustomLabel", ""),
                                 price_status=_price_status, median_usd=_ebay_median)
        if not _allowed:
            _errs = [f"{f}={i}" for f, i, s in _viol if s == "error"]
            print(f"    🟠 HOLD: {ebay_row.get('CustomLabel','')} → {_errs}")
            continue
        all_rows.append(ebay_row)
        time.sleep(2)

    if all_rows:
        all_keys = list(all_rows[0].keys())
        with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\n✅ eBay CSV出力: {OUTPUT_CSV}  ({len(all_rows)}件)")
        # Step 8 拡張: decision_log に config_version + 使用値を刻印
        try:
            import sys as _sys_dl
            _sys_dl.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI"))
            from decision_log import log_csv_batch as _log_batch
            _log_batch(project="iMak_ichibankuji", category="一番くじ",
                       output_path=OUTPUT_CSV, row_count=len(all_rows))
        except Exception as _e:
            print(f"⚠️ decision_log 失敗 (ichibankuji): {type(_e).__name__}: {_e}")
        print(f"   ※ 出品完了後、統合Hight B列にItemIDを手入力で「処理済」化")
    else:
        print("\n❌ eBay CSV対象行なし")


def main():
    print("=== iMak Trading Japan - 一番くじ → eBay CSV 自動生成 ===\n")

    import argparse as _argparse
    parser = _argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["1", "2"],
                        help="1=1kuji→中間CSV / 2=中間CSV→統合Hight転記")
    parser.add_argument("intermediate_path", nargs="?",
                        help="Phase2用 中間CSVパス（省略時は最新自動選択）")
    args, _ = parser.parse_known_args()

    # Phase 1: 1kuji → 中間CSV
    if args.phase == "1":
        try:
            with open(URLS_FILE, "r", encoding="utf-8") as f:
                urls = [l.strip() for l in f if l.strip() and l.startswith("http")]
        except FileNotFoundError:
            print(f"エラー: {URLS_FILE} が見つかりません。")
            return
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        driver = uc.Chrome(options=options, version_main=146)
        try:
            phase1_extract_intermediate(driver, urls)
        finally:
            driver.quit()
        return

    # Phase 2: 中間CSV → 統合Hight 転記
    if args.phase == "2":
        intermediate_path = args.intermediate_path
        if not intermediate_path:
            import glob
            candidates = sorted(glob.glob(_os.path.join(PENDING_DIR, "intermediate_*.csv")))
            if not candidates:
                print("エラー: 中間CSVが見つかりません。先に Phase1 を実行してください")
                return
            intermediate_path = candidates[-1]
            print(f"📂 最新中間CSV自動選択: {intermediate_path}")
        phase2_transfer_to_sheet(intermediate_path)
        return

    # デフォルト（▶実行）: 統合Hight (R=一番くじ, ItemID空) → eBay CSV
    _process_sheet_to_ebay_csv()

if __name__ == "__main__":
    main()
