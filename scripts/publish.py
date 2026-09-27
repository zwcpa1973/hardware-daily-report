"""更新 README 的自动段落与 Pages 首页，并提交推送到 GitHub。"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    CHARTS_DIR, REPORTS_DIR, ROOT, load_items, read_all_rows, read_status,
    today, weekday_cn,
)

BEGIN = "<!-- AUTO:BEGIN -->"
END = "<!-- AUTO:END -->"


def _latest_rows() -> list[dict]:
    rows = read_all_rows()
    if not rows:
        return []
    last = max(r["date"] for r in rows)
    return [r for r in rows if r["date"] == last]


def _markdown_section() -> str:
    rows = _latest_rows()
    items = {it["id"]: it for it in load_items()}
    status = read_status()
    if not rows:
        return (f"{BEGIN}\n### 最新数据\n\n暂无数据。请先运行 `python scripts/login.py` 完成登录，"
                f"再运行 `run_daily.bat` 开始采集。\n"
                f"图表占位：`output/charts/`（首次采集后自动生成）\n"
                f"### 走势图\n\n"
                f"![整机](output/charts/chart_machines.png)\n\n"
                f"![DDR5](output/charts/chart_ddr5.png)\n\n"
                f"![Neo](output/charts/chart_neo.png)\n"
                f"{END}")

    last_date = rows[0]["date"]
    by_item: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_item.setdefault(r["item_id"], {})[r["platform"]] = r
    dates = sorted({r["date"] for r in read_all_rows()})

    lines = [BEGIN, f"### 最新数据（{last_date}，累计 {len(dates)} 天）", ""]
    for group, title in (
        ("machines", "整机（迷你主机 / 笔记本 / 台式机）"),
        ("ddr5", "DDR5 内存"),
        ("neo", "iQOO Neo 手机"),
    ):
        lines += [f"#### {title}", "", "| 商品 | 芯片 | 京东 | 淘宝 |", "|---|---|---|---|"]
        for iid, platforms in by_item.items():
            it = items.get(iid)
            if not it or it.get("group") != group:
                continue
            jd = platforms.get("京东")
            tb = platforms.get("淘宝")
            jd_p = f"¥{float(jd['price']):.0f}" if jd else "—"
            tb_p = f"¥{float(tb['price']):.0f}" if tb else "—"
            link = jd["url"] if jd and jd.get("url") else (tb.get("url") if tb else "")
            name = f"[{it['model']}]({link})" if link else it["model"]
            lines.append(f"| {name} | {it.get('chip', '')} | {jd_p} | {tb_p} |")
        lines.append("")

    lines += ["### 报价走势图", "",
              "![整机](output/charts/chart_machines.png)", "",
              "![DDR5 内存](output/charts/chart_ddr5.png)", "",
              "![iQOO Neo](output/charts/chart_neo.png)", "",
              f"> 更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}（本地任务自动推送）",
              "", END]
    return "\n".join(lines)


def update_readme() -> None:
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    section = _markdown_section()
    if BEGIN in text and END in text:
        pre = text.split(BEGIN)[0]
        post = text.split(END)[1]
        text = pre + section + post
    else:
        text = text.rstrip() + "\n\n" + section + "\n"
    readme.write_text(text, encoding="utf-8")


def update_index() -> None:
    """GitHub Pages 首页：列出全部历史日报链接 + 三张图。"""
    reports = sorted(REPORTS_DIR.glob("hw_report_*.html"), reverse=True)
    items = [f'<li><a href="output/reports/{p.name}">{p.stem.replace("hw_report_", "")}</a></li>'
             for p in reports[:60]]
    date = today()
    html_doc = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>硬件日报</title><style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:900px;margin:0 auto;padding:20px;background:#fafafa;color:#222}}
h1{{border-bottom:3px solid #c0392b;padding-bottom:8px}}
img{{max-width:100%;border:1px solid #ddd;border-radius:6px;margin:8px 0}}
a{{color:#2980b9}} ul{{columns:2;font-size:14px}}
</style></head><body>
<h1>硬件日报归档</h1>
<p>迷你主机 / 笔记本 / 台式机（AMD · Intel · Apple）· DDR5 内存 · iQOO Neo 手机
—— 数据来自京东、淘宝每日 17:00 自动采集。</p>
<h2>走势图（{date} 更新）</h2>
<img src="output/charts/chart_machines.png" alt="整机走势">
<img src="output/charts/chart_ddr5.png" alt="DDR5 走势">
<img src="output/charts/chart_neo.png" alt="Neo 手机走势">
<h2>历史日报</h2>
<ul>{''.join(items) or '<li>暂无</li>'}</ul>
</body></html>"""
    (ROOT / "index.html").write_text(html_doc, encoding="utf-8")


def git_push() -> tuple[bool, str]:
    import os

    os.environ.setdefault("GIT_EDITOR", "true")  # rebase --continue 非交互

    def run(*cmd: str) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def commit_if_any() -> None:
        run("git", "add", "-A")
        if run("git", "diff", "--cached", "--quiet").returncode != 0:
            run("git", "commit", "-m", f"日报更新 {today()}")

    commit_if_any()
    push = run("git", "push")
    if push.returncode != 0 and ("rejected" in (push.stdout + push.stderr)
                                 or "fetch first" in (push.stdout + push.stderr)):
        # 远端有新提交：rebase，-X theirs 使生成的报表/图表冲突时以本次新生成的为准
        pull = run("git", "pull", "--rebase", "-X", "theirs", "--autostash")
        if pull.returncode != 0:
            run("git", "rebase", "--abort")
            commit_if_any()
        push = run("git", "push")
    if push.returncode != 0:
        run("git", "rebase", "--abort")
        return False, f"推送失败：{(push.stderr or push.stdout).strip()[:300]}"
    return True, "已提交并推送 GitHub"


def main() -> int:
    update_readme()
    update_index()
    ok, message = git_push()
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
