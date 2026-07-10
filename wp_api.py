import html as html_mod
import json
import re
import unicodedata
import socket as _socket
import urllib.request as _urllib_request
import requests
from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dataclasses import dataclass
from typing import Optional


_BROWSER_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-S908B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.6099.230 Mobile Safari/537.36"
)

_BROWSER_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}


@dataclass
class Site:
    name: str
    url: str
    username: str
    password: str
    id: str = ""
    api_key: str = ""
    proxy_url: str = ""
    lang: str = ""

    def __post_init__(self):
        self.url = _normalize_url(self.url) if self.url else ""
        if not self.id:
            import uuid
            self.id = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict:
        d = {"id": self.id, "name": self.name, "url": self.url, "username": self.username}
        if self.proxy_url:
            d["proxy_url"] = self.proxy_url
        if self.lang:
            d["lang"] = self.lang
        return d

    @staticmethod
    def from_dict(d: dict, password: str = "", api_key: str = "") -> "Site":
        return Site(
            id=d.get("id", ""), name=d["name"], url=d["url"],
            username=d["username"], password=password, api_key=api_key,
            proxy_url=d.get("proxy_url", ""), lang=d.get("lang", ""),
        )


def _lang_query(lang: str) -> str:
    return f"&lang={lang}" if lang else ""


_COMMENT_TONES = [
    ("Neutral", "نظر خنثی و معمولی"),
    ("Positive", "نظر مثبت و تشویق‌آمیز"),
    ("Critical", "نظر انتقادی سازنده"),
    ("Question", "نظر پرسشی"),
    ("Funny", "نظر طنزآمیز"),
    ("Detailed", "نظر مفصل و تحلیلی"),
    ("Short", "نظر کوتاه"),
    ("Supportive", "نظر حمایتی"),
]

_LANGUAGES = {
    "persian": {"label": "Persian (فارسی)", "instruction": "پاسخ را فقط به زبان فارسی بنویس."},
    "english": {"label": "English", "instruction": "Write the response in English only."},
    "mixed": {"label": "Mixed (متنوع)", "instruction": "Use a mix of Persian and English in the response."},
}

PROVIDERS = {
    "gemini": {"name": "Google Gemini", "docs_url": "https://aistudio.google.com/app/apikey"},
    "groq": {"name": "Groq Cloud", "docs_url": "https://console.groq.com/keys"},
    "together": {"name": "Together AI", "docs_url": "https://api.together.xyz/settings/api-keys"},
    "openrouter": {"name": "OpenRouter", "docs_url": "https://openrouter.ai/keys"},
    "ollama": {"name": "Ollama (Local)", "docs_url": ""},
    "huggingface": {"name": "HuggingFace", "docs_url": "https://huggingface.co/settings/tokens"},
    "openai": {"name": "OpenAI ChatGPT", "docs_url": "https://platform.openai.com/api-keys"},
    "deepseek": {"name": "DeepSeek", "docs_url": "https://platform.deepseek.com/api_keys"},
    "claude": {"name": "Anthropic Claude", "docs_url": "https://console.anthropic.com/"},
    "grok": {"name": "xAI Grok", "docs_url": "https://console.x.ai/"},
}


# ─── Helpers ──────────────────────────────

def _get_session(timeout: int = 20, retry: bool = True, proxy_url: str = "") -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    if retry:
        retries = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    session.headers.update(_BROWSER_HEADERS)
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    return session


def _get_auth(site: Site) -> HTTPBasicAuth:
    return HTTPBasicAuth(site.username, site.password)


def _normalize_url(raw_url: str) -> str:
    url = raw_url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    for suffix in ["/wp-admin/", "/wp-admin", "/wp-login.php", "/wp-login", "/wp-admin/network/"]:
        if url.rstrip("/").endswith(suffix.rstrip("/")):
            url = url.rstrip("/")[:len(url.rstrip("/")) - len(suffix.rstrip("/"))]
            break
    return url.rstrip("/")


def sanitize_comment_text(text: str) -> str:
    text = html_mod.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^\S\w\d\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\u2000-\u206F\u0021-\u007E\s]", "", text)
    return text[:10000]


def sanitize_guest_name(name: str) -> str:
    sanitized = re.sub(r"[<>\"'&]", "", name.strip()[:50])
    return sanitized or "Guest"


def sanitize_guest_email(email: str) -> str:
    email = email.strip()[:100]
    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return email
    return "guest@example.com"


# ─── Direct DNS Resolution (cross-platform VPN bypass) ──

def resolve_host_direct(host: str, timeout: int = 10) -> Optional[str]:
    try:
        url = f"https://dns.google/resolve?name={host}&type=A"
        req = _urllib_request.Request(url, headers={"Accept": "application/dns-json"})
        resp = _urllib_request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        if data.get("Answer"):
            for a in data["Answer"]:
                if a.get("type") == 1:
                    return a["data"]
    except Exception:
        pass
    return None


_orig_getaddrinfo = _socket.getaddrinfo


def patch_dns_for_host(host: str):
    ip = resolve_host_direct(host)
    if ip:
        def _patched(h, port, family=0, type=0, proto=0, flags=0):
            if h == host:
                return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (ip, port))]
            return _orig_getaddrinfo(h, port, family, type, proto, flags)
        _socket.getaddrinfo = _patched


def restore_dns():
    _socket.getaddrinfo = _orig_getaddrinfo


# ─── WordPress REST API calls ──

def _rest_get(url: str, site: Site, timeout: int, proxy_url: str = "") -> requests.Response:
    with _get_session(timeout, proxy_url=proxy_url) as s:
        return s.get(url, auth=_get_auth(site), timeout=timeout, stream=True)


def _wp_json_request(method: str, url: str, auth, data: dict = None, timeout: int = 20, proxy_url: str = "") -> tuple[bool, any]:
    with _get_session(timeout, retry=False, proxy_url=proxy_url) as s:
        try:
            if method == "POST":
                resp = s.post(url, auth=auth, json=data, timeout=timeout)
            else:
                resp = s.get(url, auth=auth, timeout=timeout)
            if resp.status_code in (200, 201):
                return True, resp.json()
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)


def _plugin_api_call(method: str, path: str, site: Site, timeout: int, proxy_url: str = "", body: dict = None, params: dict = None) -> tuple[bool, any]:
    api_key = site.api_key or site.password
    url = f"{site.url}/wp-json/wpcm/v1/{path.lstrip('/')}"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    try:
        with _get_session(timeout, proxy_url=proxy_url) as s:
            if method == "GET":
                resp = s.get(url, headers=headers, params=params, timeout=timeout)
            else:
                resp = s.post(url, headers=headers, json=body, timeout=timeout)
        if resp.status_code == 403:
            return False, "Invalid API Key"
        if resp.status_code == 404:
            return False, "Plugin not installed"
        if resp.status_code == 429:
            return False, "Rate limit exceeded"
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        return True, resp.json()
    except Exception as e:
        return False, str(e)


def _cookie_login(site: Site, timeout: int = 15, proxy_url: str = "") -> tuple[bool, requests.Session]:
    """Log into WordPress via wp-login.php and return authenticated session."""
    try:
        s = _get_session(timeout, proxy_url=proxy_url)
        login_url = f"{site.url}/wp-login.php"
        s.get(login_url, timeout=timeout)
        data = {"log": site.username, "pwd": site.password,
                "wp-submit": "Login", "testcookie": "1", "redirect_to": site.url}
        resp = s.post(login_url, data=data, timeout=timeout, allow_redirects=True)
        if any("wordpress_logged_in" in c.name for c in s.cookies):
            return True, s
        return False, None
    except Exception:
        return False, None


def _xmlrpc_call(site: Site, method: str, params: list, timeout: int = 15,
                 proxy_url: str = "") -> tuple[bool, any]:
    """Call a WordPress XML-RPC method."""
    import xmlrpc.client as _xmlrpc_client
    try:
        s = _get_session(timeout, proxy_url=proxy_url)
        url = f"{site.url}/xmlrpc.php"
        body = _xmlrpc_client.dumps(params, method)
        resp = s.post(url, data=body, headers={"Content-Type": "text/xml"}, timeout=timeout)
        if resp.status_code == 200:
            return True, _xmlrpc_client.loads(resp.text)
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def test_connection(site: Site, timeout: int = 15, proxy_url: str = "") -> tuple[bool, str]:
    errors = []
    tips = []
    site.url = _normalize_url(site.url)

    # ── Strategy 0: Plugin API ──
    if site.api_key:
        ok, data = _plugin_api_call("POST", "auth", site, timeout, proxy_url)
        if ok and isinstance(data, dict) and data.get("success"):
            user = data.get("user", {})
            return True, f"Connected via plugin as {user.get('name', 'Admin')}"
        errors.append(f"Plugin API: {data}")

    # ── Strategy 1: REST API Basic Auth ──
    try:
        url = f"{site.url}/wp-json/wp/v2/users/me"
        auth = _get_auth(site)
        with _get_session(timeout, proxy_url=proxy_url) as s:
            resp = s.get(url, auth=auth, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            return True, f"Connected as {data.get('name', 'OK')}"
        if resp.status_code == 401:
            errors.append("Basic Auth: 401 (wrong password or need Application Password)")
        elif resp.status_code == 403:
            errors.append("Basic Auth: 403 (server blocking)")
        else:
            errors.append(f"Basic Auth: HTTP {resp.status_code}")
        tips.append("- WordPress 6.0+ requires an Application Password (Users > Profile > Application Passwords)")
    except Exception as e:
        errors.append(f"Basic Auth: {e}")

    # ── Strategy 2: Cookie Login + REST API ──
    logged_in, session = _cookie_login(site, timeout, proxy_url)
    if logged_in:
        try:
            url = f"{site.url}/wp-json/wp/v2/users/me"
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                return True, f"Connected as {data.get('name', 'OK')} (via cookie login)"
            errors.append(f"Cookie Auth: HTTP {resp.status_code}")
        except Exception as e:
            errors.append(f"Cookie Auth: {e}")
    else:
        errors.append("Cookie login failed")
        tips.append("- Cookie login uses WordPress username (not email) and regular password")

    # ── Strategy 3: XML-RPC ──
    ok, result = _xmlrpc_call(site, "system.listMethods", [], timeout, proxy_url)
    if ok:
        ok2, blogs = _xmlrpc_call(site, "wp.getUsersBlogs", [site.username, site.password], timeout, proxy_url)
        if ok2 and blogs:
            name = blogs[1][0].get("blogName", "WordPress")
            return True, f"Connected to {name} (via XML-RPC)"
        errors.append("XML-RPC: Auth failed")
    else:
        errors.append(f"XML-RPC: {result}")

    # ── Strategy 4: HTTP fallback ──
    if site.url.startswith("https://"):
        http_url = "http://" + site.url[len("https://"):]
        original_url = site.url
        site.url = http_url
        try:
            url = f"{site.url}/wp-json/wp/v2/users/me"
            auth = _get_auth(site)
            with _get_session(timeout, proxy_url=proxy_url) as s:
                resp = s.get(url, auth=auth, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                return True, f"Connected as {data.get('name', 'OK')} (via HTTP)"
            errors.append(f"HTTP fallback: HTTP {resp.status_code}")
        except Exception as e:
            errors.append(f"HTTP fallback: {e}")
        finally:
            site.url = original_url

    msg = "All connection methods failed:\n" + "\n".join(f"  - {e}" for e in errors)
    if tips:
        msg += "\n\nTips:\n" + "\n".join(tips)
    return False, msg


def _posts_endpoint(post_type: str = "post", rest_base: Optional[str] = None) -> str:
    base = rest_base or post_type
    if post_type == "post" and not rest_base:
        base = "posts"
    elif post_type == "page" and not rest_base:
        base = "pages"
    return f"/wp-json/wp/v2/{base}"


def get_posts(site: Site, post_type: str = "post", rest_base: Optional[str] = None,
              timeout: int = 20, proxy_url: str = "", lang: str = "") -> list[dict]:
    all_posts = []
    page = 1
    use_lang = lang or site.lang

    if site.api_key:
        try:
            while True:
                params = {"post_type": post_type, "paged": page, "per_page": 100}
                if use_lang:
                    params["lang"] = use_lang
                ok, data = _plugin_api_call("GET", "posts", site, timeout, proxy_url, params=params)
                if not ok or not isinstance(data, list):
                    all_posts = []
                    break
                for p in data:
                    all_posts.append({
                        "id": p["id"], "title": {"rendered": p.get("title", "")},
                        "date": p.get("date", ""), "type": p.get("type", post_type),
                        "slug": p.get("slug", ""), "link": p.get("link", ""),
                    })
                if len(data) < 100:
                    break
                page += 1
        except Exception:
            all_posts = []

    if not all_posts:
        page = 1
        endpoint = _posts_endpoint(post_type, rest_base)
        while True:
            try:
                url = f"{site.url}{endpoint}?per_page=100&page={page}{_lang_query(use_lang)}"
                resp = _rest_get(url, site, timeout, proxy_url)
                if resp.status_code != 200:
                    break
                batch = resp.json()
                if not isinstance(batch, list) or not batch:
                    break
                all_posts.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            except Exception:
                break
    return all_posts


def get_post_content(site: Site, post_id: int, post_type: str = "post",
                     rest_base: Optional[str] = None, timeout: int = 20,
                     proxy_url: str = "", lang: str = "") -> str:
    import re as _re
    use_lang = lang or site.lang
    if site.api_key:
        params = {"id": post_id}
        if use_lang:
            params["lang"] = use_lang
        ok, data = _plugin_api_call("GET", "post-content", site, timeout, proxy_url, params=params)
        if ok and isinstance(data, dict):
            raw = data.get("content") or data.get("excerpt") or ""
            text = _re.sub(r"<[^>]+>", "", raw)
            return _re.sub(r"\s+", " ", text).strip()
    try:
        base = rest_base or post_type
        if post_type == "post" and not rest_base:
            base = "posts"
        elif post_type == "page" and not rest_base:
            base = "pages"
        url = f"{site.url}/wp-json/wp/v2/{base}/{post_id}{_lang_query(use_lang)}"
        resp = _rest_get(url, site, timeout, proxy_url)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("content", {}).get("rendered", "")
            text = _re.sub(r"<[^>]+>", "", content)
            return _re.sub(r"\s+", " ", text).strip()
        return ""
    except Exception:
        return ""


def get_comments(site: Site, post_id: int = 0, status: str = "all",
                 timeout: int = 20, proxy_url: str = "", lang: str = "") -> list[dict]:
    use_lang = lang or site.lang
    if site.api_key:
        params = {"status": status, "per_page": 200}
        if post_id:
            params["post_id"] = post_id
        if use_lang:
            params["lang"] = use_lang
        ok, data = _plugin_api_call("GET", "comments", site, timeout, proxy_url, params=params)
        if ok and isinstance(data, dict):
            raw = data.get("comments", [])
            normalized = []
            for c in raw:
                normalized.append({
                    "id": c.get("id"), "post_id": c.get("post_id"),
                    "post_title": c.get("post_title", ""),
                    "author_name": c.get("author", ""),
                    "author_email": c.get("email", ""),
                    "content": {"rendered": c.get("content", "")},
                    "status": c.get("status", ""), "date": c.get("date", ""),
                })
            return normalized
    try:
        url = f"{site.url}/wp-json/wp/v2/comments?per_page=100"
        if use_lang:
            url += f"&lang={use_lang}"
        if post_id:
            url += f"&post={post_id}"
        if status != "all":
            url += f"&status={status}"
        resp = _rest_get(url, site, timeout, proxy_url)
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception:
        return []


def send_comment(site: Site, post_id: int, content: str, as_admin: bool = True,
                 guest_name: str = "Guest", guest_email: str = "guest@example.com",
                 parent_id: Optional[int] = None, timeout: int = 20,
                 proxy_url: str = "", lang: str = "") -> tuple[bool, any]:
    safe = sanitize_comment_text(content)
    if not safe:
        return False, "Empty comment"
    use_lang = lang or site.lang
    if site.api_key:
        body = {"post_id": post_id, "content": safe,
                "author_name": sanitize_guest_name(guest_name),
                "author_email": sanitize_guest_email(guest_email)}
        if use_lang:
            body["lang"] = use_lang
        if parent_id:
            body["parent"] = parent_id
        return _plugin_api_call("POST", "comments", site, timeout, proxy_url, body=body)
    url = f"{site.url}/wp-json/wp/v2/comments"
    data = {"post": post_id, "content": safe,
            "author_name": sanitize_guest_name(guest_name),
            "author_email": sanitize_guest_email(guest_email)}
    if use_lang:
        data["lang"] = use_lang
    if parent_id:
        data["parent"] = parent_id
    if as_admin:
        auth = _get_auth(site)
        data["status"] = "approved"
    else:
        auth = None
    return _wp_json_request("POST", url, auth, data, timeout, proxy_url=proxy_url)


def send_comment_via_form(site: Site, post_id: int, content: str,
                          guest_name: str = "Guest", guest_email: str = "guest@example.com",
                          parent_id: Optional[int] = None, timeout: int = 20,
                          proxy_url: str = "", lang: str = "") -> tuple[bool, any]:
    safe = sanitize_comment_text(content)
    if not safe:
        return False, "Empty comment"
    use_lang = lang or site.lang
    data = {"comment": safe, "author": sanitize_guest_name(guest_name),
            "email": sanitize_guest_email(guest_email), "comment_post_ID": str(post_id)}
    if use_lang:
        data["lang"] = use_lang
    if parent_id:
        data["comment_parent"] = str(parent_id)
    post_url = f"{site.url}/?p={post_id}"
    headers = {"User-Agent": _BROWSER_UA, "Content-Type": "application/x-www-form-urlencoded",
               "Referer": post_url}
    try:
        with _get_session(timeout, retry=False, proxy_url=proxy_url) as s:
            s.get(post_url, timeout=timeout)
            resp = s.post(f"{site.url}/wp-comments-post.php", data=data,
                          headers=headers, timeout=timeout, allow_redirects=False)
        if resp.status_code == 302:
            return True, {"id": None, "status": "pending"}
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def approve_comment(site: Site, comment_id: int, timeout: int = 15, proxy_url: str = "") -> tuple[bool, str]:
    if site.api_key:
        ok, data = _plugin_api_call("POST", "approve", site, timeout, proxy_url, body={"id": comment_id})
        if ok:
            return True, "approved"
        return False, str(data)
    ok, data = _wp_json_request("POST", f"{site.url}/wp-json/wp/v2/comments/{comment_id}",
                                 _get_auth(site), {"status": "approve"}, timeout, proxy_url)
    if ok:
        return True, "approved"
    return False, str(data)


def delete_comment(site: Site, comment_id: int, timeout: int = 15, proxy_url: str = "") -> tuple[bool, str]:
    if site.api_key:
        ok, data = _plugin_api_call("POST", "delete", site, timeout, proxy_url, body={"id": comment_id})
        if ok:
            return True, "deleted"
        return False, str(data)
    with _get_session(timeout, proxy_url=proxy_url) as s:
        try:
            resp = s.delete(f"{site.url}/wp-json/wp/v2/comments/{comment_id}",
                           auth=_get_auth(site), timeout=timeout)
            if resp.status_code == 200:
                return True, "deleted"
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)
