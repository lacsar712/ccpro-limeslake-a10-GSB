from datetime import date, datetime, timezone

from flask_login import UserMixin
from sqlalchemy import event
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


def local_today() -> date:
    """服务器本地时区的「今天」,作为自然日口径。"""
    return datetime.now(timezone.utc).astimezone().date()


def natural_day(dt: datetime) -> date:
    """取某个时刻所属的自然日(本地时区);naive 时刻按 UTC 处理。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="worker")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Plant(db.Model):
    __tablename__ = "plants"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(200), nullable=False, default="")
    notes = db.Column(db.Text, nullable=False, default="")
    rain_season_on = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    ponds = db.relationship("Pond", back_populates="plant", cascade="all, delete-orphan")
    rain_cover_logs = db.relationship(
        "RainCoverLog",
        back_populates="plant",
        cascade="all, delete-orphan",
        order_by="desc(RainCoverLog.implemented_at)",
    )


class Pond(db.Model):
    __tablename__ = "ponds"
    __table_args__ = (
        db.UniqueConstraint("plant_id", "code", name="uq_pond_code_per_plant"),
    )

    STATUS_FILLING = "filling"
    STATUS_SLAKING = "slaking"
    STATUS_DRAWN = "drawn"
    STATUS_CHOICES = (STATUS_FILLING, STATUS_SLAKING, STATUS_DRAWN)

    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(db.Integer, db.ForeignKey("plants.id"), nullable=False)
    code = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_FILLING)
    capacity_m3 = db.Column(db.Float, nullable=False, default=0.0)
    notes = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    plant = db.relationship("Plant", back_populates="ponds")
    batches = db.relationship(
        "SlakeBatch",
        back_populates="pond",
        cascade="all, delete-orphan",
    )


class SlakeBatch(db.Model):
    __tablename__ = "slake_batches"

    id = db.Column(db.Integer, primary_key=True)
    pond_id = db.Column(db.Integer, db.ForeignKey("ponds.id"), nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    target_temp_c = db.Column(db.Float, nullable=False, default=80.0)
    peak_temp_c = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=False, default="")

    pond = db.relationship("Pond", back_populates="batches")


class RainCoverLog(db.Model):
    """雨期遮雨落实档:同厂同自然日未作废档最多一张。"""

    __tablename__ = "rain_cover_logs"
    __table_args__ = (
        db.Index(
            "uq_rain_cover_active_per_plant_day",
            "plant_id",
            "log_date",
            unique=True,
            postgresql_where=db.text("voided_at IS NULL"),
            sqlite_where=db.text("voided_at IS NULL"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(db.Integer, db.ForeignKey("plants.id"), nullable=False)
    cover_method = db.Column(db.String(120), nullable=False)
    implemented_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    implemented_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    log_date = db.Column(db.Date, nullable=False)
    voided_at = db.Column(db.DateTime(timezone=True), nullable=True)

    plant = db.relationship("Plant", back_populates="rain_cover_logs")
    implementer = db.relationship("User")


@event.listens_for(RainCoverLog, "before_insert")
def _rain_cover_defaults(mapper, connection, target):
    """任何入库路径都保证落实时刻与自然日一致。"""
    if target.implemented_at is None:
        target.implemented_at = utcnow()
    if target.log_date is None:
        target.log_date = natural_day(target.implemented_at)
