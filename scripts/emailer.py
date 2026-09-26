"""通过 QQ 邮箱 SMTP 发送硬件日报（HTML 正文 + 内嵌走势图 + 日报附件）。"""
from __future__ import annotations

import smtplib
import ssl
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPORTS_DIR, load_env, today, weekday_cn  # noqa: E402


def send(report_html_path: Path, chart_paths: dict[str, Path]) -> tuple[bool, str]:
    load_env()
    import os

    account = os.environ.get("SMTP_ACCOUNT", "").strip()
    auth_code = os.environ.get("SMTP_AUTH_CODE", "").strip()
    to_email = os.environ.get("TO_EMAIL", "").strip() or account
    if not account or not auth_code:
        return False, ("缺少 SMTP_ACCOUNT / SMTP_AUTH_CODE（请在 .env 填入 QQ 邮箱授权码），"
                       "本次跳过发信。")

    date = today()
    msg = MIMEMultipart("related")
    msg["Subject"] = f"硬件日报 {date} {weekday_cn(date)}：迷你主机 / DDR5 / iQOO Neo 报价"
    msg["From"] = account
    msg["To"] = to_email

    body = report_html_path.read_text(encoding="utf-8")
    # 报告中的 cid:chart_xxx 引用对应的内嵌图片
    msg.attach(MIMEText(body, "html", "utf-8"))
    for group, path in chart_paths.items():
        if path.exists():
            img = MIMEImage(path.read_bytes())
            img.add_header("Content-ID", f"<chart_{group}>")
            img.add_header("Content-Disposition", "inline",
                           filename=path.name)
            msg.attach(img)
    if report_html_path.exists():
        att = MIMEText(report_html_path.read_bytes(), "base64", "utf-8")
        att.add_header("Content-Disposition", "attachment",
                       filename=report_html_path.name)
        msg.attach(att)

    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465,
                              context=ssl.create_default_context(),
                              timeout=60) as server:
            server.login(account, auth_code)
            server.sendmail(account, [to_email], msg.as_string())
        return True, f"已发送到 {to_email}"
    except Exception as exc:
        return False, f"发送失败：{exc}"


def main() -> int:
    from report import build_charts, build_report

    charts = build_charts()
    report_path = build_report(charts)
    ok, message = send(report_path, charts)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
