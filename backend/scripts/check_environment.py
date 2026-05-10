"""
检查当前 backend/.env 是否符合正式运行时要求。

用法:
  python scripts/check_environment.py
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.config.validation import (  # noqa: E402
    EnvironmentValidationError,
    collect_environment_warnings,
    validate_startup_environment,
)
from app.infrastructure.llm.langsmith import get_langsmith_health_status  # noqa: E402


@dataclass(frozen=True)
class DotenvCompatibilityIssue:
    line: int
    key: str
    reason: str


def find_dotenv_shell_compatibility_issues(path: Path) -> list[DotenvCompatibilityIssue]:
    if not path.exists():
        return []

    issues: list[DotenvCompatibilityIssue] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assignment = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        if "=" not in assignment:
            continue
        key, raw_value = assignment.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            continue
        if _has_unquoted_whitespace(value):
            issues.append(
                DotenvCompatibilityIssue(
                    line=line_number,
                    key=key,
                    reason="值包含空格但没有使用引号包裹，shell source 会把空格后的内容当成命令",
                )
            )
    return issues


def _has_unquoted_whitespace(value: str) -> bool:
    value_without_comment = _strip_inline_comment(value).strip()
    if not value_without_comment:
        return False
    quote = value_without_comment[0]
    if quote in {"'", '"'}:
        return len(value_without_comment) < 2 or value_without_comment[-1] != quote
    return any(char.isspace() for char in value_without_comment)


def _strip_inline_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.rstrip()


def main() -> int:
    dotenv_path = BACKEND_ROOT / ".env"
    shell_issues = find_dotenv_shell_compatibility_issues(dotenv_path)
    if shell_issues:
        print("❌ 环境检查失败: backend/.env 存在 shell source 不兼容写法")
        for issue in shell_issues:
            print(f"  line={issue.line} key={issue.key}: {issue.reason}")
        return 1

    load_dotenv(dotenv_path=dotenv_path)

    try:
        validate_startup_environment()
    except EnvironmentValidationError as exc:
        print(f"❌ 环境检查失败: {exc}")
        return 1

    print("✅ 启动级环境检查通过")
    for warning in collect_environment_warnings():
        print(f"⚠️  {warning}")
    langsmith_health = get_langsmith_health_status()
    langsmith_status = langsmith_health.get("status", "unknown")
    langsmith_project = langsmith_health.get("project", "")
    langsmith_endpoint = langsmith_health.get("endpoint", "")
    print(
        "ℹ️  LangSmith 状态: "
        f"{langsmith_status}"
        f" | project={langsmith_project or '-'}"
        f" | endpoint={langsmith_endpoint or '-'}"
    )
    if langsmith_status == "dns_unreachable":
        print(
            "⚠️  LangSmith DNS 不可达: "
            f"host={langsmith_health.get('host', '-')}, "
            f"error_type={langsmith_health.get('error_type', '-')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
