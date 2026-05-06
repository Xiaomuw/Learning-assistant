from __future__ import annotations

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import AppSettingModel
from app.infrastructure.db.repositories._shared import serialize_app_setting_record, utcnow
from app.shared.schemas.contracts import AppSettingRecord


def get_app_setting_record(key: str, default: str | None = None) -> AppSettingRecord:
    with session_scope() as session:
        row = session.get(AppSettingModel, key)
        return serialize_app_setting_record(row, key, default)


def set_app_setting_record(key: str, value: str) -> AppSettingRecord:
    with session_scope() as session:
        row = session.get(AppSettingModel, key)
        if row is None:
            row = AppSettingModel(key=key, value=value)
            session.add(row)
        else:
            row.value = value
            row.updated_at = utcnow()
        session.flush()
        return serialize_app_setting_record(row, key)
