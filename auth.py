"""인증 블루프린트: 로그인/로그아웃, RBAC 데코레이터, 사용자 관리, CLI 명령어."""

import functools
from urllib.parse import urlparse

import bcrypt
import click
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user

from models import ROLE_HIERARCHY, ROLE_LABELS, User, db
from forms import CreateUserForm, EditUserForm, LoginForm

auth_bp = Blueprint("auth", __name__)
login_manager = LoginManager()

# ─── Flask-Login 설정 ───

login_manager.login_view = "auth.login"
login_manager.login_message = "로그인이 필요합니다."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


# ─── 비밀번호 해싱 (bcrypt 12 rounds) ───

_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt(rounds=12))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def dummy_verify():
    """타이밍 공격 방지: 사용자가 없을 때도 동일 시간 소요."""
    bcrypt.checkpw(b"dummy", _DUMMY_HASH)


# ─── RBAC 데코레이터 ───

def _role_required(min_role: str):
    """최소 역할 등급 이상만 접근 허용하는 데코레이터."""
    min_level = ROLE_HIERARCHY[min_role]

    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role_level < min_level:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


admin_required = _role_required("admin")
super_admin_required = _role_required("super_admin")
owner_required = _role_required("owner")


def _is_safe_url(target: str) -> bool:
    """Open redirect 방지: 같은 호스트의 상대 경로만 허용."""
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(target)
    return test.scheme in ("", "http", "https") and ref.netloc == (test.netloc or ref.netloc)


# ─── 로그인/로그아웃 ───

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user is None:
            dummy_verify()
            flash("이메일 또는 비밀번호가 올바르지 않습니다.", "error")
            return render_template("auth/login.html", form=form)

        if not verify_password(form.password.data, user.password_hash):
            flash("이메일 또는 비밀번호가 올바르지 않습니다.", "error")
            return render_template("auth/login.html", form=form)

        if not user.is_active:
            flash("비활성화된 계정입니다. 관리자에게 문의하세요.", "error")
            return render_template("auth/login.html", form=form)

        login_user(user, remember=False)
        next_url = request.args.get("next")
        if next_url and _is_safe_url(next_url):
            return redirect(next_url)
        return redirect(url_for("index"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("auth.login"))


# ─── 관리자: 사용자 관리 ───

@auth_bp.route("/admin/users")
@admin_required
def user_list():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users, role_labels=ROLE_LABELS)


@auth_bp.route("/admin/users/create", methods=["GET", "POST"])
@admin_required
def user_create():
    form = CreateUserForm()
    form.role.choices = form.role_choices_for(current_user.role)

    if form.validate_on_submit():
        target_level = ROLE_HIERARCHY.get(form.role.data, 0)
        if target_level >= current_user.role_level:
            flash("자신과 같거나 높은 등급의 사용자를 생성할 수 없습니다.", "error")
            return render_template("admin/user_form.html", form=form, is_edit=False)

        if User.query.filter_by(email=form.email.data.strip().lower()).first():
            flash("이미 등록된 이메일입니다.", "error")
            return render_template("admin/user_form.html", form=form, is_edit=False)

        user = User(
            email=form.email.data.strip().lower(),
            password_hash=hash_password(form.password.data),
            last_name=form.last_name.data.strip(),
            first_name=form.first_name.data.strip(),
            role=form.role.data,
        )
        db.session.add(user)
        db.session.commit()
        flash(f"사용자 {user.full_name}({user.email})이(가) 생성되었습니다.", "success")
        return redirect(url_for("auth.user_list"))

    return render_template("admin/user_form.html", form=form, is_edit=False)


@auth_bp.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id: int):
    target = db.session.get(User, user_id)
    if target is None:
        abort(404)

    if not current_user.can_manage(target) and current_user.id != target.id:
        flash("이 사용자를 수정할 권한이 없습니다.", "error")
        return redirect(url_for("auth.user_list"))

    form = EditUserForm(obj=target)
    form.role.choices = form.role_choices_for(current_user.role)

    if form.validate_on_submit():
        target_level = ROLE_HIERARCHY.get(form.role.data, 0)
        # 역할이 변경된 경우에만 등급 제한 검사 (기존 역할 유지는 허용)
        if form.role.data != target.role and target_level >= current_user.role_level:
            flash("자신과 같거나 높은 등급으로 변경할 수 없습니다.", "error")
            return render_template("admin/user_form.html", form=form, is_edit=True, target=target)

        target.email = form.email.data.strip().lower()
        target.last_name = form.last_name.data.strip()
        target.first_name = form.first_name.data.strip()
        target.role = form.role.data
        target.is_active = form.is_active.data

        if form.password.data:
            target.password_hash = hash_password(form.password.data)

        db.session.commit()
        flash(f"사용자 {target.full_name} 정보가 수정되었습니다.", "success")
        return redirect(url_for("auth.user_list"))

    return render_template("admin/user_form.html", form=form, is_edit=True, target=target)


@auth_bp.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def user_toggle(user_id: int):
    target = db.session.get(User, user_id)
    if target is None:
        abort(404)
    if not current_user.can_manage(target):
        flash("이 사용자를 수정할 권한이 없습니다.", "error")
        return redirect(url_for("auth.user_list"))

    target.is_active = not target.is_active
    db.session.commit()
    status = "활성화" if target.is_active else "비활성화"
    flash(f"{target.full_name} 계정이 {status}되었습니다.", "success")
    return redirect(url_for("auth.user_list"))


# ─── CLI 명령어 ───

def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """데이터베이스 테이블을 생성한다."""
        with app.app_context():
            db.create_all()
            click.echo("데이터베이스 테이블이 생성되었습니다.")

    @app.cli.command("seed-owner")
    def seed_owner():
        """오너 계정을 생성한다 (OWNER_EMAIL, OWNER_PASSWORD 환경변수 필요)."""
        with app.app_context():
            email = app.config.get("OWNER_EMAIL", "").strip()
            password = app.config.get("OWNER_PASSWORD", "").strip()
            if not email or not password:
                click.echo("OWNER_EMAIL과 OWNER_PASSWORD 환경변수를 설정해주세요.")
                return

            existing = User.query.filter_by(email=email.lower()).first()
            if existing:
                existing.role = "owner"
                existing.password_hash = hash_password(password)
                existing.is_active = True
                db.session.commit()
                click.echo(f"기존 사용자 {email}을(를) owner로 업데이트했습니다.")
                return

            user = User(
                email=email.lower(),
                password_hash=hash_password(password),
                last_name="관리자",
                first_name="",
                role="owner",
            )
            db.session.add(user)
            db.session.commit()
            click.echo(f"오너 계정 {email}이(가) 생성되었습니다.")
