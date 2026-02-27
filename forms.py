"""WTForms 폼 정의 (로그인, 사용자 관리)."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, Email, Length, Optional

from models import ROLE_HIERARCHY


class LoginForm(FlaskForm):
    email = StringField(
        "이메일",
        validators=[DataRequired("이메일을 입력해주세요."), Email("유효한 이메일을 입력해주세요.")],
    )
    password = PasswordField(
        "비밀번호",
        validators=[DataRequired("비밀번호를 입력해주세요.")],
    )


class CreateUserForm(FlaskForm):
    email = StringField(
        "이메일",
        validators=[DataRequired("이메일을 입력해주세요."), Email("유효한 이메일을 입력해주세요.")],
    )
    password = PasswordField(
        "비밀번호",
        validators=[DataRequired("비밀번호를 입력해주세요."), Length(min=8, message="비밀번호는 8자 이상이어야 합니다.")],
    )
    last_name = StringField("성", validators=[DataRequired("성을 입력해주세요.")])
    first_name = StringField("이름", validators=[DataRequired("이름을 입력해주세요.")])
    role = SelectField(
        "역할",
        choices=[(k, v) for k, v in [
            ("member", "일반회원"),
            ("admin", "관리자"),
            ("super_admin", "최고관리자"),
        ]],
        validators=[DataRequired()],
    )

    def role_choices_for(self, current_user_role: str) -> list:
        """현재 사용자보다 낮은 등급만 선택 가능."""
        level = ROLE_HIERARCHY.get(current_user_role, 0)
        return [(k, label) for k, label in self.role.choices if ROLE_HIERARCHY.get(k, 0) < level]


class EditUserForm(FlaskForm):
    email = StringField(
        "이메일",
        validators=[DataRequired("이메일을 입력해주세요."), Email("유효한 이메일을 입력해주세요.")],
    )
    password = PasswordField(
        "비밀번호 (변경 시에만 입력)",
        validators=[Optional(), Length(min=8, message="비밀번호는 8자 이상이어야 합니다.")],
    )
    last_name = StringField("성", validators=[DataRequired("성을 입력해주세요.")])
    first_name = StringField("이름", validators=[DataRequired("이름을 입력해주세요.")])
    role = SelectField(
        "역할",
        choices=[(k, v) for k, v in [
            ("member", "일반회원"),
            ("admin", "관리자"),
            ("super_admin", "최고관리자"),
        ]],
        validators=[DataRequired()],
    )
    is_active = BooleanField("활성 상태")

    def role_choices_for(self, current_user_role: str) -> list:
        """현재 사용자보다 낮은 등급만 선택 가능."""
        level = ROLE_HIERARCHY.get(current_user_role, 0)
        return [(k, label) for k, label in self.role.choices if ROLE_HIERARCHY.get(k, 0) < level]
