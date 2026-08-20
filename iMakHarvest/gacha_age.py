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
GASHAPON_JAN_URL = "https://gashapon.jp/products/detail.php?jan_code={code}"
GASHAPON_LIST_URL = "https://gashapon.jp/products/"      # 最新約500件 (名前 + jan_code)
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


# ---------------------------------------------------------------------------
# JAN が取れない店 (実測: jugem2020) 向け — 公式カタログの商品名で引く
# ---------------------------------------------------------------------------
# `gashapon.jp/products/` は **最新約500件**を 名前 + jan_code 付きで返す
# (`?keyword=` は効かない。 実測: どの語でも同じ500件)。 なので **一覧を落として
# 商品名で突き合わせる**。 一致は「公式の商品名 (正規化6文字以上) が 楽天タイトルに
# そのまま含まれる」時だけ = 部分一致の緩い判定はしない (別商品の年齢を貼らないため)。
# 実測 2026-08-20: jugem2020 のバンダイ品 25件中 19件が一致。
_NAME_LINK_RE = re.compile(
    r'detail\.php\?jan_code=(\d+)"[^>]*>(?:\s*<[^>]+>)*\s*([^<]{4,60})')
_TRIM_RE = re.compile(r"[\s・~〜\-−–—_/･,.。、！!？?＆&()（）\[\]【】「」『』:：;；'\"”“]+")
_catalog_cache: list[tuple[str, str, str]] | None = None


def normalize_name(s: str) -> str:
    """突合用に正規化 (全角英数 -> 半角、 記号と空白を落として小文字)."""
    s = (s or "").translate({c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)})
    return _TRIM_RE.sub("", s).lower()


def fetch_catalog(timeout: int = 25) -> list[tuple[str, str, str]]:
    """公式の最新一覧を [(正規化名, jan_code, 表示名)] で返す (プロセス内キャッシュ)."""
    global _catalog_cache  # noqa: PLW0603
    if _catalog_cache is not None:
        return _catalog_cache
    try:
        req = urllib.request.Request(GASHAPON_LIST_URL, headers=UA)
        html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        _catalog_cache = []
        return _catalog_cache
    out = []
    for code, name in _NAME_LINK_RE.findall(html):
        n = normalize_name(name)
        if len(n) >= 6:
            out.append((n, code, name.strip()))
    _catalog_cache = out
    return out


def find_by_title(title: str) -> str:
    """楽天タイトルから 公式の jan_code を引く. 当たらなければ空文字."""
    t = normalize_name(title)
    if not t:
        return ""
    best = ""
    for n, code, _ in fetch_catalog():
        if n in t and len(n) > len(best):
            best, best_code = n, code
    return best_code if best else ""


def fetch_age_by_title(title: str, timeout: int = 15) -> int | None:
    """JAN が無い時に 商品名で 対象年齢 を引く. 当たらなければ None."""
    code = find_by_title(title)
    if not code:
        return None
    try:
        req = urllib.request.Request(GASHAPON_JAN_URL.format(code=code), headers=UA)
        html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return None
    return parse_age(html)


def is_too_young(age: int | None) -> bool:
    """**15才未満と分かった** 時だけ True. 不明 (None) は False = 落とさない."""
    return age is not None and age < MIN_AGE
