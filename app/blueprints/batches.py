from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond, SlakeBatch
from app.services.rules import RuleError, assert_rain_cover_today

bp = Blueprint("batches", __name__, url_prefix="/batches")


def _form_context(batch=None):
    return {
        "ponds": Pond.query.order_by(Pond.code).all(),
        "batch": batch,
        "rainy_plants": Plant.query.filter_by(rain_season_on=True)
        .order_by(Plant.name)
        .all(),
    }


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
    if request.method == "POST":
        pond_id = int(request.form["pond_id"])
        pond = db.session.get(Pond, pond_id)
        started_raw = request.form.get("started_at") or ""
        target = float(request.form.get("target_temp_c") or 80)
        peak_raw = (request.form.get("peak_temp_c") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        started_at = (
            datetime.fromisoformat(started_raw)
            if started_raw
            else datetime.utcnow()
        )
        peak = float(peak_raw) if peak_raw else None
        if pond is None:
            flash("所选熟化池不存在", "error")
        else:
            try:
                # 雨期门槛:登记新批次前须有当日未作废遮雨档
                assert_rain_cover_today(pond.plant, "登记熟化批次")
            except RuleError as exc:
                flash(str(exc), "error")
            else:
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
    return render_template("batches/form.html", **_form_context())


@bp.route("/<int:batch_id>/edit", methods=["GET", "POST"])
@login_required
def edit_batch(batch_id: int):
    batch = SlakeBatch.query.get_or_404(batch_id)
    if request.method == "POST":
        pond_id = int(request.form["pond_id"])
        pond = db.session.get(Pond, pond_id)
        started_raw = request.form.get("started_at") or ""
        peak_raw = (request.form.get("peak_temp_c") or "").strip()
        try:
            new_peak = float(peak_raw) if peak_raw else None
        except ValueError:
            flash("峰值温度格式无效", "error")
            return render_template("batches/form.html", **_form_context(batch))
        if pond is None:
            flash("所选熟化池不存在", "error")
        else:
            try:
                # 雨期门槛:峰值有实际变化(抬峰值)同样要过
                if new_peak != batch.peak_temp_c:
                    assert_rain_cover_today(pond.plant, "登记或修改峰值温度")
            except RuleError as exc:
                flash(str(exc), "error")
            else:
                batch.pond_id = pond_id
                if started_raw:
                    batch.started_at = datetime.fromisoformat(started_raw)
                batch.target_temp_c = float(request.form.get("target_temp_c") or 80)
                batch.peak_temp_c = new_peak
                batch.notes = (request.form.get("notes") or "").strip()
                db.session.commit()
                flash("熟化批次已更新", "ok")
                return redirect(
                    url_for(
                        "board.floor_plan",
                        plant_id=batch.pond.plant_id,
                        pond=batch.pond_id,
                    )
                )
    return render_template("batches/form.html", **_form_context(batch))
