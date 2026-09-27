"""通过京东人工安全验证（滑块），并把已验证的会话保存到抓取登录态。

用法：
    python scripts/solve_captcha.py     # 打开验证窗口，最长等 15 分钟
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AUTH_DIR  # noqa: E402

EXE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def main() -> int:
    exe = next((p for p in EXE_CANDIDATES if Path(p).exists()), None)
    if not exe:
        print("未找到 Edge 浏览器")
        return 1
    profile = (AUTH_DIR / "edge_profile_jd").resolve()
    state = AUTH_DIR / "jd_state.json"
    url = "https://search.jd.com/Search?keyword=%E8%BF%B7%E4%BD%A0%E4%B8%BB%E6%9C%BA&enc=utf-8"
    print("打开京东安全验证窗口（15 分钟内完成即可）……", flush=True)
    proc = subprocess.Popen(
        [exe, f"--user-data-dir={profile}", "--remote-debugging-port=17777",
         "--no-first-run", "--no-default-browser-check", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def solved() -> bool:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            try:
                b = pw.chromium.connect_over_cdp("http://127.0.0.1:17777", timeout=3000)
                ctx = b.contexts[0]
                for p in ctx.pages:
                    if "search.jd.com" in (p.url or ""):
                        h = p.content()
                        if ("京东验证" not in h and "快速验证" not in h
                                and "plugin_goodsCardWrapper" in h):
                            time.sleep(2)
                            ctx.storage_state(path=str(state))
                            return True
            except Exception:
                pass
        return False

    ok = False
    for i in range(300):
        time.sleep(3)
        try:
            ok = solved()
        except Exception:
            ok = False
        if ok:
            break
        if i % 20 == 19:
            print("仍在等待……（请在窗口里拖动滑块完成拼图）", flush=True)
    try:
        proc.kill()
    except Exception:
        pass
    print("[OK] 验证已通过，会话已保存，可正常抓价。" if ok
          else "[FAIL] 未检测到验证通过，可稍后重试。", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
