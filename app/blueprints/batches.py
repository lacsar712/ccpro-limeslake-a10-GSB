from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond, SlakeBatch
from app.services.rules import (
    RuleError,
    assert_rain_cover_for_plant,
    find_open_cover,
    is_rain_season,
)

bp = Blueprint("batches", __name__, url_prefix="/batches")


def _rain_blocked_plants() -> list[str]:
    """处于雨期但今日无未作废遮雨档的厂区名（供表单提示，不隐藏任何按钮）。"""
    blocked = []
    for plant in Plant.query.order_by(Plant.name).all():
        if is_rain_season(plant.id) and find_open_cover(plant.id) is None:
            blocked.append(plant.name)
    return blocked


@bp.route("/")
@login_required
def list_batches():
    batches = (
        SlakeBatch.query.join(Pond)
        .order_by(SlakeBatch.started_at.desc())
        .all()
    )
    return render_template("batches/list.html", batches=batches)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_batch():
    ponds = Pond.query.order_by(Pond.code).all()
    if request.method == "POST":
        pond_id = int(request.form["pond_id"])
        pond = db.session.get(Pond, pond_id)
        if pond is None:
            flash("所选熟化池不存在", "error")
            return render_template(
                "batches/form.html",
                ponds=ponds,
                batch=None,
                rain_blocked_plants=_rain_blocked_plants(),
            )
        started_raw = request.form.get("started_at") or ""
        target = float(request.form.get("target_temp_c") or 80)
        peak_raw = (request.form.get("peak_temp_c") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        try:
            assert_rain_cover_for_plant(pond.plant_id)
        except RuleError as exc:
            flash(str(exc), "error")
            return render_template(
                "batches/form.html",
                ponds=ponds,
                batch=None,
                rain_blocked_plants=_rain_blocked_plants(),
            )
        started_at = (
            datetime.fromisoformat(started_raw)
            if started_raw
            else datetime.utcnow()
        )
        peak = float(peak_raw) if peak_raw else None
        batch = SlakeBatch(
            pond_id=pond_id,
            started_at=started_at,
            target_temp_c=target,
            peak_temp_c=peak,
            notes=notes,
        )
        db.session.add(batch)
        db.session.commit()
        flash("熟化批次已登记", "ok")
        return redirect(
            url_for(
                "board.floor_plan",
                plant_id=pond.plant_id,
                pond=pond_id,
            )
        )
    return render_template(
        "batches/form.html",
        ponds=ponds,
        batch=None,
        rain_blocked_plants=_rain_blocked_plants(),
    )


@bp.route("/<int:batch_id>/edit", methods=["GET", "POST"])
@login_required
def edit_batch(batch_id: int):
    batch = SlakeBatch.query.get_or_404(batch_id)
    ponds = Pond.query.order_by(Pond.code).all()
    if request.method == "POST":
        new_pond_id = int(request.form["pond_id"])
        new_pond = db.session.get(Pond, new_pond_id)
        if new_pond is None:
            flash("所选熟化池不存在", "error")
            return render_template(
                "batches/form.html",
                ponds=ponds,
                batch=batch,
                rain_blocked_plants=_rain_blocked_plants(),
            )
        started_raw = request.form.get("started_at") or ""
        target = float(request.form.get("target_temp_c") or 80)
        peak_raw = (request.form.get("peak_temp_c") or "").strip()
        new_peak = float(peak_raw) if peak_raw else None
        notes = (request.form.get("notes") or "").strip()
        peak_changed = new_peak != batch.peak_temp_c
        pond_changed = new_pond_id != batch.pond_id
        # 雨期：改峰值、或把批次挪到另一厂区，目标厂区必须有当日遮雨档
        if peak_changed or pond_changed:
            try:
                assert_rain_cover_for_plant(new_pond.plant_id)
            except RuleError as exc:
                flash(str(exc), "error")
                return render_template(
                    "batches/form.html",
                    ponds=ponds,
                    batch=batch,
                    rain_blocked_plants=_rain_blocked_plants(),
                )
        batch.pond_id = new_pond_id
        if started_raw:
            batch.started_at = datetime.fromisoformat(started_raw)
        batch.target_temp_c = target
        batch.peak_temp_c = new_peak
        batch.notes = notes
        db.session.commit()
        flash("熟化批次已更新", "ok")
        return redirect(
            url_for(
                "board.floor_plan",
                plant_id=new_pond.plant_id,
                pond=batch.pond_id,
            )
        )
    return render_template(
        "batches/form.html",
        ponds=ponds,
        batch=batch,
        rain_blocked_plants=_rain_blocked_plants(),
    )
