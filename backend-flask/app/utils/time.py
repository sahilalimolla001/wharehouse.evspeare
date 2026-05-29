from datetime import datetime, time, timedelta


IST_OFFSET = timedelta(hours=5, minutes=30)
IST_SUFFIX = "+05:30"


def india_now():
    return datetime.utcnow() + IST_OFFSET


def india_today_start():
    return datetime.combine(india_now().date(), time.min)


def india_timestamp(prefix_format="%Y%m%d%H%M%S%f", length=17):
    return india_now().strftime(prefix_format)[:length]


def india_iso(value):
    if not value:
        return None
    return value.isoformat() + IST_SUFFIX
