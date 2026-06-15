"""出品くん psa_to_csv 後 hook: 全カテゴリ cert 確認 → HTML viewer + http.server 自動生成.

設計 (= 5/28 ユーザー指示 「グダグダしない」 + 「download + paste 不要」):
- 出品くん cycle 後、 CSV 内 全 cert を catalog hit 状況 inspect
- ユーザー目視 verify 済 (verified_certs) と cache miss / category 不明 を除く
  **全 cert を HTML viewer + ローカル http.server で表示** (= ユーザー指示「全件表示」)
  ※ 旧設計は「怪しい cert (hit 不能/複数候補/DON 系) だけ表示」だったが、機械が
    怪しさを判定 = ユーザーを経ない不正確判断になるため撤廃。全件をユーザー目視に回す。
- ユーザー browser click + 「✉️ HQ に送信」 → POST → JSON 保存 → server auto stop
- HQ が保存 file 読込 → catalog 投入 + スプシ書込

注意 (= 2026-06-07 確認): 本 viewer の目視は「同定」(スキャン画像 ⇔ どの product_id か)
を担う。catalog 行内の英語フィールド (set_name_ebay 等) の正誤は JP カード画像から
人が検証不能なので、ここでは捕まらない。フィールド整合は catalog_set_audit.py /
check_csv の機械ゲート (Set↔番号↔世代) で別途担保する。役割分担: 人=同定 / 機械=フィールド整合。
"""
import os
import sys
import csv
import json
import sqlite3
import threading
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

PSA_CACHE_DIR = Path(r"C:/dev/iMak/iMakeBayAPI/cache/psa_certs")
DON_IMAGES_DIR = Path(r"C:/dev/iMak_data/catalog/_don_images")
CATALOG_DB = Path(r"C:/dev/iMak_data/catalog/products.sqlite")
HTML_OUTPUT = Path(r"C:/dev/iMak_data/dedupe/psa_review_latest.html")
RESULT_DIR = Path(r"C:/dev/iMak_data/dedupe/psa_review_results")
VERIFIED_CERTS_FILE = Path(r"C:/dev/iMak_data/dedupe/verified_certs.json")
SERVER_PORT = 8765


def _detect_category(brand: str) -> str | None:
    b = brand.upper()
    if "ONE PIECE" in b:
        return "one_piece_tcg"
    if "POKEMON" in b:
        return "pokemon_tcg"
    if "YU-GI-OH" in b or "YUGIOH" in b:
        return "yugioh_tcg"
    if "DRAGON BALL" in b or "DRAGONBALL" in b:
        return "dragonball_scg"
    if "GUNDAM" in b:
        return "gundam_tcg"
    return None


def _extract_set_code(brand: str, category: str) -> str | None:
    import re
    b = brand.upper()
    if category == "one_piece_tcg":
        m = re.search(r"\b(OP\d+|ST\d+|EB\d+|PRB\d+|RP|EVENT|PROMOS|STORAGE|KUMAMON|GRAND-ASIA|ANNIV)\b", b)
        return m.group(1) if m else None
    if category == "pokemon_tcg":
        m = re.search(r"\b(SV\d+[A-Z]?|S\d+[a-z]?|S-P|SV-P|M-P|SM-P|XY-P|BW-P|DP-P|M\d+L?|HG\w*|LL\w*|SoulSilver|HS)\b", b)
        return m.group(1) if m else None
    return None


def _get_candidates(category: str, set_code: str | None, card_number: str | None,
                    brand: str = "", expected_product_id: str | None = None,
                    subject: str = "") -> list[tuple[str, str]]:
    """catalog 候補 list 取得. (product_id, image_path) tuple.

    2026-05-31 改訂: Gemini 推奨 3 段階フォールバック logic.
      優先度 1: expected_product_id プレフィックス検索 (= 期待 ID + variant suffix 確実 hit)
      優先度 2: set_code 絞込 (= 既存挙動 fallback)
      優先度 3: category 全件 (= safety net、 UI 空回避)
    """
    if not category:
        return []
    conn = sqlite3.connect(str(CATALOG_DB))
    cur = conn.cursor()
    rows: list = []
    results: list = []
    try:
        # === 優先度 1: expected_product_id プレフィックス検索 ===
        if expected_product_id:
            cur.execute(
                "SELECT product_id FROM products WHERE category=? AND product_id LIKE ? ORDER BY product_id LIMIT 30",
                (category, f"{expected_product_id}%")
            )
            rows = cur.fetchall()

        # === 優先度 2: set_code 絞込 (= 既存挙動 fallback) ===
        if not rows:
            if category == "one_piece_tcg":
                if set_code and set_code not in ("PROMOS", "EVENT"):
                    cur.execute(
                        "SELECT product_id FROM products WHERE category=? AND product_id LIKE ? ORDER BY product_id LIMIT 30",
                        (category, f"%{set_code}%")
                    )
                else:
                    # PROMOS / EVENT は全 DON + 全 promo
                    cur.execute(
                        # '_' は LIKE ワイルドカードなので escape (literal '_P' promo suffix のみ狙う。'OP##' 誤マッチ防止)
                        r"SELECT product_id FROM products WHERE category=? AND (product_id LIKE 'DON-%' OR product_id LIKE '%\_P%' ESCAPE '\') ORDER BY product_id LIMIT 50",
                        (category,)
                    )
            elif category == "pokemon_tcg" and set_code:
                cur.execute(
                    "SELECT product_id FROM products WHERE category=? AND product_id LIKE ? ORDER BY product_id LIMIT 30",
                    (category, f"{set_code}-%")
                )
            elif category == "pokemon_tcg" and card_number:
                # set_code 不明 + card_number あり = 番号末尾一致で絞込
                cur.execute(
                    "SELECT product_id FROM products WHERE category=? AND product_id LIKE ? ORDER BY product_id LIMIT 30",
                    (category, f"%-{card_number}")
                )
            rows = cur.fetchall()

        # === 優先度 3: character 名 (subject) で候補を surface ===
        # set_code 抽出漏れ・promo・新セット・ID lookup 失敗 (= miss) でも、catalog に
        # そのキャラが在れば必ず候補に出す。HTML の本来目的 (人が候補から選ぶ) を担保。
        # subject 例 'SABO' / 'MONKEY D LUFFY ALTERNATE ART' → name_en LIKE で引く。
        if subject and not expected_product_id:
            import re
            _NOISE = {"ALTERNATE", "ALT", "ART", "RARE", "FOIL", "PARALLEL", "SPECIAL", "FULL",
                      "MANGA", "COMIC", "LEADER", "SUPER", "SECRET", "PROMO", "CARD", "THE", "AND",
                      "SAR", "VMAX", "VSTAR", "GX", "EX"}
            toks = [t for t in re.split(r"[^A-Za-z]+", subject)
                    if len(t) >= 3 and t.upper() not in _NOISE][:3]
            char_rows: list = []
            if toks:
                like = " OR ".join(["name_en LIKE ?"] * len(toks))
                base = f"SELECT DISTINCT product_id FROM products WHERE category=? AND ({like})"
                # card_number があれば番号末尾一致で pinpoint (例 Sabo + -049 → OP10-049)
                if card_number:
                    cur.execute(base + " AND product_id LIKE ? ORDER BY product_id LIMIT 40",
                                [category] + [f"%{t}%" for t in toks] + [f"%-{card_number}"])
                    char_rows = cur.fetchall()
                if not char_rows:  # 番号一致なし → キャラ名のみで広く
                    cur.execute(base + " ORDER BY product_id LIMIT 40",
                                [category] + [f"%{t}%" for t in toks])
                    char_rows = cur.fetchall()
            if char_rows:
                # キャラ候補を先頭に (人が選びやすい)。既存 rows は dedup して後ろに残す。
                seen = {p for (p,) in char_rows}
                rows = char_rows + [r for r in rows if r[0] not in seen]

        # === 優先度 4: category 全件 (= 最終 safety net) ===
        if not rows:
            cur.execute(
                "SELECT product_id FROM products WHERE category=? ORDER BY product_id LIMIT 30",
                (category,)
            )
            rows = cur.fetchall()

        for (pid,) in rows:
            # DON 系は専用切出画像、 他は catalog images 列の URL を使う
            if pid.startswith("DON-"):
                img = str(DON_IMAGES_DIR / f"{pid}.png")
            else:
                # catalog images 列の最初 URL
                cur2 = conn.cursor()
                cur2.execute("SELECT images FROM products WHERE product_id=? AND category=?", (pid, category))
                irow = cur2.fetchone()
                img = ""
                if irow and irow[0]:
                    try:
                        imgs = json.loads(irow[0])
                        if imgs and isinstance(imgs, list):
                            lang = "ja" if "JAPANESE" in (brand or "").upper() else "en"
                            img = _pick_image_by_language(imgs, lang) or imgs[0]
                    except Exception:
                        pass
            results.append((pid, img))
    finally:
        conn.close()
    return results


def _catalog_lookup_expected(brand: str, subject: str, card_number: str, category: str) -> str | None:
    """catalog lookup 経由で expected product_id 取得 (= 5/28 lookup_one_piece Promo 拡張 + lookup_don 等を活用)."""
    if not category:
        return None
    try:
        # catalog 越境 import (= iMakCatalog/integrations)
        _cat_dir = r"C:/dev/iMak_catalog/iMakCatalog"
        if _cat_dir not in sys.path:
            sys.path.insert(0, _cat_dir)
        from integrations import psa_to_csv as _cat_psa
        subj_up = (subject or "").upper()
        if category == "one_piece_tcg":
            if "DON" in subj_up:
                rec = _cat_psa.lookup_don(brand, subject)
                if rec:
                    return rec.get("product_id")
                return None
            rec = _cat_psa.lookup_one_piece(brand, card_number, subject)
            if rec:
                return rec.get("card_id") or rec.get("product_id")
        elif category == "pokemon_tcg":
            rec = _cat_psa.lookup_pokemon(brand, card_number, subject)
            if rec:
                return rec.get("card_id") or rec.get("product_id")
        elif category == "dragonball_scg":
            rec = _cat_psa.lookup_dragonball(brand, card_number, subject)
            if rec:
                return rec.get("card_id") or rec.get("product_id")
        elif category == "gundam_tcg":
            rec = _cat_psa.lookup_gundam(brand, card_number, subject)
            if rec:
                return rec.get("card_id") or rec.get("product_id")
        elif category == "yugioh_tcg":
            rec = _cat_psa.lookup_yugioh(brand, card_number, subject)
            if rec:
                return rec.get("card_id") or rec.get("product_id")
    except Exception:
        pass
    return None


def _get_psa_cache(cert: str) -> dict | None:
    f = PSA_CACHE_DIR / f"{cert}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _pick_image_by_language(imgs: list, lang_hint: str = "ja") -> str | None:
    """images list から language hint で 1 件選択. lang='ja' = OP-JA / pokemon-card.com 等 JA 系 URL 優先、 'en' = OP-EN 優先."""
    if not imgs:
        return None
    ja_patterns = ("/OP-JA/", "OP-JA", "pokemon-card.com", "-JA/", "_JA_", "/JA/")
    en_patterns = ("/OP-EN/", "OP-EN", "-EN/", "_EN_", "/EN/")
    if lang_hint == "ja":
        for u in imgs:
            if any(p in u for p in ja_patterns):
                return u
        for u in imgs:
            if not any(p in u for p in en_patterns):
                return u
    elif lang_hint == "en":
        for u in imgs:
            if any(p in u for p in en_patterns):
                return u
    return imgs[0]


def _find_expected_image(category: str, product_id: str, brand: str = "") -> str | None:
    """期待値 product_id の画像 path or URL 取得 (= brand から language 判定)."""
    if not product_id:
        return None
    if product_id.startswith("DON-"):
        p = DON_IMAGES_DIR / f"{product_id}.png"
        return str(p) if p.exists() else None
    conn = sqlite3.connect(str(CATALOG_DB))
    cur = conn.cursor()
    cur.execute("SELECT images FROM products WHERE product_id=? AND category=?", (product_id, category))
    row = cur.fetchone()
    conn.close()
    if row and row[0]:
        try:
            imgs = json.loads(row[0])
            if imgs and isinstance(imgs, list):
                lang = "ja" if "JAPANESE" in (brand or "").upper() else "en"
                return _pick_image_by_language(imgs, lang)
        except Exception:
            pass
    return None


def _img_url(src: str) -> str:
    """画像 src を /img/<urlencoded> に変換 (= local file + 外部 URL 両対応)."""
    if not src:
        return ""
    return "/img/" + urllib.parse.quote(src, safe="")


def _generate_html(targets: list[dict]) -> None:
    # JS で targets info (= cert / expected) を保持、 結果 collect 用
    targets_json = json.dumps([{
        "cert": t["cert"],
        "expected": t.get("csv_expected", ""),
        "category": t["category"],
    } for t in targets], ensure_ascii=False)

    html = [
        '<!DOCTYPE html><html><head><meta charset=utf-8><title>PSA Review (latest cycle)</title>',
        '<style>',
        'body{font-family:sans-serif;margin:10px;background:#1a1a1a;color:#fff}',
        '.target{border:2px solid #ffd700;padding:14px;margin:14px 0;background:#2a2a2a;border-radius:6px}',
        '.target.answered-ok{border-color:#4caf50;background:#1f3a1f}',
        '.target.answered-ng{border-color:#f44336;background:#3a1f1f}',
        '.target.answered-chosen{border-color:#2196f3;background:#1f2a3a}',
        '.target.answered-none{border-color:#9e9e9e;background:#2a2a2a;opacity:0.6}',
        '.target h2{color:#ffd700;margin:0 0 8px;font-size:20px}',
        '.cert-info{font-size:13px;color:#ccc;margin:4px 0}',
        '.confirm{display:flex;gap:24px;align-items:flex-start;margin:14px 0;padding:14px;background:#1f3a1f;border-radius:6px;border:2px solid #4caf50}',
        '.confirm .label{font-size:18px;color:#9fffa0;font-weight:bold;margin-bottom:6px}',
        '.confirm img{max-width:380px;border:1px solid #444;border-radius:4px}',
        '.confirm-q{font-size:24px;color:#ffd700;font-weight:bold;margin:8px 0;text-align:center;align-self:center}',
        '.no-expected{background:#3a1f1f;border-color:#f44336;color:#ffaaaa}',
        '.no-expected .label{color:#ffaaaa}',
        '.answer-btns{display:flex;gap:10px;margin:10px 0}',
        '.btn{padding:10px 18px;border:none;border-radius:6px;cursor:pointer;font-size:14px;font-weight:bold}',
        '.btn-ok{background:#4caf50;color:#fff}',
        '.btn-ng{background:#f44336;color:#fff}',
        '.btn-none{background:#9e9e9e;color:#fff}',
        '.btn:hover{opacity:0.85}',
        '.btn.active{box-shadow:0 0 0 3px #fff}',
        '.candidates-toggle{cursor:pointer;color:#80c0ff;text-decoration:underline;font-size:13px;margin:8px 0}',
        '.candidates{display:none;margin-top:8px}',
        '.candidates.show{display:block}',
        '.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}',
        '.cand{border:2px solid #555;padding:8px;background:#333;text-align:center;border-radius:6px;cursor:pointer;transition:all 0.15s}',
        '.cand:hover{border-color:#80c0ff;background:#3a3a4a}',
        '.cand.selected{border-color:#2196f3;background:#1f3a5a;box-shadow:0 0 0 3px #2196f3}',
        '.cand img{max-width:100%;height:auto;border-radius:2px;max-height:220px}',
        '.cand .num{font-size:16px;color:#ffd700;font-weight:bold}',
        '.cand .pid{font-size:11px;color:#aaa;word-break:break-all;margin-top:4px}',
        '.cand.expected-pid{border-color:#9fffa0;background:#2c3c2c}',
        'h1{color:#ffd700}',
        '.toolbar{position:sticky;top:0;background:#1a1a1a;padding:10px;border-bottom:1px solid #444;z-index:100;display:flex;gap:14px;align-items:center}',
        '.toolbar #status{font-size:16px;color:#ffd700;font-weight:bold}',
        '.toolbar .btn-download{background:#ffd700;color:#000}',
        '.toolbar .btn-download:disabled{background:#666;color:#aaa;cursor:not-allowed}',
        '</style>',
        '<script>',
        f'var TARGETS = {targets_json};',
        'var ANSWERS = {};',
        '',
        'function answer(cert, choice) {',
        '  ANSWERS[cert] = {choice: choice};',
        '  var target = document.getElementById("target_" + cert);',
        '  target.className = "target answered-" + choice.toLowerCase();',
        '  document.querySelectorAll("#btns_" + cert + " .btn").forEach(b => b.classList.remove("active"));',
        '  document.getElementById("btn_" + cert + "_" + choice).classList.add("active");',
        '  if (choice === "NG") {',
        '    document.getElementById("cands_" + cert).classList.add("show");',
        '  }',
        '  updateStatus();',
        '}',
        '',
        'function selectCand(cert, pid) {',
        '  ANSWERS[cert] = {choice: "CHOSEN", selected_pid: pid};',
        '  var target = document.getElementById("target_" + cert);',
        '  target.className = "target answered-chosen";',
        '  document.querySelectorAll("#cands_" + cert + " .cand").forEach(c => c.classList.remove("selected"));',
        '  document.getElementById("cand_" + cert + "_" + pid.replace(/[^a-zA-Z0-9]/g, "_")).classList.add("selected");',
        '  document.querySelectorAll("#btns_" + cert + " .btn").forEach(b => b.classList.remove("active"));',
        '  updateStatus();',
        '}',
        '',
        'function toggleCands(cert) {',
        '  document.getElementById("cands_" + cert).classList.toggle("show");',
        '}',
        '',
        'function updateStatus() {',
        '  var done = Object.keys(ANSWERS).length;',
        '  var total = TARGETS.length;',
        '  document.getElementById("status").textContent = done + "/" + total + " 回答済";',
        '  document.getElementById("dl-btn").disabled = (done === 0);',
        '}',
        '',
        'function submitResults() {',
        '  var results = TARGETS.map(t => Object.assign({cert: t.cert, expected: t.expected, category: t.category}, ANSWERS[t.cert] || {choice: "PENDING"}));',
        '  document.getElementById("dl-btn").disabled = true;',
        '  document.getElementById("dl-btn").textContent = "送信中...";',
        '  fetch("/submit", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(results)})',
        '    .then(r => r.json())',
        '    .then(j => {',
        '      var msg = "✅ 完了: スプシ書込 " + j.spreadsheet_writes + " 件 / skip " + j.skipped + " 件";',
        '      if (j.errors && j.errors.length > 0) msg += " / errors " + j.errors.length;',
        '      document.getElementById("dl-btn").textContent = msg;',
        '      document.getElementById("dl-btn").style.background = "#4caf50";',
        '      document.getElementById("status").textContent = "✅ 完了、 ブラウザ閉じて OK (HQ チャット入力不要)";',
        '      localStorage.removeItem("psa_review_answers");',
        '      if (j.errors && j.errors.length > 0) {',
        '        alert("⚠️ errors:\\n" + j.errors.join("\\n"));',
        '      }',
        '    })',
        '    .catch(e => {',
        '      document.getElementById("dl-btn").disabled = false;',
        '      document.getElementById("dl-btn").textContent = "❌ 送信失敗、 再試行";',
        '      alert("送信失敗: " + e);',
        '    });',
        '}',
        '',
        '// load saved (= localStorage)',
        'window.addEventListener("DOMContentLoaded", function() {',
        '  var saved = localStorage.getItem("psa_review_answers");',
        '  if (saved) {',
        '    try { ANSWERS = JSON.parse(saved); } catch(e) {}',
        '  }',
        '  // restore UI',
        '  for (var cert in ANSWERS) {',
        '    var a = ANSWERS[cert];',
        '    if (a.choice === "CHOSEN" && a.selected_pid) {',
        '      var elId = "cand_" + cert + "_" + a.selected_pid.replace(/[^a-zA-Z0-9]/g, "_");',
        '      var el = document.getElementById(elId);',
        '      if (el) { el.classList.add("selected"); document.getElementById("target_" + cert).className = "target answered-chosen"; }',
        '    } else if (a.choice) {',
        '      var b = document.getElementById("btn_" + cert + "_" + a.choice);',
        '      if (b) { b.classList.add("active"); document.getElementById("target_" + cert).className = "target answered-" + a.choice.toLowerCase(); }',
        '    }',
        '  }',
        '  updateStatus();',
        '});',
        '',
        '// auto save',
        'setInterval(function() { localStorage.setItem("psa_review_answers", JSON.stringify(ANSWERS)); }, 2000);',
        '</script>',
        '</head><body>',
        '<div class=toolbar>',
        '  <span id=status>0/0 回答済</span>',
        '  <button id=dl-btn class="btn btn-download" onclick="submitResults()" disabled>✉️ HQ に送信</button>',
        '  <span style="color:#888;font-size:12px">click 完了後 「✉️ HQ に送信」 → 自動処理</span>',
        '</div>',
        f'<h1>PSA Review — latest cycle ({datetime.now().strftime("%Y-%m-%d %H:%M")})</h1>',
        f'<p>{len(targets)} 件確認要。 期待値画像 ↔ PSA cert 画像 を比較、 <b>✅合ってる / ❌違う / 該当なし</b> をクリック。 違う場合は候補から画像選択。</p>',
    ]

    for idx, t in enumerate(targets):
        cert = t["cert"]
        expected_img = _find_expected_image(t["category"], t.get("csv_expected"), brand=t.get("brand", ""))

        html.append(f'<div id="target_{cert}" class=target>')
        html.append(f'<h2>cert {cert} — {t["category"]}</h2>')
        html.append(f'<div class=cert-info><b>Brand:</b> {t["brand"]}</div>')
        html.append(f'<div class=cert-info><b>Subject:</b> {t["subject"]}</div>')

        # 「合ってる？」 確認部
        if t.get("csv_expected") and expected_img:
            html.append('<div class="confirm">')
            html.append('<div>')
            html.append('<div class=label>📋 PSA cert (実物)</div>')
            if t.get("cert_image_url"):
                html.append(f'<img src="{_img_url(t["cert_image_url"])}">')
            html.append('</div>')
            html.append('<div class=confirm-q>↔️<br>合ってる？</div>')
            html.append('<div>')
            html.append(f'<div class=label>📚 catalog: {t["csv_expected"]}</div>')
            html.append(f'<img src="{_img_url(expected_img)}">')
            html.append('</div>')
            html.append('</div>')
        else:
            html.append('<div class="confirm no-expected">')
            html.append(f'<div class=label>⚠️ catalog 期待値特定不能 ({t.get("csv_expected") or "未取得"}) → 候補から選択してください</div>')
            # 2026-06-11: no-expected 分岐でも PSA 実物画像を表示 (= 期待値不明時こそ実物↔候補の
            # 見比べが要る。旧版は実物画像を出さず「元画像すらない」状態だった)
            if t.get("cert_image_url"):
                html.append('<div>')
                html.append('<div class=label>📋 PSA cert (実物)</div>')
                html.append(f'<img src="{_img_url(t["cert_image_url"])}">')
                html.append('</div>')
            html.append('</div>')

        # 回答ボタン
        html.append(f'<div id="btns_{cert}" class=answer-btns>')
        if t.get("csv_expected") and expected_img:
            html.append(f'<button id="btn_{cert}_OK" class="btn btn-ok" onclick="answer(\'{cert}\', \'OK\')">✅ 合ってる</button>')
            html.append(f'<button id="btn_{cert}_NG" class="btn btn-ng" onclick="answer(\'{cert}\', \'NG\')">❌ 違う (候補から選択)</button>')
        html.append(f'<button id="btn_{cert}_NONE" class="btn btn-none" onclick="answer(\'{cert}\', \'NONE\')">該当なし</button>')
        html.append('</div>')

        # 候補 list
        is_open = not (t.get("csv_expected") and expected_img)
        html.append(f'<div class=candidates-toggle onclick="toggleCands(\'{cert}\')">▼ 候補 {len(t["candidates"])} 件 表示/非表示</div>')
        cls = "candidates show" if is_open else "candidates"
        html.append(f'<div id="cands_{cert}" class="{cls}">')
        html.append('<div class=grid>')
        import re as _re
        for i, (pid, img_path) in enumerate(t["candidates"], 1):
            css_class = "cand expected-pid" if pid == t.get("csv_expected") else "cand"
            safe_pid_id = _re.sub(r'[^a-zA-Z0-9]', '_', pid)
            html.append(f'<div id="cand_{cert}_{safe_pid_id}" class="{css_class}" onclick="selectCand(\'{cert}\', \'{pid}\')">')
            html.append(f'<div class=num>#{i}</div>')
            if img_path and (img_path.startswith("http") or Path(img_path).exists()):
                html.append(f'<img src="{_img_url(img_path)}">')
            else:
                html.append('<div style="padding:30px;color:#666">no image</div>')
            html.append(f'<div class=pid>{pid}</div></div>')
        html.append('</div></div>')
        html.append('</div>')

    html.append('</body></html>')
    HTML_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUTPUT.write_text('\n'.join(html), encoding="utf-8")


class _ReviewHandler(BaseHTTPRequestHandler):
    """HTML viewer 配信 + 画像 proxy + POST /submit で結果受信."""

    def do_GET(self):
        try:
            if self.path == "/" or self.path == "/index.html":
                # HTML 配信 (= 既存 _generate_html 出力の HTML、 ただし画像 src を /img/<encoded> に書換済)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(HTML_OUTPUT.read_bytes())
            elif self.path.startswith("/img/"):
                # /img/<urlencoded local path or http URL>
                encoded = self.path[len("/img/"):]
                src = urllib.parse.unquote(encoded)
                if src.startswith("http://") or src.startswith("https://"):
                    # 外部画像 = proxy
                    try:
                        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=10) as r:
                            data = r.read()
                            ctype = r.headers.get("Content-Type", "image/jpeg")
                    except Exception:
                        self.send_response(502)
                        self.end_headers()
                        return
                else:
                    # ローカルファイル
                    p = Path(src)
                    if not p.exists():
                        self.send_response(404)
                        self.end_headers()
                        return
                    data = p.read_bytes()
                    ext = p.suffix.lower()
                    ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}.get(ext.lstrip("."), "image/jpeg")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            try:
                self.wfile.write(f"error: {e}".encode("utf-8"))
            except Exception:
                pass

    def do_POST(self):
        try:
            if self.path == "/submit":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                RESULT_DIR.mkdir(parents=True, exist_ok=True)
                out = RESULT_DIR / f"psa_review_{ts}.json"
                out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                if _PRE_BUILD_MODE:
                    # verify→build: 結果を build 側に渡すだけ (CSV除外/スプシ書込は build 後に実施)。
                    global _PRE_BUILD_RESULTS
                    _PRE_BUILD_RESULTS = data
                    _record_verified(data)
                    # JS が参照する key を 0 で埋める (build 側で実処理するため此処では書込なし)
                    summary = {"mode": "pre_build", "count": len(data),
                               "spreadsheet_writes": 0, "skipped": 0}
                    _PRE_BUILD_EVENT.set()
                else:
                    # 従来 (build後 hook): catalog/スプシ書込 + NONE/NG 行除外 + verified 記録
                    summary = _apply_user_judgments(data)
                    _record_verified(data)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "saved": str(out),
                    "count": len(data),
                    **summary,
                }, ensure_ascii=False).encode("utf-8"))
                # server shutdown (= 別 thread で、 response 返した後)
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            try:
                self.wfile.write(f"error: {e}".encode("utf-8"))
            except Exception:
                pass

    def log_message(self, format, *args):
        pass  # access log suppress


_GSHEET_CREDS = r"C:/dev/iMak/double-hold-421922-7c0d38d3f73d.json"
_HIGH_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
_HIGH_GID = 851100680
_HIGH_KEY1_COL = 35  # AI 列


def _find_high_row_by_cert(ws, cert: str) -> int | None:
    """HIGH スプシで cert (= col 9 Title) 一致 row 検索. 見つからなければ None."""
    cert_col_values = ws.col_values(9)  # col I = Title (cert)
    for i, v in enumerate(cert_col_values, 1):
        if str(v).strip() == str(cert).strip():
            return i
    return None


def _load_verified_certs() -> dict:
    """ユーザー目視 verify 済 cert list 読込."""
    if VERIFIED_CERTS_FILE.exists():
        try:
            return json.loads(VERIFIED_CERTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_verified_certs(data: dict) -> None:
    VERIFIED_CERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERIFIED_CERTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_verified(results: list[dict]) -> None:
    """POST 受信結果を verified_certs.json に追記."""
    verified = _load_verified_certs()
    now = datetime.now().isoformat(timespec="seconds")
    for r in results:
        cert = r.get("cert", "")
        if not cert:
            continue
        choice = r.get("choice", "")
        # NONE/NG は「確認済」ではなく「catalog で解決すべき未解決」→ verified に入れない。
        # verified に入れると HTML viewer で二度と表示されず宿題が埋もれる。OK/CHOSEN のみ確定。
        if choice in ("OK", "CHOSEN"):
            pid = r.get("selected_pid") if choice == "CHOSEN" else r.get("expected")
            verified[cert] = {
                "verified_at": now,
                "choice": choice,
                "product_id": pid,
            }
    _save_verified_certs(verified)


# run_post_psa_review が受け取る「最終入稿 CSV」パス (= .bak ではなく実 CSV)。
# do_POST → _apply_user_judgments から NONE/NG 判定 cert の行除外に使う。
_CURRENT_CSV_PATH: "str | None" = None


def _remove_certs_from_csv(csv_path, certs_to_remove) -> int:
    """NONE/NG 判定 (= 識別不能) の cert 行を入稿 CSV から物理除外する.

    出品の正確性原則: 該当なし/違う = カード identity 未確定 → 出品しない (fail-closed)。
    Description が HTML で複数物理行に跨るため、行単位でなく「"Add", で始まる論理行」
    境界で分割し、cert 列 (CDA:Certification Number) が一致する論理行を丸ごと除外。
    残す行はバイト不変なのでフォーマット (QUOTE_NONNUMERIC 等) を保持する。
    Returns: 除外した行数。
    """
    if not csv_path or not certs_to_remove:
        return 0
    import io
    certs = {str(c).strip() for c in certs_to_remove if str(c).strip()}
    if not certs:
        return 0
    p = Path(csv_path)
    if not p.exists():
        return 0
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) < 2:
        return 0
    header_line = lines[0]
    try:
        header_fields = next(csv.reader([header_line]))
    except Exception:
        return 0
    cert_idx = next((i for i, h in enumerate(header_fields)
                     if "Certification Number" in h), None)
    if cert_idx is None:
        return 0
    ROW_START = '"Add",'  # 各論理行の先頭物理行 (= *Action 値 "Add")
    blocks = []
    cur = ""
    for ln in lines[1:]:
        if ln.startswith(ROW_START) and cur:
            blocks.append(cur)
            cur = ""
        cur += ln
    if cur:
        blocks.append(cur)
    kept = []
    removed = 0
    for block in blocks:
        try:
            fields = next(csv.reader(io.StringIO(block)))
            cval = fields[cert_idx].strip() if cert_idx < len(fields) else ""
        except Exception:
            cval = ""
        if cval and cval in certs:
            removed += 1
            continue
        kept.append(block)
    if removed:
        p.write_text(header_line + "".join(kept), encoding="utf-8")
    return removed


_MISSING_MODELS_PATH = Path("C:/dev/iMak_data/catalog/missing_models.csv")


def _route_none_to_catalog(none_records: list[dict], missing_path=None,
                           trigger_request: bool = True) -> int:
    """NONE/NG (= catalog 一致無し) cert を missing_models.csv に流し catalog 追加依頼を自動生成.

    NONE は『解決済』でなく『catalog で解決すべき宿題』。build_row の catalog-miss と同経路で
    auto_catalog_add_request watcher が依頼書を自動投入する。これにより HTML から消えても
    宿題は catalog 依頼として surface し続ける。
    Returns: missing_models.csv に書いた行数。
    """
    if not none_records:
        return 0
    path = Path(missing_path) if missing_path else _MISSING_MODELS_PATH
    written = 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not path.exists()
        with path.open("a", encoding="utf-8") as f:
            if new_file:
                f.write("category,model,detected_at\n")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for rec in none_records:
                cert = str(rec.get("cert", "")).strip()
                if not cert:
                    continue
                category = (rec.get("category") or "unknown").strip()
                expected = (rec.get("expected") or "無").strip()
                meta = _get_psa_cache(cert) or {}
                brand = (meta.get("Brand") or "").strip()
                subject = (meta.get("Subject") or "").strip()
                cardno = (meta.get("CardNumber") or "").strip()
                model = (f"cert{cert} {brand} [{subject}] #{cardno} "
                         f"(auto候補{expected}=該当なし 要調査)").replace(",", " ")
                model = " ".join(model.split())  # 連続空白圧縮
                f.write(f"{category},{model},{ts}\n")
                written += 1
    except Exception:
        return written
    # auto_catalog_add_request watcher を即実行 = 依頼書まで自動生成
    if trigger_request and written:
        try:
            import importlib.util as _ilu
            _wspec = _ilu.spec_from_file_location(
                "auto_catalog_add_request",
                str(Path(__file__).parent / "auto_catalog_add_request.py"))
            _wmod = _ilu.module_from_spec(_wspec)
            _wspec.loader.exec_module(_wmod)
            _wmod.main()
        except Exception:
            pass
    return written


def _apply_user_judgments(results: list[dict]) -> dict:
    """ユーザー判定結果を catalog + スプシに適用.

    Args:
        results: [{cert, expected, category, choice, selected_pid?}, ...]
    Returns:
        {processed, spreadsheet_writes, catalog_updates, skipped, csv_excluded, errors}
    OK/CHOSEN → KEY1 をスプシ書込。NONE/NG (= 識別不能) → 入稿 CSV から行除外 (fail-closed)。
    """
    summary = {"processed": 0, "spreadsheet_writes": 0, "catalog_updates": 0,
               "skipped": 0, "csv_excluded": 0, "catalog_routed": 0, "errors": []}
    reject_records = []
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(_GSHEET_CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(_HIGH_SHEET_ID)
        ws = sh.get_worksheet_by_id(_HIGH_GID)
    except Exception as e:
        summary["errors"].append(f"gspread init: {type(e).__name__}: {e}")
        return summary

    for r in results:
        cert = r.get("cert", "")
        choice = r.get("choice", "")
        # 採用 product_id 決定
        if choice == "OK":
            target_pid = r.get("expected", "")
        elif choice == "CHOSEN":
            target_pid = r.get("selected_pid", "")
        else:
            # NONE (該当なし) / NG (違う) = identity 未確定 → 入稿 CSV 除外 + catalog 宿題化
            if choice in ("NONE", "NG") and cert:
                reject_records.append(r)
            summary["skipped"] += 1
            continue
        if not target_pid:
            summary["skipped"] += 1
            continue
        # HIGH スプシ KEY1 書込
        try:
            row = _find_high_row_by_cert(ws, cert)
            if row:
                old = ws.cell(row, _HIGH_KEY1_COL).value
                ws.update_cell(row, _HIGH_KEY1_COL, target_pid)
                summary["spreadsheet_writes"] += 1
                summary["processed"] += 1
            else:
                summary["errors"].append(f"cert {cert}: HIGH row not found")
        except Exception as e:
            summary["errors"].append(f"cert {cert} spreadsheet write: {type(e).__name__}: {e}")
        # catalog hash 蓄積 (= optional、 PSA cache image hash → catalog variants 上書き)
        # 既存 5/28 logic 流用、 ただし簡略化のため本 phase では skip (= 別 phase で蓄積)

    # NONE/NG = 識別不能カード → (1) 入稿 CSV から物理除外 (2) catalog 追加依頼に自動ルーティング
    if reject_records:
        reject_certs = {str(r.get("cert", "")).strip() for r in reject_records if r.get("cert")}
        try:
            summary["csv_excluded"] = _remove_certs_from_csv(_CURRENT_CSV_PATH, reject_certs)
        except Exception as e:
            summary["errors"].append(f"csv exclude: {type(e).__name__}: {e}")
        try:
            summary["catalog_routed"] = _route_none_to_catalog(reject_records)
        except Exception as e:
            summary["errors"].append(f"catalog route: {type(e).__name__}: {e}")
    return summary


def _build_target_for_cert(cert: str):
    """cert (PSA cache 由来) から HTML viewer の target dict を作る。CSV 非依存。

    Returns: target dict / None (cache miss・category 不明・遊戯王 SKIP 時)。
    """
    meta = _get_psa_cache(cert)
    if not meta:
        return None
    brand = meta.get("Brand", "")
    subject = meta.get("Subject", "")
    card_number = meta.get("CardNumber", "")
    category = _detect_category(brand)
    if not category or category == "yugioh_tcg":
        return None
    set_code = _extract_set_code(brand, category)
    csv_expected = _catalog_lookup_expected(brand, subject, card_number, category)
    if not csv_expected and set_code and card_number:
        csv_expected = f"{set_code}-{card_number}"
    candidates = _get_candidates(category, set_code, card_number, brand=brand,
                                 expected_product_id=csv_expected, subject=subject)
    return {
        "cert": cert, "brand": brand, "subject": subject, "card_number": card_number,
        "category": category, "set_code": set_code, "csv_expected": csv_expected,
        "cert_image_url": meta.get("CardImageUrl", ""), "candidates": candidates,
    }


# verify→build フロー用: do_POST が結果を渡す Event + 受け皿 (pre-build モード時のみ使用)
_PRE_BUILD_MODE = False
_PRE_BUILD_EVENT = threading.Event()
_PRE_BUILD_RESULTS: "list | None" = None


def run_pre_build_verify(certs, append_log_func, *, open_browser=True, timeout_sec=1800) -> dict:
    """【verify→build】CSV 生成の **前** に HTML 目視確認を回し、確定 product_id を返す。

    certs: 対象 cert list (PSA cache に scrape 済前提)。
    Returns: {cert: 確定 product_id}。OK→expected / CHOSEN→選択pid。
             NONE/NG/PENDING/未確認 は **dict に含めない** (= build しない = fail-closed)。
    既に verified 済の cert は viewer に出さず確定値をそのまま採用。
    submit が来るまで blocking (timeout 時は確定分だけ返す)。
    """
    global _PRE_BUILD_MODE, _PRE_BUILD_RESULTS
    confirmed: dict = {}
    verified = _load_verified_certs()
    targets = []
    for cert in certs:
        cert = str(cert).strip()
        if not cert:
            continue
        if cert in verified and verified[cert].get("product_id"):
            confirmed[cert] = verified[cert]["product_id"]   # 過去確定をそのまま採用
            continue
        t = _build_target_for_cert(cert)
        if t is None:
            append_log_func(f"  ⚠️ cert {cert}: cache miss/category不明/対象外 → 目視対象外 (build skip)\n")
            continue
        targets.append(t)

    if not targets:
        append_log_func(f"  ✅ 目視確認要 cert なし (確定済 {len(confirmed)} 件)、viewer skip\n")
        return confirmed

    _generate_html(targets)
    append_log_func(f"  📄 HTML viewer 生成 (build前確認): {HTML_OUTPUT}\n")
    _PRE_BUILD_MODE = True
    _PRE_BUILD_RESULTS = None
    _PRE_BUILD_EVENT.clear()

    server = None
    base_url = None
    for p in range(SERVER_PORT, SERVER_PORT + 10):
        try:
            server, thread, base_url = _start_review_server(p)
            append_log_func(f"  🌐 review server 起動: {base_url}\n")
            break
        except OSError:
            continue
    if not server:
        append_log_func("  ⚠️ server 起動失敗 → build skip (確定 cert のみ)\n")
        _PRE_BUILD_MODE = False
        return confirmed

    if open_browser:
        try:
            import subprocess
            subprocess.run(["cmd", "/c", "start", "", base_url], check=False)
            append_log_func(f"  🌐 browser 自動 open: {base_url}\n")
        except Exception:
            pass
    append_log_func(f"\n  ⚠️ 目視確認要 {len(targets)} 件: browser で確認 → 「✉️ HQ に送信」 click\n")
    append_log_func("     確認後に **確定したカードだけ** CSV 生成されます (verify→build)\n")

    got = _PRE_BUILD_EVENT.wait(timeout=timeout_sec)
    _PRE_BUILD_MODE = False
    try:
        server.shutdown()
    except Exception:
        pass
    if not got or _PRE_BUILD_RESULTS is None:
        append_log_func("  ⚠️ 確認 timeout/未送信 → 確定済 cert のみ build (未確認は出品しない)\n")
        return confirmed

    none_records = []
    for r in _PRE_BUILD_RESULTS:
        cert = str(r.get("cert", "")).strip()
        choice = r.get("choice", "")
        if not cert:
            continue
        if choice == "OK":
            pid = (r.get("expected") or "").strip()
        elif choice == "CHOSEN":
            pid = (r.get("selected_pid") or "").strip()
        else:
            pid = ""   # NONE/NG/PENDING → build しない (fail-closed)
            if choice in ("NONE", "NG"):
                none_records.append(r)   # catalog 宿題化 (= 後段で追加依頼)
        if pid:
            confirmed[cert] = pid
    # NONE/NG = identity 未確定 → catalog 追加依頼に自動ルーティング (build後 hook と同経路)
    if none_records:
        try:
            routed = _route_none_to_catalog(none_records)
            append_log_func(f"  📨 NONE/NG {len(none_records)} 件 → catalog 宿題化 ({routed} 件記録)\n")
        except Exception as _e:
            append_log_func(f"  ⚠️ catalog route 失敗: {type(_e).__name__}: {_e}\n")
    append_log_func(f"  ✅ 目視確定: {len(confirmed)} 件を build へ (未確定は除外)\n")
    return confirmed


def _start_review_server(port: int = SERVER_PORT) -> tuple[HTTPServer, threading.Thread, str]:
    """http.server background 起動. (server, thread, base_url)."""
    server = HTTPServer(("127.0.0.1", port), _ReviewHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{port}/"


def run_post_psa_review(csv_path: str, append_log_func) -> None:
    """control_panel.py poll_queue から呼出される entry point."""
    append_log_func("\n======================================================================\n")
    append_log_func("▶ post_psa_review (全カテゴリ cert HTML viewer hook)\n")
    append_log_func("======================================================================\n")

    csv_p = Path(csv_path)
    if not csv_p.exists():
        append_log_func(f"  ⚠️ CSV not found: {csv_path}\n")
        return

    # NONE/NG 判定時の行除外は「最終入稿 CSV」(= bak 差替前) に対して行う
    global _CURRENT_CSV_PATH
    _CURRENT_CSV_PATH = str(csv_p)

    # .bak (= excluder 除外前の 元 CSV) があれば優先 (= NO-GO 除外件も教師データ判定対象に)
    bak = csv_p.with_suffix(".csv.bak")
    if bak.exists():
        append_log_func(f"  📋 .bak (= 除外前 元 CSV) 採用: {bak.name}\n")
        csv_p = bak

    # CSV 内 (cert, expected KEY 候補) 取得
    rows_info = []
    try:
        with open(csv_p, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cert = (row.get("CDA:Certification Number - (ID: 27503)") or "").strip()
                if not cert:
                    continue
                rows_info.append({
                    "cert": cert,
                    "title": (row.get("*Title") or "").strip(),
                    "csv_card_number": (row.get("C:Card Number") or "").strip(),
                    "csv_set": (row.get("C:Set") or "").strip(),
                })
    except Exception as e:
        append_log_func(f"  ⚠️ CSV parse 失敗: {type(e).__name__}: {e}\n")
        return

    append_log_func(f"  CSV cert 数: {len(rows_info)}\n")

    # ユーザー目視 verify 済 cert list (= 過去判定済を skip)
    verified_certs = _load_verified_certs()
    append_log_func(f"  verify 済 cert 累計: {len(verified_certs)}\n")

    # 各 cert を inspect
    targets = []
    skipped_verified = 0
    for info in rows_info:
        cert = info["cert"]
        # ユーザー目視 verify 済 cert は skip
        if cert in verified_certs:
            skipped_verified += 1
            continue
        meta = _get_psa_cache(cert)
        if not meta:
            append_log_func(f"  ⚠️ cert {cert}: cache miss、 skip\n")
            continue
        brand = meta.get("Brand", "")
        subject = meta.get("Subject", "")
        card_number = meta.get("CardNumber", "")
        category = _detect_category(brand)
        if not category:
            append_log_func(f"  ⚠️ cert {cert}: category 不明 (brand={brand[:30]})、 skip\n")
            continue
        # 2026-06-12: 遊戯王は現在 出品対象外 (ユーザー指示で当面 SKIP)。catalog 日本版未収録のため
        # review に出しても候補が英語版のみで選べない。準備が整ったら解除。psa_to_csv 側も build_row で SKIP 済。
        if category == "yugioh_tcg":
            append_log_func(f"  ⏭️ cert {cert}: 遊戯王は現在出品対象外、 skip\n")
            continue
        set_code = _extract_set_code(brand, category)
        # 期待値 = catalog lookup 経由 (= 信頼性 ↑、 brand 推定より確実)
        csv_expected = _catalog_lookup_expected(brand, subject, card_number, category)
        if not csv_expected and set_code and card_number:
            # fallback: brand 推定
            csv_expected = f"{set_code}-{card_number}"
        # 2026-05-31: 候補生成は expected_product_id 優先 (= Gemini 推奨 3 段階フォールバック)
        candidates = _get_candidates(
            category, set_code, card_number, brand=brand,
            expected_product_id=csv_expected, subject=subject,
        )
        targets.append({
            "cert": cert,
            "brand": brand,
            "subject": subject,
            "card_number": card_number,
            "category": category,
            "set_code": set_code,
            "csv_expected": csv_expected,
            "cert_image_url": meta.get("CardImageUrl", ""),
            "candidates": candidates,
        })

    append_log_func(f"  verify 済 skip: {skipped_verified} 件\n")

    if not targets:
        append_log_func("  ✅ 確認要 cert なし (= 全件 verify 済 or cache miss)、 HTML viewer skip\n")
        return

    append_log_func(f"  確認要 cert (= 未 verify): {len(targets)} 件\n")
    for t in targets:
        append_log_func(f"    - cert {t['cert']}  {t['category']}  set={t.get('set_code')}  expected={t.get('csv_expected')}  候補 {len(t['candidates'])} 件\n")

    _generate_html(targets)
    append_log_func(f"  📄 HTML viewer 生成: {HTML_OUTPUT}\n")

    # http.server 起動 (= 既存 port 占有時は +1 して retry)
    server = None
    base_url = None
    for p in range(SERVER_PORT, SERVER_PORT + 10):
        try:
            server, thread, base_url = _start_review_server(p)
            append_log_func(f"  🌐 review server 起動: {base_url}\n")
            break
        except OSError:
            continue
    if not server:
        append_log_func(f"  ⚠️ server 起動失敗 (port {SERVER_PORT}-{SERVER_PORT+9} 全占有)、 手動で {HTML_OUTPUT} を開いてください\n")
        return

    # browser auto open
    try:
        import subprocess
        subprocess.run(["cmd", "/c", "start", "", base_url], check=False)
        append_log_func(f"  🌐 browser 自動 open: {base_url}\n")
    except Exception as e:
        append_log_func(f"  ⚠️ browser open 失敗: {e}、 手動で {base_url} を開いてください\n")

    append_log_func("\n  ⚠️ ユーザー判定要: browser で 各 cert を確認 → 「✉️ HQ に送信」 click\n")
    append_log_func(f"     結果 JSON 保存先: {RESULT_DIR}/\n")
    append_log_func("     送信後 server 自動停止、 HQ チャットで「送信完了」 と伝えてください (= HQ が catalog/スプシ書込)\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python post_psa_review.py <csv_path>")
        sys.exit(1)
    run_post_psa_review(sys.argv[1], print)
