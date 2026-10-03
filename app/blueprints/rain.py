from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Plant, RainCoverLog, local_today, natural_day, utcnow
from app.services.rules import active_rain_cover_for

bp = Blueprint("rain", __name__, url_prefix="/rain")


def _admin_only(action: str) -> bool:
    """非管理员时给出中文提示并返回 True(调用方应直接返回重定向)。"""
    if current_user.role == "admin":
        return False
    flash(f"仅管理员可{action}", "error")
    return True


@bp.route("/")
@login_required
def dashboard():
    plants = Plant.query.order_by(Plant.name).all()
    today = local_today()
    plant_cards = [
        {"plant": plant, "log": active_rain_cover_for(plant.id, today)}
        for plant in plants
    ]

    query = RainCoverLog.query.join(Plant).order_by(
        RainCoverLog.log_date.desc(),
        RainCoverLog.implemented_at.desc(),
        RainCoverLog.id.desc(),
    )
    filter_plant = request.args.get("plant_id", type=int)
    filter_status = (request.args.get("status") or "").strip()
    filter_date_raw = (request.args.get("date") or "").strip()
    filter_date = None
    if filter_plant:
        query = query.filter(RainCoverLog.plant_id == filter_plant)
    if filter_status == "active":
        query = query.filter(RainCoverLog.voided_at.is_(None))
    elif filter_status == "voided":
        query = query.filter(RainCoverLog.voided_at.isnot(None))
    if filter_date_raw:
        try:
            filter_date = datetime.strptime(filter_date_raw, "%Y-%m-%d").date()
            query = query.filter(RainCoverLog.log_date == filter_date)
        except ValueError:
            flash("日期筛选格式无效,已忽略", "error")
    logs = query.all()

    return render_template(
        "rain/dashboard.html",
        plants=plants,
        plant_cards=plant_cards,
        logs=logs,
        today=today,
        filter_plant=filter_plant,
        filter_status=filter_status,
        filter_date=filter_date_raw if filter_date else "",
    )


@bp.route("/plants/<int:plant_id>/season", methods=["POST"])
@login_required
def toggle_season(plant_id: int):
    if _admin_only("挂起或收起雨期"):
        return redirect(url_for("rain.dashboard"))
    plant = Plant.query.get_or_404(plant_id)
    plant.rain_season_on = not plant.rain_season_on
    db.session.commit()
    if plant.rain_season_on:
        flash(f"已挂起雨期:{plant.name},登记批次与抬峰值前须落实当日遮雨档", "ok")
    else:
        flash(f"已收起雨期:{plant.name},登记批次与抬峰值不再要求遮雨档", "ok")
    return redirect(url_for("rain.dashboard"))


@bp.route("/logs", methods=["POST"])
@login_required
def create_log():
    plant_id = request.form.get("plant_id", type=int)
    plant = db.session.get(Plant, plant_id) if plant_id else None
    cover_method = (request.form.get("cover_method") or "").strip()
    implemented_raw = (request.form.get("implemented_at") or "").strip()

    if plant is None:
        flash("请选择厂区", "error")
        return redirect(url_for("rain.dashboard"))
    if not cover_method:
        flash("请填写遮盖方式", "error")
        return redirect(url_for("rain.dashboard"))

    implemented_at = utcnow()
    if implemented_raw:
        try:
            implemented_at = datetime.fromisoformat(implemented_raw)
        except ValueError:
            flash("落实时刻格式无效", "error")
            return redirect(url_for("rain.dashboard"))

    log = RainCoverLog(
        plant_id=plant.id,
        cover_method=cover_method,
        implemented_at=implemented_at,
        implemented_by_id=current_user.id,
        log_date=natural_day(implemented_at),
    )
    db.session.add(log)
    try:
        db.session.commit()
    except IntegrityError:
        # 同厂同自然日已有未作废档(含并发抢建):数据库唯一索引兜底,只落一张
        db.session.rollback()
        flash("该厂区今日已存在未作废的遮雨落实档,本次登记未生效", "error")
        return redirect(url_for("rain.dashboard", plant_id=plant.id))
    flash(f"{plant.name} 遮雨落实档已登记({log.log_date.isoformat()} · {cover_method})", "ok")
    return redirect(url_for("rain.dashboard", plant_id=plant.id))


@bp.route("/logs/<int:log_id>/void", methods=["POST"])
@login_required
def void_log(log_id: int):
    if _admin_only("作废遮雨落实档"):
        return redirect(url_for("rain.dashboard"))
    log = RainCoverLog.query.get_or_404(log_id)
    if log.voided_at is not None:
        flash("该落实档此前已作废", "error")
    else:
        log.voided_at = utcnow()
        db.session.commit()
        flash(f"已作废 {log.plant.name} {log.log_date.isoformat()} 的遮雨落实档", "ok")
    return redirect(url_for("rain.dashboard"))
