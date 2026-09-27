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
import random
import re
import subprocess
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
  const seen = new Set();
  // 2026 新版搜索页：div[data-sku] 商品卡片
  document.querySelectorAll('div[data-sku]').forEach(card => {
    if (!/plugin_goodsCardWrapper/.test(card.className || '')) return;
    const sku = card.getAttribute('data-sku');
    if (!sku || seen.has(sku)) return;
    const t1 = card.querySelector('[class*="_goods_title_container"]');
    const t2 = card.querySelector('[title]');
    const c1 = t1 ? (t1.textContent || '').replace(/\s+/g, ' ').trim() : '';
    const c2 = t2 ? (t2.getAttribute('title') || '').replace(/\s+/g, ' ').trim() : '';
    const title = c2.length > c1.length ? c2 : c1;
    if (!title) return;
    let price = NaN;
    for (const pe of card.querySelectorAll('[class*="_price_"]')) {
      const m = (pe.textContent || '').replace(/,/g, '').match(/([0-9]+(?:\.[0-9]+)?)/);
      if (m) { price = parseFloat(m[1]); break; }
    }
    if (!isFinite(price) || price <= 0) return;
    seen.add(sku);
    out.push({
      title: title.slice(0, 200),
      price: price,
      url: 'https://item.jd.com/' + sku + '.html',
      shop: '',
      self_op: /自营|官方旗舰店|京东超市/.test(card.textContent || ''),
    });
  });
  if (out.length) return out;
  // 旧版搜索页兜底
  document.querySelectorAll('li.gl-item, #J_goodsList li').forEach(li => {
    const a = li.querySelector('.p-name a, a[href*="item.jd.com"]');
    const priceEl = li.querySelector('.p-price i, .p-price strong i');
    const title = a ? (a.getAttribute('title') || a.textContent || '') : '';
    const price = priceEl ? parseFloat((priceEl.textContent || '').replace(/[^0-9.]/g, '')) : NaN;
    if (!title || !isFinite(price)) return;
    out.push({
      title: title.trim().slice(0, 200),
      price: price,
      url: a ? a.href : '',
      shop: '',
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


class RateLimited(Exception):
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


def search_jd(page, keyword: str, item_id: str) -> list[dict]:
    """京东：PC 搜索优先，失败再试手机版搜索（page 为原生浏览器中的复用页面）。

    注意：手机版搜索的登录墙只影响本条商品，不能据此判定整个京东会话失效
    （PC 搜索在同一会话下通常仍可用）。
    """
    try:
        kw = _urlencode(keyword)
        page.goto(f"https://search.jd.com/Search?keyword={kw}&enc=utf-8",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        check_login_wall(page, "jd")
        gentle_scroll(page)
        cands = page.evaluate(JS_JD_PC)
        if not cands:
            dump_debug(page, f"jd_empty_{item_id}")
            body = ""
            try:
                body = page.inner_text("body")[:3000]
            except Exception:
                pass
            if "访问频繁" in body or "无法搜索" in body:
                raise RateLimited("京东搜索频控：访问频繁")
            if "京东验证" in body or "快速验证" in body:
                raise RateLimited("京东弹出人工安全验证（需在浏览器中手动通过滑块）")
        if cands:
            return cands
        # 回退：手机版搜索（撞登录墙时仅跳过本条）
        log(f"    京东PC搜索无结果，尝试手机版搜索")
        page.goto(f"https://so.m.jd.com/ware/search.action?keyword={kw}",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        url = page.url or ""
        if "passport.jd.com" in url or "plogin.m.jd.com" in url:
            log("    手机版搜索需登录，本条跳过")
            return []
        gentle_scroll(page, times=4)
        return page.evaluate(JS_GENERIC_MOBILE)
    except RateLimited:
        raise  # 频控必须交给上层做退避重试，不能在这里吞掉
    except Exception as exc:
        dump_debug(page, f"jd_{item_id}")
        log(f"    京东搜索异常：{exc}")
        return []


JS_TAOBAO_PC = r"""
() => {
  const out = [];
  const seen = new Set();
  const anchors = document.querySelectorAll(
    'a[href*="item.taobao.com"], a[href*="detail.tmall.com"], a[href*="chaoshi.detail.tmall.com"]');
  anchors.forEach(a => {
    // 从锚点向上找"最小的含价格容器"作为商品卡片
    let el = a, card = null;
    for (let i = 0; i < 8 && el; i++) {
      el = el.parentElement;
      if (!el) break;
      const t = el.textContent || '';
      if (/¥\s*[0-9]/.test(t) && t.length < 800) { card = el; break; }
    }
    if (!card) return;
    // 从专用价格元素取价（避免价格与销量数字粘连成 4599200 之类）
    let price = NaN;
    for (const pe of card.querySelectorAll('[class*="price" i]')) {
      const t = (pe.textContent || '').replace(/[,\s]/g, '');
      const m = t.match(/¥?([0-9]{2,7}(?:\.[0-9]{1,2})?)$/);
      if (m && t.length <= 12) { price = parseFloat(m[1]); break; }
    }
    if (!isFinite(price) || price <= 0) return;
    let title = '';
    const tEl = card.querySelector('[class*="title" i]');
    if (tEl) title = (tEl.textContent || '').replace(/\s+/g, ' ').trim();
    if (title.length < 8) {
      title = (a.getAttribute('aria-label') || a.title || a.textContent || '').replace(/\s+/g, ' ').trim();
    }
    if (!title || title.length < 8) return;
    const key = title.slice(0, 60) + '|' + price;
    if (seen.has(key)) return;
    seen.add(key);
    const idm = (a.href || '').match(/id=(\d+)/);
    const url = idm ? 'https://item.taobao.com/item.htm?id=' + idm[1] : a.href;
    out.push({
      title: title.slice(0, 200),
      price: price,
      url: url,
      shop: '',
      self_op: /天猫|官方|旗舰店/.test(card.textContent || ''),
    });
  });
  return out.slice(0, 40);
}
"""


def search_taobao(page, keyword: str, item_id: str) -> list[dict]:
    """淘宝 PC 搜索（page 为原生浏览器中的复用页面）。"""
    try:
        kw = _urlencode(keyword)
        page.goto(f"https://s.taobao.com/search?q={kw}",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)
        check_login_wall(page, "taobao")
        gentle_scroll(page, times=4)
        cands = page.evaluate(JS_TAOBAO_PC)
        if not cands:
            dump_debug(page, f"tb_empty_{item_id}")
            body = ""
            try:
                body = page.inner_text("body")[:3000]
            except Exception:
                pass
            if "亲，请登录" in body:
                raise SessionExpired("淘宝会话未生效（页面显示未登录）")
            if any(k in body for k in ("访问受限", "亲，太抱歉", "验证码", "安全验证")):
                raise RateLimited("淘宝风控拦截（需人工验证）")
        return cands
    except (RateLimited, SessionExpired):
        raise
    except Exception as exc:
        dump_debug(page, f"tb_{item_id}")
        log(f"    淘宝搜索异常：{exc}")
        return []


def _urlencode(s: str) -> str:
    from urllib.parse import quote

    return quote(s)


def pick_candidate(cands: list[dict], item: dict) -> dict | None:
    """按规则挑出目标商品：标题关键词命中 + 价格区间 + 优先自营 + 取最低价。"""
    # 全局排除：二手/翻新/扩容/水货等不可比商品
    global_excludes = ["二手", "翻新", "扩容", "官换", "港版", "韩版", "回收", "准新"]
    must = [m.lower() for m in item.get("must_include", [])]
    excl = [m.lower() for m in item.get("exclude", [])] + global_excludes
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


JD_PROFILE = AUTH_DIR / "edge_profile_jd"
TB_PROFILE = AUTH_DIR / "edge_profile_taobao"


def start_native(pw, profile: Path, state_path: Path | None = None):
    """原生启动 Edge（指定登录档案），返回 (proc, ctx)；失败返回 (proc, None)。

    京东/淘宝的风控都会拦截"无头/自动化浏览器"的搜索（即使携带有效登录
    Cookie），但对真实 Edge 窗口放行，因此抓取必须在原生浏览器中进行，
    Python 仅通过 CDP 读取页面数据。
    若提供 state_path（登录时导出的 storage_state），会将会话 Cookie 注入
    浏览器——即使档案未及时落盘也能保证会话新鲜。
    """
    from login import find_browser, free_port, kill_stale_edge

    exe = find_browser()
    kill_stale_edge(profile)
    port = free_port()
    proc = subprocess.Popen(
        [exe, f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
         "--no-first-run", "--no-default-browser-check",
         "--disable-blink-features=AutomationControlled",
         "--window-size=1280,860", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(1)
        try:
            b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=3000)
            if b.contexts:
                ctx = b.contexts[0]
                if state_path and Path(state_path).exists():
                    try:
                        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
                        cookies = state.get("cookies", [])
                        if cookies:
                            ctx.add_cookies(cookies)
                            log(f"    已注入登录会话（{len(cookies)} 条 Cookie）")
                    except Exception as exc:
                        log(f"    会话注入失败（改用档案自带 Cookie）：{exc}")
                return proc, ctx
        except Exception:
            continue
    return proc, None


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
            jd_ok = args.platform in ("jd", "all")
            tb_ok = args.platform in ("taobao", "all")
            jd_proc = tb_proc = None
            jd_page = tb_page = None

            if jd_ok:
                # 京东抓取在原生 Edge（登录档案）中进行——无头自动化会被风控拦截
                if not JD_PROFILE.exists():
                    log("!! 未找到京东登录档案（auth/edge_profile_jd），请先运行 python scripts/login.py jd")
                    status["jd"] = "missing_login"
                    jd_ok = False
                else:
                    jd_proc, jd_ctx = start_native(pw, JD_PROFILE, AUTH_DIR / "jd_state.json")
                    if jd_ctx is None:
                        log("!! 京东浏览器启动/连接失败")
                        status["jd"] = "start_failed"
                        jd_ok = False
                    else:
                        jd_page = jd_ctx.pages[0] if jd_ctx.pages else jd_ctx.new_page()
            if tb_ok:
                if not TB_PROFILE.exists():
                    log("!! 未找到淘宝登录档案（auth/edge_profile_taobao），请先运行 python scripts/login.py taobao")
                    status["taobao"] = "missing_login"
                    tb_ok = False
                else:
                    tb_proc, tb_ctx = start_native(pw, TB_PROFILE, AUTH_DIR / "taobao_state.json")
                    if tb_ctx is None:
                        log("!! 淘宝浏览器启动/连接失败")
                        status["taobao"] = "start_failed"
                        tb_ok = False
                    else:
                        tb_page = tb_ctx.pages[0] if tb_ctx.pages else tb_ctx.new_page()

            jd_dead = tb_dead = False

            for idx, item in enumerate(items, 1):
                iid = item["id"]
                status["results"][iid] = {}
                log(f"({idx}/{len(items)}) {item['model']} —— {item['keyword']}")

                if jd_ok and not jd_dead and jd_page:
                    try:
                        cands = search_jd(jd_page, item["keyword"], iid)
                        best = pick_candidate(cands, item)
                        if best:
                            log(f"    京东 ¥{best['price']:.0f}  {best['title'][:40]}")
                            rows.append(_row(item, "京东", best))
                            status["results"][iid]["jd"] = best["price"]
                        else:
                            log(f"    京东未命中（候选 {len(cands)} 条）")
                            status["results"][iid]["jd"] = None
                    except RateLimited:
                        log("    !! 命中京东频控，等待 100 秒后重试一次……")
                        time.sleep(100)
                        try:
                            cands = search_jd(jd_page, item["keyword"], iid)
                            best = pick_candidate(cands, item)
                            if best:
                                log(f"    京东 ¥{best['price']:.0f}  {best['title'][:40]}")
                                rows.append(_row(item, "京东", best))
                                status["results"][iid]["jd"] = best["price"]
                            else:
                                log(f"    重试仍未命中（候选 {len(cands)} 条）")
                                status["results"][iid]["jd"] = None
                        except RateLimited:
                            log("    !! 仍被频控/需人工验证，今日京东剩余商品全部跳过")
                            status["jd"] = "rate_limited"
                            status["results"][iid]["jd"] = None
                            jd_dead = True
                    except SessionExpired as exc:
                        log(f"    !! {exc}，今日京东后续跳过")
                        status["jd"] = "expired"
                        jd_dead = True
                        status["results"][iid]["jd"] = None

                if tb_ok and not tb_dead and tb_page:
                    try:
                        cands = search_taobao(tb_page, item["keyword"], iid)
                        best = pick_candidate(cands, item)
                        if best:
                            log(f"    淘宝 ¥{best['price']:.0f}  {best['title'][:40]}")
                            rows.append(_row(item, "淘宝", best))
                            status["results"][iid]["taobao"] = best["price"]
                        else:
                            log(f"    淘宝未命中（候选 {len(cands)} 条）")
                            status["results"][iid]["taobao"] = None
                    except RateLimited:
                        log("    !! 命中淘宝风控，等待 100 秒后重试一次……")
                        time.sleep(100)
                        try:
                            cands = search_taobao(tb_page, item["keyword"], iid)
                            best = pick_candidate(cands, item)
                            if best:
                                log(f"    淘宝 ¥{best['price']:.0f}  {best['title'][:40]}")
                                rows.append(_row(item, "淘宝", best))
                                status["results"][iid]["taobao"] = best["price"]
                            else:
                                log(f"    重试仍未命中（候选 {len(cands)} 条）")
                                status["results"][iid]["taobao"] = None
                        except RateLimited:
                            log("    !! 仍被淘宝风控拦截，今日淘宝剩余商品全部跳过")
                            status["taobao"] = "rate_limited"
                            status["results"][iid]["taobao"] = None
                            tb_dead = True
                    except SessionExpired as exc:
                        log(f"    !! {exc}，今日淘宝后续跳过")
                        status["taobao"] = "expired"
                        tb_dead = True
                        status["results"][iid]["taobao"] = None

                # 商品之间随机间隔，避免触发京东搜索频控
                if idx < len(items) and not (jd_dead and tb_dead):
                    time.sleep(random.uniform(20, 35))

            if jd_page and status.get("jd") not in ("expired", "rate_limited"):
                status["jd"] = "ok" if any(
                    v.get("jd") for v in status["results"].values()
                ) else "no_hits"
            if tb_page and status.get("taobao") not in ("expired", "rate_limited"):
                status["taobao"] = "ok" if any(
                    v.get("taobao") for v in status["results"].values()
                ) else "no_hits"
            if jd_proc or tb_proc:
                # 关闭原生浏览器（kill_stale_edge 按档案名定向清理）
                from login import kill_stale_edge
                if jd_proc:
                    kill_stale_edge(JD_PROFILE)
                if tb_proc:
                    kill_stale_edge(TB_PROFILE)
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
