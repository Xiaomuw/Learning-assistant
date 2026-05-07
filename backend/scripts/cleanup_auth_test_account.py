from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import delete, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.infrastructure.db.database import session_scope  # noqa: E402
from app.infrastructure.db.models import (  # noqa: E402
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
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or delete a temporary auth E2E registration account."
    )
    parser.add_argument("--email", required=True, help="Temporary email address to clean up.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete records. Without this flag the script only prints counts.",
    )
    return parser.parse_args()


def _validate_test_email(email: str) -> str:
    normalized = email.strip().lower()
    allowed_markers = ("+auth-auto-", "+ui-e2e-")
    if not normalized.endswith("@gmail.com") or not any(marker in normalized for marker in allowed_markers):
        raise SystemExit("只允许清理包含 +auth-auto- 或 +ui-e2e- 的 Gmail 临时测试邮箱。")
    return normalized


def _count_for_delete(session, statement) -> int:
    result = session.execute(statement)
    return int(result.rowcount or 0)


def main() -> None:
    args = _parse_args()
    email = _validate_test_email(args.email)

    with session_scope() as session:
        user_ids = list(session.scalars(select(UserModel.id).where(UserModel.email == email)).all())
        graph_run_ids = []
        if user_ids:
            graph_run_ids = list(
                session.scalars(select(GraphRunModel.id).where(GraphRunModel.user_id.in_(user_ids))).all()
            )

        counts: dict[str, int] = {}
        if args.execute:
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
                ("graph_runs", GraphRunModel),
            ]:
                if user_ids:
                    counts[name] = _count_for_delete(
                        session,
                        delete(model).where(model.user_id.in_(user_ids)),
                    )
                else:
                    counts[name] = 0
            if user_ids:
                counts["users"] = _count_for_delete(
                    session,
                    delete(UserModel).where(UserModel.id.in_(user_ids)),
                )
            else:
                counts["users"] = 0
            counts["email_verification_challenges"] = _count_for_delete(
                session,
                delete(EmailVerificationChallengeModel).where(
                    EmailVerificationChallengeModel.email == email
                ),
            )
        else:
            counts["users"] = len(user_ids)
            counts["graph_runs"] = len(graph_run_ids)
            counts["email_verification_challenges"] = len(
                session.scalars(
                    select(EmailVerificationChallengeModel.id).where(
                        EmailVerificationChallengeModel.email == email
                    )
                ).all()
            )

    mode = "EXECUTED" if args.execute else "DRY_RUN"
    print(f"{mode} cleanup for {email}")
    for name, count in counts.items():
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()
