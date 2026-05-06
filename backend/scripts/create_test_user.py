import sys
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.infrastructure.auth.security import hash_password
from app.infrastructure.db.database import SessionLocal
from app.infrastructure.db.models import UserModel

def create_user(email: str, password: str):
    db = SessionLocal()
    try:
        user = db.query(UserModel).filter(UserModel.email == email).first()
        if user:
            print(f"User {email} already exists.")
            return

        new_user = UserModel(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=hash_password(password),
            status="active"
        )
        db.add(new_user)
        db.commit()
        print(f"User {email} created successfully.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    load_dotenv(BACKEND_ROOT / ".env")
    create_user("test@example.com", "password123")
