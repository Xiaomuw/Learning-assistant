from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from sqlalchemy import delete, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

ACCESS_COOKIE_NAME = "la_access_token"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TEMP_EMAIL_PREFIX = "codex+auth-auto-smoke"


class SmokeFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class SmokeAccount:
    email: str
    password: str
    created_by_runner: bool


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _temporary_email() -> str:
    return f"{TEMP_EMAIL_PREFIX}-{uuid.uuid4().hex[:12]}@gmail.com"


def _default_password() -> str:
    return f"SmokePass{uuid.uuid4().hex[:12]}!"


def _response_excerpt(response: requests.Response) -> str:
    text = response.text.strip().replace("\n", " ")
    return text[:500]


def _request_json(
    session: requests.Session,
    method: str,
    base_url: str,
    path: str,
    *,
    expected_status: int = 200,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    url = _join_url(base_url, path)
    try:
        response = session.request(
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SmokeFailure(f"{method} {url} failed: {exc}") from exc

    if response.status_code != expected_status:
        raise SmokeFailure(
            f"{method} {url} returned {response.status_code}, "
            f"expected {expected_status}: {_response_excerpt(response)}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise SmokeFailure(
            f"{method} {url} did not return JSON: {_response_excerpt(response)}"
        ) from exc


def _create_temp_user(email: str, password: str) -> str:
    from app.infrastructure.auth.security import hash_password
    from app.infrastructure.db.repositories.auth import create_auth_user_record

    try:
        user = create_auth_user_record(
            email=email,
            password_hash=hash_password(password),
            display_name="Backend Smoke",
        )
    except Exception as exc:
        raise SmokeFailure(f"Could not create temporary smoke user {email}: {exc}") from exc
    return user.id


def _validate_generated_email(email: str) -> None:
    if not email.startswith(f"{TEMP_EMAIL_PREFIX}-") or not email.endswith("@gmail.com"):
        raise SmokeFailure(f"Refusing to clean up non-generated smoke account: {email}")


def _count_for_delete(session, statement) -> int:
    result = session.execute(statement)
    return int(result.rowcount or 0)


def _cleanup_generated_user(email: str) -> dict[str, int]:
    _validate_generated_email(email)

    from app.infrastructure.db.database import session_scope
    from app.infrastructure.db.models import (
        AuthRefreshTokenModel,
        ChatSessionModel,
        EmailVerificationChallengeModel,
        GraphAttemptModel,
        GraphQuestionItemModel,
        GraphRunModel,
        LearningEventModel,
        MasterySnapshotModel,
        NodeRunModel,
        PracticeAttemptModel,
        ToolRunModel,
        UserKnowledgeStatModel,
        UserMemoryModel,
        UserModel,
        UserProfileModel,
        WechatMiniIdentityModel,
    )

    with session_scope() as session:
        user_ids = list(
            session.scalars(select(UserModel.id).where(UserModel.email == email)).all()
        )
        graph_run_ids: list[str] = []
        if user_ids:
            graph_run_ids = list(
                session.scalars(
                    select(GraphRunModel.id).where(GraphRunModel.user_id.in_(user_ids))
                ).all()
            )

        counts: dict[str, int] = {}
        if graph_run_ids:
            counts["node_runs"] = _count_for_delete(
                session,
                delete(NodeRunModel).where(NodeRunModel.graph_run_id.in_(graph_run_ids)),
            )
            counts["tool_runs"] = _count_for_delete(
                session,
                delete(ToolRunModel).where(ToolRunModel.graph_run_id.in_(graph_run_ids)),
            )

        for name, model in [
            ("auth_refresh_tokens", AuthRefreshTokenModel),
            ("chat_sessions", ChatSessionModel),
            ("practice_attempts", PracticeAttemptModel),
            ("learning_events", LearningEventModel),
            ("attempts", GraphAttemptModel),
            ("mastery_snapshots", MasterySnapshotModel),
            ("question_items", GraphQuestionItemModel),
            ("user_knowledge_stats", UserKnowledgeStatModel),
            ("user_memories", UserMemoryModel),
            ("user_profiles", UserProfileModel),
            ("wechat_mini_identities", WechatMiniIdentityModel),
            ("graph_runs", GraphRunModel),
        ]:
            counts[name] = (
                _count_for_delete(session, delete(model).where(model.user_id.in_(user_ids)))
                if user_ids
                else 0
            )

        counts["users"] = (
            _count_for_delete(session, delete(UserModel).where(UserModel.id.in_(user_ids)))
            if user_ids
            else 0
        )
        counts["email_verification_challenges"] = _count_for_delete(
            session,
            delete(EmailVerificationChallengeModel).where(
                EmailVerificationChallengeModel.email == email
            ),
        )

    return counts


def _build_account(args: argparse.Namespace) -> SmokeAccount:
    email = (args.email or "").strip().lower()
    password = (args.password or "").strip()
    if email:
        if not password:
            raise SmokeFailure("--password is required when --email is provided")
        return SmokeAccount(email=email, password=password, created_by_runner=False)

    return SmokeAccount(
        email=_temporary_email(),
        password=password or _default_password(),
        created_by_runner=True,
    )


def run_smoke(args: argparse.Namespace) -> None:
    base_url = (args.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    account = _build_account(args)
    created_user_id = ""
    cleanup_counts: dict[str, int] = {}
    session = requests.Session()

    try:
        _request_json(session, "GET", base_url, "/health", timeout=args.timeout)
        print(f"ok health {base_url}/health")

        if account.created_by_runner:
            created_user_id = _create_temp_user(account.email, account.password)
            print(f"ok created temporary user {created_user_id}")

        login_payload = _request_json(
            session,
            "POST",
            base_url,
            "/api/auth/login",
            timeout=args.timeout,
            json_body={"email": account.email, "password": account.password},
        )
        if not isinstance(login_payload, dict) or not login_payload.get("user"):
            raise SmokeFailure("POST /api/auth/login returned an unexpected payload")

        access_token = session.cookies.get(ACCESS_COOKIE_NAME)
        if not access_token:
            raise SmokeFailure("POST /api/auth/login did not set la_access_token cookie")
        print("ok login cookie")

        me_payload = _request_json(
            session,
            "GET",
            base_url,
            "/api/auth/me",
            timeout=args.timeout,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if not isinstance(me_payload, dict) or "user" not in me_payload:
            raise SmokeFailure("GET /api/auth/me returned an unexpected payload")
        user = me_payload["user"]
        user_id = str(user.get("id") or "")
        if not user_id:
            raise SmokeFailure("GET /api/auth/me did not return user.id")
        print(f"ok auth/me bearer user_id={user_id}")

        subjects_payload = _request_json(
            session,
            "GET",
            base_url,
            "/api/subjects",
            timeout=args.timeout,
        )
        if not isinstance(subjects_payload, list):
            raise SmokeFailure("GET /api/subjects did not return a list")
        print(f"ok subjects count={len(subjects_payload)}")

        learning_center_payload = _request_json(
            session,
            "GET",
            base_url,
            f"/api/users/{user_id}/learning-center",
            timeout=args.timeout,
        )
        if (
            not isinstance(learning_center_payload, dict)
            or "subjects" not in learning_center_payload
        ):
            raise SmokeFailure(
                "GET /api/users/{id}/learning-center returned an unexpected payload"
            )
        print(
            "ok learning-center "
            f"subjects={len(learning_center_payload.get('subjects') or [])}"
        )

        recommendations_payload = _request_json(
            session,
            "GET",
            base_url,
            f"/api/users/{user_id}/practice/recommendations",
            timeout=args.timeout,
        )
        if (
            not isinstance(recommendations_payload, dict)
            or "items" not in recommendations_payload
        ):
            raise SmokeFailure(
                "GET /api/users/{id}/practice/recommendations returned an unexpected payload"
            )
        print(
            "ok practice/recommendations "
            f"items={len(recommendations_payload.get('items') or [])}"
        )

        try:
            _request_json(
                session,
                "POST",
                base_url,
                "/api/auth/logout",
                timeout=args.timeout,
            )
            print("ok logout")
        except SmokeFailure as exc:
            print(f"warn logout failed before cleanup: {exc}", file=sys.stderr)
    finally:
        if account.created_by_runner and created_user_id and not args.no_cleanup:
            cleanup_counts = _cleanup_generated_user(account.email)
            total_deleted = sum(cleanup_counts.values())
            print(f"ok cleanup email={account.email} deleted_rows={total_deleted}")
        elif account.created_by_runner and created_user_id:
            print(f"warn kept temporary user email={account.email}", file=sys.stderr)

    if created_user_id and cleanup_counts.get("users") != 1 and not args.no_cleanup:
        raise SmokeFailure(
            f"Temporary user cleanup removed {cleanup_counts.get('users', 0)} users, expected 1"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an authenticated backend smoke test against a live FastAPI server."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("SMOKE_BASE_URL", DEFAULT_BASE_URL),
        help="Backend base URL. Defaults to SMOKE_BASE_URL or http://127.0.0.1:8000.",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("SMOKE_EMAIL", ""),
        help="Existing test account email. If omitted, the runner creates a temp account.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("SMOKE_PASSWORD", ""),
        help="Existing test account password, or override password for generated accounts.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("SMOKE_TIMEOUT_SECONDS", "10")),
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep a generated temporary account for debugging.",
    )
    return parser.parse_args()


def main() -> None:
    try:
        run_smoke(_parse_args())
    except SmokeFailure as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
