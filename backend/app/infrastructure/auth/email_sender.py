from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


class EmailSenderError(Exception):
    pass


class EmailSenderConfigurationError(EmailSenderError):
    pass


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise EmailSenderConfigurationError(f"缺少 SMTP 配置：{name}")
    return value


def send_register_verification_email(email: str, code: str, expires_in_minutes: int = 10) -> None:
    host = _require_env("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587") or "587")
    username = _require_env("SMTP_USERNAME")
    password = _require_env("SMTP_PASSWORD")
    from_email = _require_env("SMTP_FROM_EMAIL")
    from_name = os.getenv("SMTP_FROM_NAME", "").strip() or "Learning Assistant"
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    message = EmailMessage()
    message["Subject"] = "Learning Assistant 注册验证码"
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = email
    message.set_content(
        "\n".join(
            [
                "你好，",
                "",
                "你正在注册 Learning Assistant 账号。",
                f"本次验证码：{code}",
                f"验证码有效期：{expires_in_minutes} 分钟",
                "",
                "如果这不是你的操作，请忽略这封邮件。",
            ]
        )
    )

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            if use_tls:
                server.starttls()
                server.ehlo()
            server.login(username, password)
            server.send_message(message)
    except EmailSenderConfigurationError:
        raise
    except Exception as exc:  # pragma: no cover - exact SMTP failures vary by env
        raise EmailSenderError("SMTP 发信失败，请稍后重试") from exc

