"""出品くん psa_to_csv 後 hook: DON cert 検出 → HTML viewer 自動生成 + browser open.

設計 (= 5/28 ユーザー提案、 Gemini 第 10-11 弾承認):
- 出品くん cycle 後、 CSV 内 cert list 取得
- 各 cert の iMakeBayAPI cache から brand/subject 確認
- DON cert (= subject に "DON" 含む) 抽出
- catalog 候補絞込 (= brand から set_code 推定、 該当 DON-{set_code}-* + general fallback)
- HTML viewer 自動生成 (= 候補画像 grid + 番号付き)
- browser 自動 open
- ユーザー番号回答後、 HQ が ad-hoc gspread + catalog 投入

呼出 source: control_panel.py poll_queue 内 Step 5 (= excluder/dedupe 後)
"""
import os
import sys
import csv
import json
from pathlib import Path
from datetime import datetime

PSA_CACHE_DIR = Path(r"C:/dev/iMak/iMakeBayAPI/cache/psa_certs")
DON_IMAGES_DIR = Path(r"C:/dev/iMak_data/catalog/_don_images")
CATALOG_DB = Path(r"C:/dev/iMak_data/catalog/products.sqlite")
HTML_OUTPUT = Path(r"C:/dev/iMak_data/dedupe/don_review_latest.html")


def _extract_set_code_from_brand(brand: str) -> str | None:
    """brand から set_code (= OP15 / ST13 / EB04 / PRB01 等) 抽出. None = PROMOS 等 不明."""
    import re
    m = re.search(r"\b(OP\d+|ST\d+|EB\d+|PRB\d+|RP|EVENT|PROMOS|STORAGE|KUMAMON|GRAND-ASIA|ANNIV)\b", brand.upper())
    return m.group(1) if m else None


def _get_don_candidates(set_code: str | None) -> list[tuple[str, str]]:
    """catalog から DON candidate (= product_id, image_path) 取得."""
    import sqlite3
    conn = sqlite3.connect(str(CATALOG_DB))
    cur = conn.cursor()
    if set_code and set_code != "PROMOS":
        # 該当 set_code のみ
        cur.execute(
            "SELECT product_id FROM products WHERE category='one_piece_tcg' AND product_id LIKE ? ORDER BY product_id",
            (f"DON-{set_code}-%",)
        )
        results = cur.fetchall()
        if results:
            conn.close()
            return [(r[0], str(DON_IMAGES_DIR / f"{r[0]}.png")) for r in results]
    # PROMOS or 不明 = 全 DON
    cur.execute(
        "SELECT product_id FROM products WHERE category='one_piece_tcg' AND product_id LIKE 'DON-%' ORDER BY product_id"
    )
    results = cur.fetchall()
    conn.close()
    return [(r[0], str(DON_IMAGES_DIR / f"{r[0]}.png")) for r in results]


def _get_psa_cache(cert: str) -> dict | None:
    """iMakeBayAPI cache から cert metadata 取得."""
    f = PSA_CACHE_DIR / f"{cert}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _generate_html(don_targets: list[dict]) -> None:
    """DON cert × catalog 候補 を HTML viewer に出力.

    don_targets: list of {'cert', 'brand', 'subject', 'cert_image_url', 'candidates'}
    """
    html = [
        '<!DOCTYPE html><html><head><meta charset=utf-8><title>DON Review (latest cycle)</title>',
        '<style>body{font-family:sans-serif;margin:10px;background:#1a1a1a;color:#fff}',
        '.target{border:2px solid #ffd700;padding:12px;margin:12px 0;background:#2a2a2a;border-radius:6px}',
        '.target h2{color:#ffd700;margin:0 0 8px}',
        '.cert-info{font-size:13px;color:#ccc;margin:4px 0}',
        '.cert-image{max-width:300px;border:1px solid #444}',
        '.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:12px}',
        '.cand{border:1px solid #555;padding:6px;background:#333;text-align:center;border-radius:4px}',
        '.cand img{max-width:100%;height:auto;border-radius:2px}',
        '.cand .num{font-size:16px;color:#ffd700;font-weight:bold}',
        '.cand .pid{font-size:10px;color:#888;word-break:break-all;margin-top:4px}',
        'h1{color:#ffd700}',
        '</style></head><body>',
        f'<h1>DON Review — latest cycle ({datetime.now().strftime("%Y-%m-%d %H:%M")})</h1>',
        f'<p>{len(don_targets)} 件 DON cert 検出、 各 cert の候補を画像比較で番号回答してください。</p>',
    ]
    for t in don_targets:
        html.append('<div class=target>')
        html.append(f'<h2>cert {t["cert"]}</h2>')
        html.append(f'<div class=cert-info><b>Brand:</b> {t["brand"]}</div>')
        html.append(f'<div class=cert-info><b>Subject:</b> {t["subject"]}</div>')
        if t.get("cert_image_url"):
            html.append(f'<div><img class=cert-image src="{t["cert_image_url"]}"></div>')
        html.append(f'<div class=cert-info><b>候補 {len(t["candidates"])} 件:</b></div>')
        html.append('<div class=grid>')
        for i, (pid, img_path) in enumerate(t["candidates"], 1):
            html.append('<div class=cand>')
            html.append(f'<div class=num>#{i}</div>')
            if Path(img_path).exists():
                html.append(f'<img src="file:///{img_path}">')
            else:
                html.append('<div style="padding:30px;color:#666">no image</div>')
            html.append(f'<div class=pid>{pid}</div></div>')
        html.append('</div></div>')
    html.append('</body></html>')

    HTML_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUTPUT.write_text('\n'.join(html), encoding="utf-8")


def run_post_psa_don_check(csv_path: str, append_log_func) -> None:
    """control_panel.py poll_queue から呼出される entry point.

    Args:
        csv_path: 最新 psa CSV path
        append_log_func: log 出力関数 (= self.append_log)
    """
    append_log_func("\n======================================================================\n")
    append_log_func("▶ post_psa_don_check (DON cert HTML viewer hook)\n")
    append_log_func("======================================================================\n")

    csv_p = Path(csv_path)
    if not csv_p.exists():
        append_log_func(f"  ⚠️ CSV not found: {csv_path}\n")
        return

    # CSV 内 cert list 取得 (= CDA: Certification Number 列)
    certs = []
    try:
        with open(csv_p, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cert = (row.get("CDA:Certification Number - (ID: 27503)") or "").strip()
                if cert:
                    certs.append(cert)
    except Exception as e:
        append_log_func(f"  ⚠️ CSV parse 失敗: {type(e).__name__}: {e}\n")
        return

    append_log_func(f"  CSV cert 数: {len(certs)}\n")

    # 各 cert の cache 確認 + DON 抽出
    don_targets = []
    for cert in certs:
        meta = _get_psa_cache(cert)
        if not meta:
            continue
        subj = (meta.get("Subject") or "").upper()
        brand = (meta.get("Brand") or "").upper()
        if "DON" in subj and "ONE PIECE" in brand:
            set_code = _extract_set_code_from_brand(brand)
            candidates = _get_don_candidates(set_code)
            don_targets.append({
                "cert": cert,
                "brand": meta.get("Brand", ""),
                "subject": meta.get("Subject", ""),
                "cert_image_url": meta.get("CardImageUrl", ""),
                "set_code": set_code,
                "candidates": candidates,
            })

    if not don_targets:
        append_log_func("  ✅ DON cert 検出ゼロ、 HTML viewer skip\n")
        return

    append_log_func(f"  DON cert 検出: {len(don_targets)} 件\n")
    for t in don_targets:
        append_log_func(f"    - cert {t['cert']}  brand={t['brand'][:50]}  候補 {len(t['candidates'])} 件\n")

    # HTML 生成 + browser open
    _generate_html(don_targets)
    append_log_func(f"  📄 HTML viewer 生成: {HTML_OUTPUT}\n")

    try:
        import subprocess
        subprocess.run(["cmd", "/c", "start", "", str(HTML_OUTPUT)], check=False)
        append_log_func("  🌐 browser 自動 open\n")
    except Exception as e:
        append_log_func(f"  ⚠️ browser open 失敗: {e}\n")
        append_log_func(f"     手動で開いてください: {HTML_OUTPUT}\n")

    append_log_func("\n  ⚠️ ユーザー判定要: 各 cert に該当する番号を HQ に回答してください\n")
    append_log_func("     例: 「cert 156219827 = #15 (DON-OP15-001)」\n")


if __name__ == "__main__":
    # standalone test
    if len(sys.argv) < 2:
        print("usage: python post_psa_don_check.py <csv_path>")
        sys.exit(1)
    run_post_psa_don_check(sys.argv[1], print)
