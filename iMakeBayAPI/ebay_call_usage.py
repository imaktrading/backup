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


def record_call(callname, path=None, now=None):
    """呼出を1件数える。数えられなくても API 呼出は止めない (補助なので)。"""
    path = path or _USAGE_PATH
    day = ebay_day(now)
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
