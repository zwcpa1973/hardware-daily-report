"""交互式登录京东 / 淘宝，保存浏览器登录态供每日抓取使用。

用法：
    python scripts/login.py          # 依次登录京东、淘宝
    python scripts/login.py jd       # 只登录京东
    python scripts/login.py taobao   # 只登录淘宝

会弹出 Edge 窗口，用京东/淘宝 App 扫码即可，登录成功后自动保存并关闭。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AUTH_DIR, ensure_dirs  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
)

TARGETS = {
    "jd": {
        "url": "https://passport.jd.com/new/login.aspx",
        "state": AUTH_DIR / "jd_state.json",
        "check": "https://www.jd.com/",
        # 登录成功后页面会离开 passport.jd.com 且 cookie 里出现 pt_key
        "cookie_key": "pt_key",
    },
    "taobao": {
        "url": "https://login.taobao.com/member/login.jhtml",
        "state": AUTH_DIR / "taobao_state.json",
        "check": "https://i.taobao.com/my_taobao.htm",
        "cookie_key": "cookie2",
    },
}


def launch(pw, headless: bool = False):
    try:
        return pw.chromium.launch(channel="msedge", headless=headless)
    except Exception:
        return pw.chromium.launch(headless=headless)


def do_login(pw, key: str) -> bool:
    cfg = TARGETS[key]
    print(f"\n===== 请在弹出的浏览器窗口中登录 {'京东' if key == 'jd' else '淘宝'}（扫码）=====")
    browser = launch(pw)
    context = browser.new_context(
        user_agent=UA,
        viewport={"width": 1280, "height": 800},
        storage_state=str(cfg["state"]) if cfg["state"].exists() else None,
    )
    page = context.new_page()
    page.goto(cfg["url"], wait_until="domcontentloaded")

    ok = False
    for _ in range(120):  # 最长等待 5 分钟扫码
        time.sleep(2.5)
        try:
            cookies = {c["name"] for c in context.cookies()}
            if cfg["cookie_key"] in cookies:
                ok = True
                break
            if key == "jd" and "passport.jd.com" not in page.url:
                # 有时登录成功但不写 pt_key，跳转首页也算成功
                ok = True
                break
        except Exception:
            pass
    if ok:
        cfg["state"].parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(cfg["state"]))
        print(f"[OK] 登录态已保存：{cfg['state']}")
    else:
        print("[FAIL] 超时未检测到登录，请重试。")
    browser.close()
    return ok


def main() -> int:
    ensure_dirs()
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        results = {}
        if what in ("all", "jd"):
            results["jd"] = do_login(pw, "jd")
        if what in ("all", "taobao"):
            results["taobao"] = do_login(pw, "taobao")
    print("\n结果：", results or "未执行")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
