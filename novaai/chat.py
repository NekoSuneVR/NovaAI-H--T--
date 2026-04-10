from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import requests

from .config import Config
from .storage import read_recent_history

PLACEHOLDER_PATTERN = re.compile(r"\[[^\]\n]{3,120}\]")
RAW_URL_PATTERN = re.compile(r"(?i)(?:<\s*)?(?:https?://|www\.)[^\s>]+(?:\s*>)?")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _as_clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _format_list_or_default(items: list[str], fallback: str) -> str:
    return ", ".join(items) if items else fallback


def _as_clean_text(value: Any, fallback: str = "") -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return fallback


def build_system_prompt(profile: dict[str, Any]) -> str:
    memory_notes = _as_clean_list(profile.get("memory_notes"))
    shared_goals = _as_clean_list(profile.get("shared_goals"))
    tags = _as_clean_list(profile.get("tags"))

    details = profile.get("profile_details")
    if not isinstance(details, dict):
        details = {}

    identity = details.get("identity") if isinstance(details.get("identity"), dict) else {}
    conversation = (
        details.get("conversation")
        if isinstance(details.get("conversation"), dict)
        else {}
    )
    personality_sliders = (
        details.get("personality_sliders")
        if isinstance(details.get("personality_sliders"), dict)
        else {}
    )
    boundaries = (
        details.get("boundaries")
        if isinstance(details.get("boundaries"), dict)
        else {}
    )
    capabilities = (
        details.get("capabilities")
        if isinstance(details.get("capabilities"), dict)
        else {}
    )
    memory = details.get("memory") if isinstance(details.get("memory"), dict) else {}
    voice = details.get("voice") if isinstance(details.get("voice"), dict) else {}
    custom_rules = (
        details.get("custom_rules")
        if isinstance(details.get("custom_rules"), dict)
        else {}
    )

    goals_text = _format_list_or_default(
        shared_goals,
        "have thoughtful, useful conversations",
    )
    memory_text = _format_list_or_default(
        memory_notes,
        "No saved memory notes yet.",
    )
    likes_text = _format_list_or_default(
        _as_clean_list(memory.get("likes")),
        "No specific likes saved.",
    )
    dislikes_text = _format_list_or_default(
        _as_clean_list(memory.get("dislikes")),
        "No specific dislikes saved.",
    )
    facts_text = _format_list_or_default(
        _as_clean_list(memory.get("personal_facts")),
        "No personal facts saved.",
    )
    capabilities_text = _format_list_or_default(
        _as_clean_list(capabilities.get("what_ai_can_do")),
        "chat conversationally",
    )
    forbidden_claims_text = _format_list_or_default(
        _as_clean_list(capabilities.get("forbidden_claims")),
        "abilities outside the current toolset",
    )
    must_follow_rules = _as_clean_list(custom_rules.get("must_follow"))
    additional_rules_text = (
        "\n".join(f"- {rule}" for rule in must_follow_rules)
        if must_follow_rules
        else "- No additional mandatory rules provided."
    )
    slider_text = []
    for key in (
        "warmth",
        "sass",
        "directness",
        "patience",
        "playfulness",
        "formality",
    ):
        value = personality_sliders.get(key)
        if isinstance(value, (int, float)):
            slider_text.append(f"{key}: {int(value)}/100")
    slider_summary = ", ".join(slider_text) if slider_text else "No slider values provided."

    allow_emojis = conversation.get("allow_emojis")
    emoji_rule = (
        "Emojis are allowed when they help tone."
        if bool(allow_emojis)
        else "Do not use emojis, emoticons, or decorative symbols."
    )
    default_reply_length = _as_clean_text(
        conversation.get("default_reply_length"),
        "short",
    )
    response_pacing = _as_clean_text(
        conversation.get("response_pacing"),
        "snappy",
    )
    explanation_style = _as_clean_text(
        conversation.get("explanation_style"),
        "expand when asked",
    )
    roast_intensity = _as_clean_text(
        boundaries.get("roast_intensity"),
        "light",
    )
    allow_roasting = bool(boundaries.get("allow_roasting", True))
    roast_rule = (
        f"Roasting is allowed at {roast_intensity} intensity."
        if allow_roasting
        else "Do not roast or mock the user."
    )
    relationship_style = _as_clean_text(
        identity.get("relationship_style"),
        "friendly and grounded",
    )
    companion_role = _as_clean_text(
        identity.get("companion_role"),
        "AI friend and companion",
    )
    voice_delivery_notes = _as_clean_text(
        voice.get("delivery_notes"),
        "Natural conversational delivery.",
    )
    profile_description = _as_clean_text(
        profile.get("description"),
        "",
    )
    profile_tags = _format_list_or_default(tags, "none")

    return f"""
You are {profile['companion_name']}, a {companion_role} for {profile['user_name']}.
Relationship style: {relationship_style}

Profile context:
- Profile name: {profile.get('profile_name', 'Custom Profile')}
- Description: {profile_description or 'No profile description provided.'}
- Tags: {profile_tags}

Core personality:
- {profile['companion_style']}
- Personality sliders: {slider_summary}
- Sound human and natural, not scripted.
- Keep tone consistent with the profile.

Conversation defaults:
- Default reply length: {default_reply_length}
- Response pacing: {response_pacing}
- Explanation style: {explanation_style}
- {emoji_rule}
- {roast_rule}
- Keep answers concise by default, and only go long when asked.
- Use plain language and contractions.
- Do not include raw URLs or hyperlinks in replies unless the user explicitly asks for a link.

Relationship context:
- Your shared goals are: {goals_text}.
- Things to remember about the user: {memory_text}
- User likes: {likes_text}
- User dislikes: {dislikes_text}
- User facts: {facts_text}

Capabilities and limits:
- What you can do in this app: {capabilities_text}
- Never claim abilities beyond available tools.
- Avoid claiming: {forbidden_claims_text}

Voice behavior hints:
- {voice_delivery_notes}

Additional required rules:
{additional_rules_text}

Safety and honesty:
- Never manipulate the user or encourage emotional dependency.
- Never pretend to have a body, real-world presence, or real-life experiences.
- If asked directly, be honest that you are an AI companion.
- Never make up facts when you are unsure; say so plainly.
- Never become hateful, abusive, or degrading.
""".strip()


def _contains_placeholder_markup(text: str) -> bool:
    return bool(PLACEHOLDER_PATTERN.search(text))


def _strip_links_from_reply(text: str) -> str:
    without_markdown_links = MARKDOWN_LINK_PATTERN.sub(r"\1", text)
    without_raw_urls = RAW_URL_PATTERN.sub("", without_markdown_links)

    cleaned_lines: list[str] = []
    for line in without_raw_urls.splitlines():
        cleaned = re.sub(r"\s{2,}", " ", line).strip()
        cleaned = re.sub(r"[:;,.\-]\s*$", "", cleaned)
        if cleaned:
            cleaned_lines.append(cleaned)

    return "\n".join(cleaned_lines).strip()


def _extract_web_items(web_context: str) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    current_title = ""
    current_url = ""
    current_snippet = ""
    current_excerpt = ""

    def append_current() -> None:
        if current_url and (current_excerpt or current_snippet):
            items.append(
                (
                    current_title or "Result",
                    current_url,
                    current_excerpt or current_snippet,
                )
            )

    for raw_line in web_context.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^\d+\.\s+", line):
            append_current()
            current_title = re.sub(r"^\d+\.\s+", "", line).strip()
            current_url = ""
            current_snippet = ""
            current_excerpt = ""
            continue
        if line.startswith("URL:"):
            current_url = line[4:].strip()
            continue
        if line.startswith("Snippet:"):
            current_snippet = line[8:].strip()
            continue
        if line.startswith("Website excerpt:"):
            current_excerpt = line[16:].strip()
            continue

    append_current()
    return items


def _extract_web_query(web_context: str) -> str:
    for raw_line in web_context.splitlines():
        line = raw_line.strip()
        if line.lower().startswith("search query:"):
            return line.split(":", 1)[1].strip()
    return ""


def _shorten(text: str, max_chars: int = 170) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= max_chars:
        return compact
    clipped = compact[: max_chars - 3].rsplit(" ", 1)[0].strip()
    return (clipped or compact[: max_chars - 3]).rstrip(" ,.;:") + "..."


def _host_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or "source"


def _build_web_fallback_reply(user_text: str, web_context: str) -> str | None:
    items = _extract_web_items(web_context)
    if not items:
        return None

    search_query = _extract_web_query(web_context)
    first_title, first_url, first_snippet = items[0]
    summary = _shorten(first_snippet or first_title, max_chars=170)

    seen_hosts: list[str] = []
    for _title, url, _snippet in items:
        host = _host_from_url(url)
        if host not in seen_hosts:
            seen_hosts.append(host)
    source_text = ", ".join(seen_hosts[:2])

    lead = "Quick web check"
    if search_query:
        lead += f" for \"{search_query}\""
    reply = f"{lead}: {summary}"
    if source_text:
        reply += f" Sources: {source_text}."

    if "weather" in user_text.lower() and " weather " in f" {search_query.lower()} ":
        if " in " not in f" {search_query.lower()} ":
            reply += " Want me to check your exact city/suburb?"
    return reply


def request_reply(
    user_text: str,
    profile: dict[str, Any],
    config: Config,
    web_context: str | None = None,
) -> str:
    messages = [{"role": "system", "content": build_system_prompt(profile)}]
    messages.extend(read_recent_history(config.history_turns))
    if web_context:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Use the following fresh web context when relevant. "
                    "Do not fabricate details. Mention source names only and do "
                    "not output any links or raw URLs. Never output placeholder text like "
                    "[Weather information here] or [Insert source]. "
                    "If important details are missing, say what is missing. "
                    "Keep the final answer casual and concise by default. "
                    "Prefer details from any 'Website excerpt' lines when available."
                ),
            }
        )
        messages.append({"role": "system", "content": web_context})
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "keep_alive": config.ollama_keep_alive,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.ollama_num_predict,
        },
    }

    try:
        response = requests.post(
            config.ollama_api_url,
            json=payload,
            timeout=config.request_timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "I could not reach Ollama. Install/start Ollama, make sure the server is "
            "running, and confirm OLLAMA_API_URL is correct."
        ) from exc

    detail = ""
    try:
        detail = response.json().get("error", "")
    except ValueError:
        detail = response.text.strip()

    if response.status_code >= 400:
        if "not found" in detail.lower():
            raise RuntimeError(
                f"Ollama could not find the model '{config.model}'. "
                f"After installing Ollama, run: ollama pull {config.model}"
            )
        raise RuntimeError(
            f"Ollama returned HTTP {response.status_code}. {detail or 'No error details were returned.'}"
        )

    try:
        data = response.json()
        reply = data["message"]["content"].strip()
        if web_context and _contains_placeholder_markup(reply):
            fallback_reply = _build_web_fallback_reply(user_text, web_context)
            if fallback_reply:
                reply = fallback_reply
        reply = _strip_links_from_reply(reply)
        return reply
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Ollama returned an unexpected response format.") from exc
