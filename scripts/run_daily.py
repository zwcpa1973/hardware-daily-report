"""每日总调度：抓取 -> 出图出报告 -> 发邮件 -> 推送 GitHub。

用法：
    python scripts/run_daily.py                 # 全流程
    python scripts/run_daily.py --no-scrape     # 只重新出图/发信/推送
    python scripts/run_daily.py --no-email      # 抓取+出图+推送，不发信
    python scripts/run_daily.py --no-push       # 不推送 GitHub
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="硬件日报每日任务")
    parser.add_argument("--no-scrape", action="store_true")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    log("========== 硬件日报开始 ==========")

    if not args.no_scrape:
        log("步骤 1/4 抓取价格 ...")
        import scrape

        try:
            scrape.main()
        except SystemExit:
            pass
        except Exception:
            log("抓取异常：\n" + traceback.format_exc())
    else:
        log("步骤 1/4 跳过抓取")

    log("步骤 2/4 生成图表与日报 ...")
    import report

    charts = report.build_charts()
    report_path = report.build_report(charts)
    log(f"图表与日报完成：{report_path.name}")

    if not args.no_email:
        log("步骤 3/4 发送邮件 ...")
        import emailer

        ok, message = emailer.send(report_path, charts)
        log(("  " if ok else "!! ") + message)
    else:
        log("步骤 3/4 跳过发信")

    if not args.no_push:
        log("步骤 4/4 推送 GitHub ...")
        import publish

        publish.main()
    else:
        log("步骤 4/4 跳过推送")

    log("========== 硬件日报结束 ==========")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
