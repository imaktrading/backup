"""ledger_lock — decision_log の台帳を複数 cycle から安全に触るための排他 (2026-08-19).

なぜ要るか:
    取下げ待ち (pending_revise) / 復活待ち (pending_revive) / 要対応 (action_required) は
    「全行読む → 消えた分を外す → **全部書き直す**」という更新をしている。
    HIGH と LOW を並走させると、片方が書き直している最中にもう片方が append した行が
    **まるごと消える**。消えるのが取下げ待ちなら、売切れた商品が eBay に残る = 履行不能
    = キャンセル = Defect Rate。silent に起きるので一番たちが悪い。

設計:
    - Windows でプロセスを跨げること (= O_CREAT|O_EXCL のファイル作成を lock とする)
    - 取れなければ **書き直しをしない** (= 台帳はそのまま残る)。消すより残す方が安全。
      残った分は次 cycle が再処理する
    - 持ち主が死んでいれば奪う (PC 再起動/クラッシュで永久に詰まらない)

使い方:
    from ledger_lock import ledger_lock, LedgerBusy
    try:
        with ledger_lock():
            ...台帳の読み書き...
    except LedgerBusy:
        ...今回は触らない (次 cycle に回す)...
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOCK_PATH = SCRIPT_DIR / "decision_log" / ".ledger.lock"

#: 取得を諦めるまでの待ち時間。lock 区間はファイル読み書きだけ (API 呼出を含めない)
#: 設計なので実際は数十ミリ秒。これを超えるのは異常。
DEFAULT_TIMEOUT_SEC = 60
POLL_SEC = 0.2
#: これを超えて残っている lock は、持ち主の生死を見て奪う。
#: 通常のlock保持はミリ秒なので、60 秒残っている = 持ち主が落ちたか固まっている。
STALE_SEC = 60


class LedgerBusy(RuntimeError):
    """lock を取れなかった (= 台帳を触らずに諦める)."""


def _pid_alive(pid: int) -> bool:
    """pid の生存確認。判定できなければ True (= 生きている扱い = 安全側で奪わない)."""
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except Exception:
            return True
    try:
        # ★ os.kill(pid, 0) は Windows では「終了させて」しまうので使わない
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=10)
        return str(pid) in (out.stdout or "")
    except Exception:
        return True


def _steal_if_dead(path: Path) -> None:
    """持ち主が死んでいる / 異常に古い lock を削除する。"""
    try:
        age = time.time() - path.stat().st_mtime
        if age < STALE_SEC:
            return
        content = path.read_text(encoding="utf-8", errors="replace")[:200]
        m_pid = re.search(r"pid=(\d+)", content)
        m_host = re.search(r"host=(\S+)", content)
        # 別 host の lock は生死を判定できない (単機運用だが安全側)
        if m_host and m_host.group(1) != socket.gethostname():
            return
        if m_pid and _pid_alive(int(m_pid.group(1))):
            return
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    except Exception:
        pass


@contextmanager
def ledger_lock(timeout_sec: int = DEFAULT_TIMEOUT_SEC, path: Path = None):
    """台帳の read-modify-write を包む排他。取れなければ LedgerBusy."""
    lock_path = Path(path) if path else LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_sec
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            _steal_if_dead(lock_path)
            if time.time() >= deadline:
                raise LedgerBusy(
                    f"台帳 lock を {timeout_sec}s 取得できず (保持: "
                    f"{_holder(lock_path)})")
            time.sleep(POLL_SEC)

    try:
        os.write(fd, f"pid={os.getpid()} host={socket.gethostname()} "
                     f"ts={datetime.now().isoformat(timespec='seconds')}\n".encode("utf-8"))
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def _holder(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()[:120]
    except Exception:
        return "?"


def remove_entries(
    ledger_path,
    should_remove,
    archive_path=None,
    stamp_field: str = None,
    stamp_extra: dict = None,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> int:
    """台帳から「消すと決めた entry」だけを取り除く (並走 append を巻き込まない).

    ★ ここが並走の肝: 呼出側が読んだ時点の内容を **そのまま書き戻さない**。
      lock を取った後にもう一度読み直し、`should_remove` が True の行だけ落とす。
      こうすると、判定中に別 cycle が append した行は評価対象になるか、そのまま残る。
      「自分が読んだ snapshot を書き戻す」実装だと、その間の append が消える
      (= 取下げ待ちの silent 消失 = 売切れ品が eBay に残る)。

    eBay API 等の遅い判定は **呼出側が lock の外で済ませてから** ここに来ること
    (lock 保持はファイル読み書きだけに留める)。

    Args:
        ledger_path:  対象 jsonl
        should_remove: entry(dict) -> bool。壊れた行は常に残す (debug 用)
        archive_path: 取り除いた entry の退避先 (省略時は退避しない)
        stamp_field:  退避時に押す時刻の key 名 (例 "consumed_at")
        stamp_extra:  退避時に足す追加フィールド

    Returns: 取り除いた件数
    """
    import json  # noqa: PLC0415

    ledger_path = Path(ledger_path)
    if not ledger_path.exists():
        return 0

    with ledger_lock(timeout_sec=timeout_sec):
        keep, removed = [], []
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                keep.append(line)      # 壊れた行は維持 (debug 可能にする)
                continue
            if should_remove(entry):
                removed.append(entry)
            else:
                keep.append(line)

        if not removed:
            return 0

        if archive_path:
            with open(archive_path, "a", encoding="utf-8") as af:
                for e in removed:
                    if stamp_field:
                        e[stamp_field] = datetime.now().isoformat(timespec="seconds")
                    if stamp_extra:
                        e.update(stamp_extra)
                    af.write(json.dumps(e, ensure_ascii=False) + "\n")

        ledger_path.write_text(
            ("\n".join(keep) + "\n") if keep else "", encoding="utf-8")
        return len(removed)
