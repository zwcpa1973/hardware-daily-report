"""交互式登录京东 / 淘宝，保存浏览器登录态供每日抓取使用。

用法：
    python scripts/login.py jd       # 登录京东（单次尝试）
    python scripts/login.py taobao   # 登录淘宝
    python scripts/login.py all      # 依次登录（建议用 login_watchdog.py）

设计要点：
- Edge 由系统命令直接启动并原生打开登录页（窗口与自动化完全解耦，
  不受任何驱动缺陷影响，怎么都不会崩）；
- Python 通过远程调试端口连上浏览器，只读 Cookie，不做任何页面操作；
- 额外"保活"逻辑：即使登录页标签被网站关闭，浏览器仍活着，Cookie 可读；
- 登录信息持久保存在浏览器档案 auth/edge_profile_* 中；某次尝试中断后，
  下次尝试启动时会自动识别档案里已有的登录（Edge 会把 Cookie 落盘），
  无需重复扫码；
- 二维码约 2 分钟过期：过期请在登录页按 F5 手动刷新。
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AUTH_DIR, ensure_dirs  # noqa: E402

LOGIN_URLS = {
    "jd": "https://passport.jd.com/new/login.aspx",
    "taobao": "https://login.taobao.com/member/login.jhtml",
}
# 登录成功后才会出现的 Cookie（京东新版 QR 登录发 thor/unick/pin，老版发 pt_key/pt_pin）
LOGIN_COOKIES = {
    "jd": {"pt_key", "pt_pin", "thor", "unick"},
    "taobao": {"_nk_", "lgc", "tracknick"},
}
WAIT_SECONDS = 600  # 单次尝试等待窗口（看门狗会反复拉起本脚本）

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str:
    for p in EDGE_PATHS:
        if Path(p).exists():
            return p
    raise RuntimeError("未找到 Edge 浏览器（msedge.exe）")


def kill_stale_edge(profile_dir: Path) -> None:
    """结束占用本档案目录的残留浏览器进程，避免档案被锁。"""
    marker = profile_dir.name
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             f"Where-Object {{ $_.CommandLine -like '*{marker}*' }} | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
             "-ErrorAction SilentlyContinue }"],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _export_state(pw, profile_dir: Path, state_path: Path) -> bool:
    """用档案重新拉起无头浏览器导出 storage_state，供抓取脚本使用。"""
    kwargs = dict(user_data_dir=str(profile_dir), headless=True, locale="zh-CN")
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False
    for channel in ("msedge", None):
        try:
            if channel:
                ctx = pw.chromium.launch_persistent_context(channel=channel, **kwargs)
            else:
                ctx = pw.chromium.launch_persistent_context(**kwargs)
            ctx.storage_state(path=str(state_path))
            ctx.close()
            return True
        except Exception:
            continue
    return False


def do_login(pw, key: str) -> bool:
    """单次登录尝试：成功返回 True；超时/中断返回 False，由看门狗重新拉起。"""
    label = "京东" if key == "jd" else "淘宝"
    profile_dir = AUTH_DIR / f"edge_profile_{key}"
    state_path = AUTH_DIR / f"{key}_state.json"
    print(f"\n===== 请在弹出的浏览器窗口中登录 {label}（扫码或账号密码）=====", flush=True)
    print("提示：二维码约 2 分钟过期，过期请在登录页按 F5 刷新；"
          f"单次等待约 {WAIT_SECONDS // 60} 分钟。", flush=True)

    kill_stale_edge(profile_dir)
    port = free_port()
    exe = find_browser()
    print(f"正在启动 Edge（调试端口 {port}）……", flush=True)
    proc = subprocess.Popen(
        [exe, f"--user-data-dir={profile_dir}",
         f"--remote-debugging-port={port}",
         "--no-first-run", "--no-default-browser-check",
         "--disable-blink-features=AutomationControlled",
         "--window-size=1280,860",
         LOGIN_URLS[key]],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # 连上浏览器（Edge 启动需要几秒，重试 30 次）
    ctx = None
    for _ in range(30):
        time.sleep(1)
        try:
            browser = pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}", timeout=3000)
            if browser.contexts:
                ctx = browser.contexts[0]
                break
        except Exception:
            continue
    if ctx is None:
        print("[FAIL] 无法连接浏览器调试端口。", flush=True)
        kill_stale_edge(profile_dir)
        return False

    ok = False
    deadline = time.time() + WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(1)
        try:
            names = {c["name"] for c in ctx.cookies()}
        except Exception:
            if proc.poll() is not None:
                print(f"[WARN] {label}浏览器窗口已退出。", flush=True)
                break
            continue
        if names & LOGIN_COOKIES[key]:
            time.sleep(2)  # 等 Cookie 写全
            try:
                ctx.storage_state(path=str(state_path))
                print(f"[OK] {label}登录态已保存：{state_path}", flush=True)
            except Exception:
                if _export_state(pw, profile_dir, state_path):
                    print(f"[OK] {label}登录态已保存：{state_path}", flush=True)
                else:
                    print(f"[OK] {label}已登录，但导出失败；下次尝试会自动识别。",
                          flush=True)
            ok = True
            break

    kill_stale_edge(profile_dir)  # 收尾：关掉本次启动的浏览器
    if not ok:
        print(f"[FAIL] {label}本次未检测到登录。", flush=True)
    return ok


def main() -> int:
    ensure_dirs()
    what = sys.argv[1] if len(sys.argv) > 1 else "jd"
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        results = {}
        if what in ("all", "jd"):
            results["jd"] = do_login(pw, "jd")
        if what in ("all", "taobao"):
            results["taobao"] = do_login(pw, "taobao")
        print("\n结果：", results or "未执行", flush=True)
        code = 0 if results and all(results.values()) else 1
    except Exception as exc:
        print(f"!! 登录流程异常：{exc}", flush=True)
        code = 1
    finally:
        try:
            pw.stop()
        except Exception:
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
