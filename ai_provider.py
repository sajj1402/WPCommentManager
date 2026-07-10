import json
import re
import requests


COMMENT_TONES = [
    ("Neutral", "نظر خنثی"),
    ("Positive", "نظر مثبت"),
    ("Critical", "نظر انتقادی"),
    ("Question", "نظر پرسشی"),
    ("Funny", "نظر طنز"),
    ("Detailed", "نظر مفصل"),
    ("Short", "نظر کوتاه"),
    ("Supportive", "نظر حمایتی"),
]

LANGUAGES = {
    "persian": {"label": "Persian (فارسی)", "instruction": "پاسخ را فقط به زبان فارسی بنویس."},
    "english": {"label": "English", "instruction": "Write the response in English only."},
    "mixed": {"label": "Mixed (متنوع)", "instruction": "Use a mix of Persian and English."},
}

PROVIDERS = {
    "gemini": {"name": "Google Gemini", "base": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}", "default_model": "gemini-2.0-flash"},
    "groq": {"name": "Groq Cloud", "base": "https://api.groq.com/openai/v1/chat/completions", "default_model": "mixtral-8x7b-32768"},
    "together": {"name": "Together AI", "base": "https://api.together.xyz/v1/chat/completions", "default_model": "mistralai/Mixtral-8x7B-Instruct-v0.1"},
    "openrouter": {"name": "OpenRouter", "base": "https://openrouter.ai/api/v1/chat/completions", "default_model": "gpt-3.5-turbo"},
    "ollama": {"name": "Ollama (Local)", "default_model": "llama3"},
    "huggingface": {"name": "HuggingFace", "default_model": "mistralai/Mistral-7B-Instruct-v0.2"},
    "openai": {"name": "OpenAI ChatGPT", "base": "https://api.openai.com/v1/chat/completions", "default_model": "gpt-4o-mini"},
    "deepseek": {"name": "DeepSeek", "base": "https://api.deepseek.com/v1/chat/completions", "default_model": "deepseek-chat"},
    "claude": {"name": "Anthropic Claude", "base": "https://api.anthropic.com/v1/messages", "default_model": "claude-3-5-haiku-20241022"},
    "grok": {"name": "xAI Grok", "base": "https://api.x.ai/v1/chat/completions", "default_model": "grok-beta"},
}


def _build_prompt(post_content: str, tone: str = "Neutral", language: str = "persian", min_words: int = 10, max_words: int = 60) -> str:
    lang_info = LANGUAGES.get(language, LANGUAGES["persian"])
    return (
        f"Write a {tone} blog comment (between {min_words} and {max_words} words) "
        f"for the following post. {lang_info['instruction']} "
        f"The comment should be relevant, natural, and add value to the discussion. "
        f"Do NOT mention AI or that you are an AI.\n\nPost content:\n{post_content[:3000]}"
    )


def _build_batch_prompt(posts: list[dict], tone: str = "Neutral", language: str = "persian", min_words: int = 10, max_words: int = 60) -> str:
    lang_info = LANGUAGES.get(language, LANGUAGES["persian"])
    prompt = (
        f"Write one {tone} blog comment for EACH of the following posts. "
        f"Each comment should be between {min_words} and {max_words} words. "
        f"{lang_info['instruction']} "
        f"Make sure comments are diverse, natural, and relevant to each post. "
        f"Do NOT mention AI.\n\n"
        f"Respond with valid JSON only: keys are post numbers, values are comment texts.\n"
        f'Example: {{"1": "Great article!", "2": "Thanks for sharing"}}\n\n'
    )
    for i, p in enumerate(posts, 1):
        title = p.get("title", "")
        if isinstance(title, dict):
            title = title.get("rendered", "")
        excerpt = (p.get("content", "") or "")[:500]
        prompt += f"--- Post {i}: {title} ---\n{excerpt}\n\n"
    return prompt


def _parse_batch_response(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        pass
    matches = re.findall(r'["\']?(\d+)["\']?\s*:\s*["\'](.+?)["\']', text, re.DOTALL)
    if matches:
        return {k: v.strip() for k, v in matches}
    result = {}
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines, 1):
        line = re.sub(r'^["\'\d\s:.,\-]+', "", line).strip()
        if line:
            result[str(i)] = line
    return result


def generate_comment(provider: str, api_key: str, post_content: str,
                     model: str = "", tone: str = "Neutral",
                     language: str = "persian", temperature: float = 0.7,
                     min_words: int = 10, max_words: int = 60,
                     ollama_url: str = "") -> tuple[bool, str]:
    prompt = _build_prompt(post_content, tone, language, min_words, max_words)
    prov = PROVIDERS.get(provider)
    if not prov:
        return False, "Unknown provider"

    if provider == "ollama":
        return _ollama_generate(ollama_url or "http://localhost:11434", model or prov["default_model"], prompt, temperature)

    if not api_key:
        return False, "API key required"

    if provider == "gemini":
        return _gemini_generate(api_key, model or prov["default_model"], prompt, temperature)
    elif provider == "claude":
        return _claude_generate(api_key, model or prov["default_model"], prompt, temperature)
    elif provider == "huggingface":
        return _huggingface_generate(api_key, model or prov["default_model"], prompt, temperature)
    else:
        return _openai_compat_generate(api_key, prov["base"], model or prov["default_model"], prompt, temperature)


def generate_batch_comments(provider: str, api_key: str, posts: list[dict],
                            model: str = "", tone: str = "Neutral",
                            language: str = "persian", temperature: float = 0.7,
                            min_words: int = 10, max_words: int = 60,
                            ollama_url: str = "") -> list[tuple[int, bool, str]]:
    prompt = _build_batch_prompt(posts, tone, language, min_words, max_words)
    prov = PROVIDERS.get(provider)
    if not prov:
        return [(p["id"], False, "Unknown provider") for p in posts]

    if provider == "ollama":
        ok, raw = _ollama_generate(ollama_url or "http://localhost:11434", model or prov["default_model"], prompt, temperature)
    elif not api_key:
        return [(p["id"], False, "API key required") for p in posts]
    elif provider == "gemini":
        ok, raw = _gemini_generate(api_key, model or prov["default_model"], prompt, temperature)
    elif provider == "claude":
        ok, raw = _claude_generate(api_key, model or prov["default_model"], prompt, temperature)
    elif provider == "huggingface":
        ok, raw = _huggingface_generate(api_key, model or prov["default_model"], prompt, temperature)
    else:
        ok, raw = _openai_compat_generate(api_key, prov["base"], model or prov["default_model"], prompt, temperature)

    if not ok:
        return [(p["id"], False, raw) for p in posts]

    parsed = _parse_batch_response(raw)
    results = []
    for i, p in enumerate(posts, 1):
        comment = parsed.get(str(i), "").strip()
        if comment:
            results.append((p["id"], True, comment))
        else:
            results.append((p["id"], False, "AI response parsing failed"))
    return results


def test_provider(provider: str, api_key: str, model: str = "", ollama_url: str = "") -> tuple[bool, str]:
    prov = PROVIDERS.get(provider)
    if not prov:
        return False, "Unknown provider"
    if provider == "ollama":
        return _ollama_test(ollama_url or "http://localhost:11434", model or prov["default_model"])
    if not api_key:
        return False, "API key required"
    if provider == "gemini":
        return _gemini_test(api_key, model or prov["default_model"])
    elif provider == "claude":
        return _claude_test(api_key, model or prov["default_model"])
    elif provider == "huggingface":
        return _huggingface_test(api_key, model or prov["default_model"])
    else:
        return _openai_compat_test(api_key, prov["base"], model or prov["default_model"])


def _openai_compat_generate(api_key: str, base_url: str, model: str, prompt: str, temperature: float = 0.7) -> tuple[bool, str]:
    try:
        resp = requests.post(base_url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                             json={"model": model, "messages": [{"role": "user", "content": prompt}],
                                   "temperature": temperature}, timeout=60)
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"]
            return True, text.strip()
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


def _openai_compat_test(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    try:
        resp = requests.get(base_url.replace("/chat/completions", "/models"),
                           headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
        if resp.status_code == 200:
            return True, "Connected"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def _gemini_generate(api_key: str, model: str, prompt: str, temperature: float = 0.7) -> tuple[bool, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}],
                                        "generationConfig": {"temperature": temperature}}, timeout=60)
        if resp.status_code == 200:
            parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
            if parts:
                return True, parts[0].get("text", "").strip()
            return False, "Empty response"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


def _gemini_test(api_key: str, model: str) -> tuple[bool, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}?key={api_key}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return True, f"Model: {resp.json().get('name', model)}"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def _claude_generate(api_key: str, model: str, prompt: str, temperature: float = 0.7) -> tuple[bool, str]:
    try:
        resp = requests.post("https://api.anthropic.com/v1/messages",
                            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                     "Content-Type": "application/json"},
                            json={"model": model, "max_tokens": 2000,
                                  "messages": [{"role": "user", "content": prompt}],
                                  "temperature": temperature}, timeout=60)
        if resp.status_code == 200:
            return True, resp.json()["content"][0]["text"].strip()
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


def _claude_test(api_key: str, model: str) -> tuple[bool, str]:
    try:
        resp = requests.get("https://api.anthropic.com/v1/models",
                           headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}, timeout=15)
        if resp.status_code == 200:
            return True, "Connected"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def _huggingface_generate(api_key: str, model: str, prompt: str, temperature: float = 0.7) -> tuple[bool, str]:
    url = f"https://api-inference.huggingface.co/models/{model}"
    try:
        resp = requests.post(url, headers={"Authorization": f"Bearer {api_key}"},
                            json={"inputs": prompt, "parameters": {"temperature": temperature,
                                    "max_new_tokens": 500}}, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                text = data[0].get("generated_text", "")
                if text:
                    return True, text.replace(prompt, "").strip()
            return False, "Empty response"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def _huggingface_test(api_key: str, model: str) -> tuple[bool, str]:
    try:
        resp = requests.head(f"https://api-inference.huggingface.co/models/{model}",
                            headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
        if resp.status_code in (200, 503):
            return True, f"Model available: {model}"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def _ollama_generate(base_url: str, model: str, prompt: str, temperature: float = 0.7) -> tuple[bool, str]:
    try:
        resp = requests.post(f"{base_url}/api/generate",
                            json={"model": model, "prompt": prompt,
                                  "stream": False, "options": {"temperature": temperature}}, timeout=120)
        if resp.status_code == 200:
            return True, resp.json().get("response", "").strip()
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def _ollama_test(base_url: str, model: str) -> tuple[bool, str]:
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=15)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            for m in models:
                if model in m.get("name", ""):
                    return True, f"Model found: {model}"
            names = [m.get("name", "?") for m in models]
            return False, f"Model '{model}' not found. Available: {', '.join(names[:5])}"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)
