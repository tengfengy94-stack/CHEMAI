"""业务日期与进程内事件（第 07 章）。"""
from datetime import date, datetime, timezone

from app import clock, events


def test_business_date_crosses_at_utc_1600():
    assert clock.business_date_of(datetime(2026, 11, 21, 15, 59, tzinfo=timezone.utc)) == date(
        2026, 11, 21
    )
    assert clock.business_date_of(datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc)) == date(
        2026, 11, 22
    )


def test_business_date_handles_naive_utc_and_month_end():
    assert clock.business_date_of(datetime(2026, 1, 31, 16, 0)) == date(2026, 2, 1)
    assert clock.business_date_of(datetime(2025, 12, 31, 16, 0)) == date(2026, 1, 1)


def test_business_today_accepts_injected_now():
    assert clock.business_today(datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)) == date(
        2026, 11, 22
    )


def test_event_subscriber_receives_kwargs():
    seen = []

    def handler(**kwargs):
        seen.append(kwargs)

    events.subscribe("test_event", handler)
    events.publish("test_event", value=3)
    assert seen == [{"value": 3}]


def test_publish_without_subscribers_is_noop():
    events.publish("test_event_without_subscriber", value=1)


def test_multiple_subscribers_all_called():
    seen = []
    events.subscribe("test_multi", lambda **kw: seen.append(("a", kw["n"])))
    events.subscribe("test_multi", lambda **kw: seen.append(("b", kw["n"])))
    events.publish("test_multi", n=1)
    assert seen == [("a", 1), ("b", 1)]
