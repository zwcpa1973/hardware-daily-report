"""生成走势图与 HTML 日报。

输出：
    output/charts/chart_machines.png   整机（迷你主机/笔记本/台式机）走势
    output/charts/chart_ddr5.png       DDR5 内存走势
    output/charts/chart_neo.png        iQOO Neo 系列走势
    output/reports/hw_report_YYYY-MM-DD.html
"""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    CHARTS_DIR, REPORTS_DIR, ensure_dirs, load_items, read_all_rows,
    read_status, today, weekday_cn,
)

GROUP_TITLES = {
    "machines": "整机报价走势（迷你主机 / 笔记本 / 台式机）",
    "ddr5": "DDR5 内存报价走势",
    "neo": "iQOO Neo 系列手机报价走势",
}


def _setup_font():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC",
        "PingFang SC", "WenQuanYi Micro Hei", "Arial Unicode MS", "sans-serif",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _placeholder(plt, path: Path, text: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
    ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=16, color="#888")
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_lines(ax, series: dict[str, dict[str, float]], dates: list[str]) -> None:
    """series: model -> {date: price}"""
    colors = ["#c0392b", "#2980b9", "#27ae60", "#8e44ad", "#e67e22",
              "#16a085", "#d35400", "#2c3e50", "#7f8c8d", "#f39c12"]
    for i, (model, points) in enumerate(series.items()):
        xs, ys = [], []
        for d in dates:
            if d in points:
                xs.append(d)
                ys.append(points[d])
        if not xs:
            continue
        c = colors[i % len(colors)]
        ax.plot(xs, ys, marker="o", markersize=4, linewidth=1.8, label=model, color=c)
        ax.annotate(f"{ys[-1]:.0f}", (xs[-1], ys[-1]),
                    textcoords="offset points", xytext=(6, 4),
                    fontsize=8, color=c)
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(fontsize=8, loc="best")


def build_charts(only_jd: bool = True) -> dict[str, Path]:
    plt = _setup_font()
    ensure_dirs()
    rows = read_all_rows()
    items = {it["id"]: it for it in load_items()}

    if only_jd and rows:
        # 同时抓到京东与淘宝时，图表用京东价为主（口径统一），表格里两个平台都展示
        rows = [r for r in rows if r["platform"] == "京东"] or rows

    dates = sorted({r["date"] for r in rows})
    tick = max(1, len(dates) // 8)  # 日期标签过密时抽稀

    def series_for(ids: list[str]) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for iid in ids:
            pts = {r["date"]: float(r["price"]) for r in rows if r["item_id"] == iid}
            if pts:
                model = items.get(iid, {}).get("model", iid)
                out[model] = pts
        return out

    paths: dict[str, Path] = {}

    # ---- 图 1：整机（按形态分三个子图） ----
    p1 = CHARTS_DIR / "chart_machines.png"
    machine_ids = [iid for iid, it in items.items() if it.get("group") == "machines"]
    forms = ["迷你主机", "笔记本", "台式机"]
    any_data = any(series_for([iid]) for iid in machine_ids)
    if not any_data:
        _placeholder(plt, p1, "暂无数据：请先完成登录并运行一次抓取")
    else:
        fig, axes = plt.subplots(
            len(forms), 1, figsize=(10, 12), dpi=150, sharex=True,
        )
        for ax, form in zip(axes, forms):
            ids = [iid for iid, it in items.items()
                   if it.get("group") == "machines" and it.get("form") == form]
            s = series_for(ids)
            ax.set_title(form, fontsize=12, loc="left", fontweight="bold")
            if s:
                _plot_lines(ax, s, dates)
            else:
                ax.text(0.5, 0.5, "暂无数据", ha="center", va="center",
                        fontsize=11, color="#999", transform=ax.transAxes)
        axes[-1].set_xticks(range(0, len(dates), tick))
        axes[-1].set_xticklabels(dates[::tick], rotation=30, ha="right", fontsize=8)
        fig.suptitle(GROUP_TITLES["machines"], fontsize=14, fontweight="bold")
        fig.tight_layout(rect=(0, 0, 1, 0.98))
        fig.savefig(p1)
        plt.close(fig)
    paths["machines"] = p1

    # ---- 图 2 / 图 3：DDR5 与 Neo ----
    for group, fname in (("ddr5", "chart_ddr5.png"), ("neo", "chart_neo.png")):
        path = CHARTS_DIR / fname
        ids = [iid for iid, it in items.items() if it.get("group") == group]
        s = series_for(ids)
        if not s:
            _placeholder(plt, path, "暂无数据：请先完成登录并运行一次抓取")
        else:
            fig, ax = plt.subplots(figsize=(10, 4.8), dpi=150)
            _plot_lines(ax, s, dates)
            ax.set_xticks(range(0, len(dates), tick))
            ax.set_xticklabels(dates[::tick], rotation=30, ha="right", fontsize=8)
            ax.set_title(GROUP_TITLES[group], fontsize=13, fontweight="bold")
            fig.tight_layout()
            fig.savefig(path)
            plt.close(fig)
        paths[group] = path

    return paths


# ---------- HTML 日报 ----------

CSS = """
body{font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;max-width:860px;
     margin:0 auto;padding:16px;color:#222;background:#fafafa;}
h1{font-size:20px;border-bottom:3px solid #c0392b;padding-bottom:8px;}
h2{font-size:16px;margin-top:26px;border-left:4px solid #c0392b;padding-left:8px;}
table{border-collapse:collapse;width:100%;font-size:13px;background:#fff;}
th{background:#34495e;color:#fff;padding:6px 8px;text-align:left;}
td{border-bottom:1px solid #eee;padding:6px 8px;}
tr:hover td{background:#f4f8fb;}
.up{color:#c0392b;font-weight:bold;}
.down{color:#27ae60;font-weight:bold;}
img{max-width:100%;border:1px solid #ddd;border-radius:6px;margin-top:8px;}
.note{background:#fff8e1;border:1px solid #f0db9b;padding:8px 12px;border-radius:6px;
      font-size:12px;color:#7a6200;margin-top:12px;}
.footer{color:#999;font-size:11px;margin-top:24px;text-align:center;}
.muted{color:#999;}
"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _latest_table(rows: list[dict], items: list[dict]) -> str:
    """最新一天各商品价格表（含日涨跌与相对首日涨跌）。"""
    by_item: dict[str, list[dict]] = {}
    for r in rows:
        by_item.setdefault(r["item_id"], []).append(r)

    def price_on(iid: str, platform: str, date: str):
        vals = [float(r["price"]) for r in by_item.get(iid, [])
                if r["platform"] == platform and r["date"] == date]
        return vals[0] if vals else None

    dates = sorted({r["date"] for r in rows})
    last_date = dates[-1] if dates else None
    prev_date = dates[-2] if len(dates) >= 2 else None

    out = ['<table><tr><th>商品</th><th>平台</th><th>最新价</th>',
           '<th>日涨跌</th><th>相对首日</th><th>链接</th></tr>']
    for it in items:
        iid = it["id"]
        for platform in ("京东", "淘宝"):
            cur = price_on(iid, platform, last_date) if last_date else None
            if cur is None:
                continue
            prev = price_on(iid, platform, prev_date) if prev_date else None
            first_vals = [float(r["price"]) for r in by_item.get(iid, [])
                          if r["platform"] == platform]
            first = min(first_vals) if first_vals else None
            url = next((r["url"] for r in by_item.get(iid, [])
                        if r["platform"] == platform and r["date"] == last_date), "")
            day_html = first_html = '<span class="muted">—</span>'
            if prev:
                d = cur - prev
                day_html = (f'<span class="up">▲{d:.0f}</span>' if d > 0
                            else f'<span class="down">▼{abs(d):.0f}</span>' if d < 0
                            else "持平")
            if first and len(first_vals) > 1:
                pct = (cur - first) / first * 100
                first_html = (f'<span class="up">+{pct:.1f}%</span>' if pct > 0
                              else f'<span class="down">{pct:.1f}%</span>')
            link = f'<a href="{esc(url)}">看</a>' if url else ""
            out.append(
                f'<tr><td>{esc(it["model"])}<br>'
                f'<span class="muted">{esc(it.get("chip", ""))} · {esc(it.get("form", ""))}</span></td>'
                f'<td>{esc(platform)}</td><td>¥{cur:.0f}</td><td>{day_html}</td>'
                f'<td>{first_html}</td><td>{link}</td></tr>')
    out.append("</table>")
    return "".join(out)


def build_report(chart_paths: dict[str, Path]) -> Path:
    ensure_dirs()
    rows = read_all_rows()
    items = load_items()
    status = read_status()
    date = today()

    tables = ""
    for group in ("machines", "ddr5", "neo"):
        group_items = [it for it in items if it.get("group") == group]
        tables += f'<h2>{GROUP_TITLES[group]}</h2>'
        tables += _latest_table(rows, group_items)
        tables += f'<img src="cid:chart_{group}" alt="{esc(GROUP_TITLES[group])}">'

    notes = []
    jd_st = status.get("jd")
    tb_st = status.get("taobao")
    if jd_st == "expired":
        notes.append("京东登录态已过期：请运行 python scripts/login.py jd 重新扫码。")
    if jd_st == "missing_login":
        notes.append("尚未登录京东：请运行 python scripts/login.py jd 扫码登录。")
    if tb_st == "missing_login":
        notes.append("尚未登录淘宝（可选）：运行 python scripts/login.py taobao 可补充淘宝报价。")
    if tb_st == "expired":
        notes.append("淘宝登录态已过期：请运行 python scripts/login.py taobao 重新扫码。")
    miss = [iid for iid, v in (status.get("results") or {}).items()
            if v and v.get("jd") is None]
    if miss:
        names = {it["id"]: it["model"] for it in items}
        notes.append("今日京东未命中的商品：" + "、".join(names.get(i, i) for i in miss))
    if not rows:
        notes.append("暂无历史数据：首次运行抓取后即可开始积累走势。")
    notes_html = f'<div class="note">{"；".join(esc(n) for n in notes)}</div>' if notes else ""

    n_days = len({r["date"] for r in rows})
    doc = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>硬件日报 {date}</title><style>{CSS}</style></head><body>
<h1>硬件日报 · {date} {weekday_cn(date)}</h1>
<p class="muted">迷你主机 / 笔记本 / 台式机（AMD · Intel · Apple）· DDR5 内存 · iQOO Neo 手机
—— 数据来自京东、淘宝实时搜索，共积累 {n_days} 天。</p>
{notes_html}
{tables}
<div class="footer">由硬件日报机器人自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}
· GitHub 归档与全部走势图见仓库 README</div>
</body></html>"""
    path = REPORTS_DIR / f"hw_report_{date}.html"
    path.write_text(doc, encoding="utf-8")
    return path


def main() -> int:
    charts = build_charts()
    report_path = build_report(charts)
    print(f"图表：{list(charts.values())}")
    print(f"日报：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
