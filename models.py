"""User 모델 및 RBAC 체계."""

from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

ROLE_HIERARCHY = {
    "owner": 4,
    "super_admin": 3,
    "admin": 2,
    "member": 1,
}

ROLE_LABELS = {
    "owner": "소유자",
    "super_admin": "최고관리자",
    "admin": "관리자",
    "member": "일반회원",
}


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False, default="")
    last_name = db.Column(db.String(100), nullable=False, default="")
    role = db.Column(db.String(20), nullable=False, default="member")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def full_name(self) -> str:
        return f"{self.last_name}{self.first_name}".strip() or self.email

    @property
    def role_level(self) -> int:
        return ROLE_HIERARCHY.get(self.role, 0)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    def can_manage(self, target: "User") -> bool:
        """자신보다 낮은 등급의 사용자만 관리 가능."""
        return self.role_level > target.role_level

    def get_id(self) -> str:
        return str(self.id)
