#!/usr/bin/env python3
"""Send an ops alert email using ALERT_* SMTP settings from the environment."""
import os
import smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg["Subject"] = "[oentbox] server alert"
msg["From"] = (
    os.environ.get("ALERT_EMAIL_FROM")
    or os.environ.get("ALERT_SMTP_USER")
    or ("oentbox@" + os.uname().nodename)
)
msg["To"] = os.environ["ALERT_TO"]
msg.set_content(os.environ.get("ALERT_TEXT", ""))

host = os.environ["ALERT_SMTP_HOST"]
port = int(os.environ.get("ALERT_SMTP_PORT", "587"))
user = os.environ.get("ALERT_SMTP_USER")
password = os.environ.get("ALERT_SMTP_PASSWORD")

with smtplib.SMTP(host, port, timeout=20) as smtp:
    if os.environ.get("ALERT_SMTP_TLS", "1") == "1":
        smtp.starttls()
    if user and password:
        smtp.login(user, password)
    smtp.send_message(msg)
