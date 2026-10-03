from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import Index
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


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
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    ponds = db.relationship("Pond", back_populates="plant", cascade="all, delete-orphan")


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


class RainSeasonStatus(db.Model):
    """厂区雨期挂起状态：存在一行且 active 为真即处于雨期。"""

    __tablename__ = "rain_season_status"

    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(
        db.Integer, db.ForeignKey("plants.id"), unique=True, nullable=False
    )
    active = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    plant = db.relationship("Plant")


class RainCover(db.Model):
    """遮雨落实档：同厂同自然日最多一张未作废档（由部分唯一索引兜底）。"""

    __tablename__ = "rain_covers"
    __table_args__ = (
        # 同厂同自然日只允许一张未作废档。
        # postgresql_where / sqlite_where 均为方言专属参数：
        # PG 建库时用前者，SQLite（本地/测试）建库时用后者，互不串台。
        Index(
            "uq_rain_cover_open_per_plant_day",
            "plant_id",
            "cover_date",
            unique=True,
            postgresql_where=db.text("voided_at IS NULL"),
            sqlite_where=db.text("voided_at IS NULL"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(
        db.Integer, db.ForeignKey("plants.id"), nullable=False
    )
    cover_method = db.Column(db.String(120), nullable=False)
    implemented_at = db.Column(db.DateTime(timezone=True), nullable=False)
    implemented_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    voided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    voided_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    void_reason = db.Column(db.String(200), nullable=False, default="")
    cover_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    plant = db.relationship("Plant")
    implemented_by = db.relationship("User", foreign_keys=[implemented_by_id])
    voided_by = db.relationship("User", foreign_keys=[voided_by_id])
