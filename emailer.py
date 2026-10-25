"""Отчёты о покупках на почту владельца (Gmail + пароль приложения)."""
import asyncio
import logging
import smtplib
import ssl
import time
from email.mime.text import MIMEText

from config import SMTP_EMAIL, SMTP_PASSWORD, REPORT_EMAIL

log = logging.getLogger("mcgen.email")


def _send(subject: str, body: str):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        log.warning("SMTP не настроен (.env) — отчёт не отправлен: %s", subject)
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_EMAIL
    msg["To"] = REPORT_EMAIL
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(SMTP_EMAIL, SMTP_PASSWORD)
        s.sendmail(SMTP_EMAIL, [REPORT_EMAIL], msg.as_string())


async def notify_purchase(username: str, uid: int, tier_label: str, stars: int, charge_id: str):
    body = (
        "Новая покупка в MCGen Bot\n\n"
        f"Пользователь: @{username} (ID: {uid})\n"
        f"Тариф: {tier_label}\n"
        f"Звёзд: {stars}\n"
        f"Дата: {time.strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"Платёж (для возврата): {charge_id}\n"
    )
    try:
        await asyncio.to_thread(_send, f"💰 Подписка «{tier_label}» — {stars}⭐", body)
    except Exception:
        log.exception("Не удалось отправить email-отчёт")
