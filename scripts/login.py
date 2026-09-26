"""交互式登录京东 / 淘宝，保存浏览器登录态供每日抓取使用。

用法：
    python scripts/login.py          # 依次登录京东、淘宝
    python scripts/login.py jd       # 只登录京东
    python scripts/login.py taobao   # 只登录淘宝

要点：
- 登录成功后网站会自动关闭登录页（window.close），脚本先开一个"保活"空白页，
  保证浏览器不随登录页退出，Cookie 才能导出；
- 二维码约 2 分钟过期，脚本每 100 秒自动刷新登录页（手机已扫码待确认时不刷新）；
- 窗口被手动关闭会自动重新弹出（打不死模式），总等待窗口 15 分钟；
- 登录信息持久保存在浏览器档案 auth/edge_profile_* 中，中途异常后重跑本脚本
  会自动识别已登录状态并补存，无需重复扫码。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AUTH_DIR, ensure_dirs  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
)

LOGIN_URLS = {
    "jd": "https://passport.jd.com/new/login.aspx",
    "taobao": "https://login.taobao.com/member/login.jhtml",
}
LOGIN_DOMAINS = {"jd": "passport.jd.com", "taobao": "login.taobao.com"}
# 登录成功后才会出现的 Cookie（多列几个做冗余判断）
LOGIN_COOKIES = {
    "jd": {"pt_key", "pt_pin"},
    "taobao": {"_nk_", "lgc", "tracknick"},
}
WAIT_SECONDS = 280      # 单次尝试等待窗口（看门狗会反复拉起本脚本）
REFRESH_EVERY = 10 ** 9  # 禁用自动刷新：reload 会触发驱动崩溃；二维码过期请按 F5 手动刷新
QR_BUSY_MARKS = ("扫描成功", "扫码成功", "扫描结果", "请在手机")  # 已扫码待确认，勿刷新


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


def launch(pw, profile_dir: Path):
    """启动带持久档案的有头浏览器（优先 Edge）。"""
    kwargs = dict(
        headless=False,
        viewport={"width": 1280, "height": 860},
        locale="zh-CN",
        args=["--disable-blink-features=AutomationControlled"],
    )
    errors = []
    for channel in ("msedge", None):
        for user_data_dir in (str(profile_dir), str(profile_dir) + "_alt"):
            kwargs["user_data_dir"] = user_data_dir
            try:
                if channel:
                    return pw.chromium.launch_persistent_context(
                        channel=channel, user_agent=UA, **kwargs
                    )
                return pw.chromium.launch_persistent_context(user_agent=UA, **kwargs)
            except Exception as exc:
                errors.append(f"{channel}/{user_data_dir}: {exc}")
    raise RuntimeError("无法启动浏览器：\n" + "\n".join(errors))


def _open_login_page(browser, key: str):
    """新开一个标签并打开登录页。"""
    page = browser.new_page()
    try:
        page.goto(LOGIN_URLS[key], wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    return page


def _scan_in_progress(page) -> bool:
    """手机已扫码、等待确认时不要刷新页面。"""
    try:
        body = page.evaluate("document.body ? document.body.innerText : ''") or ""
        return any(m in body for m in QR_BUSY_MARKS)
    except Exception:
        return True  # 读不了页面时保守处理：不刷新


def _wait_login(browser, key: str, deadline: float) -> bool:
    """在当前浏览器实例里等待登录成功；窗口被关则抛异常返回。"""
    keeper = browser.new_page()  # 保活页：登录页自关时浏览器不退出
    try:
        # 核心对策：京东/淘宝登录成功后会调用 window.close() 自毁页面，
        # 连累浏览器与驱动一起崩溃、登录态丢失。废掉 close() 后页面安然无恙，
        # Cookie 可以从容读取导出。
        browser.add_init_script(
            "window.close = function(){}; window.top.close = function(){};"
        )
    except Exception:
        pass
    page = _open_login_page(browser, key)
    last_nav = time.time()
    dead_streak = 0
    page_fail = 0

    while time.time() < deadline:
        time.sleep(1)
        try:
            names = {c["name"] for c in browser.cookies()}
            dead_streak = 0
        except Exception:
            dead_streak += 1
            if dead_streak > 10:
                raise RuntimeError("browser closed")
            continue
        if names & LOGIN_COOKIES[key]:
            return True
        try:
            url = page.url or ""
            page_fail = 0
            if url.startswith("http") and LOGIN_DOMAINS[key] not in url:
                return True  # 登录后跳转到了首页等
        except Exception:
            # 页面异常：连续几次失败再重开（避免对已死驱动调用导致卡死）
            page_fail += 1
            if page_fail >= 3:
                try:
                    page = _open_login_page(browser, key)
                    last_nav = time.time()
                except Exception:
                    raise RuntimeError("browser closed")
                page_fail = 0
            continue
        # 二维码过期处理：定时刷新登录页（已扫码待确认时跳过）
        if time.time() - last_nav > REFRESH_EVERY and not _scan_in_progress(page):
            try:
                page.reload(wait_until="domcontentloaded", timeout=20000)
            except Exception:
                page = _open_login_page(browser, key)
            last_nav = time.time()
    return False


def do_login(pw, key: str) -> bool:
    """单次登录尝试：成功返回 True；崩溃/超时返回 False，由看门狗重新拉起。"""
    label = "京东" if key == "jd" else "淘宝"
    profile_dir = AUTH_DIR / f"edge_profile_{key}"
    state_path = AUTH_DIR / f"{key}_state.json"
    print(f"\n===== 请在弹出的浏览器窗口中登录 {label}（扫码或账号密码）=====", flush=True)
    print(f"提示：二维码每 {REFRESH_EVERY} 秒自动刷新；单次等待约 "
          f"{WAIT_SECONDS // 60} 分钟。", flush=True)

    kill_stale_edge(profile_dir)
    browser = launch(pw, profile_dir)
    ok = False
    try:
        ok = _wait_login(browser, key, time.time() + WAIT_SECONDS)
    except Exception:
        print(f"[WARN] {label}浏览器窗口被关闭/驱动中断。", flush=True)
    if ok:
        try:
            time.sleep(2)  # 等 Cookie 写全
            browser.storage_state(path=str(state_path))
            print(f"[OK] {label}登录态已保存：{state_path}", flush=True)
        except Exception:
            # 原实例已关闭，用档案重新拉起无头浏览器导出
            if _export_state(pw, profile_dir, state_path):
                print(f"[OK] {label}登录态已保存：{state_path}", flush=True)
            else:
                print(f"[OK] {label}已登录，但导出失败；下次尝试会自动识别。", flush=True)
    else:
        print(f"[FAIL] {label}本次未检测到登录。", flush=True)
    try:
        browser.close()
    except Exception:
        pass
    return ok


def _export_state(pw, profile_dir: Path, state_path: Path) -> bool:
    """用档案重新拉起无头浏览器导出 storage_state，供抓取脚本使用。"""
    kwargs = dict(user_data_dir=str(profile_dir), headless=True, locale="zh-CN")
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


def main() -> int:
    ensure_dirs()
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
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
