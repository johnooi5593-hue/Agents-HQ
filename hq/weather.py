"""The weather outside the office: the current weather in Petaling Jaya (owner, 2026-11-02: "make agents hq weather
follow the current weather status at Malaysia PJ"), from Open-Meteo (free, no key), asked at most every 10 minutes.
GET /api/weather returns {kind, code, day, temp, label, place, at}; kind is one of clear, cloudy, fog, drizzle, rain,
storm, and the office draws its sky, haze, rain and lightning from it. Without a connection the last answer stays, or
a clear night when there never was one."""
import json, threading, time, urllib.request

PLACE, LAT, LON = "Petaling Jaya", 3.1073, 101.6067
URL = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&timezone=Asia%%2FKuala_Lumpur"
       "&current=temperature_2m,weather_code,is_day,cloud_cover,precipitation" % (LAT, LON))
EVERY = 600
_lock, _last = threading.Lock(), {"t": 0.0, "data": None}

# WMO weather codes → what the office draws, and the words for the pill
KINDS = [((0, 1), "clear", "Clear"), ((2,), "cloudy", "Partly cloudy"), ((3,), "cloudy", "Cloudy"), ((45, 48), "fog", "Haze"),
         ((51, 53, 55, 56, 57), "drizzle", "Drizzle"), ((61, 63, 66, 80, 81), "rain", "Rain"), ((65, 67, 82), "rain", "Heavy rain"),
         ((71, 73, 75, 77, 85, 86), "rain", "Rain"), ((95, 96, 99), "storm", "Thunderstorm")]


def describe(code, day, temp, at=""):
    kind, label = "cloudy", "Cloudy"
    for codes, k, l in KINDS:
        if code in codes:
            kind, label = k, l
            break
    return {"kind": kind, "code": code, "day": bool(day), "temp": temp, "label": label, "place": PLACE, "at": at}


def fetch():
    with urllib.request.urlopen(URL, timeout=8) as r:
        cur = json.load(r)["current"]
    return describe(int(cur.get("weather_code") or 0), cur.get("is_day"), round(float(cur.get("temperature_2m") or 0)), cur.get("time", ""))


def current():
    """The current PJ weather, cached for 10 minutes."""
    with _lock:
        if _last["data"] and time.time() - _last["t"] < EVERY:
            return _last["data"]
        try:
            _last["data"] = fetch()
        except Exception:                                  # offline or the service is down: keep the last answer
            if not _last["data"]:
                _last["data"] = dict(describe(0, 0, None), stale=True)
        _last["t"] = time.time()                           # try again in 10 minutes either way
        return _last["data"]
