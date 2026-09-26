"""每日价格抓取：用 Playwright 驱动 Edge（携带登录态）搜索京东/淘宝并解析价格。

用法：
    python scripts/scrape.py                 # 正常抓取（无头）
    python scripts/scrape.py --headed        # 有头模式，便于排查
    python scripts/scrape.py --platform jd   # 只抓京东
    python scripts/scrape.py --limit 2       # 只抓前 2 个商品（调试）

依赖 auth/jd_state.json / auth/taobao_state.json（由 login.py 生成）。
结果：data/prices.csv 追加今日价格；output/run_status.json 记录运行状态。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    AUTH_DIR, DEBUG_DIR, append_rows, ensure_dirs, load_items, today, write_status,
)

UA_PC = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
)

# ---------- 页面内提取脚本 ----------

JS_JD_PC = r"""
() => {
  const out = [];
  document.querySelectorAll('li.gl-item, #J_goodsList li').forEach(li => {
    const a = li.querySelector('.p-name a, a[href*="item.jd.com"]');
    const priceEl = li.querySelector('.p-price i, .p-price strong i');
    const shopEl = li.querySelector('.p-shop a');
    const title = a ? (a.getAttribute('title') || a.textContent || '') : '';
    const price = priceEl ? parseFloat((priceEl.textContent || '').replace(/[^0-9.]/g, '')) : NaN;
    if (!title || !isFinite(price)) return;
    out.push({
      title: title.trim().slice(0, 200),
      price: price,
      url: a ? a.href : '',
      shop: shopEl ? (shopEl.textContent || '').trim() : '',
      self_op: /自营/.test(li.textContent || ''),
    });
  });
  return out;
}
"""

JS_GENERIC_MOBILE = r"""
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="item.m.jd.com"], a[href*="item.jd.com"], a[href*="item.taobao.com"], a[href*="detail.tmall.com"]').forEach(a => {
    const card = a.closest('li, div, section');
    if (!card) return;
    const txt = (card.textContent || '').replace(/\s+/g, ' ');
    const m = txt.match(/¥\s*([0-9][0-9,]*\.?[0-9]*)/);
    if (!m) return;
    const price = parseFloat(m[1].replace(/,/g, ''));
    if (!isFinite(price)) return;
    let title = (a.getAttribute('aria-label') || a.title || a.textContent || txt).trim();
    title = title.replace(/\s+/g, ' ').slice(0, 200);
    const key = title + '|' + price;
    if (seen.has(key) || title.length < 6) return;
    seen.add(key);
    out.push({title: title, price: price, url: a.href, shop: '', self_op: /自营/.test(txt)});
  });
  return out;
}
"""


class SessionExpired(Exception):
    pass


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def gentle_scroll(page, times: int = 6, step: int = 900, wait: float = 0.5) -> None:
    for _ in range(times):
        try:
            page.evaluate(f"window.scrollBy(0, {step})")
        except Exception:
            pass
        page.wait_for_timeout(int(wait * 1000))


def check_login_wall(page, platform: str) -> None:
    url = page.url or ""
    if platform == "jd":
        if "passport.jd.com" in url or "plogin.m.jd.com" in url:
            raise SessionExpired("京东登录态已失效（跳转到登录页）")
    else:
        if "login.taobao.com" in url or "login.m.taobao.com" in url:
            raise SessionExpired("淘宝登录态已失效（跳转到登录页）")


def dump_debug(page, tag: str) -> None:
    ensure_dirs()
    try:
        path = DEBUG_DIR / f"{today()}_{tag}.html"
        path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(DEBUG_DIR / f"{today()}_{tag}.png"), full_page=False)
    except Exception:
        pass


def search_jd(context, keyword: str, item_id: str) -> list[dict]:
    """京东：PC 搜索优先，失败再试手机版搜索。"""
    page = context.new_page()
    try:
        kw = _urlencode(keyword)
        page.goto(f"https://search.jd.com/Search?keyword={kw}&enc=utf-8",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        check_login_wall(page, "jd")
        gentle_scroll(page)
        cands = page.evaluate(JS_JD_PC)
        if cands:
            return cands
        # 回退：手机版搜索
        log(f"    京东PC搜索无结果，尝试手机版搜索")
        page.goto(f"https://so.m.jd.com/ware/search.action?keyword={kw}",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        check_login_wall(page, "jd")
        gentle_scroll(page, times=4)
        return page.evaluate(JS_GENERIC_MOBILE)
    except SessionExpired:
        raise
    except Exception as exc:
        dump_debug(page, f"jd_{item_id}")
        log(f"    京东搜索异常：{exc}")
        return []
    finally:
        page.close()


def search_taobao(context, keyword: str, item_id: str) -> list[dict]:
    page = context.new_page()
    try:
        kw = _urlencode(keyword)
        page.goto(f"https://s.taobao.com/search?q={kw}",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)
        check_login_wall(page, "taobao")
        gentle_scroll(page, times=4)
        return page.evaluate(JS_GENERIC_MOBILE)
    except SessionExpired:
        raise
    except Exception as exc:
        dump_debug(page, f"tb_{item_id}")
        log(f"    淘宝搜索异常：{exc}")
        return []
    finally:
        page.close()


def _urlencode(s: str) -> str:
    from urllib.parse import quote

    return quote(s)


def pick_candidate(cands: list[dict], item: dict) -> dict | None:
    """按规则挑出目标商品：标题关键词命中 + 价格区间 + 优先自营 + 取最低价。"""
    must = [m.lower() for m in item.get("must_include", [])]
    excl = [m.lower() for m in item.get("exclude", [])]
    lo, hi = item.get("price_range", [0, 10 ** 9])
    ok = []
    for c in cands:
        t = c.get("title", "").lower()
        if any(m not in t for m in must):
            continue
        if any(x in t for x in excl):
            continue
        p = c.get("price")
        if not isinstance(p, (int, float)) or not (lo <= p <= hi):
            continue
        ok.append(c)
    if not ok:
        return None
    pool = [c for c in ok if c.get("self_op")] or ok
    return sorted(pool, key=lambda c: c["price"])[0]


def make_context(browser, state_path: Path, mobile: bool = False):
    kwargs = {
        "user_agent": UA_PC,
        "viewport": {"width": 1280, "height": 900} if not mobile else {"width": 440, "height": 900},
        "locale": "zh-CN",
    }
    if state_path.exists():
        kwargs["storage_state"] = str(state_path)
    return browser.new_context(**kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取京东/淘宝监控商品今日价格")
    parser.add_argument("--platform", choices=["jd", "taobao", "all"], default="all")
    parser.add_argument("--headed", action="store_true", help="有头模式（调试用）")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个商品")
    args = parser.parse_args()

    ensure_dirs()
    items = load_items()
    if args.limit:
        items = items[: args.limit]

    from playwright.sync_api import sync_playwright

    status: dict = {"date": today(), "results": {}}
    rows: list[dict] = []

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(
                    channel="msedge",
                    headless=not args.headed,
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception:
                log("未找到 Edge，回退到 Playwright 自带 Chromium（如报错请执行 playwright install chromium）")
                browser = pw.chromium.launch(headless=not args.headed)

            jd_ok = args.platform in ("jd", "all")
            tb_ok = args.platform in ("taobao", "all")
            jd_ctx = tb_ctx = None

            if jd_ok:
                if not (AUTH_DIR / "jd_state.json").exists():
                    log("!! 未找到京东登录态（auth/jd_state.json），请先运行 python scripts/login.py jd")
                    status["jd"] = "missing_login"
                    jd_ok = False
                else:
                    jd_ctx = make_context(browser, AUTH_DIR / "jd_state.json")
            if tb_ok:
                if not (AUTH_DIR / "taobao_state.json").exists():
                    log("!! 未找到淘宝登录态（auth/taobao_state.json），淘宝今日跳过（可选）")
                    status["taobao"] = "missing_login"
                    tb_ok = False
                else:
                    tb_ctx = make_context(browser, AUTH_DIR / "taobao_state.json")

            jd_dead = tb_dead = False

            for idx, item in enumerate(items, 1):
                iid = item["id"]
                status["results"][iid] = {}
                log(f"({idx}/{len(items)}) {item['model']} —— {item['keyword']}")

                if jd_ok and not jd_dead and jd_ctx:
                    try:
                        cands = search_jd(jd_ctx, item["keyword"], iid)
                        best = pick_candidate(cands, item)
                        if best:
                            log(f"    京东 ¥{best['price']:.0f}  {best['title'][:40]}")
                            rows.append(_row(item, "京东", best))
                            status["results"][iid]["jd"] = best["price"]
                        else:
                            log(f"    京东未命中（候选 {len(cands)} 条）")
                            status["results"][iid]["jd"] = None
                    except SessionExpired as exc:
                        log(f"    !! {exc}，今日京东后续跳过")
                        status["jd"] = "expired"
                        jd_dead = True
                        status["results"][iid]["jd"] = None

                if tb_ok and not tb_dead and tb_ctx:
                    try:
                        cands = search_taobao(tb_ctx, item["keyword"], iid)
                        best = pick_candidate(cands, item)
                        if best:
                            log(f"    淘宝 ¥{best['price']:.0f}  {best['title'][:40]}")
                            rows.append(_row(item, "淘宝", best))
                            status["results"][iid]["taobao"] = best["price"]
                        else:
                            log(f"    淘宝未命中（候选 {len(cands)} 条）")
                            status["results"][iid]["taobao"] = None
                    except SessionExpired as exc:
                        log(f"    !! {exc}，今日淘宝后续跳过")
                        status["taobao"] = "expired"
                        tb_dead = True
                        status["results"][iid]["taobao"] = None

            if jd_ctx and status.get("jd") != "expired":
                status["jd"] = "ok" if any(
                    v.get("jd") for v in status["results"].values()
                ) else "no_hits"
            if tb_ctx and status.get("taobao") != "expired":
                status["taobao"] = "ok" if any(
                    v.get("taobao") for v in status["results"].values()
                ) else "no_hits"
            if jd_ctx:
                jd_ctx.close()
            if tb_ctx:
                tb_ctx.close()
            browser.close()
    except Exception as exc:
        status["fatal"] = str(exc)
        log(f"!! 抓取流程异常：{exc}")

    status["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status["rows_today"] = len(rows)
    write_status(status)
    if rows:
        append_rows(rows)
        log(f"共写入 {len(rows)} 条价格记录 -> data/prices.csv")
    else:
        log("今日未获取到任何价格数据")
    return 0


def _row(item: dict, platform: str, best: dict) -> dict:
    return {
        "date": today(),
        "item_id": item["id"],
        "model": item["model"],
        "platform": platform,
        "form": item.get("form", ""),
        "brand": item.get("brand", ""),
        "chip": item.get("chip", ""),
        "price": f"{best['price']:.2f}",
        "shop": best.get("shop", ""),
        "title": best.get("title", "")[:200],
        "url": best.get("url", "")[:300],
    }


if __name__ == "__main__":
    raise SystemExit(main())
