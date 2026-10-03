"""雨期挂起/收起与遮雨落实档管理（同一专页）。"""

from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Plant, RainCover, RainSeasonStatus, User, utcnow
from app.services.rules import LOCAL_TZ, local_today

bp = Blueprint("rain", __name__, url_prefix="/rain")

COVER_STATE_OPEN = "open"
COVER_STATE_VOIDED = "voided"
COVER_STATE_ALL = "all"


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _parse_local_dt(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        naive = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # datetime-local 视为厂区当地时间（UTC+8），统一存 UTC
    return naive.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)


@bp.route("/")
@login_required
def rain_center():
    plants = Plant.query.order_by(Plant.name).all()
    statuses = {s.plant_id: s for s in RainSeasonStatus.query.all()}

    plant_id_raw = request.args.get("plant_id", "").strip()
    state = request.args.get("state", COVER_STATE_OPEN)
    date_raw = request.args.get("date", "").strip()

    filter_plant_id = int(plant_id_raw) if plant_id_raw.isdigit() else None
    filter_date = None
    if date_raw:
        try:
            filter_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
        except ValueError:
            date_raw = ""

    query = RainCover.query.join(Plant)
    if filter_plant_id is not None:
        query = query.filter(RainCover.plant_id == filter_plant_id)
    if filter_date is not None:
        query = query.filter(RainCover.cover_date == filter_date)
    if state == COVER_STATE_OPEN:
        query = query.filter(RainCover.voided_at.is_(None))
    elif state == COVER_STATE_VOIDED:
        query = query.filter(RainCover.voided_at.isnot(None))
    covers = query.order_by(
        RainCover.cover_date.desc(), RainCover.implemented_at.desc()
    ).all()

    today = local_today()
    today_open = {
        c.plant_id: c
        for c in RainCover.query.filter_by(cover_date=today)
        .filter(RainCover.voided_at.is_(None))
        .all()
    }

    workers = User.query.order_by(User.username).all()

    return render_template(
        "rain/center.html",
        plants=plants,
        statuses=statuses,
        covers=covers,
        workers=workers,
        is_admin=current_user.role == "admin",
        current_user=current_user,
        today=today,
        now_local=datetime.now(LOCAL_TZ).strftime("%Y-%m-%dT%H:%M"),
        today_open=today_open,
        filters={"plant_id": plant_id_raw, "state": state, "date": date_raw},
    )


@bp.route("/season/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_season():
    plant_id = int(request.form["plant_id"])
    plant = db.session.get(Plant, plant_id) or abort(404)
    status = RainSeasonStatus.query.filter_by(plant_id=plant.id).one_or_none()
    if status is None:
        status = RainSeasonStatus(plant_id=plant.id, active=False)
        db.session.add(status)
    if status.active:
        status.active = False
        flash(f"「{plant.name}」雨期已收起，登记与改峰值不再要求遮雨档", "ok")
    else:
        status.active = True
        flash(f"「{plant.name}」雨期已挂起，登记批次与抬峰值须有当日遮雨档", "ok")
    db.session.commit()
    return redirect(url_for("rain.rain_center", plant_id=plant.id))


@bp.route("/covers/new", methods=["POST"])
@login_required
def create_cover():
    plant_id = int(request.form["plant_id"])
    plant = db.session.get(Plant, plant_id) or abort(404)
    cover_method = (request.form.get("cover_method") or "").strip()
    implemented_at = _parse_local_dt(request.form.get("implemented_at") or "")
    implemented_by_id = int(
        request.form.get("implemented_by_id") or current_user.id
    )

    if not cover_method:
        flash("遮盖方式不能为空", "error")
    elif implemented_at is None:
        flash("落实时刻格式无效", "error")
    elif not db.session.get(User, implemented_by_id):
        flash("落实人无效", "error")
    else:
        cover = RainCover(
            plant_id=plant.id,
            cover_method=cover_method,
            implemented_at=implemented_at,
            implemented_by_id=implemented_by_id,
            cover_date=implemented_at.astimezone(LOCAL_TZ).date(),
        )
        db.session.add(cover)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            # 并发抢档：数据库部分唯一索引兜底，只允许一张落库
            flash(
                f"「{plant.name}」当日已存在未作废遮雨档，同厂同自然日只许一张，本档未落库",
                "error",
            )
        else:
            flash(
                f"遮雨落实档已登记（{plant.name} · {cover.cover_date.strftime('%Y-%m-%d')}）",
                "ok",
            )
    return redirect(url_for("rain.rain_center", plant_id=plant.id))


@bp.route("/covers/<int:cover_id>/void", methods=["POST"])
@login_required
@admin_required
def void_cover(cover_id: int):
    cover = RainCover.query.get_or_404(cover_id)
    if cover.voided_at is not None:
        flash("该遮雨档已作废，无需重复操作", "error")
    else:
        reason = (request.form.get("void_reason") or "").strip()
        cover.voided_at = utcnow()
        cover.voided_by_id = current_user.id
        cover.void_reason = reason
        db.session.commit()
        flash(
            f"遮雨档已作废（{cover.plant.name} · {cover.cover_date.strftime('%Y-%m-%d')}）",
            "ok",
        )
    return redirect(url_for("rain.rain_center", plant_id=cover.plant_id))
