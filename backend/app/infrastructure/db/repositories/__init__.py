"""Database repository package.

正式入口是各子模块里的 `*Record` / `*record` 函数。
本包根只导出当前正式仓储能力；旧函数名兼容层已移除。
"""

from app.infrastructure.db.repositories.auth import (  # noqa: F401
    consume_refresh_token_record,
    consume_email_verification_challenge_record,
    create_auth_user_record,
    create_or_refresh_email_verification_challenge_record,
    get_active_email_verification_challenge_record,
    get_user_auth_record_by_email,
    get_user_auth_record_by_id,
    get_user_auth_view_record,
    increment_email_verification_attempt_record,
    mark_email_verification_verified_record,
    revoke_refresh_token_by_jti,
    revoke_refresh_tokens_for_user,
    save_refresh_token_record,
    touch_refresh_token_last_used_record,
    touch_user_last_login,
    update_user_password_hash,
)
from app.infrastructure.db.repositories.bootstrap import init_database  # noqa: F401
from app.infrastructure.db.repositories.practice import (  # noqa: F401
    create_practice_attempt_record,
    list_practice_recommendation_records,
    list_question_bank_item_records,
    upsert_question_bank_item_records,
)
from app.infrastructure.db.repositories.practice_questions import (  # noqa: F401
    get_practice_question,
    import_practice_questions,
    load_practice_question_json,
    validate_practice_questions,
)
from app.infrastructure.db.repositories.knowledge_stats import (  # noqa: F401
    list_knowledge_mastery_records,
    record_knowledge_attempt,
    record_knowledge_exposure,
)
from app.infrastructure.db.repositories.knowledge_taxonomy import (  # noqa: F401
    delete_kb_chunks_by_source,
    list_unmapped_chunks,
    save_kb_chunk_record,
    sync_knowledge_taxonomy,
)
from app.infrastructure.db.repositories.sessions import (  # noqa: F401
    append_chat_turn_record,
    delete_chat_session_record,
    get_chat_session_record,
    list_chat_session_records,
    update_chat_session_memory_record,
)
from app.infrastructure.db.repositories.settings import (  # noqa: F401
    get_app_setting_record,
    set_app_setting_record,
)
from app.infrastructure.db.repositories.subjects import (  # noqa: F401
    create_subject_record,
    delete_subject_record,
    get_subject_record,
    list_subject_records,
    update_subject_record,
)
from app.infrastructure.db.repositories.users import (  # noqa: F401
    get_user_memory_record,
    get_user_profile_record,
    save_user_memory_record,
    save_user_profile_record,
)
