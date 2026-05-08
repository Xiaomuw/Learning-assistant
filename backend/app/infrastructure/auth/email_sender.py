from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


_SMTP_PLACEHOLDER_MARKERS = (
    "example.com",
    "your-smtp-",
    "replace-with",
    "placeholder",
    "no-reply@example.com",
)


class EmailSenderError(Exception):
    pass


class EmailSenderConfigurationError(EmailSenderError):
    pass


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return any(marker in normalized for marker in _SMTP_PLACEHOLDER_MARKERS)


def _require_smtp_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise EmailSenderConfigurationError(f"缺少 SMTP 配置：{name}")
    if _looks_like_placeholder(value):
        raise EmailSenderConfigurationError(f"SMTP 配置仍是占位值：{name}")
    return value


def _get_smtp_port() -> int:
    raw_port = os.getenv("SMTP_PORT", "587").strip() or "587"
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise EmailSenderConfigurationError("SMTP_PORT 必须是有效端口号") from exc
    if port <= 0 or port > 65535:
        raise EmailSenderConfigurationError("SMTP_PORT 必须是有效端口号")
    return port


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _message_id_domain(from_email: str) -> str | None:
    if "@" not in from_email:
        return None
    domain = from_email.rsplit("@", 1)[1].strip()
    return domain or None


def send_register_verification_email(email: str, code: str, expires_in_minutes: int = 10) -> None:
    host = _require_smtp_env("SMTP_HOST")
    port = _get_smtp_port()
    username = _require_smtp_env("SMTP_USERNAME")
    password = _require_smtp_env("SMTP_PASSWORD")
    from_email = _require_smtp_env("SMTP_FROM_EMAIL")
    from_name = os.getenv("SMTP_FROM_NAME", "").strip() or "Learning Assistant"
    use_ssl = _env_flag("SMTP_USE_SSL", False)
    use_tls = _env_flag("SMTP_USE_TLS", True) and not use_ssl

    message = EmailMessage()
    message["Subject"] = "Learning Assistant 注册验证码"
    message["From"] = formataddr((from_name, from_email))
    message["To"] = email
    message["Reply-To"] = from_email
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=_message_id_domain(from_email))
    text_body = "\n".join(
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
    html_body = f"""\
<html>
  <body>
    <p>你好，</p>
    <p>你正在注册 Learning Assistant 账号。</p>
    <p>本次验证码：<strong>{code}</strong></p>
    <p>验证码有效期：{expires_in_minutes} 分钟</p>
    <p>如果这不是你的操作，请忽略这封邮件。</p>
  </body>
</html>
"""
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        smtp_client = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_client(host, port, timeout=20) as server:
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
