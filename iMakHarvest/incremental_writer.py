"""incremental_writer - 収集の途中で **こまめに保存する** ための共通部品.

2026-09-13 新設。 user「なんでまめな保存をしないの？学習機能ないの？」。

経緯: 2026-08-20 に楽天ガチャで「途中で保存するようにしてね」と指示を受けて入れたが、
その runner にしか入れず、 2026-09-13 に新しく作ったメルカリ UT 収集が
最後だけ書く作りのまま走って **140件が丸ごと消えた**。 全 runner を洗うと
同じ作りが他に 7本あった。 1本ずつ手で書くと また漏れるので部品にする。

使い方:
    w = PendingWriter(write_fn=lambda rows: append_xxx(rows, ...), every=5,
                      dump_path=DUMP_DIR / "xxx_<ts>.json")
    for ...:
        w.add(item)            # every 件たまったら書く。 失敗したら持ち越す
    w.close()                  # finally で呼ぶ。 書けなければ unwritten ファイルに退避

守り: `tests/test_harvest_runners_save_incrementally.py` が全 runner を走査する。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional


class PendingWriter:
    """一定件数ごとに書き、 失敗は持ち越し、 最後まで書けなければファイルへ退避する."""

    def __init__(self, write_fn: Callable[[list], object], every: int = 5,
                 dump_path: Optional[Path] = None, log: Callable[[str], None] = print,
                 enabled: bool = True):
        self.write_fn = write_fn
        self.every = max(1, int(every))
        self.dump_path = Path(dump_path) if dump_path else None
        self.log = log
        self.enabled = enabled          # dry-run の時は False (書かない。 JSON だけ残す)
        self.pending: list = []
        self.all_items: list = []
        self.written = 0
        self.failures = 0

    def _dump(self) -> None:
        if not self.dump_path:
            return
        try:
            self.dump_path.parent.mkdir(parents=True, exist_ok=True)
            self.dump_path.write_text(json.dumps({"kept": self.all_items}, ensure_ascii=False,
                                                 indent=2, default=str), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 - 退避の失敗で走行を殺さない
            self.log(f"  ⚠️ JSON 退避に失敗 ({type(e).__name__})")

    def flush(self) -> bool:
        """溜まっている分を書く。 書けたら True。 失敗したら持ち越して False."""
        if not self.enabled or not self.pending:
            return True
        try:
            self.write_fn(list(self.pending))
            self.written += len(self.pending)
            self.pending = []
            return True
        except Exception as e:  # noqa: BLE001 - 書込失敗で走行を殺さない
            self.failures += 1
            self.log(f"  ⚠️ スプシ書込に失敗 ({type(e).__name__}) → 持ち越し ({len(self.pending)}件)")
            return False

    def add(self, item) -> None:
        """1件足す。 JSON は毎回書き、 every 件たまったらスプシへ書く."""
        self.pending.append(item)
        self.all_items.append(item)
        self._dump()
        if len(self.pending) >= self.every:
            self.flush()

    def close(self) -> Optional[Path]:
        """最後に書く。 書けなければ unwritten ファイルに退避してそのパスを返す."""
        self._dump()
        if self.flush() or not self.pending:
            return None
        left = None
        if self.dump_path:
            left = self.dump_path.with_name(self.dump_path.stem + "_unwritten.json")
            try:
                left.write_text(json.dumps({"unwritten": self.pending}, ensure_ascii=False,
                                           indent=2, default=str), encoding="utf-8")
            except Exception:  # noqa: BLE001
                left = None
        self.log(f"  ⚠️ 書けなかった {len(self.pending)}件"
                 + (f" を {left.name} に退避 (要再投入)" if left else " (退避も失敗)"))
        return left
