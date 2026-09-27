"""登录看门狗：反复拉起 login.py，直到登录态保存成功或总时间用完。

每次尝试（约 5 分钟）独立运行；脚本崩溃、窗口被关、驱动中断都会被看门狗
自动恢复，并利用浏览器档案（auth/edge_profile_*）自动识别已完成的登录。

用法：
    python scripts/login_watchdog.py jd 20     # 京东，总窗口 20 分钟
    python scripts/login_watchdog.py all 30    # 京东+淘宝，总窗口 30 分钟
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AUTH_DIR  # noqa: E402

STATE_FILES = {
    "jd": AUTH_DIR / "jd_state.json",
    "taobao": AUTH_DIR / "taobao_state.json",
}
ATTEMPT_TIMEOUT = 660  # 单次尝试的硬超时（秒），需大于 login.py 的 WAIT_SECONDS


def main() -> int:
    key = sys.argv[1] if len(sys.argv) > 1 else "jd"
    total = int(sys.argv[2]) * 60 if len(sys.argv) > 2 else 20 * 60
    keys = ["jd", "taobao"] if key == "all" else [key]
    deadline = time.time() + total

    while time.time() < deadline:
        missing = [k for k in keys if not STATE_FILES[k].exists()]
        if not missing:
            break
        remaining = int(deadline - time.time())
        print(f"[watchdog] 开始尝试登录 {'、'.join(missing)}"
              f"（总剩余 {remaining // 60} 分 {remaining % 60} 秒）", flush=True)
        for k in missing:
            try:
                subprocess.run(
                    [sys.executable, str(Path(__file__).resolve().parent / "login.py"), k],
                    timeout=ATTEMPT_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                print("[watchdog] 本次尝试超时，重开窗口。", flush=True)
            except Exception as exc:
                print(f"[watchdog] 尝试异常：{exc}", flush=True)
        time.sleep(2)

    ok = all(STATE_FILES[k].exists() for k in keys)
    print("[watchdog] DONE：登录态已就绪" if ok else "[watchdog] GIVEUP：超时未完成登录",
          flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
