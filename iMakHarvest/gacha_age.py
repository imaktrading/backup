"""gacha_age - バンダイ品の 対象年齢 を公式 (gashapon.jp) で確認する.

2026-08-20 新設。 CPSIA (米) の規制対象は **12歳以下向けの玩具**。 13歳以上向けなら
児童製品から外れる。 出品は一番くじと同じく `C:Age Level = "15+"` を入れる運用なので、
**15才未満と分かった物はここで落とす** (HQ 依頼 2026-08-20)。

対象年齢が公式で取れるのは **バンダイだけ** (実測: タカラトミーアーツ公式は載せていない、
楽天の商品ページも 14件中0件)。 バンダイは **JAN 直引き**できる:

    https://gashapon.jp/products/detail.php?jan_code=<JAN>000

読めなければ `None` (= 不明) を返し、 **落とさない**。 不明分は出品時に画像で目視する
(HQ と分担合意済)。 「読めない」と「15才未満」を混同しない。
"""
from __future__ import annotations

import re
import urllib.request

GASHAPON_URL = "https://gashapon.jp/products/detail.php?jan_code={jan}000"
MIN_AGE = 15          # これ未満と**分かった**物は入れない
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_AGE_RE = re.compile(r"対象年齢\s*(\d{1,2})\s*(?:才|歳)")


def parse_age(html: str) -> int | None:
    """gashapon の商品ページ HTML から 対象年齢 (才) を返す. 無ければ None.

    「対象年齢」と数字の間にタグが入るので **タグを剥がしてから**見る。
    """
    text = re.sub(r"<[^>]+>", " ", html or "")
    m = _AGE_RE.search(re.sub(r"\s+", " ", text))
    return int(m.group(1)) if m else None


def fetch_age(jan: str, timeout: int = 15) -> int | None:
    """JAN から 対象年齢 を引く. 引けなければ None (通信失敗も None)."""
    jan = (jan or "").strip()
    if not jan.isdigit():
        return None
    try:
        req = urllib.request.Request(GASHAPON_URL.format(jan=jan), headers=UA)
        html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001 - 引けない = 不明 (落とさない)
        return None
    return parse_age(html)


def is_too_young(age: int | None) -> bool:
    """**15才未満と分かった** 時だけ True. 不明 (None) は False = 落とさない."""
    return age is not None and age < MIN_AGE
