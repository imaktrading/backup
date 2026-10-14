# -*- coding: utf-8 -*-
"""eBay Trading API の1日の呼出回数を数える (読み込んでも何も起きない部品)。

★2026-10-15 fix_de_speedpak_shipping から切り出した。あちらは読み込むと作業フォルダを
  変えるため、GetItem の口 (ebay_getitem_images) から使えず、**GetItem / GetOrders /
  GetMyMessages が数えられていなかった**。10/14 に Trading API の1日5000回 (全呼び出しで
  共有・取下げも同じ枠) を使い切った時、数えてあったのは約570回だけで出どころが追えなかった。
★eBay の1日は **日本時間 16:00 区切り**。
"""
import json
import os
import sys
import threading

_USAGE_PATH = r"C:\dev\iMak_data\hq\ebay_api_usage.json"
_LOCK = threading.Lock()      # 8件ずつ同時に聞く道具があるので、同じプロセス内の書込を順番にする


def ebay_day(now=None):
    """eBay の「1日」(日本時間 16:00 区切り) の日付文字列。純関数。"""
    from datetime import datetime, timedelta
    return ((now or datetime.now()) - timedelta(hours=16)).strftime('%Y-%m-%d')


def record_call(callname, path=None, now=None, key=None):
    """呼出を1件数える。数えられなくても API 呼出は止めない (補助なので)。

    2つ目の鍵 (sub) で呼んだ分は `<日付>@sub` に分けて数える (上限は鍵ごとに別枠)。
    """
    path = path or _USAGE_PATH
    day = ebay_day(now) + ("@sub" if (key or active_key(now)) == "sub" else "")
    try:
        with _LOCK:
            try:
                with open(path, encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:                                  # noqa: BLE001
                data = {}
            bucket = data.setdefault(day, {})
            bucket[callname] = int(bucket.get(callname, 0)) + 1
            bucket['_total'] = int(bucket.get('_total', 0)) + 1
            # ★2026-10-01: 誰が呼んだか (起動したスクリプト名)
            try:
                who = os.path.basename((sys.argv or [''])[0] or '') or '?'
            except Exception:                                  # noqa: BLE001
                who = '?'
            by = bucket.setdefault('_by_caller', {})
            k = f'{callname}@{who}'
            by[k] = int(by.get(k, 0)) + 1
            for old in sorted(data)[:-14]:          # 直近14日だけ残す
                data.pop(old, None)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, path)               # 書きかけを他のプロセスに読ませない (読めないと {} から数え直す)
            return bucket['_total']
    except Exception:                                          # noqa: BLE001
        return 0


# ── 使い過ぎの歯止めと 2つ目の鍵への切替 (2026-10-15 ユーザー指示) ─────────────
# ★なぜ: 10/14 にリバイスの確認が20分おきに1件ずつ GetBestOffers を聞き、16〜23時で約3,300回。
#   Trading API の上限は **鍵ごとに1つ (全呼出で共有・取下げも同じ枠)** なので、
#   1本の道具の暴走で取下げまで止まった。気づいたのは止まった後だった。
# 決まり:
#   1. 1本の道具は eBay の1日 (16時区切り) に CALLER_LIMIT 回まで。超えたら **その道具だけ** 止めて知らせる
#      (取下げ・数量0 は止めない = EXEMPT)
#   2. 自分で数えた合計が WARN_AT を超えたら知らせる (1日1回)
#   3. eBay が「上限を超えた」と返したら、その日は **2つ目の鍵 (imaktrading・同じ imax-64 の出品を操作できる)** に切り替えて
#      呼び直し、知らせる。2つ目も使い切ったら知らせて止まる
CALLER_LIMIT = 1000
# ★2026-10-15 07時 止めた: eBay の API 規約に「Attempts to circumvent API call limits may result in termination
#   ... suspension of your license」とある。上限を超えるために別の鍵へ回すのはこれに当たる恐れがあるので、
#   ユーザーの判断が出るまで切り替えない (上限に当たったら記録して知らせ、16時まで止まる)
SWITCH_TO_SUB = False
WARN_AT = 3000
EXEMPT = {"EndItem", "EndItems", "ReviseInventoryStatus", "EndFixedPriceItem"}
STATE_PATH = r"C:\dev\iMak_data\hq\ebay_key_state.json"
SUB_KEYS = r"C:/dev/iMak_data/credentials/imaktrading.txt"
SUB_TOKEN = r"C:/dev/iMak_data/credentials/ebay_oauth_token_imaktrading.json"
NTFY_TOPIC = r"C:/dev/iMak_data/credentials/ntfy_topic.txt"
_QUOTA_RE = ("exceeded usage limit", "<ErrorCode>518</ErrorCode>")
_SUB_TOK = {"value": "", "until": 0.0}


def is_quota_error(text):
    """eBay が「この鍵は今日の上限を超えた」と返したか。純関数。"""
    t = text or ""
    return "<Ack>Failure</Ack>" in t and any(q in t for q in _QUOTA_RE)


def _load_state(path=None):
    try:
        with open(path or STATE_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:                                          # noqa: BLE001
        return {}


def _save_state(st, path=None):
    path = path or STATE_PATH
    for old in sorted(st)[:-7]:
        st.pop(old, None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def active_key(now=None, path=None):
    """今日使う鍵。本鍵が上限に当たった日は 'sub'。日付が変われば (16時) 本鍵に戻る。"""
    if not SWITCH_TO_SUB:
        return "main"
    return "sub" if _load_state(path).get(ebay_day(now), {}).get("main_exhausted") else "main"


def notify_once(tag, title, body, now=None, path=None):
    """同じ日・同じ tag は1回だけスマホ (ntfy) と走行ログに出す。出したら True。"""
    day = ebay_day(now)
    with _LOCK:
        st = _load_state(path)
        sent = st.setdefault(day, {}).setdefault("notified", [])
        if tag in sent:
            return False
        sent.append(tag)
        try:
            _save_state(st, path)
        except Exception:                                      # noqa: BLE001
            pass
    print(f"🚨 eBay の呼出: {title} / {body}", flush=True)
    try:
        import requests
        topic = open(NTFY_TOPIC, encoding="utf-8").read().strip()
        requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=20,
                      headers={"Title": title.encode("utf-8"), "Priority": "high", "Tags": "warning"})
    except Exception:                                          # noqa: BLE001
        pass
    return True


def mark_exhausted(key, now=None, path=None):
    """その鍵が今日の上限に当たったと記録して知らせる。"""
    day = ebay_day(now)
    with _LOCK:
        st = _load_state(path)
        st.setdefault(day, {})[f"{key}_exhausted"] = True
        _save_state(st, path)
    if key == "main" and SWITCH_TO_SUB:
        notify_once("main_exhausted", "eBay の上限 → 2つ目の鍵に切替",
                    "本鍵 (imax-64) が今日の上限に当たりました。16時まで imaktrading の鍵で動かします。"
                    "誰が使ったかは python iMakHQ/tools/ebay_api_usage.py", now, path)
    elif key == "main":
        notify_once("main_exhausted", "eBay の上限に当たった (16時まで止まる)",
                    "本鍵 (imax-64) が今日の上限に当たりました。取下げも16時まで送れません。"
                    "誰が使ったかは python iMakHQ/tools/ebay_api_usage.py", now, path)
    else:
        notify_once("sub_exhausted", "eBay の上限 → 2つ目の鍵も切れた",
                    "imaktrading の鍵も今日の上限に当たりました。16時まで eBay を呼べません。", now, path)


def guard(callname, now=None, usage_path=None, state_path=None):
    """送る前に呼ぶ。止める時は理由の文字列、通す時は None。

    - 1本の道具が今日 CALLER_LIMIT 回を超えた → その道具だけ止める (取下げ系は通す)
    - 合計が WARN_AT を超えた → 知らせるだけ (止めない)
    """
    try:
        key = active_key(now, state_path)
        day = ebay_day(now) + ("@sub" if key == "sub" else "")
        with open(usage_path or _USAGE_PATH, encoding="utf-8") as f:
            bucket = (json.load(f) or {}).get(day, {})
    except Exception:                                          # noqa: BLE001
        return None
    total = int(bucket.get("_total", 0))
    if total >= WARN_AT:
        notify_once(f"warn_{key}", "eBay の呼出が多い",
                    f"今日 {total}回 (上限5000・取下げと共有)。python iMakHQ/tools/ebay_api_usage.py で内訳",
                    now, state_path)
    if callname in EXEMPT:
        return None
    who = os.path.basename((sys.argv or [""])[0] or "") or "?"
    mine = sum(int(v) for k, v in (bucket.get("_by_caller") or {}).items() if k.endswith("@" + who))
    if mine >= CALLER_LIMIT:
        notify_once(f"cap_{key}_{who}", f"eBay の呼出を止めた: {who}",
                    f"{who} が今日 {mine}回 呼んだので止めました (1本 {CALLER_LIMIT}回まで・取下げは止めない)。"
                    "16時に戻ります", now, state_path)
        return f"{who} は今日 {mine}回 呼んだので止めた (1本 {CALLER_LIMIT}回まで)"
    return None


def guard_xml(reason):
    """止めた時に返す Trading 形式の失敗 (呼び出し側の「失敗」処理にそのまま乗る)。"""
    return ("<Ack>Failure</Ack><Errors><ShortMessage>iMak guard</ShortMessage>"
            f"<LongMessage>iMak の歯止め: {reason}</LongMessage></Errors>")


def sub_access_token():
    """2つ目の鍵 (imaktrading) のアクセストークン。imax-64 が同意した物なので うちの出品を操作できる
    (2026-10-15 GetUser で UserID=imax-64 を確認)。ファイルには書き戻さない (書き手は market_getitem)。"""
    import base64
    import time
    import datetime
    import requests
    if _SUB_TOK["value"] and time.time() < _SUB_TOK["until"]:
        return _SUB_TOK["value"]
    with open(SUB_TOKEN, encoding="utf-8") as f:
        tok = json.load(f)
    got = tok.get("_obtained_at")
    if got:
        age = (datetime.datetime.now() - datetime.datetime.fromisoformat(got)).total_seconds()
        left = int(tok.get("expires_in", 7200)) - 300 - age
        if left > 60:
            _SUB_TOK.update(value=tok["access_token"], until=time.time() + left)
            return _SUB_TOK["value"]
    keys = {}
    with open(SUB_KEYS, encoding="utf-8-sig") as f:
        for ln in f:
            if "=" in ln:
                k, v = ln.split("=", 1)
                keys[k.strip()] = v.strip()
    auth = base64.b64encode(f"{keys['AppID']}:{keys['AppSecret']}".encode()).decode()
    r = requests.post("https://api.ebay.com/identity/v1/oauth2/token", timeout=30,
                      headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": "Basic " + auth},
                      data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    if r.status_code != 200:
        raise RuntimeError(f"2つ目の鍵のトークン更新に失敗: {r.status_code} {r.text[:120]}")
    j = r.json()
    _SUB_TOK.update(value=j["access_token"], until=time.time() + int(j.get("expires_in") or 7200) - 300)
    return _SUB_TOK["value"]


def send(do_post, callname, headers):
    """Trading API を1回送る共通の手順。do_post(headers) -> 応答の文字列。

    歯止め → 送る → 本鍵が上限なら記録して 2つ目の鍵で1回だけ呼び直す。
    """
    why = guard(callname)
    if why:
        return guard_xml(why)
    was_sub = active_key() == "sub"
    if was_sub:
        try:
            headers = dict(headers, **{"X-EBAY-API-IAF-TOKEN": sub_access_token()})
        except Exception as e:                                 # noqa: BLE001
            return guard_xml(f"2つ目の鍵のトークンが取れない: {e}"[:200])
    text = do_post(headers)
    if is_quota_error(text):
        mark_exhausted("sub" if was_sub else "main")
        if not was_sub and SWITCH_TO_SUB:
            try:
                text = do_post(dict(headers, **{"X-EBAY-API-IAF-TOKEN": sub_access_token()}))
            except Exception as e:                             # noqa: BLE001
                return guard_xml(f"2つ目の鍵のトークンが取れない: {e}"[:200])
            if is_quota_error(text):
                mark_exhausted("sub")
    return text
