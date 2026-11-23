"""业务日期：固定按 UTC+8 算"今天/明天"。

事件时间（判分、作答）仍按 UTC 存；只有到期日这种"日历日"走这里。
时区只在这一个文件定义，将来要支持多时区只改这里。
"""
from datetime import date, datetime, timedelta, timezone

BUSINESS_TZ = timezone(timedelta(hours=8))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def as_utc(moment: datetime | None) -> datetime | None:
    """补上 UTC 时区；None 原样返回。"""
    return _as_utc(moment) if moment is not None else None


def iso_utc(moment: datetime | None) -> str | None:
    """接口时间统一格式：UTC ISO，末尾用 Z。"""
    if moment is None:
        return None
    return _as_utc(moment).isoformat().replace("+00:00", "Z")


def business_date_of(moment: datetime) -> date:
    """把任意时刻转成 UTC+8 的业务日期。"""
    return _as_utc(moment).astimezone(BUSINESS_TZ).date()


def business_today(now: datetime | None = None) -> date:
    """当前业务日期；测试可以传入固定时刻。"""
    return business_date_of(now or utcnow())
