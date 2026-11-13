import copy
import json
import os
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

DAYS = ["????", "??????", "??????", "???????", "????????", "???????", "????"]
ALL_DAYS = DAYS + ["?? ???"]
KINDS = ["study", "class", "health", "optional"]
ENERGY = ["???? ??", "??", "?????", "???", "???? ???"]
MONTHS_FA = ["???????", "????????", "?????", "???", "?????", "??????",
             "???", "????", "???", "??", "????", "?????"]

DEFAULT_EVENTS = [
    {"day": "????", "time": "18:00", "title": "????? ?????", "kind": "study"},
    {"day": "????", "time": "19:00", "title": "???? ???? (?? 20:20)", "kind": "class"},
    {"day": "????", "time": "20:30", "title": "?????? ???? ? ???????", "kind": "study"},
    {"day": "??????", "time": "18:00", "title": "????? ??????", "kind": "study"},
    {"day": "??????", "time": "19:00", "title": "????? ??????", "kind": "study"},
    {"day": "??????", "time": "20:15", "title": "???? ???????? ?????", "kind": "study"},
    {"day": "??????", "time": "18:00", "title": "????? ? ??? ?????", "kind": "study"},
    {"day": "??????", "time": "19:00", "title": "?????", "kind": "study"},
    {"day": "??????", "time": "20:15", "title": "????? ??????", "kind": "study"},
    {"day": "???????", "time": "18:00", "title": "???? ??????", "kind": "study"},
    {"day": "???????", "time": "19:00", "title": "???? ???? ???", "kind": "study"},
    {"day": "???????", "time": "20:15", "title": "???? ? ?????", "kind": "study"},
    {"day": "????????", "time": "18:00", "title": "????? ?????", "kind": "study"},
    {"day": "????????", "time": "19:00", "title": "???? ???? (?? 20:20)", "kind": "class"},
    {"day": "????????", "time": "20:30", "title": "???? ? ??????", "kind": "study"},
    {"day": "???????", "time": "18:00", "title": "?????", "kind": "study"},
    {"day": "???????", "time": "19:00", "title": "????? ? ?????", "kind": "study"},
    {"day": "???????", "time": "20:15", "title": "???? ???? ? ??????", "kind": "study"},
    {"day": "????", "time": "18:00", "title": "????? ????? (??? ????? ?????)", "kind": "optional"},
    {"day": "????", "time": "18:00", "title": "Python (??? ???? ???? ?????)", "kind": "optional"},
    {"day": "?? ???", "time": "22:00", "title": "????????? ???? ????", "kind": "health"},
]

DEFAULT_CHECKLIST = [
    {"id": "d1", "text": "?????? ????? ???? ??"},
    {"id": "d2", "text": "???? ????? ????? ?????"},
    {"id": "d3", "text": "?? ???? ?????? ? ??? ???? ????"},
    {"id": "d4", "text": "????? ???? ????? ??"},
]

_DIGITS = str.maketrans("????????????????????", "01234567890123456789")

def normalize_digits(value):
    return str(value).translate(_DIGITS).replace("?", ".").replace(",", ".").replace("?", ".").strip()

def parse_time(value):
    try:
        return datetime.strptime(normalize_digits(value), "%H:%M").strftime("%H:%M")
    except Exception:
        return None

def parse_float(value, default=None):
    v = normalize_digits(value)
    if v == "":
        return default
    try:
        return float(v)
    except Exception:
        return None

def valid_date(s):
    try:
        datetime.strptime(str(s), "%Y-%m-%d")
        return True
    except Exception:
        return False

def g2j(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100
            + (gy2 + 399) // 400 + gd + g_d_m[gm - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd

def j2g(jy, jm, jd):
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    sal = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal[gm]:
        gd -= sal[gm]
        gm += 1
    return gy, gm, gd

def weekday_name(d):
    return DAYS[(d.weekday() + 2) % 7]

def week_start(d):
    return d - timedelta(days=(d.weekday() + 2) % 7)

def fmt_jalali(d):
    jy, jm, jd = g2j(d.year, d.month, d.day)
    return f"{jd} {MONTHS_FA[jm - 1]} {jy}"

def jalali_month_range(d, offset=0):
    jy, jm, _ = g2j(d.year, d.month, d.day)
    m = jm - 1 - offset
    jy += m // 12
    jm = m % 12 + 1
    start = date(*j2g(jy, jm, 1))
    ny, nm = (jy + 1, 1) if jm == 12 else (jy, jm + 1)
    end = date(*j2g(ny, nm, 1)) - timedelta(days=1)
    return start, end

def guess_resource_kind(target):
    t = str(target).strip()
    if t.lower().startswith(("content://", "file://", "/")) or os.path.exists(t):
        return "file"
    return "link"

def clean_resources(raw):
    out = []
    if not isinstance(raw, list):
        return out
    for r in raw:
        if not isinstance(r, dict):
            continue
        target = str(r.get("target", "")).strip()
        if not target:
            continue
        kind = r.get("kind") if r.get("kind") in ("file", "link") else guess_resource_kind(target)
        out.append({"name": str(r.get("name", "")).strip() or target,
                    "target": target, "kind": kind})
    return out

def clean_event(e):
    if not isinstance(e, dict):
        return None
    day = e.get("day")
    t = parse_time(e.get("time", ""))
    title = str(e.get("title", "")).strip()
    if day not in ALL_DAYS or t is None or not title:
        return None
    kind = e.get("kind") if e.get("kind") in KINDS else "study"
    out = {"day": day, "time": t, "title": title, "kind": kind}
    resources = clean_resources(e.get("resources"))
    if resources:
        out["resources"] = resources
    return out

def clean_task(t):
    if not isinstance(t, dict) or not str(t.get("text", "")).strip():
        return None
    return {"text": str(t["text"]).strip(), "done": bool(t.get("done", False))}

def clean_log(x):
    if not isinstance(x, dict) or not valid_date(x.get("date", "")):
        return None
    sleep = parse_float(x.get("sleep", 0), 0.0)
    study = parse_float(x.get("study", 0), 0.0)
    if sleep is None or study is None:
        return None
    return {"date": str(x["date"]), "sleep": sleep, "study": study,
            "energy": str(x.get("energy", "")), "note": str(x.get("note", ""))}

def clean_session(s):
    if not isinstance(s, dict) or not valid_date(s.get("date", "")):
        return None
    title = str(s.get("title", "")).strip()
    minutes = parse_float(s.get("minutes"))
    if not title or minutes is None or minutes < 0:
        return None
    planned = parse_float(s.get("planned", 0), 0.0) or 0.0
    out = {"date": str(s["date"]), "start": parse_time(s.get("start", "")) or "",
           "title": title, "kind": s.get("kind") if s.get("kind") in KINDS else "study",
           "minutes": minutes, "planned": planned}
    resources = clean_resources(s.get("resources"))
    if resources:
        out["resources"] = resources
    return out

def clean_checklist_item(c):
    if not isinstance(c, dict) or not str(c.get("text", "")).strip():
        return None
    cid = str(c.get("id") or uuid.uuid4().hex[:8]).strip() or uuid.uuid4().hex[:8]
    return {"id": cid, "text": str(c["text"]).strip()}

def clean_checks(d):
    out = {}
    for k, v in d.items():
        if valid_date(k) and isinstance(v, list):
            items = list(dict.fromkeys(str(i) for i in v))
            if items:
                out[str(k)] = items
    return out

def clean_meta(d):
    out = {}
    for k in ("reported_week", "reported_month"):
        if valid_date(d.get(k, "")):
            out[k] = str(d[k])
    return out

def clean_data(d):
    if not isinstance(d, dict):
        raise ValueError("?????? ???? ????? ????")
    out = {}
    for key, fn in (("events", clean_event), ("tasks", clean_task), ("logs", clean_log),
                    ("sessions", clean_session), ("checklist", clean_checklist_item)):
        raw = d.get(key)
        if isinstance(raw, list):
            cleaned = [c for c in map(fn, raw) if c]
            if cleaned or not raw:
                out[key] = cleaned
    if isinstance(d.get("checks"), dict):
        out["checks"] = clean_checks(d["checks"])
    if isinstance(d.get("meta"), dict):
        out["meta"] = clean_meta(d["meta"])
    return out

def merge_data(cur, inc):
    out = copy.deepcopy(cur)
    ev = out.setdefault("events", [])
    seen = {(e["day"], e["time"], e["title"]): e for e in ev}
    for e in inc.get("events", []):
        k = (e["day"], e["time"], e["title"])
        if k not in seen:
            ev.append(e)
            seen[k] = e
        elif e.get("resources"):
            cur = seen[k].setdefault("resources", [])
            have = {r["target"] for r in cur}
            cur.extend(r for r in e["resources"] if r["target"] not in have)
    tasks = out.setdefault("tasks", [])
    texts = {t["text"] for t in tasks}
    for t in inc.get("tasks", []):
        if t["text"] not in texts:
            tasks.append(t)
            texts.add(t["text"])
    logs = {x["date"]: x for x in out.setdefault("logs", [])}
    for x in inc.get("logs", []):
        logs[x["date"]] = x
    out["logs"] = [logs[k] for k in sorted(logs)]
    ses = out.setdefault("sessions", [])
    seen = {(s["date"], s["start"], s["title"]) for s in ses}
    for s in inc.get("sessions", []):
        k = (s["date"], s["start"], s["title"])
        if k not in seen:
            ses.append(s)
            seen.add(k)
    cl = out.setdefault("checklist", [])
    ids = {c["id"] for c in cl}
    for c in inc.get("checklist", []):
        if c["id"] not in ids:
            cl.append(c)
            ids.add(c["id"])
    checks = out.setdefault("checks", {})
    for k, v in inc.get("checks", {}).items():
        checks[k] = list(dict.fromkeys(checks.get(k, []) + v))
    out.setdefault("meta", {})
    return out

def event_key(e):
    return "e:%s|%s|%s" % (e["day"], e["time"], e["title"])

def planned_items(data, d):
    wd = weekday_name(d)
    items = [event_key(e) for e in data.get("events", [])
             if e.get("kind") != "optional" and e["day"] in (wd, "?? ???")]
    items += ["c:" + c["id"] for c in data.get("checklist", [])]
    return items

def first_record_date(data):
    ds = list(data.get("checks", {}).keys())
    ds += [s["date"] for s in data.get("sessions", [])]
    ds += [x["date"] for x in data.get("logs", [])]
    return min(ds) if ds else None

def build_report(data, start, end, today=None):
    today = today or date.today()
    r = {"start": start, "end": end, "empty": True}
    last = min(end, today)
    first = first_record_date(data)
    if not first:
        return r
    eff = max(start, date.fromisoformat(first))
    if eff > last:
        return r
    days = [eff + timedelta(days=i) for i in range((last - eff).days + 1)]
    iso = {d.isoformat() for d in days}
    r["empty"] = False
    r["days"] = len(days)

    sess = [s for s in data.get("sessions", []) if s["date"] in iso]
    by = {}
    for s in sess:
        by[s["title"]] = by.get(s["title"], 0) + s["minutes"]
    r["timer_minutes"] = sum(s["minutes"] for s in sess)
    r["sessions"] = len(sess)
    r["study_days"] = len({s["date"] for s in sess})
    r["top"] = sorted(by.items(), key=lambda x: -x[1])[:3]

    logs = [x for x in data.get("logs", []) if x["date"] in iso]
    r["log_days"] = len(logs)
    r["avg_sleep"] = sum(x["sleep"] for x in logs) / len(logs) if logs else None
    en = [ENERGY.index(x["energy"]) + 1 for x in logs if x["energy"] in ENERGY]
    r["avg_energy"] = sum(en) / len(en) if en else None

    checks = data.get("checks", {})
    done = total = perfect = 0
    for d in days:
        items = set(planned_items(data, d))
        ticked = set(checks.get(d.isoformat(), [])) & items
        done += len(ticked)
        total += len(items)
        if items and len(ticked) == len(items):
            perfect += 1
    r["check_done"], r["check_total"], r["perfect_days"] = done, total, perfect

    tasks = data.get("tasks", [])
    r["tasks_done"] = sum(1 for t in tasks if t.get("done"))
    r["tasks_total"] = len(tasks)
    return r

def desktop_data_path():
    env = os.environ.get("HAMRAH_DATA")
    return Path(env) if env else Path.home() / ".hamrahdars" / "study_data.json"

def load_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return clean_data(json.load(f))

def data_to_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2)

def save_file(path, data):
    path = str(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data_to_text(data))
    os.replace(tmp, path)