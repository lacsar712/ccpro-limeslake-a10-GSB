"""石灰熟化池业务规则。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.extensions import db
from app.models import Pond, RainCover, RainSeasonStatus, SlakeBatch

MIN_PEAK_TEMP_FOR_DRAWN = 60.0

# 厂区自然日按东八区计算
LOCAL_TZ = timezone(timedelta(hours=8))


class RuleError(ValueError):
    """业务规则校验失败。"""


def local_today(now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(LOCAL_TZ).date()


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: b.started_at)


def can_mark_pond_drawn(pond: Pond) -> tuple[bool, str]:
    """
    熟化池转为「已出灰」(drawn) 的前提：
    最近一条熟化批次的峰值温度已记录，且 >= 60℃。
    雨期不改变出灰门槛。
    """
    latest = latest_batch_for_pond(pond)
    if latest is None:
        return False, "该池尚无熟化批次，不能标记为已出灰"
    if latest.peak_temp_c is None:
        return False, "最近批次尚未记录峰值温度，不能标记为已出灰"
    if latest.peak_temp_c < MIN_PEAK_TEMP_FOR_DRAWN:
        return (
            False,
            f"最近批次峰值温度 {latest.peak_temp_c}℃ 低于 {MIN_PEAK_TEMP_FOR_DRAWN:.0f}℃，不能标记为已出灰",
        )
    return True, ""


def assert_can_set_pond_status(pond: Pond, new_status: str) -> None:
    if new_status not in Pond.STATUS_CHOICES:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Pond.STATUS_DRAWN:
        ok, msg = can_mark_pond_drawn(pond)
        if not ok:
            raise RuleError(msg)


def is_rain_season(plant_id: int) -> bool:
    status = RainSeasonStatus.query.filter_by(plant_id=plant_id).one_or_none()
    return bool(status and status.active)


def find_open_cover(
    plant_id: int, day: date | None = None
) -> RainCover | None:
    """厂区某日未作废的遮雨档；默认查当日。"""
    day = day or local_today()
    return (
        RainCover.query.filter_by(plant_id=plant_id, cover_date=day)
        .filter(RainCover.voided_at.is_(None))
        .one_or_none()
    )


def assert_rain_cover_for_plant(plant_id: int) -> None:
    """
    雨期中登记批次 / 改峰值前，必须存在当日合格未作废遮雨档。
    非雨期不拦截。
    """
    if not is_rain_season(plant_id):
        return
    cover = find_open_cover(plant_id)
    if cover is None:
        raise RuleError("厂区正处于雨期且当日遮雨落实档缺失，禁止登记批次或抬峰值，请先建档")
