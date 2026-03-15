from datetime import date
from zoneinfo import ZoneInfo
from astral import LocationInfo
from astral.sun import sun

TZ = ZoneInfo("Europe/London")

LONDON = LocationInfo(
    name="London",
    region="UK",
    timezone="Europe/London",
    latitude=51.5074,
    longitude=-0.1278,
)

def get_sunrise_dt(day: date):
    s = sun(LONDON.observer, date=day, tzinfo=TZ)
    return s["sunrise"]
