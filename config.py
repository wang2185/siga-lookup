"""환경변수 및 상수 설정."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    VWORLD_API_KEY = os.getenv("VWORLD_API_KEY", "")
    JUSO_API_KEY = os.getenv("JUSO_API_KEY", "")
    DATA_GO_KR_API_KEY = os.getenv("DATA_GO_KR_API_KEY", "")
    DEBUG = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    PORT = int(os.getenv("PORT", "5000"))

    # Database (PostgreSQL 또는 SQLite 폴백)
    _db_url = os.getenv("DATABASE_URL", "")
    SQLALCHEMY_DATABASE_URI = _db_url or "sqlite:///" + os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "siga_lookup.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = (
        {"pool_pre_ping": True, "pool_recycle": 300}
        if _db_url and _db_url.startswith("postgresql")
        else {}
    )

    # Flask-Session (서버사이드, PostgreSQL)
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMANENT = True
    SESSION_USE_SIGNER = True
    SESSION_SQLALCHEMY_TABLE = "sessions"
    PERMANENT_SESSION_LIFETIME = 4 * 60 * 60  # 4시간
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("FLASK_DEBUG", "true").lower() != "true"

    # Owner 계정 (시딩용)
    OWNER_EMAIL = os.getenv("OWNER_EMAIL", "")
    OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "")
