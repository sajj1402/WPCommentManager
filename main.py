import sys, os, json, re, csv, threading, time as _time, html as _html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kivy.config import Config
Config.set("kivy", "log_level", "warning")
Config.set("input", "mouse", "mouse,multitouch_on_demand")

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.slider import Slider
from kivy.uix.progressbar import ProgressBar
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.graphics import Color, RoundedRectangle
from kivy.core.window import Window

from lib.security import vault_exists, load_vault, save_vault, DEFAULT_VAULT
from lib.wp_api import Site, test_connection, get_posts, get_post_content, get_comments, send_comment, send_comment_via_form, approve_comment, delete_comment, PROVIDERS as WP_PROVIDERS
from lib.ai_provider import PROVIDERS as AI_PROVIDERS, COMMENT_TONES, LANGUAGES, generate_comment, generate_batch_comments, test_provider


THEME = {
    "bg_dark": "#0f0f1a", "bg_card": "#1a1a2e", "bg_input": "#16213e",
    "accent": "#00d4ff", "accent_dark": "#0099cc", "success": "#00e676",
    "warning": "#ffab00", "danger": "#ff1744",
    "text_primary": "#e0e0e0", "text_secondary": "#8899aa", "text_accent": "#00d4ff",
}


def _rgba(hex_color, a=1):
    h = hex_color.lstrip("#")
    return [int(h[i:i+2], 16)/255 for i in (0, 2, 4)] + [a]


def _resolve_provider_key(label):
    for k, v in AI_PROVIDERS.items():
        if v["name"] == label:
            return k
    return "gemini"


def _tone_key(label):
    for k, v in COMMENT_TONES:
        if v == label:
            return k
    return "Neutral"


def _lang_key(label):
    for k, v in LANGUAGES.items():
        if v["label"] == label:
            return k
    return "persian"


# ─── Custom Widgets ──────────────────────────

class RoundedButton(Button):
    def __init__(self, **kwargs):
        self.bg = kwargs.pop("bg", THEME["accent"])
        self.rad = kwargs.pop("radius", dp(12))
        super().__init__(**kwargs)
        self.background_color = (0, 0, 0, 0)
        self.background_normal = ""
        self.size_hint_y = None
        self.height = dp(48)
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*_rgba(self.bg))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.rad])


class TLabel(Label):
    def __init__(self, **kwargs):
        self.c = kwargs.pop("color", THEME["text_primary"])
        self.fs = kwargs.pop("font_size", dp(14))
        super().__init__(**kwargs)
        self.color = _rgba(self.c)
        self.font_size = self.fs
        self.halign = kwargs.get("halign", "left")
        self.valign = "middle"
        self.text_size = (self.width, None)
        self.bind(width=lambda s, w: setattr(s, "text_size", (w, None)))
        self.bind(texture_size=lambda s, ts: setattr(s, "height", max(self.height, ts[1] + dp(4))))


class TInput(TextInput):
    def __init__(self, **kwargs):
        self.is_pwd = kwargs.pop("password", False)
        super().__init__(**kwargs)
        self.password = self.is_pwd
        self.background_color = (0, 0, 0, 0)
        self.background_normal = ""
        self.foreground_color = _rgba(THEME["text_primary"])
        self.padding = (dp(12), dp(12))
        self.size_hint_y = None
        self.height = dp(48)
        self.cursor_color = _rgba(THEME["accent"])
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*_rgba(THEME["bg_input"]))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])


class TSpinner(Spinner):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_color = (0, 0, 0, 0)
        self.background_normal = ""
        self.color = _rgba(THEME["text_primary"])
        self.size_hint_y = None
        self.height = dp(48)
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*_rgba(THEME["bg_input"]))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])


class DarkPopup(Popup):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_color = _rgba(THEME["bg_dark"])
        self.title_color = _rgba(THEME["text_accent"])
        self.separator_color = _rgba(THEME["bg_card"])


def msgbox(title, text, btn="OK", cb=None):
    content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(20))
    content.add_widget(TLabel(text=text, color=THEME["text_primary"],
                              text_size=(dp(260), None), halign="center"))
    b = RoundedButton(text=btn, bg=THEME["accent"])
    content.add_widget(b)
    pop = DarkPopup(title=title, content=content, size_hint=(0.85, 0.35), auto_dismiss=False)
    b.bind(on_press=lambda x: [pop.dismiss(), cb() if cb else None])
    pop.open()


def confirm(title, text, cb):
    content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(20))
    content.add_widget(TLabel(text=text, color=THEME["text_primary"],
                              text_size=(dp(260), None), halign="center"))
    row = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(44))
    yb = RoundedButton(text="Yes", bg=THEME["danger"])
    nb = RoundedButton(text="No", bg=THEME["bg_card"])
    row.add_widget(yb); row.add_widget(nb)
    content.add_widget(row)
    pop = DarkPopup(title=title, content=content, size_hint=(0.85, 0.3), auto_dismiss=False)
    yb.bind(on_press=lambda x: [pop.dismiss(), cb(True)])
    nb.bind(on_press=lambda x: [pop.dismiss(), cb(False)])
    pop.open()


# ─── Helper: Build card widget ──
def _card(height=dp(60), **kwargs):
    box = BoxLayout(**kwargs)
    with box.canvas.before:
        Color(*_rgba(THEME["bg_card"]))
        RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(8)])
    box.bind(pos=lambda s, v: setattr(s.canvas.before.children[-1], "pos", v) if s.canvas.before.children else None,
             size=lambda s, v: setattr(s.canvas.before.children[-1], "size", v) if s.canvas.before.children else None)
    return box


# ─── Job Queue ──
class Job:
    def __init__(self, site, post_id, content, guest_name="Guest", guest_email="guest@example.com",
                 as_admin=True, schedule_at=None):
        self.site = site
        self.post_id = post_id
        self.content = content
        self.guest_name = guest_name
        self.guest_email = guest_email
        self.as_admin = as_admin
        self.schedule_at = schedule_at
        self.status = "pending"
        self.result = ""


class JobQueue:
    def __init__(self):
        self.jobs = []
        self.running = False
        self._thread = None
        self.on_progress = None

    def add(self, job):
        self.jobs.append(job)

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _run(self):
        while self.running:
            now = _time.time()
            for job in self.jobs:
                if job.status != "pending":
                    continue
                if job.schedule_at and now < job.schedule_at:
                    continue
                job.status = "running"
                self._execute(job)
                if self.on_progress:
                    Clock.schedule_once(lambda dt: self.on_progress())
                _time.sleep(1.5)
            _time.sleep(2)

    def _execute(self, job):
        try:
            ok, res = send_comment(
                site=job.site, post_id=job.post_id, content=job.content,
                guest_name=job.guest_name, guest_email=job.guest_email,
                as_admin=job.as_admin, timeout=20,
                proxy_url=job.site.proxy_url, lang=job.site.lang,
            )
            if ok:
                job.status = "done"
                job.result = "sent"
                return
            ok2, res2 = send_comment_via_form(
                site=job.site, post_id=job.post_id, content=job.content,
                guest_name=job.guest_name, guest_email=job.guest_email,
                timeout=20, proxy_url=job.site.proxy_url, lang=job.site.lang,
            )
            if ok2:
                job.status = "done"
                job.result = "sent (via form)"
            else:
                job.status = "failed"
                job.result = str(res) if not ok else str(res2)
        except Exception as e:
            job.status = "failed"
            job.result = str(e)


# ─── Screen Helpers ──

def _build_header(title, back_target="sites"):
    header = BoxLayout(size_hint_y=None, height=dp(50), padding=[dp(8), dp(8)])
    with header.canvas.before:
        Color(*_rgba(THEME["bg_card"]))
        RoundedRectangle(pos=header.pos, size=header.size)
    header.bind(pos=lambda s, v: setattr(s.canvas.before.children[-1], "pos", v) if s.canvas.before.children else None,
                size=lambda s, v: setattr(s.canvas.before.children[-1], "size", v) if s.canvas.before.children else None)
    bk = Button(text="←", font_size=dp(22), background_color=(0,0,0,0),
                color=_rgba(THEME["text_accent"]), size_hint_x=None, width=dp(44))
    bk.bind(on_press=lambda x: setattr(App.get_running_app().root, "current", back_target))
    header.add_widget(bk)
    header.add_widget(TLabel(text=title, font_size=dp(17), bold=True, color=THEME["text_accent"]))
    return header


def _bg(screen):
    with screen.canvas.before:
        Color(*_rgba(THEME["bg_dark"]))
        RoundedRectangle(pos=screen.pos, size=screen.size)
    screen.bind(pos=lambda s, v: setattr(s.canvas.before.children[-1], "pos", v) if s.canvas.before.children else None,
                size=lambda s, v: setattr(s.canvas.before.children[-1], "size", v) if s.canvas.before.children else None)


# ═══════════════════════════════════════════════════
#  SCREEN: Login
# ═══════════════════════════════════════════════════

class LoginScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.app = App.get_running_app()
        _bg(self)
        box = BoxLayout(orientation="vertical", padding=dp(30), spacing=dp(15))
        box.add_widget(TLabel(text="WP Comment Manager", font_size=dp(22), bold=True,
                              color=THEME["text_accent"], halign="center", size_hint_y=None, height=dp(50)))
        box.add_widget(TLabel(text="Android", font_size=dp(14), color=THEME["text_secondary"],
                              halign="center", size_hint_y=None, height=dp(24)))
        self.pw = TInput(hint_text="Master Password", password=True, multiline=False)
        box.add_widget(self.pw)
        self.lb = RoundedButton(text="Unlock", bg=THEME["accent"])
        self.lb.bind(on_press=self.login)
        box.add_widget(self.lb)
        self.st = TLabel(text="", color=THEME["danger"], size_hint_y=None, height=dp(28), halign="center")
        box.add_widget(self.st)
        box.add_widget(Label(size_hint_y=1))
        self.add_widget(box)
        self.pw.bind(on_text_validate=self.login)

    def on_enter(self):
        if vault_exists():
            self.pw.text = ""
            Clock.schedule_once(lambda dt: setattr(self.pw, "focus", True))
        else:
            self.manager.current = "setup"

    def login(self, *a):
        p = self.pw.text.strip()
        if not p:
            self.st.text = "Enter password"; return
        data = load_vault(p)
        if data is None:
            self.st.text = "Wrong password"; return
        self.app.master_pwd = p
        self.app.vault_data = data
        self.app.settings = data.get("settings", dict(DEFAULT_VAULT["settings"]))
        self.app.ai_api_keys = data.get("api_keys_ai", {})
        sites = data.get("sites", [])
        self.app.sites = [Site.from_dict(s, data["passwords"].get(s["id"], ""),
                                         data["api_keys"].get(s["id"], "")) for s in sites]
        self.manager.current = "sites"


# ═══════════════════════════════════════════════════
#  SCREEN: Setup
# ═══════════════════════════════════════════════════

class SetupScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.app = App.get_running_app()
        _bg(self)
        box = BoxLayout(orientation="vertical", padding=dp(30), spacing=dp(12))
        box.add_widget(TLabel(text="Create Master Password", font_size=dp(20), bold=True,
                              color=THEME["text_accent"], halign="center", size_hint_y=None, height=dp(44)))
        box.add_widget(TLabel(text="Min 8 characters", font_size=dp(13), color=THEME["text_secondary"],
                              halign="center", size_hint_y=None, height=dp(22)))
        self.p1 = TInput(hint_text="New password", password=True, multiline=False)
        box.add_widget(self.p1)
        self.p2 = TInput(hint_text="Confirm password", password=True, multiline=False)
        box.add_widget(self.p2)
        b = RoundedButton(text="Create Account", bg=THEME["success"])
        b.bind(on_press=self.doit)
        box.add_widget(b)
        self.st = TLabel(text="", color=THEME["danger"], size_hint_y=None, height=dp(26), halign="center")
        box.add_widget(self.st)
        box.add_widget(Label(size_hint_y=1))
        self.add_widget(box)

    def doit(self, *a):
        a, b = self.p1.text.strip(), self.p2.text.strip()
        if len(a) < 8:
            self.st.text = "Min 8 characters"; return
        if a != b:
            self.st.text = "Passwords don't match"; return
        save_vault(a, dict(DEFAULT_VAULT))
        self.app.master_pwd = a
        self.app.vault_data = dict(DEFAULT_VAULT)
        self.app.sites = []
        self.app.settings = dict(DEFAULT_VAULT["settings"])
        self.app.ai_api_keys = {}
        self.app.job_queue = JobQueue()
        self.manager.current = "sites"


# ═══════════════════════════════════════════════════
#  SCREEN: Sites
# ═══════════════════════════════════════════════════

class SitesScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.app = App.get_running_app()
        self._built = False

    def _ensure(self):
        if self._built:
            return
        self._built = True
        _bg(self)
        layout = BoxLayout(orientation="vertical")

        # Header
        hdr = BoxLayout(size_hint_y=None, height=dp(52), padding=[dp(12), dp(8)])
        with hdr.canvas.before:
            Color(*_rgba(THEME["bg_card"]))
            RoundedRectangle(pos=hdr.pos, size=hdr.size)
        hdr.bind(pos=self._upd_hdr, size=self._upd_hdr)
        hdr.add_widget(TLabel(text="My Sites", font_size=dp(18), bold=True, color=THEME["text_accent"]))
        tools = BoxLayout(size_hint_x=None, width=dp(144), spacing=dp(2))
        for sym, sc in [("📋", "csv"), ("⏱", "jobs"), ("⚙", "settings")]:
            b = Button(text=sym, font_size=dp(16), background_color=(0,0,0,0),
                       color=_rgba(THEME["text_secondary"]), size_hint_x=None, width=dp(44))
            b.bind(on_press=lambda x, s=sc: setattr(self.manager, "current", s))
            tools.add_widget(b)
        hdr.add_widget(tools)
        layout.add_widget(hdr)

        self.scroll = ScrollView()
        self.list = BoxLayout(orientation="vertical", spacing=dp(6), padding=[dp(12), dp(6), dp(12), dp(6)],
                               size_hint_y=None)
        self.list.bind(minimum_height=self.list.setter("height"))
        self.scroll.add_widget(self.list)
        layout.add_widget(self.scroll)

        # Bottom bar
        bot = BoxLayout(size_hint_y=None, height=dp(56), padding=dp(12), spacing=dp(8))
        with bot.canvas.before:
            Color(*_rgba(THEME["bg_card"]))
            RoundedRectangle(pos=bot.pos, size=bot.size)
        bot.bind(pos=self._upd_bot, size=self._upd_bot)
        addb = RoundedButton(text="+ Add Site", bg=THEME["accent"])
        addb.bind(on_press=lambda x: setattr(self.manager, "current", "add_site"))
        bot.add_widget(addb)
        layout.add_widget(bot)
        self.add_widget(layout)

    def _upd_hdr(self, s, v):
        if s.canvas.before.children:
            s.canvas.before.children[-1].pos = v
            s.canvas.before.children[-1].size = s.size

    def _upd_bot(self, s, v):
        if s.canvas.before.children:
            s.canvas.before.children[-1].pos = v
            s.canvas.before.children[-1].size = s.size

    def on_enter(self):
        self.refresh()

    def refresh(self):
        self.list.clear_widgets()
        if not self.app.sites:
            self.list.add_widget(TLabel(text="No sites yet.\nTap + Add Site", color=THEME["text_secondary"],
                                        halign="center", size_hint_y=None, height=dp(70)))
            return
        for site in self.app.sites:
            card = _card(orientation="horizontal", size_hint_y=None, height=dp(68),
                         padding=[dp(10), dp(6)], spacing=dp(6))
            info = BoxLayout(orientation="vertical")
            info.add_widget(TLabel(text=site.name, font_size=dp(15), bold=True,
                                   color=THEME["text_primary"]))
            info.add_widget(TLabel(text=site.url[:35] + ("..." if len(site.url) > 35 else ""),
                                   font_size=dp(10), color=THEME["text_secondary"]))
            if site.lang:
                info.add_widget(TLabel(text=f"lang: {site.lang}", font_size=dp(9),
                                       color=THEME["text_accent"]))
            card.add_widget(info)
            acts = BoxLayout(size_hint_x=None, width=dp(100), spacing=dp(4))
            for sym, cb in [("✎", self._edit), ("✕", self._delete)]:
                b = Button(text=sym, font_size=dp(18), background_color=_rgba(THEME["bg_input"]),
                           color=_rgba(THEME["text_primary"]))
                b.site = site
                b.bind(on_press=cb)
                acts.add_widget(b)
            card.site = site
            card.bind(on_touch_down=self._open)
            card.add_widget(acts)
            self.list.add_widget(card)

    def _open(self, inst, touch):
        if inst.collide_point(*touch.pos) and hasattr(inst, "site"):
            self.app.current_site = inst.site
            Clock.schedule_once(lambda dt: setattr(self.manager, "current", "site_detail"))

    def _edit(self, b):
        self.app.edit_site = b.site
        self.manager.current = "add_site"

    def _delete(self, b):
        def cb(yes):
            if yes:
                self.app.sites = [s for s in self.app.sites if s.id != b.site.id]
                self._save()
        confirm("Delete", f"Delete '{b.site.name}'?", cb)

    def _save(self):
        self.app.vault_data["sites"] = [s.to_dict() for s in self.app.sites]
        self.app.vault_data["passwords"] = {s.id: s.password for s in self.app.sites}
        self.app.vault_data["api_keys"] = {s.id: s.api_key for s in self.app.sites if s.api_key}
        save_vault(self.app.master_pwd, self.app.vault_data)
        self.refresh()


# ═══════════════════════════════════════════════════
#  SCREEN: Add/Edit Site
# ═══════════════════════════════════════════════════

class AddSiteScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.app = App.get_running_app()
        _bg(self)
        layout = BoxLayout(orientation="vertical")
        layout.add_widget(_build_header("Add Site"))

        scroll = ScrollView()
        form = BoxLayout(orientation="vertical", spacing=dp(10), padding=[dp(20), dp(8)],
                         size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))
        self.entries = {}
        for key, hint, pwd in [("name", "Site Name", False), ("url", "WordPress URL", False),
                               ("username", "Username", False), ("password", "Password", True)]:
            form.add_widget(TLabel(text=hint, color=THEME["text_secondary"], size_hint_y=None, height=dp(22)))
            e = TInput(hint_text=hint, password=pwd, multiline=False)
            self.entries[key] = e
            form.add_widget(e)

        for key, hint in [("api_key", "API Key (optional)"), ("proxy", "Proxy (optional)"),
                          ("lang", "Language (optional, e.g. en, fa)")]:
            form.add_widget(TLabel(text=hint, color=THEME["text_secondary"], size_hint_y=None, height=dp(22)))
            e = TInput(hint_text=hint, multiline=False)
            self.entries[key] = e
            form.add_widget(e)

        form.add_widget(Label(size_hint_y=None, height=dp(6)))
        self.save_btn = RoundedButton(text="Save & Test", bg=THEME["success"])
        self.save_btn.bind(on_press=self.save)
        form.add_widget(self.save_btn)
        self.st = TLabel(text="", color=THEME["danger"], size_hint_y=None, height=dp(26), halign="center")
        form.add_widget(self.st)
        form.add_widget(Label(size_hint_y=0.4))
        scroll.add_widget(form)
        layout.add_widget(scroll)
        self.add_widget(layout)

    def on_enter(self):
        es = getattr(self.app, "edit_site", None)
        if es:
            self.save_btn.text = "Save Changes"
            self.entries["name"].text = es.name
            self.entries["url"].text = es.url
            self.entries["username"].text = es.username
            self.entries["password"].text = es.password
            self.entries["api_key"].text = es.api_key
            self.entries["proxy"].text = es.proxy_url
            self.entries["lang"].text = es.lang
        else:
            self.save_btn.text = "Save & Test"
            for e in self.entries.values():
                e.text = ""

    def save(self, *a):
        vals = {k: v.text.strip() for k, v in self.entries.items()}
        if not all([vals["name"], vals["url"], vals["username"], vals["password"]]):
            self.st.text = "Name, URL, Username, Password required"; return
        if getattr(self.app, "edit_site", None) and self.app.edit_site:
            s = self.app.edit_site
            s.name, s.url, s.username = vals["name"], vals["url"], vals["username"]
            s.password, s.api_key = vals["password"], vals["api_key"]
            s.proxy_url, s.lang = vals["proxy"], vals["lang"]
        else:
            s = Site(name=vals["name"], url=vals["url"], username=vals["username"],
                     password=vals["password"], api_key=vals["api_key"],
                     proxy_url=vals["proxy"], lang=vals["lang"])
            self.app.sites.append(s)
        self.st.text = "Testing..."
        def t():
            ok, msg = test_connection(s, timeout=self.app.settings.get("timeout", 20))
            Clock.schedule_once(lambda dt: self._r(ok, msg))
        threading.Thread(target=t, daemon=True).start()

    def _r(self, ok, msg):
        if ok:
            self.app.edit_site = None
            self._commit()
            msgbox("Success", msg)
        else:
            def cb(y):
                if y:
                    self.app.edit_site = None
                    self._commit()
            confirm("Connection Failed", msg + "\n\nSave anyway?", cb)

    def _commit(self):
        self.app.vault_data["sites"] = [s.to_dict() for s in self.app.sites]
        self.app.vault_data["passwords"] = {s.id: s.password for s in self.app.sites}
        self.app.vault_data["api_keys"] = {s.id: s.api_key for s in self.app.sites if s.api_key}
        save_vault(self.app.master_pwd, self.app.vault_data)
        self.manager.current = "sites"


# ═══════════════════════════════════════════════════
#  SCREEN: Site Detail (Posts / Comments / AI / Batch AI)
# ═══════════════════════════════════════════════════

class SiteDetailScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.app = App.get_running_app()
        _bg(self)
        layout = BoxLayout(orientation="vertical")
        # Header
        hdr = BoxLayout(size_hint_y=None, height=dp(48), padding=[dp(8), dp(6)])
        with hdr.canvas.before:
            Color(*_rgba(THEME["bg_card"]))
            RoundedRectangle(pos=hdr.pos, size=hdr.size)
        hdr.bind(pos=lambda s, v: self._pos_upd(s, v),
                 size=lambda s, v: self._size_upd(s, v))
        bk = Button(text="←", font_size=dp(20), background_color=(0,0,0,0),
                    color=_rgba(THEME["text_accent"]), size_hint_x=None, width=dp(40))
        bk.bind(on_press=lambda x: setattr(self.manager, "current", "sites"))
        hdr.add_widget(bk)
        self.site_label = TLabel(text="", font_size=dp(16), bold=True, color=THEME["text_primary"])
        hdr.add_widget(self.site_label)
        layout.add_widget(hdr)

        # Tabs
        self.tab_bar = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(2), padding=[dp(8), 0])
        with self.tab_bar.canvas.before:
            Color(*_rgba(THEME["bg_card"]))
            RoundedRectangle(pos=self.tab_bar.pos, size=self.tab_bar.size)
        self.tab_bar.bind(pos=lambda s, v: self._pos_upd(s, v, "tab"),
                          size=lambda s, v: self._size_upd(s, v, "tab"))
        self.tab_btns = {}
        for name in ["Posts", "Comments", "AI", "Batch AI"]:
            b = Button(text=name, font_size=dp(12), background_color=_rgba("#15152a"), color=_rgba("#777"))
            b.bind(on_press=self._switch_tab)
            self.tab_btns[name] = b
            self.tab_bar.add_widget(b)
        layout.add_widget(self.tab_bar)

        self.content = BoxLayout(orientation="vertical")
        layout.add_widget(self.content)

        # Send Comment popup fields (reused)
        self.send_content = None
        self.send_name = None
        self.send_email = None

        self.add_widget(layout)

    def _pos_upd(self, s, v, tag=None):
        if s.canvas.before.children:
            s.canvas.before.children[-1].pos = v

    def _size_upd(self, s, v, tag=None):
        if s.canvas.before.children:
            s.canvas.before.children[-1].size = v

    def on_enter(self):
        site = getattr(self.app, "current_site", None)
        if site:
            self.site_label.text = f"  {site.name}"
        self._activate_tab("Posts")

    def _activate_tab(self, name):
        for n, b in self.tab_btns.items():
            b.background_color = _rgba("#15152a")
            b.color = _rgba("#777")
        self.tab_btns[name].background_color = _rgba("#003355")
        self.tab_btns[name].color = _rgba(THEME["text_accent"])
        if name == "Posts":
            self._show_posts()
        elif name == "Comments":
            self._show_comments()
        elif name == "AI":
            self._show_ai()
        elif name == "Batch AI":
            self._show_batch_ai()

    def _switch_tab(self, b):
        self._activate_tab(b.text)

    # ── Posts Tab ──
    def _show_posts(self):
        self.content.clear_widgets()
        site = getattr(self.app, "current_site", None)
        if not site:
            return
        self.content.add_widget(TLabel(text="Loading posts...", color=THEME["text_secondary"], halign="center"))
        def load():
            posts = get_posts(site, timeout=self.app.settings.get("timeout", 20), proxy_url=site.proxy_url)
            Clock.schedule_once(lambda dt: self._disp_posts(posts))
        threading.Thread(target=load, daemon=True).start()

    def _disp_posts(self, posts):
        self.content.clear_widgets()
        if not posts:
            self.content.add_widget(TLabel(text="No posts found", color=THEME["text_secondary"], halign="center"))
            return
        scroll = ScrollView()
        layout = BoxLayout(orientation="vertical", spacing=dp(4), padding=[dp(8), dp(4)],
                           size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))
        for p in posts:
            t = p.get("title", {}); t = t.get("rendered", "") if isinstance(t, dict) else str(t)
            card = _card(orientation="vertical", size_hint_y=None, height=dp(72), padding=[dp(10), dp(6)])
            card.add_widget(TLabel(text=f"{_html.unescape(t[:60])}", font_size=dp(13),
                                   bold=True, color=THEME["text_primary"]))
            card.add_widget(TLabel(text=f"ID: {p['id']} | {p.get('date','')[:10]}",
                                   font_size=dp(10), color=THEME["text_secondary"]))
            card.post_id = p["id"]
            card.content = _html.unescape(t)
            card.bind(on_touch_down=self._post_tap)
            layout.add_widget(card)
        scroll.add_widget(layout)
        self.content.add_widget(scroll)

    def _post_tap(self, inst, touch):
        if not inst.collide_point(*touch.pos) or not hasattr(inst, "post_id"):
            return
        site = getattr(self.app, "current_site", None)
        if not site:
            return
        self._show_send_dialog(site, inst.post_id, inst.content)

    def _show_send_dialog(self, site, post_id, post_title):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        box.add_widget(TLabel(text=f"Send comment to Post {post_id}", font_size=dp(14),
                              bold=True, color=THEME["text_accent"], halign="center"))
        box.add_widget(TInput(hint_text="Comment text", multiline=True, size_hint_y=None, height=dp(100)))
        box.add_widget(TInput(hint_text="Your name (optional)", multiline=False))
        box.add_widget(TInput(hint_text="Your email (optional)", multiline=False))
        btn = RoundedButton(text="Send Comment", bg=THEME["success"])

        pop = DarkPopup(title=f"Post: {_html.unescape(post_title[:40])}...",
                        content=box, size_hint=(0.92, 0.55), auto_dismiss=False)
        cancel = RoundedButton(text="Cancel", bg=THEME["bg_card"])
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(44))
        row.add_widget(cancel)
        row.add_widget(btn)
        box.add_widget(row)

        def do_send(*a):
            text = box.children[4].text.strip()
            name = box.children[3].text.strip() or "Guest"
            email = box.children[2].text.strip() or "guest@example.com"
            if not text:
                msgbox("Error", "Comment text is empty")
                return
            pop.dismiss()
            self.content.clear_widgets()
            self.content.add_widget(TLabel(text="Sending...", color=THEME["text_secondary"], halign="center"))
            def t():
                ok, res = send_comment(site=site, post_id=post_id, content=text,
                                       guest_name=name, guest_email=email,
                                       as_admin=True, timeout=self.app.settings.get("timeout", 20),
                                       proxy_url=site.proxy_url, lang=site.lang)
                if ok:
                    Clock.schedule_once(lambda dt: [msgbox("Success", "Comment sent!"), self._show_posts()])
                else:
                    ok2, res2 = send_comment_via_form(site=site, post_id=post_id, content=text,
                                                      guest_name=name, guest_email=email,
                                                      timeout=self.app.settings.get("timeout", 20),
                                                      proxy_url=site.proxy_url, lang=site.lang)
                    if ok2:
                        Clock.schedule_once(lambda dt: [msgbox("Success", "Sent via form!"), self._show_posts()])
                    else:
                        Clock.schedule_once(lambda dt: msgbox("Failed", f"Admin: {res}\nForm: {res2}"))
            threading.Thread(target=t, daemon=True).start()
        btn.bind(on_press=do_send)
        cancel.bind(on_press=pop.dismiss)
        pop.open()

    # ── Comments Tab ──
    def _show_comments(self):
        self.content.clear_widgets()
        site = getattr(self.app, "current_site", None)
        if not site:
            return
        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6), padding=[dp(8), dp(4)])
        self.cmt_spin = TSpinner(text="All", values=("All", "Hold", "Approved", "Spam"), size_hint_x=0.6)
        self.cmt_spin.bind(text=lambda s, v: self._load_cmts())
        top.add_widget(self.cmt_spin)
        rf = Button(text="↻", font_size=dp(20), background_color=(0,0,0,0),
                    color=_rgba(THEME["text_accent"]), size_hint_x=None, width=dp(44))
        rf.bind(on_press=lambda x: self._load_cmts())
        top.add_widget(rf)
        self.content.add_widget(top)

        self.cmt_scroll = ScrollView()
        self.cmt_list = BoxLayout(orientation="vertical", spacing=dp(4), padding=[dp(8), dp(4)],
                                   size_hint_y=None)
        self.cmt_list.bind(minimum_height=self.cmt_list.setter("height"))
        self.cmt_scroll.add_widget(self.cmt_list)
        self.content.add_widget(self.cmt_scroll)
        self._load_cmts()

    def _load_cmts(self, *a):
        site = getattr(self.app, "current_site", None)
        if not site:
            return
        self.cmt_list.clear_widgets()
        self.cmt_list.add_widget(TLabel(text="Loading...", color=THEME["text_secondary"],
                                        size_hint_y=None, height=dp(36), halign="center"))
        smap = {"All": "all", "Hold": "hold", "Approved": "approve", "Spam": "spam"}
        def load():
            cmts = get_comments(site, status=smap.get(self.cmt_spin.text, "all"),
                                timeout=self.app.settings.get("timeout", 20))
            Clock.schedule_once(lambda dt: self._disp_cmts(cmts))
        threading.Thread(target=load, daemon=True).start()

    def _disp_cmts(self, cmts):
        self.cmt_list.clear_widgets()
        if not cmts:
            self.cmt_list.add_widget(TLabel(text="No comments", color=THEME["text_secondary"],
                                            size_hint_y=None, height=dp(36), halign="center"))
            return
        for c in cmts:
            content = c.get("content", {}); content = content.get("rendered", "") if isinstance(content, dict) else str(content)
            card = _card(orientation="vertical", size_hint_y=None, height=dp(72), padding=[dp(10), dp(4)])
            hd = BoxLayout(size_hint_y=None, height=dp(22))
            hd.add_widget(TLabel(text=f"{c.get('author_name','?')} [{c.get('status','')}]",
                                 font_size=dp(11), color=THEME["text_primary"]))
            hd.add_widget(TLabel(text=c.get("date","")[:16], font_size=dp(9),
                                 color=THEME["text_secondary"], halign="right"))
            card.add_widget(hd)
            card.add_widget(TLabel(text=f"{_html.unescape(content[:80])}...",
                                   font_size=dp(11), color=THEME["text_secondary"]))
            card.cid = c.get("id")
            card.cstatus = c.get("status","")
            card.bind(on_touch_down=self._cmt_tap)
            self.cmt_list.add_widget(card)

    def _cmt_tap(self, inst, touch):
        if not inst.collide_point(*touch.pos) or not hasattr(inst, "cid"):
            return
        site = getattr(self.app, "current_site", None)
        if not site:
            return
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        acts = []
        if inst.cstatus != "approved":
            ab = RoundedButton(text="Approve", bg=THEME["success"])
            ab.bind(on_press=lambda x: self._cmt_act(site, inst.cid, "approve"))
            acts.append(ab)
        db = RoundedButton(text="Delete", bg=THEME["danger"])
        db.bind(on_press=lambda x: self._cmt_act(site, inst.cid, "delete"))
        acts.append(db)
        for a in acts:
            box.add_widget(a)
        pop = DarkPopup(title="Comment Action", content=box, size_hint=(0.7, 0.25), auto_dismiss=False)
        for a in acts:
            a.bind(on_press=pop.dismiss)
        pop.open()

    def _cmt_act(self, site, cid, action):
        def t():
            if action == "approve":
                ok, msg = approve_comment(site, cid, proxy_url=site.proxy_url)
            else:
                ok, msg = delete_comment(site, cid, proxy_url=site.proxy_url)
            Clock.schedule_once(lambda dt: [msgbox("Result", msg), self._load_cmts()])
        threading.Thread(target=t, daemon=True).start()

    # ── AI Tab ──
    def _show_ai(self):
        self.content.clear_widgets()
        scroll = ScrollView()
        form = BoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(14), dp(6)],
                         size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        form.add_widget(TLabel(text="AI Comment Generator", font_size=dp(16), bold=True,
                               color=THEME["text_accent"], size_hint_y=None, height=dp(34)))

        # Provider
        form.add_widget(TLabel(text="Provider", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        plabels = [v["name"] for v in AI_PROVIDERS.values()]
        self.ai_prov = TSpinner(text=plabels[0], values=tuple(plabels))
        self.ai_prov.bind(text=self._ai_prov_change)
        form.add_widget(self.ai_prov)

        # Model
        form.add_widget(TLabel(text="Model", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        self.ai_model = TInput(hint_text="Model name (auto-filled)", multiline=False)
        form.add_widget(self.ai_model)

        # API key input
        form.add_widget(TLabel(text="API Key for this provider", color=THEME["text_secondary"],
                               size_hint_y=None, height=dp(20)))
        self.ai_key = TInput(hint_text="Enter API key", password=True, multiline=False)
        form.add_widget(self.ai_key)

        # Ollama URL (shown only when Ollama selected)
        self.ai_ollama_row = BoxLayout(orientation="vertical", size_hint_y=None)
        self.ai_ollama_row.add_widget(TLabel(text="Ollama URL", color=THEME["text_secondary"],
                                             size_hint_y=None, height=dp(20)))
        self.ai_ollama_url = TInput(hint_text="http://192.168.1.100:11434", multiline=False)
        self.ai_ollama_row.add_widget(self.ai_ollama_url)
        form.add_widget(self.ai_ollama_row)
        self.ai_ollama_row.opacity = 0
        self.ai_ollama_row.disabled = True

        # Tone
        form.add_widget(TLabel(text="Tone", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        tones = [v for _, v in COMMENT_TONES]
        self.ai_tone = TSpinner(text=tones[0], values=tuple(tones))
        form.add_widget(self.ai_tone)

        # Language
        form.add_widget(TLabel(text="Language", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        langs = [v["label"] for v in LANGUAGES.values()]
        self.ai_lang = TSpinner(text=langs[0], values=tuple(langs))
        form.add_widget(self.ai_lang)

        # Temperature
        form.add_widget(TLabel(text="Temperature", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        temp_box = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self.ai_temp_slider = Slider(min=0, max=2, value=0.7, step=0.1,
                                     value_normalized=0.35, cursor_color=_rgba(THEME["accent"]))
        self.ai_temp_label = TLabel(text="0.7", color=THEME["text_primary"], size_hint_x=None, width=dp(30),
                                    halign="center")
        self.ai_temp_slider.bind(value=lambda s, v: setattr(self.ai_temp_label, "text", f"{v:.1f}"))
        temp_box.add_widget(self.ai_temp_slider)
        temp_box.add_widget(self.ai_temp_label)
        form.add_widget(temp_box)

        # Word count
        wc_box = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        form.add_widget(TLabel(text="Word count range", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        self.ai_minw = TInput(text="10", multiline=False, size_hint_x=0.5)
        self.ai_maxw = TInput(text="60", multiline=False, size_hint_x=0.5)
        wc_box.add_widget(TLabel(text="Min:", color=THEME["text_secondary"], size_hint_x=None, width=dp(30)))
        wc_box.add_widget(self.ai_minw)
        wc_box.add_widget(TLabel(text="Max:", color=THEME["text_secondary"], size_hint_x=None, width=dp(30)))
        wc_box.add_widget(self.ai_maxw)
        form.add_widget(wc_box)

        # Buttons
        btn_box = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        genb = RoundedButton(text="Generate", bg=THEME["accent"])
        genb.bind(on_press=self._ai_gen)
        testb = RoundedButton(text="Test", bg=THEME["bg_input"])
        testb.bind(on_press=self._ai_test)
        btn_box.add_widget(genb)
        btn_box.add_widget(testb)
        form.add_widget(btn_box)

        # Result
        self.ai_result = TextInput(hint_text="Generated comment...", readonly=True,
                                    size_hint_y=None, height=dp(120),
                                    background_color=_rgba("#0a0a14"),
                                    foreground_color=_rgba(THEME["text_primary"]),
                                    padding=[dp(8), dp(8)])
        form.add_widget(self.ai_result)

        # Send button
        sndb = RoundedButton(text="Send as Comment (current post)", bg=THEME["success"])
        sndb.bind(on_press=self._ai_send)
        form.add_widget(sndb)

        form.add_widget(Label(size_hint_y=0.3))
        scroll.add_widget(form)
        self.content.add_widget(scroll)
        self._ai_prov_change()

    def _ai_prov_change(self, *a):
        label = self.ai_prov.text
        key = _resolve_provider_key(label)
        prov = AI_PROVIDERS.get(key, {})
        self.ai_model.text = prov.get("default_model", "")
        is_ollama = (key == "ollama")
        self.ai_ollama_row.opacity = 1 if is_ollama else 0
        self.ai_ollama_row.disabled = not is_ollama
        self.ai_key.opacity = 0 if is_ollama else 1
        self.ai_key.disabled = is_ollama
        if not is_ollama:
            self.ai_key.text = self.app.ai_api_keys.get(key, "")

    def _ai_gen(self, *a):
        site = getattr(self.app, "current_site", None)
        if not site:
            msgbox("Error", "No site selected"); return
        key = _resolve_provider_key(self.ai_prov.text)
        api_key = self.app.ai_api_keys.get(key, "")
        if key != "ollama" and not api_key:
            msgbox("Error", f"API key needed for {self.ai_prov.text}\nSet in Settings"); return
        tone = _tone_key(self.ai_tone.text)
        lang = _lang_key(self.ai_lang.text)
        temp = self.ai_temp_slider.value
        try:
            minw = max(1, int(self.ai_minw.text.strip() or "10"))
        except: minw = 10
        try:
            maxw = max(minw, int(self.ai_maxw.text.strip() or "60"))
        except: maxw = 60
        o_url = self.ai_ollama_url.text.strip() or ""
        self.ai_result.text = "Generating..."
        def t():
            ok, res = generate_comment(
                key, api_key, "Sample post content. Write a relevant comment.",
                model=self.ai_model.text.strip() or None,
                tone=tone, language=lang, temperature=temp,
                min_words=minw, max_words=maxw, ollama_url=o_url,
            )
            Clock.schedule_once(lambda dt: setattr(self.ai_result, "text",
                                                   res if ok else f"Error: {res}"))
        threading.Thread(target=t, daemon=True).start()

    def _ai_test(self, *a):
        key = _resolve_provider_key(self.ai_prov.text)
        api_key = self.app.ai_api_keys.get(key, "")
        if key != "ollama" and not api_key:
            msgbox("Error", "No API key"); return
        o_url = self.ai_ollama_url.text.strip() or ""
        self.ai_result.text = "Testing..."
        def t():
            ok, msg = test_provider(key, api_key,
                                    model=self.ai_model.text.strip() or None,
                                    ollama_url=o_url)
            Clock.schedule_once(lambda dt: setattr(self.ai_result, "text",
                                                   f"{'OK' if ok else 'FAIL'}: {msg}"))
        threading.Thread(target=t, daemon=True).start()

    def _ai_send(self, *a):
        site = getattr(self.app, "current_site", None)
        text = self.ai_result.text.strip()
        if not text or text.startswith("Generating") or text.startswith("Error") or text.startswith("OK"):
            msgbox("Error", "Generate a comment first"); return
        msgbox("Info", "To send:\n1. Go to Posts tab\n2. Tap a post\n3. Paste the comment text")

    # ── Batch AI Tab ──
    def _show_batch_ai(self):
        self.content.clear_widgets()
        site = getattr(self.app, "current_site", None)
        if not site:
            return
        self.batch_posts = []
        self.batch_results = []
        self.batch_selected = set()

        top = BoxLayout(orientation="vertical", size_hint_y=None)
        top.add_widget(TLabel(text="Batch AI: Generate comments for ALL posts",
                              font_size=dp(14), bold=True, color=THEME["text_accent"],
                              size_hint_y=None, height=dp(28)))

        ctrl = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6), padding=[dp(4), dp(2)])
        genb = RoundedButton(text="Generate All", bg=THEME["accent"], height=dp(36))
        genb.bind(on_press=self._batch_gen)
        selb = RoundedButton(text="Select All", bg=THEME["bg_input"], height=dp(36))
        selb.bind(on_press=self._batch_sel_all)
        sndb = RoundedButton(text="Send Selected", bg=THEME["success"], height=dp(36))
        sndb.bind(on_press=self._batch_send)
        ctrl.add_widget(genb); ctrl.add_widget(selb); ctrl.add_widget(sndb)
        top.add_widget(ctrl)

        self.batch_count = TLabel(text="0 posts loaded", color=THEME["text_secondary"],
                                  size_hint_y=None, height=dp(22))
        top.add_widget(self.batch_count)
        self.content.add_widget(top)

        self.batch_scroll = ScrollView()
        self.batch_list = BoxLayout(orientation="vertical", spacing=dp(4), padding=[dp(6), dp(2)],
                                     size_hint_y=None)
        self.batch_list.bind(minimum_height=self.batch_list.setter("height"))
        self.batch_scroll.add_widget(self.batch_list)
        self.content.add_widget(self.batch_scroll)

        self.content.add_widget(TLabel(text="Loading posts...", color=THEME["text_secondary"],
                                       size_hint_y=None, height=dp(36), halign="center"))
        def load():
            posts = get_posts(site, timeout=self.app.settings.get("timeout", 20), proxy_url=site.proxy_url)
            Clock.schedule_once(lambda dt: self._batch_disp_posts(posts))
        threading.Thread(target=load, daemon=True).start()

    def _batch_disp_posts(self, posts):
        self.batch_list.clear_widgets()
        self.batch_posts = posts
        self.batch_results = [None] * len(posts)
        self.batch_selected = set()
        self.batch_count.text = f"{len(posts)} posts loaded"
        if not posts:
            self.batch_list.add_widget(TLabel(text="No posts found", color=THEME["text_secondary"],
                                              size_hint_y=None, height=dp(36), halign="center"))
            return
        for i, p in enumerate(posts):
            t = p.get("title", {}); t = t.get("rendered", "") if isinstance(t, dict) else str(t)
            card = _card(orientation="vertical", size_hint_y=None, height=dp(68), padding=[dp(10), dp(4)])
            hd = BoxLayout(size_hint_y=None, height=dp(22))
            cb = Button(text="☐", font_size=dp(16), background_color=(0,0,0,0),
                        color=_rgba(THEME["text_secondary"]), size_hint_x=None, width=dp(30))
            cb.i = i
            cb.bind(on_press=self._batch_toggle)
            hd.add_widget(cb)
            hd.add_widget(TLabel(text=f"#{p['id']} {_html.unescape(t[:50])}", font_size=dp(12),
                                 color=THEME["text_primary"]))
            card.add_widget(hd)
            self.batch_results[i] = None
            cl = TLabel(text="⏳ Waiting...", font_size=dp(10), color=THEME["text_secondary"])
            card.cl = cl
            card.add_widget(cl)
            card.i = i
            self.batch_list.add_widget(card)

    def _batch_toggle(self, b):
        i = b.i
        if i in self.batch_selected:
            self.batch_selected.discard(i)
            b.text = "☐"
        else:
            self.batch_selected.add(i)
            b.text = "☑"

    def _batch_sel_all(self, *a):
        if len(self.batch_selected) == len(self.batch_posts):
            self.batch_selected.clear()
            for child in self.batch_list.children:
                if hasattr(child, "i"):
                    pass
            self._batch_refresh_checks(False)
        else:
            self.batch_selected = set(range(len(self.batch_posts)))
            self._batch_refresh_checks(True)

    def _batch_refresh_checks(self, sel):
        for i, child in enumerate(reversed(self.batch_list.children)):
            if hasattr(child, "i"):
                try:
                    cb = child.children[1] if child.children else None
                    if cb and hasattr(cb, "text"):
                        cb.text = "☑" if sel else "☐"
                except:
                    pass

    def _batch_gen(self, *a):
        site = getattr(self.app, "current_site", None)
        if not site or not self.batch_posts:
            msgbox("Error", "No posts loaded"); return
        key = _resolve_provider_key(getattr(self, "ai_prov", TSpinner()).text) if hasattr(self, "ai_prov") else "gemini"
        api_key = self.app.ai_api_keys.get(key, "")
        if key != "ollama" and not api_key:
            msgbox("Error", "Set API key in Settings first"); return

        # Build post data with content
        self.batch_count.text = "Fetching post content..."
        def fetch():
            post_data = []
            for p in self.batch_posts:
                content = get_post_content(site, p["id"], timeout=self.app.settings.get("timeout", 20))
                t = p.get("title", {}); t = t.get("rendered", "") if isinstance(t, dict) else str(t)
                post_data.append({"id": p["id"], "title": t, "content": content})
            Clock.schedule_once(lambda dt: self._batch_do_gen(post_data))
        threading.Thread(target=fetch, daemon=True).start()

    def _batch_do_gen(self, post_data):
        self.batch_count.text = f"Generating {len(post_data)} comments..."
        key = _resolve_provider_key("Google Gemini")
        api_key = self.app.ai_api_keys.get("gemini", "")
        i = 0
        for child in reversed(self.batch_list.children):
            if hasattr(child, "i") and child.i < len(post_data):
                child.cl.text = "⏳ Generating..."
        def t():
            nonlocal i
            pd = post_data
            results = generate_batch_comments(
                key, api_key, pd,
                tone="Neutral", language="persian",
                temperature=0.7, min_words=10, max_words=60,
            )
            for pid, ok, text in results:
                for idx, child in enumerate(reversed(self.batch_list.children)):
                    if hasattr(child, "i") and self.batch_posts[child.i]["id"] == pid:
                        if ok:
                            child.cl.text = f"✅ {text[:60]}..."
                            self.batch_results[child.i] = text
                        else:
                            child.cl.text = f"❌ {text}"
                        break
            Clock.schedule_once(lambda dt: setattr(self.batch_count, "text",
                                                   f"Done: {sum(1 for r in self.batch_results if r)}/{len(pd)}"))
        threading.Thread(target=t, daemon=True).start()

    def _batch_send(self, *a):
        site = getattr(self.app, "current_site", None)
        if not site:
            msgbox("Error", "No site"); return
        selected = [(i, self.batch_posts[i], self.batch_results[i])
                     for i in self.batch_selected if i < len(self.batch_results) and self.batch_results[i]]
        if not selected:
            msgbox("Error", "No selected comments to send"); return
        self.batch_count.text = f"Sending {len(selected)} comments..."
        def t():
            sent = 0
            for i, p, text in selected:
                ok, res = send_comment(site=site, post_id=p["id"], content=text,
                                       as_admin=True, timeout=self.app.settings.get("timeout", 20),
                                       proxy_url=site.proxy_url, lang=site.lang)
                if ok:
                    sent += 1
                    for child in reversed(self.batch_list.children):
                        if hasattr(child, "i") and child.i == i:
                            child.cl.text = "✅ Sent!"
                            break
                else:
                    ok2, res2 = send_comment_via_form(site=site, post_id=p["id"], content=text,
                                                      timeout=self.app.settings.get("timeout", 20),
                                                      proxy_url=site.proxy_url, lang=site.lang)
                    if ok2:
                        sent += 1
                        for child in reversed(self.batch_list.children):
                            if hasattr(child, "i") and child.i == i:
                                child.cl.text = "✅ Sent (form)!"
                                break
                    else:
                        for child in reversed(self.batch_list.children):
                            if hasattr(child, "i") and child.i == i:
                                child.cl.text = f"❌ {res}"
                                break
                _time.sleep(1.5)
            Clock.schedule_once(lambda dt: setattr(self.batch_count, "text",
                                                   f"Sent {sent}/{len(selected)}"))
        threading.Thread(target=t, daemon=True).start()


# ═══════════════════════════════════════════════════
#  SCREEN: Jobs / Scheduler
# ═══════════════════════════════════════════════════

class JobsScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.app = App.get_running_app()
        _bg(self)
        layout = BoxLayout(orientation="vertical")
        layout.add_widget(_build_header("Job Queue", "sites"))

        # Controls
        ctrl = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6), padding=[dp(10), dp(4)])
        self.start_btn = RoundedButton(text="▶ Start", bg=THEME["success"], height=dp(36))
        self.start_btn.bind(on_press=self._toggle)
        ctrl.add_widget(self.start_btn)
        ctrl.add_widget(RoundedButton(text="+ Add", bg=THEME["accent"], height=dp(36)))
        clear_btn = RoundedButton(text="Clear Done", bg=THEME["bg_input"], height=dp(36))
        clear_btn.bind(on_press=self._clear)
        ctrl.add_widget(clear_btn)
        layout.add_widget(ctrl)

        self.job_scroll = ScrollView()
        self.job_list = BoxLayout(orientation="vertical", spacing=dp(4), padding=[dp(10), dp(4)],
                                   size_hint_y=None)
        self.job_list.bind(minimum_height=self.job_list.setter("height"))
        self.job_scroll.add_widget(self.job_list)
        layout.add_widget(self.job_scroll)
        self.add_widget(layout)

    def on_enter(self):
        if not hasattr(self.app, "job_queue") or not self.app.job_queue:
            self.app.job_queue = JobQueue()
            self.app.job_queue.on_progress = self.refresh
        self.refresh()

    def refresh(self, *a):
        self.job_list.clear_widgets()
        q = getattr(self.app, "job_queue", None)
        if not q or not q.jobs:
            self.job_list.add_widget(TLabel(text="No jobs. Add from Batch AI.", color=THEME["text_secondary"],
                                            size_hint_y=None, height=dp(40), halign="center"))
            return
        for job in q.jobs:
            status_colors = {"pending": THEME["warning"], "running": THEME["text_accent"],
                             "done": THEME["success"], "failed": THEME["danger"]}
            card = _card(orientation="horizontal", size_hint_y=None, height=dp(48), padding=[dp(10), dp(4)])
            card.add_widget(TLabel(text=f"Post #{job.post_id}", font_size=dp(13),
                                   bold=True, color=THEME["text_primary"]))
            card.add_widget(TLabel(text=job.status, font_size=dp(12),
                                   color=status_colors.get(job.status, THEME["text_secondary"]),
                                   halign="right"))
            self.job_list.add_widget(card)

    def _toggle(self, *a):
        q = getattr(self.app, "job_queue", None)
        if not q:
            return
        if q.running:
            q.stop()
            self.start_btn.text = "▶ Start"
        else:
            q.start()
            self.start_btn.text = "⏹ Stop"

    def _clear(self, *a):
        q = getattr(self.app, "job_queue", None)
        if q:
            q.jobs = [j for j in q.jobs if j.status not in ("done", "failed")]
            self.refresh()


# ═══════════════════════════════════════════════════
#  SCREEN: Settings
# ═══════════════════════════════════════════════════

class SettingsScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.app = App.get_running_app()
        _bg(self)
        layout = BoxLayout(orientation="vertical")
        layout.add_widget(_build_header("Settings"))

        scroll = ScrollView()
        form = BoxLayout(orientation="vertical", spacing=dp(10), padding=[dp(20), dp(8)],
                         size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        form.add_widget(TLabel(text="General", font_size=dp(15), bold=True, color=THEME["text_accent"],
                               size_hint_y=None, height=dp(28)))
        form.add_widget(TLabel(text="Request Timeout (sec)", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        self.inp_timeout = TInput(text=str(self.app.settings.get("timeout", 20)), multiline=False, input_filter="int")
        form.add_widget(self.inp_timeout)

        form.add_widget(TLabel(text="Delay Between Comments (sec)", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        self.inp_delay = TInput(text=str(self.app.settings.get("request_delay", 1.5)), multiline=False)
        form.add_widget(self.inp_delay)

        form.add_widget(TLabel(text="Global Proxy", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        self.inp_proxy = TInput(text=self.app.settings.get("proxy_url", ""), hint_text="http://... or leave empty", multiline=False)
        form.add_widget(self.inp_proxy)

        form.add_widget(TLabel(text="Ollama URL", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        self.inp_ollama = TInput(text=self.app.settings.get("ollama_url", ""), hint_text="http://192.168.1.100:11434", multiline=False)
        form.add_widget(self.inp_ollama)

        form.add_widget(TLabel(text="Schedule Interval (sec)", color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
        self.inp_sched = TInput(text=str(self.app.settings.get("schedule_interval", 3600)), multiline=False, input_filter="int")
        form.add_widget(self.inp_sched)

        form.add_widget(TLabel(text="AI API Keys", font_size=dp(15), bold=True, color=THEME["text_accent"],
                               size_hint_y=None, height=dp(28)))
        self.ai_inputs = {}
        for key, prov in AI_PROVIDERS.items():
            if key == "ollama":
                continue
            form.add_widget(TLabel(text=prov["name"], color=THEME["text_secondary"], size_hint_y=None, height=dp(20)))
            inp = TInput(text=self.app.ai_api_keys.get(key, ""), hint_text=f"{prov['name']} Key",
                         password=True, multiline=False)
            self.ai_inputs[key] = inp
            form.add_widget(inp)

        form.add_widget(Label(size_hint_y=None, height=dp(8)))
        sv = RoundedButton(text="Save Settings", bg=THEME["success"])
        sv.bind(on_press=self._save)
        form.add_widget(sv)
        self.st = TLabel(text="", color=THEME["success"], size_hint_y=None, height=dp(24), halign="center")
        form.add_widget(self.st)
        form.add_widget(Label(size_hint_y=0.5))
        scroll.add_widget(form)
        layout.add_widget(scroll)
        self.add_widget(layout)

    def _save(self, *a):
        try:
            self.app.settings["timeout"] = int(self.inp_timeout.text.strip() or "20")
        except: pass
        try:
            self.app.settings["request_delay"] = float(self.inp_delay.text.strip() or "1.5")
        except: pass
        self.app.settings["proxy_url"] = self.inp_proxy.text.strip()
        self.app.settings["ollama_url"] = self.inp_ollama.text.strip()
        try:
            self.app.settings["schedule_interval"] = int(self.inp_sched.text.strip() or "3600")
        except: pass
        for k, inp in self.ai_inputs.items():
            self.app.ai_api_keys[k] = inp.text.strip()
        self.app.vault_data["settings"] = self.app.settings
        self.app.vault_data["api_keys_ai"] = self.app.ai_api_keys
        save_vault(self.app.master_pwd, self.app.vault_data)
        self.st.text = "Saved!"


# ═══════════════════════════════════════════════════
#  SCREEN: CSV Import/Export
# ═══════════════════════════════════════════════════

class CSVScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.app = App.get_running_app()
        _bg(self)
        layout = BoxLayout(orientation="vertical")
        layout.add_widget(_build_header("CSV Manager"))

        scroll = ScrollView()
        form = BoxLayout(orientation="vertical", spacing=dp(10), padding=[dp(20), dp(8)],
                         size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        form.add_widget(TLabel(text="Import Comments from CSV", font_size=dp(15), bold=True,
                               color=THEME["text_accent"], size_hint_y=None, height=dp(28)))
        form.add_widget(TLabel(text="CSV format: post_id,content,author_name,author_email",
                               color=THEME["text_secondary"], size_hint_y=None, height=dp(22)))
        self.csv_text = TextInput(hint_text="Paste CSV content here...\npost_id,content,name,email\n12,Great post!,Ali,ali@example.com",
                                   size_hint_y=None, height=dp(150),
                                   background_color=_rgba("#0a0a14"),
                                   foreground_color=_rgba(THEME["text_primary"]),
                                   padding=[dp(8), dp(8)])
        form.add_widget(self.csv_text)

        impb = RoundedButton(text="Import & Add to Queue", bg=THEME["accent"])
        impb.bind(on_press=self._import)
        form.add_widget(impb)

        form.add_widget(Label(size_hint_y=None, height=dp(16)))

        form.add_widget(TLabel(text="Export Sample CSV", font_size=dp(15), bold=True,
                               color=THEME["text_accent"], size_hint_y=None, height=dp(28)))
        expb = RoundedButton(text="Generate Sample", bg=THEME["bg_input"])
        expb.bind(on_press=self._export_sample)
        form.add_widget(expb)

        self.export_text = TextInput(readonly=True, size_hint_y=None, height=dp(120),
                                     background_color=_rgba("#0a0a14"),
                                     foreground_color=_rgba(THEME["text_primary"]),
                                     padding=[dp(8), dp(8)])
        form.add_widget(self.export_text)

        form.add_widget(Label(size_hint_y=0.4))
        scroll.add_widget(form)
        layout.add_widget(scroll)
        self.add_widget(layout)

    def _import(self, *a):
        raw = self.csv_text.text.strip()
        if not raw:
            msgbox("Error", "Paste CSV data first"); return
        lines = raw.split("\n")
        if len(lines) < 2:
            msgbox("Error", "CSV needs header + data rows"); return
        if not hasattr(self.app, "job_queue") or not self.app.job_queue:
            self.app.job_queue = JobQueue()
        added = 0
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                post_id = int(parts[0])
            except:
                continue
            content = parts[1] if len(parts) > 1 else ""
            name = parts[2] if len(parts) > 2 else "Guest"
            email = parts[3] if len(parts) > 3 else "guest@example.com"
            if not content:
                continue
            site = getattr(self.app, "current_site", None)
            if not site:
                msgbox("Error", "Select a site first from Sites screen"); return
            job = Job(site, post_id, content, name, email, as_admin=True)
            self.app.job_queue.add(job)
            added += 1
        msgbox("Success", f"{added} jobs added to queue.\nGo to Jobs to start.")

    def _export_sample(self, *a):
        sample = "post_id,content,author_name,author_email\n12,Great article! Thank you.,Ali,ali@example.com\n15,Very informative. Keep it up.,Sara,sara@example.com"
        self.export_text.text = sample


# ═══════════════════════════════════════════════════
#  APP
# ═══════════════════════════════════════════════════

class WPCMApp(App):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.master_pwd = ""
        self.vault_data = {}
        self.sites = []
        self.settings = dict(DEFAULT_VAULT["settings"])
        self.ai_api_keys = {}
        self.current_site = None
        self.edit_site = None
        self.job_queue = JobQueue()

    def build(self):
        self.title = "WP Comment Manager"
        Window.clearcolor = _rgba(THEME["bg_dark"])
        sm = ScreenManager(transition=SlideTransition(direction="left"))
        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(SetupScreen(name="setup"))
        sm.add_widget(SitesScreen(name="sites"))
        sm.add_widget(AddSiteScreen(name="add_site"))
        sm.add_widget(SiteDetailScreen(name="site_detail"))
        sm.add_widget(JobsScreen(name="jobs"))
        sm.add_widget(SettingsScreen(name="settings"))
        sm.add_widget(CSVScreen(name="csv"))
        return sm


if __name__ == "__main__":
    WPCMApp().run()
