"""石灰熟化池业务规则。"""

from __future__ import annotations

from datetime import date

from app.models import Plant, Pond, RainCoverLog, SlakeBatch, local_today

MIN_PEAK_TEMP_FOR_DRAWN = 60.0


class RuleError(ValueError):
    """业务规则校验失败。"""


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: b.started_at)


def can_mark_pond_drawn(pond: Pond) -> tuple[bool, str]:
    """
    熟化池转为「已出灰」(drawn) 的前提：
    最近一条熟化批次的峰值温度已记录，且 >= 60℃。
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


def active_rain_cover_for(plant_id: int, on_day: date | None = None) -> RainCoverLog | None:
    """某厂区某自然日(默认今天)的未作废遮雨落实档,没有则 None。"""
    day = on_day or local_today()
    return (
        RainCoverLog.query.filter(
            RainCoverLog.plant_id == plant_id,
            RainCoverLog.log_date == day,
            RainCoverLog.voided_at.is_(None),
        )
        .order_by(RainCoverLog.id.desc())
        .first()
    )


def assert_rain_cover_today(plant: Plant | None, action: str) -> None:
    """
    雨期门槛:厂区正处于雨期时,动作(登记批次 / 抬峰值)前
    必须已存在当日未作废的遮雨落实档;收起雨期后不校验。
    """
    if plant is None or not plant.rain_season_on:
        return
    if active_rain_cover_for(plant.id) is None:
        raise RuleError(
            f"{plant.name} 正处于雨期,{action}前须先在「雨期遮雨」专页落实当日遮雨档"
        )
