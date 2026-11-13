import copy
import json
import math
import os
import time
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.metrics import dp
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.widget import Widget

from schedule_core import (ALL_DAYS, KINDS, ENERGY, DEFAULT_EVENTS, DEFAULT_CHECKLIST,
                           parse_time, parse_float, clean_data, merge_data, load_file,
                           save_file, data_to_text, desktop_data_path, weekday_name,
                           week_start, fmt_jalali, jalali_month_range, event_key,
                           build_report, guess_resource_kind)

try:
    from plyer import notification
except Exception:
    notification = None
try:
    from plyer import vibrator
except Exception:
    vibrator = None
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:
    arabic_reshaper = None
    get_display = None

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT = os.path.join(_HERE, "fonts", "Vazirmatn-Regular.ttf")
FONT = _FONT if os.path.exists(_FONT) else "Roboto"
EXPORT_NAME = "hamrah_dars_schedule.json"
PERIODS = [("week0", "???? ????"), ("week1", "???? ???"),
           ("month0", "??? ????"), ("month1", "??? ???")]
GREEN = (0.35, 0.75, 0.45, 1)
BLUE = (0.45, 0.65, 1, 1)
WHITE = (1, 1, 1, 1)

def fa(text):
    text = str(text)
    if arabic_reshaper and get_display:
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text
    return text

def est_height(text, per=36):
    return dp(20) * (1 + len(str(text)) // per) + dp(10)

def tick_color(done):
    return GREEN if done else WHITE

class FLabel(Label):
    def __init__(self, text="", **kw):
        kw.setdefault("font_name", FONT)
        kw.setdefault("halign", "center")
        kw.setdefault("valign", "middle")
        super().__init__(text=fa(text), **kw)
        self.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))

class FButton(Button):
    def __init__(self, text="", **kw):
        kw.setdefault("font_name", FONT)
        kw.setdefault("halign", "center")
        kw.setdefault("valign", "middle")
        super().__init__(text=fa(text), **kw)
        self.bind(size=lambda w, s: setattr(w, "text_size", (s[0] - dp(8), None)))

class FInput(TextInput):
    def __init__(self, hint_text="", **kw):
        kw.setdefault("font_name", FONT)
        super().__init__(hint_text=fa(hint_text), **kw)

class FSpinner(Spinner):
    def __init__(self, **kw):
        kw.setdefault("font_name", FONT)
        super().__init__(**kw)

def android_sdk():
    try:
        from jnius import autoclass
        return autoclass("android.os.Build$VERSION").SDK_INT
    except Exception:
        return 0

def default_db():
    return {"events": copy.deepcopy(DEFAULT_EVENTS), "tasks": [], "logs": [],
            "sessions": [], "checklist": copy.deepcopy(DEFAULT_CHECKLIST),
            "checks": {}, "meta": {}}

class StudyCompanion(App):
    def build(self):
        self.title = "????? ??? ? ?????"
        if platform == "android":
            self.data_path = os.path.join(self.user_data_dir, "study_data.json")
        else:
            self.data_path = str(desktop_data_path())
        self.db = default_db()
        self.notified = set()
        self._busy = 0
        self._mtime = 0
        self.current = None
        self.timer = None
        self.timer_label = None
        self.last_minutes = 45
        self._prefill = ""
        self._prefill_kind = "study"
        self._prefill_minutes = None
        self._prefill_resources = []
        self._pick_cb = None
        self._asking = False
        self.report_period = "week0"
        self._check_keys = []
        self._progress_label = None
        self.bind_activity()
        self.load_data()
        self.request_permissions()

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(7))
        root.add_widget(FLabel(text="????? ??? ? ?????", bold=True,
                               size_hint_y=None, height=dp(42), font_size="22sp"))
        nav = GridLayout(cols=4, size_hint_y=None, height=dp(92), spacing=dp(3))
        for name, cb in [("??????", self.show_schedule), ("?????", self.show_timer),
                         ("???????", self.show_checklist), ("?????", self.show_tasks),
                         ("???", self.show_log), ("?????", self.show_report),
                         ("??????", self.show_transfer)]:
            b = FButton(text=name, font_size="13sp")
            b.bind(on_release=lambda _, cb=cb: cb())
            nav.add_widget(b)
        root.add_widget(nav)
        self.content = BoxLayout(orientation="vertical")
        root.add_widget(self.content)
        self.show_schedule()
        Clock.schedule_interval(self.check_reminders, 15)
        Clock.schedule_interval(self.watch_file, 3)
        Clock.schedule_interval(self.tick, 1)
        return root

    def request_permissions(self):
        if platform != "android":
            return
        try:
            from android.permissions import request_permissions
            perms = ["android.permission.POST_NOTIFICATIONS"]
            if android_sdk() < 29:
                perms.append("android.permission.WRITE_EXTERNAL_STORAGE")
            request_permissions(perms)
        except Exception:
            pass

    def snapshot(self):
        return self.db

    def apply(self, d):
        self.db.update(d)

    def file_mtime(self):
        try:
            return os.path.getmtime(self.data_path)
        except OSError:
            return 0

    def load_data(self):
        try:
            self.apply(load_file(self.data_path))
        except Exception:
            pass
        self._mtime = self.file_mtime()

    def save_data(self):
        save_file(self.data_path, self.db)
        self._mtime = self.file_mtime()

    def watch_file(self, *_):
        if self._busy:
            return
        m = self.file_mtime()
        if m and m != self._mtime:
            try:
                self.apply(load_file(self.data_path))
            except Exception:
                self._mtime = m
                return
            self._mtime = m
            if self.current in (self.show_schedule, self.show_tasks,
                                self.show_report, self.show_checklist):
                self.current()

    def refresh(self):
        if self.current:
            self.current()

    def set_content(self, widget):
        self.content.clear_widgets()
        self.content.add_widget(widget)

    def scroll_page(self, current):
        self.current = current
        self.timer_label = None
        sc = ScrollView()
        box = BoxLayout(orientation="vertical", spacing=dp(7), padding=dp(4), size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        sc.add_widget(box)
        self.set_content(sc)
        return box

    def heading(self, parent, text):
        parent.add_widget(FLabel(text=text, bold=True, size_hint_y=None,
                                 height=dp(35), font_size="17sp"))

    def note(self, parent, text, height=None, size="13sp"):
        parent.add_widget(FLabel(text=text, size_hint_y=None,
                                 height=height or est_height(text), font_size=size))

    def action_button(self, parent, text, fn):
        b = FButton(text=text, size_hint_y=None, height=dp(44))
        b.bind(on_release=lambda *_: fn())
        parent.add_widget(b)

    def open_popup(self, pop):
        self._busy += 1
        pop.bind(on_dismiss=lambda *_: setattr(self, "_busy", max(0, self._busy - 1)))
        pop.open()

    def message(self, title, text):
        Popup(title=fa(title), title_font=FONT, content=FLabel(text=text),
              size_hint=(.88, .4)).open()

    def show_schedule(self, *_):
        box = self.scroll_page(self.show_schedule)
        self.heading(box, "?????? ?????")
        self.note(box, "?????? ????? ???? ????? ???. ?? ?????? «????» ???? ?? ???? ????? ???? ??? ???? ??????.")
        for day in ALL_DAYS:
            rows = sorted([e for e in self.db["events"] if e["day"] == day], key=lambda x: x["time"])
            if not rows:
                continue
            self.heading(box, day)
            for e in rows:
                line = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(3))
                line.add_widget(FLabel(text=self.event_label(e),
                                       halign="right", font_size="13sp"))
                if e.get("kind") != "health":
                    st = FButton(text="????", size_hint_x=None, width=dp(52), font_size="12sp")
                    st.bind(on_release=lambda _, item=e: self.begin_event_timer(item))
                    line.add_widget(st)
                edit = FButton(text="??????", size_hint_x=None, width=dp(60), font_size="12sp")
                edit.bind(on_release=lambda _, item=e: self.event_popup(item))
                delete = FButton(text="×", size_hint_x=None, width=dp(36))
                delete.bind(on_release=lambda _, item=e: self.delete_event(item))
                line.add_widget(edit)
                line.add_widget(delete)
                box.add_widget(line)
        self.action_button(box, "+ ?????? ??????", self.event_popup)
        self.action_button(box, "????????? ?????? ?????", self.reset_events)
        self.note(box, "??????? ???? ?????? ??? ? ???? ??? ????? ???????. ???? ????? ????? ?? ???? ????? ???? ???? ??????? ???? ???.",
                  size="12sp")

    def event_popup(self, event=None):
        is_new = event is None or not isinstance(event, dict)
        item = {"day": "????", "time": "18:00", "title": "", "kind": "study"} if is_new else event
        form = BoxLayout(orientation="vertical", spacing=dp(7), padding=dp(10))
        day = FSpinner(text=item["day"], values=ALL_DAYS, size_hint_y=None, height=dp(44))
        tm = FInput(text=item["time"], hint_text="???? ??? 18:30",
                    multiline=False, size_hint_y=None, height=dp(44))
        title = FInput(text=item["title"], hint_text="????? ??????",
                       multiline=False, size_hint_y=None, height=dp(44))
        kind = FSpinner(text=item.get("kind", "study"), values=KINDS,
                        size_hint_y=None, height=dp(44))
        for label, widget in [("???", day), ("???? (?? ?????)", tm), ("?????", title),
                              ("???: study/class/health/optional", kind)]:
            form.add_widget(FLabel(text=label, size_hint_y=None, height=dp(22)))
            form.add_widget(widget)
        if not is_new:
            rb = FButton(
                text=fa(f"????? ? ???????? ??? ({len(item.get('resources', []))})"),
                size_hint_y=None, height=dp(44))

            def refresh_rb(*_):
                rb.text = fa(
                    f"????? ? ???????? ??? ({len(item.get('resources', []))})")

            rb.bind(on_release=lambda *_: self.resources_popup(item, on_close=refresh_rb))
            form.add_widget(rb)
        buttons = BoxLayout(size_hint_y=None, height=dp(45), spacing=dp(5))
        pop = Popup(title=fa("?????? ????" if is_new else "?????? ??????"),
                    title_font=FONT, content=form, size_hint=(.94, .95))
        save = FButton(text="?????")
        cancel = FButton(text="???")

        def do_save(*_):
            t = parse_time(tm.text)
            if t is None or not title.text.strip():
                self.message("??????? ????", "???? ?? ??? 18:30 ? ????? ?? ???? ??.")
                return
            item.update(day=day.text, time=t, title=title.text.strip(), kind=kind.text)
            if is_new:
                self.db["events"].append(item)
            self.save_data()
            pop.dismiss()
            self.show_schedule()

        save.bind(on_release=do_save)
        cancel.bind(on_release=pop.dismiss)
        buttons.add_widget(save)
        buttons.add_widget(cancel)
        form.add_widget(buttons)
        self.open_popup(pop)

    def delete_event(self, item):
        self.db["events"] = [e for e in self.db["events"] if e is not item]
        self.save_data()
        self.show_schedule()

    def reset_events(self):
        self.db["events"] = copy.deepcopy(DEFAULT_EVENTS)
        self.save_data()
        self.show_schedule()

    def default_minutes(self, item):
        later = sorted({e["time"] for e in self.db["events"]
                        if e["day"] in (item["day"], "?? ???") and e["time"] > item["time"]})
        if not later:
            return self.last_minutes
        h1, m1 = map(int, item["time"].split(":"))
        h2, m2 = map(int, later[0].split(":"))
        return max(20, min(90, (h2 * 60 + m2) - (h1 * 60 + m1)))

    def begin_event_timer(self, item):
        if self.timer:
            self.message("????? ???? ???", "????? ????? ???? ?? ???? ?? ??? ??.")
            self.show_timer()
            return
        self._prefill = item["title"]
        self._prefill_kind = item.get("kind", "study")
        self._prefill_minutes = self.default_minutes(item)
        self._prefill_resources = list(item.get("resources", []))
        self.show_timer()

    def timer_elapsed(self):
        t = self.timer
        return t["base"] + (time.time() - t["t0"] if t["running"] else 0)

    def timer_text(self):
        remaining = max(0, self.timer["total"] - self.timer_elapsed())
        s = int(math.ceil(remaining))
        h, m, sec = s // 3600, (s % 3600) // 60, s % 60
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

    def show_timer(self, *_):
        box = self.scroll_page(self.show_timer)
        self.heading(box, "????? ???")
        t = self.timer
        if t:
            self.note(box, t["title"], size="17sp")
            self.timer_label = FLabel(text="", font_size="56sp", size_hint_y=None, height=dp(100))
            self.timer_label.text = self.timer_text()
            box.add_widget(self.timer_label)
            self.note(box, "?? ??? ????" if t["running"] else "????? ???", height=dp(28))
            self.resource_buttons(box, t.get("resources", []))
            self.action_button(box, "???? ????" if t["running"] else "?????", self.toggle_timer)
            self.action_button(box, "????? ? ??? ??????", lambda: self.finish_timer(True))
            self.action_button(box, "??? (???? ???)", lambda: self.finish_timer(False))
            self.note(box, "????? ?? ???? ????? ??? ??????. ??? ?????? ?? ?????? ?????? ????? ?? ??? ??????.",
                      size="12sp")
            return
        box.add_widget(FLabel(text="??? ???", size_hint_y=None, height=dp(22)))
        title = FInput(text=self._prefill, hint_text="??? ???", multiline=False,
                       size_hint_y=None, height=dp(45))
        box.add_widget(title)
        box.add_widget(FLabel(text="??? (?????)", size_hint_y=None, height=dp(22)))
        minutes = FInput(text=str(int(self._prefill_minutes or self.last_minutes)),
                         hint_text="??? (?????)", multiline=False,
                         size_hint_y=None, height=dp(45))
        box.add_widget(minutes)
        self.action_button(box, "???? ?????",
                           lambda: self.start_timer(title.text, minutes.text, self._prefill_kind,
                                                    list(self._prefill_resources)))
        self.resource_buttons(box, self._prefill_resources)

        today = date.today()
        lessons = [e for e in sorted(self.db["events"], key=lambda x: x["time"])
                   if e.get("kind") in ("study", "class") and e["day"] in (weekday_name(today), "?? ???")]
        if lessons:
            self.heading(box, "??????? ?????")
            for e in lessons:
                b = FButton(text=f'{e["time"]}  |  {e["title"]}', size_hint_y=None, height=dp(44))
                b.bind(on_release=lambda _, item=e: self.begin_event_timer(item))
                box.add_widget(b)
        mine = [s for s in self.db["sessions"] if s["date"] == today.isoformat()]
        if mine:
            self.heading(box, "?????? ?????")
            self.note(box, f'??? ?????: {round(sum(s["minutes"] for s in mine))} ?????', height=dp(30))
            for s in mine:
                self.note(box, f'{s["start"]}  {s["title"]}  ({s["minutes"]:g} ?????)', size="12sp")

    def start_timer(self, title, minutes_text, kind, resources=()):
        title = title.strip()
        m = parse_float(minutes_text)
        if not title:
            self.message("??? ??? ???? ???", "??? ??? ?? ???? ??.")
            return
        if m is None or not (1 <= m <= 600):
            self.message("??? ???????", "??? ?? ?? ????? ? ??? ? ?? ??? ???? ??.")
            return
        self.last_minutes = int(round(m))
        self.timer = {"title": title, "kind": kind if kind in KINDS else "study",
                      "total": m * 60, "planned": m, "base": 0.0, "t0": time.time(),
                      "running": True, "start": datetime.now().strftime("%H:%M"),
                      "resources": list(resources)}
        self._prefill = ""
        self._prefill_minutes = None
        self._prefill_resources = []
        self.show_timer()

    def toggle_timer(self):
        t = self.timer
        if not t:
            return
        now = time.time()
        if t["running"]:
            t["base"] += now - t["t0"]
            t["running"] = False
        else:
            t["t0"] = now
            t["running"] = True
        self.show_timer()

    def tick(self, *_):
        t = self.timer
        if not t:
            return
        if self.timer_elapsed() >= t["total"]:
            self.finish_timer(True, auto=True)
            return
        if self.timer_label is not None:
            self.timer_label.text = self.timer_text()

    def vibrate(self):
        try:
            if vibrator:
                vibrator.vibrate(1)
        except Exception:
            pass

    def finish_timer(self, save, auto=False):
        t = self.timer
        if not t:
            return
        elapsed = t["total"] if auto else self.timer_elapsed()
        self.timer = None
        minutes = round(elapsed / 60, 1)
        if save and elapsed >= 30:
            self.db["sessions"].append({
                "date": datetime.now().strftime("%Y-%m-%d"), "start": t["start"],
                "title": t["title"], "kind": t["kind"],
                "minutes": minutes, "planned": round(t["planned"], 1),
                "resources": list(t.get("resources", []))})
            self.save_data()
            msg = f'{minutes:g} ????? ?????? «{t["title"]}» ??? ??.'
        elif save:
            msg = "???? ?? ?? ????? ???? ??? ???."
        else:
            msg = "????? ??? ??."
        if auto:
            self.send_notification("???? ???? ??", t["title"])
            self.vibrate()
            msg = "???? ???? ??! " + msg
        self.message("?????", msg)
        if self.current == self.show_timer:
            self.show_timer()

    def show_checklist(self, *_):
        box = self.scroll_page(self.show_checklist)
        today = date.today()
        self.heading(box, "??????? ?????")
        self._progress_label = FLabel(text="", size_hint_y=None, height=dp(34), font_size="14sp")
        box.add_widget(self._progress_label)
        keys = []
        lessons = [e for e in sorted(self.db["events"], key=lambda x: x["time"])
                   if e.get("kind") != "optional" and e["day"] in (weekday_name(today), "?? ???")]
        if lessons:
            self.heading(box, "?????? ?????")
            for e in lessons:
                k = event_key(e)
                keys.append(k)
                self.tick_row(box, k, f'{e["time"]}  |  {e["title"]}')
        self.heading(box, "?????? ?????? ??????")
        for c in self.db["checklist"]:
            k = "c:" + c["id"]
            keys.append(k)
            self.tick_row(box, k, c["text"], on_delete=lambda c=c: self.delete_check_item(c))
        self._check_keys = keys
        self.update_progress()
        self.action_button(box, "+ ?????? ???? ?? ???????", self.add_check_item)
        self.note(box, "??????? ????? ?????? ?? ?? «??????» ??????? (????? ??????? ??). ?????? ???? ????? ????? ? ?????? ????? ???????.",
                  size="12sp")

    def is_ticked(self, key):
        return key in self.db["checks"].get(date.today().isoformat(), [])

    def toggle_check(self, key):
        iso = date.today().isoformat()
        cur = list(self.db["checks"].get(iso, []))
        if key in cur:
            cur.remove(key)
        else:
            cur.append(key)
        if cur:
            self.db["checks"][iso] = cur
        else:
            self.db["checks"].pop(iso, None)
        self.save_data()

    def update_progress(self):
        if self._progress_label is None:
            return
        today = date.today()
        total = len(self._check_keys)
        done = sum(1 for k in self._check_keys if self.is_ticked(k))
        txt = f"{weekday_name(today)} {fmt_jalali(today)}  |  "
        txt += f"{done} ?? {total} ????? ??" if total else "????? ???? ????? ????"
        self._progress_label.text = fa(txt)

    def tick_row(self, parent, key, text, on_delete=None):
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
        b = FButton(text=text, background_color=tick_color(self.is_ticked(key)))

        def toggle(*_):
            self.toggle_check(key)
            b.background_color = tick_color(self.is_ticked(key))
            self.update_progress()

        b.bind(on_release=toggle)
        row.add_widget(b)
        if on_delete:
            rm = FButton(text="×", size_hint_x=None, width=dp(44))
            rm.bind(on_release=lambda *_: on_delete())
            row.add_widget(rm)
        parent.add_widget(row)

    def add_check_item(self):
        ti = FInput(hint_text="?????: ???? ???? ????", multiline=False)
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        content.add_widget(ti)
        buttons = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(5))
        pop = Popup(title=fa("???? ????"), title_font=FONT, content=content, size_hint=(.9, .38))
        ok = FButton(text="???")
        no = FButton(text="???")

        def save(*_):
            if ti.text.strip():
                self.db["checklist"].append({"id": uuid.uuid4().hex[:8], "text": ti.text.strip()})
                self.save_data()
                pop.dismiss()
                self.show_checklist()

        ok.bind(on_release=save)
        no.bind(on_release=pop.dismiss)
        buttons.add_widget(ok)
        buttons.add_widget(no)
        content.add_widget(buttons)
        self.open_popup(pop)

    def delete_check_item(self, c):
        self.db["checklist"] = [x for x in self.db["checklist"] if x is not c]
        self.save_data()
        self.show_checklist()

    def show_tasks(self, *_):
        box = self.scroll_page(self.show_tasks)
        self.heading(box, "????? ?????")
        self.note(box, "??? ??? ??? ?? ????????? (???) ???.", height=dp(30), size="12sp")
        for i, task in enumerate(self.db["tasks"]):
            row = BoxLayout(size_hint_y=None, height=dp(48))
            b = FButton(text=task["text"], background_color=tick_color(task.get("done")))
            b.bind(on_release=lambda _, n=i: self.toggle_task(n))
            rm = FButton(text="×", size_hint_x=None, width=dp(44))
            rm.bind(on_release=lambda _, n=i: self.remove_task(n))
            row.add_widget(b)
            row.add_widget(rm)
            box.add_widget(row)
        self.action_button(box, "+ ?????? ????? ?? ???", self.add_task)
        self.note(box, "?????: ?? ? ??? ?????? ???? ??? ????? ????? ???????", size="12sp")

    def add_task(self):
        ti = FInput(hint_text="????? ???", multiline=False)
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        content.add_widget(ti)
        buttons = BoxLayout(size_hint_y=None, height=dp(44))
        pop = Popup(title=fa("??? ????"), title_font=FONT, content=content, size_hint=(.9, .38))
        ok = FButton(text="???")
        no = FButton(text="???")

        def save(*_):
            if ti.text.strip():
                self.db["tasks"].append({"text": ti.text.strip(), "done": False})
                self.save_data()
                pop.dismiss()
                self.show_tasks()

        ok.bind(on_release=save)
        no.bind(on_release=pop.dismiss)
        buttons.add_widget(ok)
        buttons.add_widget(no)
        content.add_widget(buttons)
        self.open_popup(pop)

    def toggle_task(self, n):
        tasks = self.db["tasks"]
        if 0 <= n < len(tasks):
            tasks[n]["done"] = not tasks[n].get("done", False)
            self.save_data()
            self.show_tasks()

    def remove_task(self, n):
        if 0 <= n < len(self.db["tasks"]):
            self.db["tasks"].pop(n)
            self.save_data()
            self.show_tasks()

    def show_log(self, *_):
        box = self.scroll_page(self.show_log)
        self.heading(box, "??? ????? ??????")
        today = datetime.now().strftime("%Y-%m-%d")
        old = next((x for x in self.db["logs"] if x.get("date") == today), {})
        sleep = FInput(text=str(old.get("sleep", "")), hint_text="??? ???? ???????? ???? 7.5",
                       multiline=False, size_hint_y=None, height=dp(45))
        energy = FSpinner(text=old.get("energy") or "????? ?????", values=ENERGY,
                          size_hint_y=None, height=dp(45))
        study = FInput(text=str(old.get("study", "")), hint_text="???????? ???? ????? (????)? ???? 3",
                       multiline=False, size_hint_y=None, height=dp(45))
        memo = FInput(text=old.get("note", ""), hint_text="??????? ?? ????? ????? (???????)",
                      size_hint_y=None, height=dp(85))
        for w in [sleep, energy, study, memo]:
            box.add_widget(w)
        self.action_button(box, "????? ????? ?????",
                           lambda: self.save_log(today, sleep.text, energy.text, study.text, memo.text))
        self.note(box, "???????? ????? ?????? ??? ??????? ??? ???? ??? ???? ????????? ??? ?? ???? ????? ?????. ??? ?????? ??????? ????? ????? ??????? ????? ????? ?? ?? ?????? ? ???? ?????? ??.",
                  size="12sp")

    def save_log(self, day, sleep, energy, study, memo):
        s = parse_float(sleep)
        st = parse_float(study, default=0.0)
        if s is None or st is None or not (0 <= s <= 24) or not (0 <= st <= 24):
            self.message("??? ???????", "???? ???? ? ?????? ?? ?? ???? ??? ??? ? ?? ?? ???? ??.")
            return
        if energy not in ENERGY:
            self.message("????? ?????? ????", "??? ????? ????? ?? ?????? ??.")
            return
        entry = {"date": day, "sleep": s, "energy": energy, "study": st, "note": memo}
        self.db["logs"] = [x for x in self.db["logs"] if x.get("date") != day]
        self.db["logs"].append(entry)
        self.save_data()
        self.message("??? ??", "????? ????? ????? ??.")

    def period_range(self, key, today=None):
        today = today or date.today()
        kind, off = key[:-1], int(key[-1])
        if kind == "week":
            ws = week_start(today) - timedelta(days=7 * off)
            return ws, ws + timedelta(days=6)
        return jalali_month_range(today, off)

    def report_lines(self, r):
        lines = [f"{fmt_jalali(r['start'])} ?? {fmt_jalali(r['end'])}"]
        if r["empty"]:
            lines.append("???? ??? ???? ???? ??????? ??? ???? ???.")
            return lines
        lines.append(f"?????? ?????????: {r['days']}")
        h, m = divmod(int(round(r["timer_minutes"])), 60)
        lines.append(f"?????? ?? ?????: {h} ???? ? {m} ????? ?? {r['sessions']} ????")
        if r["sessions"]:
            lines.append(f"??????? ??????: {r['timer_minutes'] / r['days']:.0f} ????? "
                         f"(?? {r['study_days']} ??? ?? {r['days']} ??? ?????? ?????)")
        if r["top"]:
            lines.append("??????? ????: " + "? ".join(
                f"{t} ({int(round(mn))} ?????)" for t, mn in r["top"]))
        if r["check_total"]:
            pct = 100 * r["check_done"] / r["check_total"]
            lines.append(f"???????: {r['check_done']} ?? {r['check_total']} ???? ({pct:.0f}%)? "
                         f"?????? ????: {r['perfect_days']}")
        if r["avg_sleep"] is not None:
            lines.append(f"??????? ????: {r['avg_sleep']:.1f} ???? (?? {r['log_days']} ??? ???????)")
        if r["avg_energy"] is not None:
            lines.append("??????? ?????: " + ENERGY[int(round(r["avg_energy"])) - 1])
        if r["tasks_total"]:
            lines.append(f"?????: {r['tasks_done']} ?? {r['tasks_total']} ????? ???")
        if r["check_total"]:
            pct = 100 * r["check_done"] / r["check_total"]
            if pct >= 80:
                lines.append("???? ???! ????? ?????? ?? ????? ????.")
            elif pct < 50:
                lines.append("???? ?? ??? ?????? ????? ??? ???? ???? ???? ?????? ?? ?????? ? ?????????????? ???.")
        if r["avg_sleep"] is not None and r["avg_sleep"] < 7:
            lines.append("??????? ????? ???? ?? ? ???? ???? ???? ???? ??? ????? ? ??????? ??? ?????? ????.")
        return lines

    def set_period(self, key):
        self.report_period = key
        self.show_report()

    def open_report(self, key):
        self.report_period = key
        self.show_report()

    def show_report(self, *_):
        box = self.scroll_page(self.show_report)
        self.heading(box, "?????")
        nav = GridLayout(cols=4, size_hint_y=None, height=dp(44), spacing=dp(3))
        for k, name in PERIODS:
            b = FButton(text=name, font_size="12sp",
                        background_color=BLUE if k == self.report_period else WHITE)
            b.bind(on_release=lambda _, k=k: self.set_period(k))
            nav.add_widget(b)
        box.add_widget(nav)
        start, end = self.period_range(self.report_period)
        r = build_report(self.db, start, end)
        lines = self.report_lines(r)
        self.note(box, lines[0], height=dp(32), size="14sp")
        for line in lines[1:]:
            self.note(box, line, size="14sp")
        self.action_button(box, "??? ????? ?????", self.show_log)

    def check_reports(self):
        now = datetime.now()
        today = now.date()
        evening = now.hour >= 21
        ws = week_start(today)
        week_now = weekday_name(today) == "????" and evening
        wk = ws if week_now else ws - timedelta(days=7)
        self.maybe_deliver("reported_week", wk, wk + timedelta(days=6), "????? ?????",
                           "week0" if week_now else "week1", week_now)
        ms, me = jalali_month_range(today, 0)
        month_now = today == me and evening
        mk = ms if month_now else jalali_month_range(today, 1)[0]
        self.maybe_deliver("reported_month", mk, jalali_month_range(mk, 0)[1], "????? ??????",
                           "month0" if month_now else "month1", month_now)

    def maybe_deliver(self, meta_key, start, end, title, period_key, is_current):
        iso = start.isoformat()
        last = self.db["meta"].get(meta_key)
        if last is not None and last >= iso:
            return
        self.db["meta"][meta_key] = iso
        self.save_data()
        if last is None and not is_current:
            return
        r = build_report(self.db, start, end)
        if r["empty"]:
            return
        self.send_notification(title, "????? ????? ???? ?????? ?? ??? ??.")
        self.report_popup(title, r, period_key)

    def report_popup(self, title, r, period_key):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(4))
        for line in self.report_lines(r)[:8]:
            content.add_widget(FLabel(text=line, size_hint_y=None,
                                      height=est_height(line), font_size="13sp"))
        content.add_widget(Widget())
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(5))
        pop = Popup(title=fa(title), title_font=FONT, content=content, size_hint=(.94, .88))
        full = FButton(text="????? ????")
        close = FButton(text="????")
        full.bind(on_release=lambda *_: (pop.dismiss(), self.open_report(period_key)))
        close.bind(on_release=pop.dismiss)
        row.add_widget(full)
        row.add_widget(close)
        content.add_widget(row)
        pop.open()

    def show_transfer(self, *_):
        box = self.scroll_page(self.show_transfer)
        self.heading(box, "?????? ? ?????? ?? ??????")
        self.note(box, "????? ????? ???? ?? ??? ???????? ?? schedule_tool.py ?? ?? ???????? ????? ???? "
                       "? ?????? ???? ?????? ??. ???????? ????? ? ??????? ??????? ?? ?? ???? ?????.")
        self.action_button(box, "????? ?? ???? (???? Download)", self.export_file)
        self.action_button(box, "??? ??? ??????? ?? ?????????", self.copy_clipboard)
        self.action_button(box, "???? ?? ????", self.import_from_file)
        self.action_button(box, "???? ?? ??? (???????)", self.import_from_text_popup)
        self.action_button(box, "???? ?? ?????????", self.import_from_clipboard)
        if platform != "android":
            self.note(box, f"???? ???? ??? ????????: {self.data_path}", size="11sp")

    def write_export(self, name, text):
        if platform == "android":
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            if android_sdk() >= 29:
                ContentValues = autoclass("android.content.ContentValues")
                Downloads = autoclass("android.provider.MediaStore$Downloads")
                values = ContentValues()
                values.put("_display_name", name)
                values.put("mime_type", "application/json")
                values.put("relative_path", "Download/")
                resolver = activity.getContentResolver()
                uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
                stream = resolver.openOutputStream(uri)
                stream.write(text.encode("utf-8"))
                stream.flush()
                stream.close()
                return "Download/" + name
            Env = autoclass("android.os.Environment")
            folder = Env.getExternalStoragePublicDirectory(Env.DIRECTORY_DOWNLOADS).getAbsolutePath()
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return path
        folder = Path.home() / "Downloads"
        if not folder.exists():
            folder = Path.home()
        path = folder / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def export_file(self):
        try:
            where = self.write_export(EXPORT_NAME, data_to_text(self.db))
            self.message("????? ????? ??",
                         f"????? ?? ??: {where}\n(??? ???? ?????? ???? ??????? ??????? ???? ??????.)")
        except Exception as ex:
            self.message("??? ?? ?????", f"{ex}\n?? «??? ?? ?????????» ??????? ??.")

    def copy_clipboard(self):
        try:
            Clipboard.copy(data_to_text(self.db))
            self.message("??? ??", "??? ???? ??????? ?? ????????? ???? ???????? ?? ?? ???? ???? ??????.")
        except Exception as ex:
            self.message("???", str(ex))

    def import_from_file(self):
        try:
            from plyer import filechooser
            filechooser.open_file(on_selection=self._file_chosen, filters=["*.json"])
        except Exception:
            self.message("?????? ???? ?? ????? ????", "?? «???? ?? ???» ?? «???? ?? ?????????» ??????? ??.")

    def _file_chosen(self, selection):
        if not selection:
            return
        path = selection[0]
        Clock.schedule_once(lambda dt: self._import_path(path), 0)

    def _import_path(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            self.message("?????? ???? ???? ???",
                         "???? ??????? ??????? ?????? ?????? ???????. ??? ???? ?? ??? ?? ? ?? «???? ?? ???» ??????? ??.")
            return
        self.import_text(text)

    def import_from_clipboard(self):
        try:
            self.import_text(Clipboard.paste() or "")
        except Exception as ex:
            self.message("???", str(ex))

    def import_from_text_popup(self):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        ti = FInput(hint_text="??? JSON ?? ????? ??????", multiline=True)
        content.add_widget(ti)
        buttons = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(5))
        pop = Popup(title=fa("???? ?? ???"), title_font=FONT, content=content, size_hint=(.94, .8))
        ok = FButton(text="????")
        no = FButton(text="???")

        def go(*_):
            text = ti.text
            pop.dismiss()
            self.import_text(text)

        ok.bind(on_release=go)
        no.bind(on_release=pop.dismiss)
        buttons.add_widget(ok)
        buttons.add_widget(no)
        content.add_widget(buttons)
        self.open_popup(pop)

    def import_text(self, text):
        try:
            inc = clean_data(json.loads(text))
        except Exception:
            self.message("??? ???????", "??? ??? ?? ???? JSON ????? ?????? ????.")
            return
        if not inc:
            self.message("??????? ???? ???", "?????? ?????? ?? ?? ????.")
            return
        summary = (f"??????: {len(inc.get('events', []))}  |  ???: {len(inc.get('tasks', []))}  "
                   f"|  ??? ??????: {len(inc.get('logs', []))}  |  ???? ?????: {len(inc.get('sessions', []))}"
                   f"\n???? ???? ????")
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        content.add_widget(FLabel(text=summary))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(5))
        pop = Popup(title=fa("????? ????"), title_font=FONT, content=content, size_hint=(.92, .42))
        rep, mrg, no = FButton(text="????????"), FButton(text="?????"), FButton(text="???")
        rep.bind(on_release=lambda *_: (pop.dismiss(), self.apply_import(inc, "replace")))
        mrg.bind(on_release=lambda *_: (pop.dismiss(), self.apply_import(inc, "merge")))
        no.bind(on_release=pop.dismiss)
        for b in (rep, mrg, no):
            row.add_widget(b)
        content.add_widget(row)
        self.open_popup(pop)

    def apply_import(self, inc, mode):
        if mode == "replace":
            self.apply(inc)
        else:
            self.db.update(merge_data(self.db, inc))
        self.save_data()
        self.refresh()
        self.message("????? ??", "??????? ???? ????.")

    def check_reminders(self, *_):
        self.check_reports()
        now = datetime.now()
        weekday = weekday_name(now.date())
        current = now.strftime("%H:%M")
        stamp = now.strftime("%Y-%m-%d")
        self.notified = {k for k in self.notified if k.startswith(stamp)}
        for e in self.db["events"]:
            if e["time"] != current or e["day"] not in (weekday, "?? ???"):
                continue
            key = f'{stamp}|{e["day"]}|{e["time"]}|{e["title"]}'
            if key in self.notified:
                continue
            self.notified.add(key)
            sent = self.send_notification(e["title"], f'???? ?????? ???????????????: {e["time"]}')
            if e.get("kind") in ("study", "class") or e.get("resources"):
                self.ask_start(e)
            elif not sent:
                self.message(e["title"], f'???? ?????? ???????????????: {e["time"]}')

    def send_notification(self, title, message):
        if notification:
            try:
                notification.notify(title=title, message=message,
                                    app_name="????? ??? ? ?????", timeout=10)
                return True
            except Exception:
                pass
        return False

    def event_label(self, e):
        n = len(e.get("resources", []))
        text = f'{e["time"]}  |  {e["title"]}'
        return text + (f"  ({n} ????)" if n else "")

    def bind_activity(self):
        if platform != "android":
            return
        try:
            from android import activity as android_activity
            android_activity.bind(on_activity_result=self._on_pick)
        except Exception:
            pass

    def pick_file(self, callback):
        if platform == "android":
            try:
                from jnius import autoclass
                Intent = autoclass("android.content.Intent")
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                self._pick_cb = callback
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType("*/*")
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
                activity.startActivityForResult(intent, 4242)
            except Exception as ex:
                self.message("?????? ???? ???? ???", str(ex))
            return
        try:
            from plyer import filechooser

            def chosen(sel):
                if sel:
                    path = sel[0]
                    Clock.schedule_once(
                        lambda dt: callback(path, os.path.basename(path)), 0)

            filechooser.open_file(on_selection=chosen)
        except Exception:
            self.message("?????? ???? ?? ????? ????", "???? ???? ?? ???? ???? ??.")

    def _on_pick(self, request, result, intent):
        if request != 4242:
            return
        cb, self._pick_cb = self._pick_cb, None
        if cb is None or result != -1 or intent is None:
            return
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            uri = intent.getData()
            if uri is None:
                return
            resolver = activity.getContentResolver()
            try:
                resolver.takePersistableUriPermission(
                    uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            except Exception:
                pass
            name = ""
            try:
                cursor = resolver.query(uri, None, None, None, None)
                if cursor is not None:
                    if cursor.moveToFirst():
                        idx = cursor.getColumnIndex("_display_name")
                        if idx >= 0:
                            name = cursor.getString(idx) or ""
                    cursor.close()
            except Exception:
                pass
            target = uri.toString()
        except Exception:
            return
        Clock.schedule_once(lambda dt: cb(target, name), 0)

    def open_resource(self, res):
        target = res["target"]
        kind = res.get("kind") or guess_resource_kind(target)
        try:
            if platform == "android":
                from jnius import autoclass
                Intent = autoclass("android.content.Intent")
                Uri = autoclass("android.net.Uri")
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                if kind == "link" and "://" not in target:
                    target = "https://" + target
                uri = Uri.parse(target)
                intent = Intent(Intent.ACTION_VIEW)
                if kind == "file":
                    mime = activity.getContentResolver().getType(uri) or "*/*"
                    intent.setDataAndType(uri, mime)
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                else:
                    intent.setData(uri)
                activity.startActivity(intent)
            elif kind == "link":
                import webbrowser
                webbrowser.open(target if "://" in target else "https://" + target)
            else:
                import subprocess
                import sys as _sys
                if _sys.platform.startswith("win"):
                    os.startfile(target)
                elif _sys.platform == "darwin":
                    subprocess.Popen(["open", target])
                else:
                    subprocess.Popen(["xdg-open", target])
        except Exception as ex:
            self.message("??? ???? ???? ???",
                         f"????????? ???? ??? ???? ???? ??? ?? ?????? ?? ??? ????.\n{ex}")

    def resource_buttons(self, parent, resources, heading=True):
        if not resources:
            return
        if heading:
            if hasattr(self, "heading"):
                self.heading(parent, "????? ??? ???")
            else:
                parent.add_widget(FLabel(text="????? ??? ???",
                                         size_hint_y=None, height=dp(30)))
        for r in resources:
            prefix = "????: " if r.get("kind") == "link" else "????: "
            b = FButton(text=prefix + r["name"], size_hint_y=None, height=dp(44))
            b.bind(on_release=lambda _, r=r: self.open_resource(r))
            parent.add_widget(b)

    def resources_list_popup(self, resources):
        if not resources:
            return
        if len(resources) == 1:
            self.open_resource(resources[0])
            return
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        sc = ScrollView()
        lst = BoxLayout(orientation="vertical", spacing=dp(5), size_hint_y=None)
        lst.bind(minimum_height=lst.setter("height"))
        sc.add_widget(lst)
        content.add_widget(sc)
        self.resource_buttons(lst, resources, heading=False)
        pop = Popup(title=fa("???? ?????"), title_font=FONT,
                    content=content, size_hint=(.92, .7))
        close = FButton(text="????", size_hint_y=None, height=dp(44))
        close.bind(on_release=pop.dismiss)
        content.add_widget(close)
        pop.open()

    def resources_popup(self, item, on_close=None):
        res = item.setdefault("resources", [])
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        sc = ScrollView()
        lst = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None)
        lst.bind(minimum_height=lst.setter("height"))
        sc.add_widget(lst)
        content.add_widget(sc)
        name = FInput(hint_text="??? ???? (?????: ???? ?????)", multiline=False,
                      size_hint_y=None, height=dp(44))
        target = FInput(hint_text="???? ???? ?? ???? ????", multiline=False,
                        size_hint_y=None, height=dp(44))
        content.add_widget(name)
        content.add_widget(target)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(5))
        pick = FButton(text="?????? ????")
        add = FButton(text="??????")
        close = FButton(text="????")
        for b in (pick, add, close):
            row.add_widget(b)
        content.add_widget(row)
        pop = Popup(title=fa("????? ? ???????? ???"), title_font=FONT,
                    content=content, size_hint=(.94, .9))

        def remove(r):
            for i, x in enumerate(res):
                if x is r:
                    del res[i]
                    break
            self.save_data()
            rebuild()

        def rebuild():
            lst.clear_widgets()
            if not res:
                lst.add_widget(FLabel(text="???? ????? ????? ????.",
                                      size_hint_y=None, height=dp(40)))
            for r in res:
                line = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(4))
                prefix = "????: " if r.get("kind") == "link" else "????: "
                ob = FButton(text=prefix + r["name"])
                ob.bind(on_release=lambda _, r=r: self.open_resource(r))
                rm = FButton(text="×", size_hint_x=None, width=dp(42))
                rm.bind(on_release=lambda _, r=r: remove(r))
                line.add_widget(ob)
                line.add_widget(rm)
                lst.add_widget(line)

        def picked(t, n):
            target.text = t
            if not name.text.strip():
                name.text = n

        def do_add(*_):
            t = target.text.strip()
            if not t:
                self.message("???? ???? ???",
                             "???? ?? ???? ?? ?? «?????? ????» ?? ???.")
                return
            kind = guess_resource_kind(t)
            if kind == "link" and "://" not in t:
                t = "https://" + t
            res.append({"name": name.text.strip() or t, "target": t, "kind": kind})
            name.text = ""
            target.text = ""
            self.save_data()
            rebuild()

        pick.bind(on_release=lambda *_: self.pick_file(picked))
        add.bind(on_release=do_add)
        close.bind(on_release=pop.dismiss)
        if on_close:
            pop.bind(on_dismiss=lambda *_: on_close())
        rebuild()
        pop.open()

    def ask_start(self, e):
        resources = e.get("resources", [])
        can_timer = e.get("kind") in ("study", "class") and not self.timer
        if not can_timer and not resources:
            return
        if getattr(self, "_asking", False):
            return
        self._asking = True
        mins = self.default_minutes(e)
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        content.add_widget(FLabel(text=f"???? «{e['title']}» ????."))
        if can_timer:
            content.add_widget(FLabel(text=f"????? {mins} ???????? ???? ????"))
        if resources:
            content.add_widget(FLabel(text=f"{len(resources)} ???? ???? ??? ??? ????? ???."))
        pop = Popup(title=fa("???? ???"), title_font=FONT,
                    content=content, size_hint=(.92, .55))
        pop.bind(on_dismiss=lambda *_: setattr(self, "_asking", False))

        def start(open_res):
            pop.dismiss()
            if can_timer and not self.timer:
                self.start_timer(e["title"], str(mins), e.get("kind", "study"),
                                 list(resources))
            if open_res:
                self.resources_list_popup(resources)

        btns = []
        if can_timer:
            b = FButton(text="???? ?????", size_hint_y=None, height=dp(44))
            b.bind(on_release=lambda *_: start(False))
            btns.append(b)
        if resources:
            b = FButton(text="???? ????? ? ??? ???? ???" if can_timer else "??? ???? ???",
                        size_hint_y=None, height=dp(44))
            b.bind(on_release=lambda *_: start(True))
            btns.append(b)
        b = FButton(text="?????", size_hint_y=None, height=dp(44))
        b.bind(on_release=pop.dismiss)
        btns.append(b)
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(5),
                        height=dp(44) * len(btns) + dp(5) * (len(btns) - 1))
        for b in btns:
            col.add_widget(b)
        content.add_widget(col)
        pop.open()

if __name__ == "__main__":
    StudyCompanion().run()