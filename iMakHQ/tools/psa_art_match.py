#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""現物PSA画像 × 仕入候補画像 を突き合わせて「同じ絵柄か」を先に判定する (2026-08-02)。

■ なぜ要るか
PSA の印字ラベルは**同じカードでも書式が複数ある**。実物2枚で確認:
    cert 97317368  "2024 ONE PIECE JPN."    / 3行目 "OP09-ALTERNATE ART"
    cert 165347848 "2024 ONE PIECE OP09 JP" / 3行目 "ALTERNATE ART"
  (どちらも OP09-050 ナミ ALTERNATE ART・絵柄も完全一致)
ユーザー報告: 「画像は酷似していてラベルが違えば、違うカードと目視で判別してしまう」
= 同一カードを「違う」と押して**使える仕入元を捨てる**。
逆に、同番号でも配布が違えば別カード (ブースター版パラレル vs 始めようキャンペーン版) で、
こちらは絵柄が本当に違う。実測で両方向とも判別できた。

■ 方針 (ユーザー指示 2026-08-02)
  「明らかに違うとわかったものは省いてね。自信が無いものは出して目視で落とすけど。」
  → different(明らかに別) だけ省く。same / unsure は**全部出す**。最終判断は人。
  判定不能(API失敗・キー無し・画像取得失敗)は **unsure** に倒す。
  [[failclosed_must_skip_not_destructive]] — 判定できないことを理由に捨てない。
  省いた分は件数と内訳を必ず表に出す (silent drop 禁止)。

■ 精度の前提
メルカリ/スニダンの出品写真は角度・光の反射・トリミング・スリーブ越しが入り、公式スキャンより
条件が悪い。だから「同じ」判定は**採用の根拠にしない**(出すだけ)。効かせるのは
「明らかに別の絵柄」の除外だけ = 誤って捨てるリスクを最小にする非対称な使い方。
"""
import base64
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 全 TCG スクリプト共通の SSOT を再利用 (モデル変更は iMakTCG/card_identifier.py 側1箇所)
_TCG_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "iMakTCG"))
_KEY_FILE = os.path.join(_TCG_DIR, "API key.txt")
MODEL = "claude-sonnet-4-6"
CACHE_PATH = r"C:/dev/iMak_data/dedupe/psa_art_match_cache.json"

VERDICTS = ("same", "different", "unsure")

_PROMPT = (
    "2枚のPSA鑑定済みTCGカード画像を比べる。1枚目=現物(自分の出品)、2枚目=仕入候補。\n"
    "**カードの絵柄(イラスト)そのもの**が同じ商品かを判定せよ。\n"
    "\n"
    "重要:\n"
    "- PSAラベルの印字書式(行の並び / 'JPN.' と 'OP09 JP' の違い / セットコードが1行目か3行目か)は\n"
    "  **同じカードでも変わる**。ラベルの書き方の違いを『別カード』の根拠にしてはいけない。\n"
    "- 判定はイラストの構図・登場人物・背景・カード番号で行う。\n"
    "- 仕入候補は個人の出品写真なので、角度・光の反射・スリーブ・トリミングで見え方が変わる。\n"
    "  撮影条件の違いは『別カード』の根拠にならない。\n"
    "- 構図や登場人物が明らかに違う場合だけ different。\n"
    "- 少しでも迷ったら unsure。unsure は人が目視するので、無理に same/different を選ばない。\n"
    "\n"
    'JSONのみ出力: {"verdict":"same|different|unsure","reason":"40字以内の日本語"}'
)


def _load_key():
    try:
        with open(_KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _cache_key(ref_url, cand_url):
    return hashlib.sha1(f"{ref_url}|{cand_url}".encode("utf-8")).hexdigest()[:20]


def load_cache(path=CACHE_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache, path=CACHE_PATH):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def parse_verdict(text):
    """モデル出力 → {"verdict", "reason"} (純関数・test可)。

    未知の値・壊れた JSON は **unsure** に倒す (捨てる方向に倒さない)。
    """
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        d = json.loads(s)
    except Exception:
        return {"verdict": "unsure", "reason": "判定結果を読めなかった"}
    v = str(d.get("verdict", "")).strip().lower()
    if v not in VERDICTS:
        return {"verdict": "unsure", "reason": "判定値が不正"}
    return {"verdict": v, "reason": str(d.get("reason", ""))[:60]}


def _image_block(url, fetch):
    data, ctype = fetch(url)
    if not data:
        return None
    mt = (ctype or "").split(";")[0].strip().lower()
    if mt not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        mt = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return {"type": "image",
            "source": {"type": "base64", "media_type": mt,
                       "data": base64.b64encode(data).decode()}}


def compare_art(ref_url, cand_url, *, client=None, fetch=None, cache=None, api_key=None):
    """現物 vs 候補 の絵柄一致を判定 → {"verdict","reason","cached"}。

    判定できない事情 (キー無 / 画像取れない / API失敗) は全て **unsure**。
    client/fetch/cache を注入できる = ネットワーク無しでテスト可能。
    """
    out_unsure = {"verdict": "unsure", "reason": "判定不能(目視で確認)", "cached": False}
    if not ref_url or not cand_url:
        return out_unsure
    ck = _cache_key(ref_url, cand_url)
    if cache is not None and ck in cache:
        hit = dict(cache[ck])
        hit["cached"] = True
        return hit

    if fetch is None:
        import psa_resource_confirm as prc

        def fetch(u):
            return prc._fetch_image(prc._resolve_image_url(u))

    if client is None:
        key = api_key or _load_key()
        if not key:
            return out_unsure
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
        except Exception:
            return out_unsure

    blocks = []
    for u in (ref_url, cand_url):
        b = _image_block(u, fetch)
        if b is None:
            return out_unsure
        blocks.append(b)
    try:
        r = client.messages.create(
            model=MODEL, max_tokens=200,
            messages=[{"role": "user",
                       "content": blocks + [{"type": "text", "text": _PROMPT}]}])
        res = parse_verdict(r.content[0].text)
    except Exception as e:
        return {"verdict": "unsure", "reason": f"判定失敗({type(e).__name__})", "cached": False}
    if cache is not None:
        cache[ck] = dict(res)
    res["cached"] = False
    return res


def annotate_candidates(ref_url, cands, *, client=None, fetch=None, cache=None, api_key=None,
                        image_of=None):
    """候補リストに art 判定を付ける → (残す候補, 省いた候補)。

    - different = **明らかに別の絵柄** → 省く (ユーザー指示 2026-08-02)
    - same / unsure = 残して人が見る。unsure は「自信が無い」= 目視で落とす前提
    元の順序は保つ (呼出側の「確証済を先頭」等の並びを壊さない)。
    """
    image_of = image_of or (lambda c: c.get("image") or c.get("url") or "")
    keep, dropped = [], []
    for c in cands or []:
        res = compare_art(ref_url, image_of(c), client=client, fetch=fetch,
                          cache=cache, api_key=api_key)
        c = dict(c)
        c["art"] = res["verdict"]
        c["art_reason"] = res.get("reason", "")
        (dropped if res["verdict"] == "different" else keep).append(c)
    return keep, dropped
