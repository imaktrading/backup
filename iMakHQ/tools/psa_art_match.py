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

_PROMPT_HEAD = (
    "PSA鑑定済みTCGカードの画像を比べる。最初の1枚=現物(自分の出品)、残り=仕入候補(同一商品の別写真)。\n"
    "**同じカードか**を3つの軸で判定せよ。\n"
    "\n"
    "軸① art  = イラスト(絵柄)が同じか。構図・登場人物・ポーズ・背景で見る。\n"
    "軸② variant = 変種/加工が同じか。パラレル(箔・ホログラム)、通常、SP、ゴールド等。\n"
    "         写真の光り方・箔の反射・枠の加工、および出品タイトルの表記で見る。\n"
    "軸③ dist = 配布(どのセットで出たか)が同じか。ブースター / プロモ / キャンペーン配布 等。\n"
    "         PSAラベルのセット名、および出品タイトルのセット名で見る。\n"
    "\n"
    "重要:\n"
    "- PSAラベルの印字書式(行の並び / 'JPN.' と 'OP09 JP' の違い / セットコードが1行目か3行目か)は\n"
    "  **同じカードでも変わる**。ラベルの書き方の違いを『別カード』の根拠にしてはいけない。\n"
    "  違うのは**セット名の中身**であって、書式ではない。\n"
    "- 仕入候補は個人の出品写真なので、角度・光の反射・スリーブ・トリミングで見え方が変わる。\n"
    "  撮影条件の違いは『別カード』の根拠にならない。\n"
    "- 各軸は same / different / unknown の3値。**判断材料が写っていない・書かれていない場合は\n"
    "  必ず unknown**。unknown は人が目視するので、無理に same/different を選ばない。\n"
    "- 絵柄が同じでも配布が違えば別カード(例: ブースター版 と キャンペーン配布版)。\n"
    "\n"
    "match_pct = **同じカードである**確からしさ(0-100の整数)。3軸を総合して出す。\n"
    "画質が悪い・一部しか見えないなら正直に下げる。100 は『間違いなく同一』の時だけ。\n"
    "\n"
    "JSONのみ出力:\n"
    '{"verdict":"same|different|unsure","match_pct":0-100,\n'
    ' "art":"same|different|unknown","art_reason":"30字以内",\n'
    ' "variant":"same|different|unknown","variant_reason":"30字以内",\n'
    ' "dist":"same|different|unknown","dist_reason":"30字以内",\n'
    ' "reason":"40字以内。総合判断の決め手"}\n'
)


def build_prompt(ref_facts=None, cand_title=""):
    """照合の手がかり(現物の確定情報 + 候補の出品タイトル)を付けた質問文を作る (純関数)。

    現物側は catalog / PSA から取れた**確定値**なので、モデルに推測させず与える。
    候補側は出品タイトル = 他人が書いた自由文なので「参考」と明示して渡す
    (書いていないことを『無い』と解釈させない = unknown に倒させる)。
    """
    f = ref_facts or {}
    lines = [_PROMPT_HEAD]
    known = [(k, f.get(v)) for k, v in
             (("カード番号", "number"), ("変種", "variety"),
              ("PSA登録セット", "brand"), ("公式セット名", "set_name"))]
    known = [(k, str(v).strip()) for k, v in known if str(v or "").strip()]
    if known:
        lines.append("\n【現物の確定情報(catalog/PSA由来・これが正)】\n"
                     + "\n".join(f"  {k}: {v}" for k, v in known))
    if (cand_title or "").strip():
        lines.append("\n【候補の出品タイトル(他人が書いた自由文・参考)】\n  "
                     + str(cand_title).strip()[:120]
                     + "\n  ※書かれていない情報を『無い』と解釈しないこと。不明なら unknown。")
    return "".join(lines)


def _load_key():
    try:
        with open(_KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


# 質問や返す項目を変えたら上げる。古い判定は自動で無効になり、次回に取り直される
# (混在すると「一致度—」と「一致度93%」が並んで読めなくなる)。
PROMPT_VERSION = 3


def _cache_key(ref_url, cand_url, cand_title="", version=None):
    v = PROMPT_VERSION if version is None else version
    payload = (f"v{v}|{ref_url}|{cand_url}" if v < 3
               else f"v{v}|{ref_url}|{cand_url}|{cand_title}")
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


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


def _pct(v):
    """match_pct を 0-100 の int に正規化。数値でなければ None (= 表示しない)。"""
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


AXES = ("art", "variant", "dist")
AXIS_VALUES = ("same", "different", "unknown")


def _axis(d, name):
    """軸の値を正規化。未知・欠落は unknown (= 人が見る)。"""
    v = str(d.get(name, "")).strip().lower()
    return v if v in AXIS_VALUES else "unknown"


def _blank(verdict, reason):
    out = {"verdict": verdict, "match_pct": None, "reason": reason}
    for a in AXES:
        out[a] = "unknown"
        out[a + "_reason"] = ""
    return out


def parse_verdict(text):
    """モデル出力 → {"verdict","match_pct","reason", 各軸 same/different/unknown} (純関数)。

    未知の値・壊れた JSON は **unsure / 全軸 unknown** に倒す (捨てる方向に倒さない)。
    match_pct が無い/不正なら None = UI は「%不明」として出す (0% と混同させない)。
    """
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        d = json.loads(s)
    except Exception:
        return _blank("unsure", "判定結果を読めなかった")
    v = str(d.get("verdict", "")).strip().lower()
    if v not in VERDICTS:
        return _blank("unsure", "判定値が不正")
    out = {"verdict": v, "match_pct": _pct(d.get("match_pct")),
           "reason": str(d.get("reason", ""))[:60]}
    for a in AXES:
        out[a] = _axis(d, a)
        out[a + "_reason"] = str(d.get(a + "_reason", ""))[:40]
    return out


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


def extra_photo_urls(cand_url, n=2):
    """候補の**追加写真**URL を作る (mercari の item は _1.._N が連番で存在する)。

    ★1枚だけだと箔の光り方やラベルが写っていないことが多く、変種/配布が unknown に倒れる。
    2枚目(多くは裏面・ラベル寄り)まで見ると判別材料が増える = 「拡大してよく見る」の自動化。
    取れなければ黙って無視する (存在しない写真は fetch 失敗 → skip)。
    """
    import re as _re
    m = _re.search(r"/photos/(m\d{9,})_1\.jpg", cand_url or "")
    if not m:
        return []
    base = cand_url[: m.start()] + f"/photos/{m.group(1)}_"
    return [f"{base}{i}.jpg" for i in range(2, 2 + max(0, n - 1))]


def compare_art(ref_url, cand_url, *, client=None, fetch=None, cache=None, api_key=None,
                ref_facts=None, cand_title="", extra_photos=1):
    """現物 vs 候補 を3軸(絵柄/変種/配布)で判定 → dict + "cached"。

    判定できない事情 (キー無 / 画像取れない / API失敗) は全て **unsure / 全軸 unknown**。
    client/fetch/cache を注入できる = ネットワーク無しでテスト可能。
    """
    out_unsure = dict(_blank("unsure", "判定不能(目視で確認)"), cached=False)
    if not ref_url or not cand_url:
        return out_unsure
    ck = _cache_key(ref_url, cand_url, cand_title)
    if cache is not None:
        hit = cache.get(ck)
        if hit is None:
            # ★旧バージョンの判定を捨てない。質問を増やした時に**全部再判定**になると、
            #   API が使えない状況で判定済みの分まで消える。古い形式は軸が無いだけで
            #   verdict/一致度は有効なので、そのまま使う (新しい軸は unknown = 目視)。
            for old in range(PROMPT_VERSION - 1, 0, -1):
                hit = cache.get(_cache_key(ref_url, cand_url, cand_title, version=old))
                if hit is not None:
                    break
        if hit is not None:
            res = dict(_blank(hit.get("verdict", "unsure"), hit.get("reason", "")))
            res.update({k: v for k, v in hit.items() if k != "cached"})
            res["cached"] = True
            return res

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
    # 候補の追加写真は「取れたら足す」= 失敗しても判定は続ける
    for u in extra_photo_urls(cand_url, n=extra_photos + 1):
        try:
            b = _image_block(u, fetch)
        except Exception:
            b = None
        if b is not None:
            blocks.append(b)
    try:
        r = client.messages.create(
            model=MODEL, max_tokens=400,
            messages=[{"role": "user",
                       "content": blocks + [{"type": "text",
                                             "text": build_prompt(ref_facts, cand_title)}]}])
        res = parse_verdict(r.content[0].text)
    except Exception as e:
        return dict(_blank("unsure", f"判定失敗({type(e).__name__})"), cached=False)
    if cache is not None:
        cache[ck] = dict(res)
    res["cached"] = False
    return res


def drop_reason(res):
    """「明らかに別カード」と言い切れる根拠だけを返す。無ければ "" (= 残して人が見る)。

    省くのは **絵柄が別** または **配布が別** の時だけ。どちらも「別の商品」が確定する軸。
    変種(パラレル/加工)は写真では見誤りやすいので **省かない** — 目立つ印を付けて人に見せる。
    """
    if res.get("art") == "different":
        return f"絵柄が別: {res.get('art_reason') or res.get('reason', '')}"
    if res.get("dist") == "different":
        return f"配布が別: {res.get('dist_reason') or res.get('reason', '')}"
    if res.get("verdict") == "different" and res.get("art") != "same":
        return f"別カード: {res.get('reason', '')}"
    return ""


def annotate_candidates(ref_url, cands, *, client=None, fetch=None, cache=None, api_key=None,
                        image_of=None, ref_facts=None, title_of=None, extra_photos=1):
    """候補に3軸判定を付ける → (残す候補, 省いた候補)。

    - 絵柄が別 / 配布が別 = **明らかに別カード** → 省く (ユーザー指示 2026-08-02)
    - 変種違いは省かない (写真では見誤る) → UI で目立たせて人が判断
    - それ以外は残す。unknown は「自信が無い」= 目視で落とす前提
    元の順序は保つ (呼出側の「確証済を先頭」等の並びを壊さない)。
    """
    image_of = image_of or (lambda c: c.get("image") or c.get("url") or "")
    title_of = title_of or (lambda c: c.get("name") or "")
    keep, dropped = [], []
    for c in cands or []:
        res = compare_art(ref_url, image_of(c), client=client, fetch=fetch, cache=cache,
                          api_key=api_key, ref_facts=ref_facts, cand_title=title_of(c),
                          extra_photos=extra_photos)
        c = dict(c)
        c["art"] = res["verdict"]
        c["art_pct"] = res.get("match_pct")
        c["art_reason"] = res.get("reason", "")
        for a in AXES:
            c["ax_" + a] = res.get(a, "unknown")
            c["ax_" + a + "_reason"] = res.get(a + "_reason", "")
        why = drop_reason(res)
        if why:
            c["drop_why"] = why
            dropped.append(c)
        else:
            keep.append(c)
    return keep, dropped
