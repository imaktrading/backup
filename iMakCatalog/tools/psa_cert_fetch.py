"""PSA の cert ページを取って、券面の値とスラブ写真の URL を出す.

なぜ catalog に置くか: 1丁目1番地の判定 (①カタログのデータは正しいか) を
**現物で**確かめるのに要るから。公式カードリストに無いカードは、券面の印字
(番号 / レアリティ / 名前) が唯一の一次情報になる (CLAUDE.md「公式カードリストに
無いカードを登録してよいか」)。2026-08 に 5枚をこれで確定した
(ST21-001_p2 / OP12-079_AN03 / OP07-118_AN03 / ST15-005_AN03 / EB02-003_CH01)。

★PSA は Cloudflare で普通の HTTP を弾く (curl も WebFetch も 403)。実ブラウザで開く。
★headless も弾かれる。**画面が出る**ので、走らせる時はそれを承知で。
★undetected_chromedriver の version は固定しない (グローバル規約)。

使い方:
    python tools/psa_cert_fetch.py 152977069
    python tools/psa_cert_fetch.py 152977069 --out C:/tmp/cert.txt   # 全文も保存
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import time

FIELDS = ("Cert Number", "Item Grade", "Label Type", "Year", "Brand/Title",
          "Subject", "Card Number", "Variety", "Category")


def chrome_major() -> int | None:
    """実機の Chrome の major version (取れなければ None = uc の自動検出に任せる)."""
    for hive in ("HKCU", "HKLM"):
        try:
            out = subprocess.run(
                ["reg", "query", rf"{hive}\Software\Google\Chrome\BLBeacon", "/v", "version"],
                capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"(\d+)\.\d+\.\d+\.\d+", out)
            if m:
                return int(m.group(1))
        except Exception:
            pass
    return None


def fetch(cert: str, wait: int = 9) -> tuple[str, list[str]]:
    import undetected_chromedriver as uc  # 遅い import なので関数内
    d = uc.Chrome(options=uc.ChromeOptions(), version_main=chrome_major())
    try:
        d.get(f"https://www.psacard.com/cert/{cert}")
        time.sleep(wait)
        text = d.find_element("tag name", "body").text
        imgs = [e.get_attribute("src") for e in d.find_elements("tag name", "img")]
        return text, [u for u in imgs if u and "cloudfront" in u]
    finally:
        try:
            d.quit()
        except Exception:
            pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cert")
    p.add_argument("--out", help="ページ全文の保存先 (任意)")
    p.add_argument("--wait", type=int, default=9)
    a = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    text, imgs = fetch(a.cert, a.wait)
    if "Ray ID" in text and "Cert Number" not in text:
        print("✗ Cloudflare に止められた (headless か、開くのが速すぎた)。--wait を伸ばす")
        sys.exit(1)
    for k in FIELDS:
        m = re.search(rf"^{re.escape(k)}\n(.+)$", text, re.M)
        print(f"  {k:12s}: {m.group(1) if m else '-'}")
    # /small/ は一覧用のサムネ。券面の印字を読むなら /large/
    print("  slab        :", (imgs[0].replace("/small/", "/large/") if imgs else "(写真なし)"))
    if a.out:
        io.open(a.out, "w", encoding="utf-8").write(text)
        print(f"  (全文 {a.out})")


if __name__ == "__main__":
    main()
