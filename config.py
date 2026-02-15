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
