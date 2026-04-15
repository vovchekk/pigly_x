import logging
import re
import time

from django.conf import settings

from history.models import GenerationRequest, GenerationResult
from users.models import UserProfile

from .utils import coerce_int, first_sentence, normalize_language, normalize_text, normalize_tone, trim_words


logger = logging.getLogger(__name__)

DEFAULT_SHORTEN_MODE = "blitz:auto"
DEFAULT_REPLY_MODEL = "gemini-2.5-flash-lite"
MAX_SOURCE_TEXT_LENGTH = 6000

BUILTIN_STYLE_PROMPTS = {
    UserProfile.STYLE_SHARP: {
        "label": "Sharp",
        "prompt": "Write short, direct, opinionated replies with zero fluff.",
    },
    UserProfile.STYLE_SUPPORTIVE: {
        "label": "Supportive",
        "prompt": "Sound warm, human, and constructive without becoming generic praise.",
    },
    UserProfile.STYLE_CURIOUS: {
        "label": "With a question",
        "prompt": "Reply through a concrete, relevant question that keeps the discussion open.",
    },
    UserProfile.STYLE_EXPERT: {
        "label": "Expert",
        "prompt": "Sound informed and precise, pointing at the practical implication or nuance.",
    },
    UserProfile.STYLE_IRONIC: {
        "label": "With irony",
        "prompt": "Use light irony or wit, but keep it clean and not toxic.",
    },
}


def _build_request_data(
    *,
    source_text,
    tone,
    language,
    variant_count,
    context_text="",
    target_length=None,
    engine="fallback",
    generation_mode=None,
    profile_defaults=None,
):
    data = {
        "source_text": source_text,
        "tone": tone,
        "language": language,
        "variant_count": variant_count,
        "engine": engine,
    }
    if context_text:
        data["context_text"] = context_text
    if target_length is not None:
        data["target_length"] = target_length
    if generation_mode:
        data["generation_mode"] = generation_mode
    if profile_defaults:
        data["profile_defaults"] = profile_defaults
    return data


def _is_transient_generation_error(exc):
    message = str(exc).lower()
    transient_markers = (
        "timeout",
        "timed out",
        "temporar",
        "rate limit",
        "unavailable",
        "connection reset",
        "internal",
        "503",
        "429",
    )
    return any(marker in message for marker in transient_markers)


def _get_gemini_client():
    api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return None, None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai is not installed; using fallback generator.")
        return None, None

    return genai.Client(api_key=api_key), types


def _call_gemini_text(*, prompt, max_output_tokens, temperature, top_p):
    client, types = _get_gemini_client()
    if client is None or types is None:
        return None

    model_name = getattr(settings, "GEMINI_MODEL", DEFAULT_REPLY_MODEL)
    retry_delays = (0.0, 1.0, 2.5)
    last_exc = None

    for attempt, delay in enumerate(retry_delays, start=1):
        if delay:
            time.sleep(delay)
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    top_p=top_p,
                    max_output_tokens=max_output_tokens,
                ),
            )
            text = normalize_text(getattr(response, "text", ""))
            if text:
                return text
        except Exception as exc:
            last_exc = exc
            if attempt == len(retry_delays) or not _is_transient_generation_error(exc):
                break
            logger.warning("Gemini transient error on attempt %s/%s: %s", attempt, len(retry_delays), exc)

    if last_exc:
        logger.exception("Gemini generation failed: %s", last_exc)
    return None


def _extract_comment_hooks_from_post(text, limit=3):
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return []

    patterns = (
        r"\bmust\b",
        r"\bonly if\b",
        r"\bcannot\b",
        r"\bcan't\b",
        r"\bdo not\b",
        r"\bdon't\b",
        r"\bmetric",
        r"\bdeadline\b",
        r"\bedge case",
        r"\blaunch\b",
        r"\bship\b",
        r"\bthread\b",
        r"\breply\b",
        r"\btoken\b",
        r"\bapi\b",
    )

    candidates = []
    seen = set()
    for line in re.split(r"\n+|(?<=[.!?])\s+", normalized):
        candidate = normalize_text(line).strip(" -")
        if len(candidate) < 20:
            continue
        lowered = candidate.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        score = 0
        if any(re.search(pattern, lowered) for pattern in patterns):
            score += 4
        if re.search(r"\b\d+\b", candidate):
            score += 2
        if candidate.endswith("?"):
            score += 2
        score += min(len(candidate) // 50, 2)
        candidates.append((score, candidate[:180]))

    candidates.sort(key=lambda item: (-item[0], -len(item[1])))
    return [item[1] for item in candidates[:limit]]


def _coerce_profile_defaults(profile, source_text, context_text, tone, language, variant_count):
    defaults = {
        "comment_styles": [],
        "emoji_mode": "moderate",
        "dash_style": "ndash",
        "terminal_punctuation": "none",
        "capitalization": "upper",
        "comment_length": "mix",
        "variant_count": variant_count,
        "translate_to_language": "",
    }

    if profile is None:
        defaults["tone"] = normalize_tone(tone)
        defaults["language"] = normalize_language(language, source_text or context_text)
        return defaults

    resolved_styles = profile.selected_comment_styles
    resolved_tone = normalize_tone(
        tone or UserProfile.map_style_to_tone(resolved_styles[0] if resolved_styles else profile.preferred_tone)
    )
    preferred_language = profile.preferred_translate_language or profile.preferred_language
    resolved_language = normalize_language(language or preferred_language, source_text or context_text)

    defaults.update(
        {
            "comment_styles": resolved_styles,
            "emoji_mode": profile.preferred_emoji_mode,
            "dash_style": profile.preferred_dash_style,
            "terminal_punctuation": profile.preferred_terminal_punctuation,
            "capitalization": profile.preferred_capitalization,
            "comment_length": profile.preferred_comment_length,
            "variant_count": coerce_int(
                variant_count or profile.preferred_variant_count,
                default=profile.preferred_variant_count,
                minimum=1,
                maximum=3,
            ),
            "translate_to_language": profile.preferred_translate_language,
            "tone": resolved_tone,
            "language": resolved_language,
        }
    )
    return defaults


def _style_variants_for_profile(profile):
    variants = []
    if profile is None:
        return variants

    for style_id in profile.selected_comment_styles:
        style_data = BUILTIN_STYLE_PROMPTS.get(style_id)
        if style_data:
            variants.append(
                {
                    "id": style_id,
                    "label": style_data["label"],
                    "prompt": style_data["prompt"],
                }
            )

    for item in profile.custom_comment_styles:
        variants.append(
            {
                "id": item["id"],
                "label": item["label"],
                "prompt": item["prompt"],
            }
        )
    return variants


def _reply_length_instruction(comment_length):
    return {
        "short": "Each reply must be one short sentence, usually 4-9 words.",
        "medium": "Each reply should be 1-2 concise sentences, usually 8-18 words.",
        "long": "Each reply can be 2 compact sentences with more substance, but still social-media natural.",
        "mix": "Vary the length naturally depending on the source post instead of making every option the same size.",
    }.get(comment_length, "Keep every reply short and social-media natural.")


def _emoji_instruction(mode):
    return {
        "none": "Do not use emojis.",
        "moderate": "Use at most one emoji and only if it helps the tone.",
        "many": "You may use emojis more freely, but keep them tasteful.",
        "mix": "Mix emoji and no-emoji replies naturally.",
    }.get(mode, "Use emojis only when they genuinely help the tone.")


def _dash_instruction(style):
    return {
        "hyphen": "If you use a dash, prefer the hyphen character '-'.",
        "ndash": "If you use a dash, prefer the en dash character '–'.",
        "mdash": "If you use a dash, prefer the em dash character '—'.",
    }.get(style, "If you use a dash, prefer the en dash character '–'.")


def _punctuation_instruction(style):
    return {
        "none": "Avoid ending the reply with a period unless it sounds unnatural without one.",
        "keep": "Use normal sentence-ending punctuation when it feels natural.",
        "mix": "Mix ending punctuation naturally across variants.",
    }.get(style, "Avoid ending the reply with a period unless it sounds unnatural without one.")


def _capitalization_instruction(style):
    return {
        "upper": "Start replies with uppercase naturally.",
        "preserve": "Keep capitalization natural to the style and source.",
        "mix": "Mix capitalization naturally where it helps the voice.",
    }.get(style, "Start replies with uppercase naturally.")


def _build_reply_prompt(*, source_text, context_text, defaults, style_variants, variant_count, language):
    target_language = {"ru": "Russian", "en": "English", "zh": "Chinese"}.get(language, "English")
    style_lines = []
    for item in style_variants:
        line = f"- [{item['id']}] {item['label']}"
        if item["prompt"]:
            line += f": {item['prompt']}"
        style_lines.append(line)
    styles_section = "\n".join(style_lines) if style_lines else "- [supportive] Warm, concrete, human"
    hooks = _extract_comment_hooks_from_post(source_text, limit=3)
    hooks_section = "\n".join(f"- {hook}" for hook in hooks) if hooks else "- Focus on the concrete claim, detail, or implication."
    context_section = f"\nExtra context:\n{context_text}\n" if context_text else ""
    numbered_slots = "\n".join(f"{index}. [style_id] <reply>" for index in range(1, variant_count + 1))

    return (
        "You write smart replies for X/Twitter inside Pigly.\n"
        f"Return exactly {variant_count} numbered reply options in {target_language}.\n"
        "Each option must sound like a real person, not an AI assistant or brand account.\n"
        "Do not use @mentions, usernames, hashtags, or made-up facts.\n"
        "Do not give generic praise detached from the post.\n"
        "Each reply should hook into a concrete detail, implication, metric, edge case, or tension from the source post.\n"
        "Keep the tone social-first, crisp, and publication-ready.\n"
        f"{_reply_length_instruction(defaults['comment_length'])}\n"
        f"{_emoji_instruction(defaults['emoji_mode'])}\n"
        f"{_dash_instruction(defaults['dash_style'])}\n"
        f"{_punctuation_instruction(defaults['terminal_punctuation'])}\n"
        f"{_capitalization_instruction(defaults['capitalization'])}\n"
        "If the chosen style implies a question, make the reply end with a real question.\n"
        "Return only the numbered list, no intro, no notes.\n\n"
        "Available styles:\n"
        f"{styles_section}\n\n"
        "Most relevant hooks from the post:\n"
        f"{hooks_section}\n"
        f"{context_section}\n"
        "Source post:\n"
        f"{source_text[:MAX_SOURCE_TEXT_LENGTH]}\n\n"
        "Output format:\n"
        f"{numbered_slots}"
    )


def _build_shorten_prompt(*, source_text, language, variant_count, target_length):
    target_language = {"ru": "Russian", "en": "English", "zh": "Chinese"}.get(language, "English")
    target_words = max(8, (target_length or 180) // 8)
    numbered_slots = "\n".join(f"{index}. <compressed thought>" for index in range(1, variant_count + 1))
    return (
        "You compress long social posts into short, clean thought summaries for Pigly.\n"
        f"Return exactly {variant_count} numbered options in {target_language}.\n"
        "This is not a rewrite for posting and not a marketing headline.\n"
        "Preserve the core idea of the original post while removing fluff, repetition, and weak setup.\n"
        "Keep every option concise, readable, and faithful to the original meaning.\n"
        "Do not add facts or interpretations that are not present in the source.\n"
        "Each option should feel like a compact version of the author's thought, usually one or two short sentences.\n"
        f"Aim for roughly {target_words} words or less per option.\n"
        "Return only the numbered list, no notes or commentary.\n\n"
        "Source post:\n"
        f"{source_text[:MAX_SOURCE_TEXT_LENGTH]}\n\n"
        "Output format:\n"
        f"{numbered_slots}"
    )


def _parse_numbered_items(text, expected_count):
    items = []
    for line in str(text or "").replace("\r", "\n").split("\n"):
        cleaned = line.strip()
        if not cleaned:
            continue
        match = re.match(r"^\d+[\.\)]\s+(?:\[[^\]]+\]\s*)?(.*)$", cleaned)
        if not match:
            continue
        value = normalize_text(match.group(1)).strip(" -")
        if value:
            items.append(value)
        if len(items) >= expected_count:
            break
    return items


def _fallback_reply_variants(source_text, context_text, language, tone, variant_count):
    base = normalize_text(context_text or source_text)
    summary = first_sentence(base) or trim_words(base, 18)
    summary = trim_words(summary, 18)
    if not summary:
        summary = "this"

    if language == "ru":
        templates = {
            "confident": [
                "Да, это прямо в точку. {summary}",
                "Именно. {summary} здесь главное.",
                "Сильная мысль. {summary}",
            ],
            "concise": [
                "Согласен. {summary}",
                "Да, именно так. {summary}",
                "Точно. {summary}",
            ],
            "neutral": [
                "Хороший тезис. {summary}",
                "Звучит логично. {summary}",
                "В этом и суть. {summary}",
            ],
            "friendly": [
                "Хорошая мысль. {summary}",
                "Да, это чувствуется. {summary}",
                "Согласен, особенно тут: {summary}",
            ],
        }
    else:
        templates = {
            "confident": [
                "Exactly. {summary}",
                "That is the real point. {summary}",
                "Strong take. {summary}",
            ],
            "concise": [
                "Agreed. {summary}",
                "Yep. {summary}",
                "Right. {summary}",
            ],
            "neutral": [
                "Good point. {summary}",
                "That makes sense. {summary}",
                "That is the key point. {summary}",
            ],
            "friendly": [
                "Good take. {summary}",
                "Yeah, that lands. {summary}",
                "Totally, especially this part: {summary}",
            ],
        }

    variants = []
    selected_templates = templates.get(tone, templates["friendly"])
    for index in range(variant_count):
        variants.append(selected_templates[index % len(selected_templates)].format(summary=summary))
    return variants


def _fallback_shorten_variants(source_text, variant_count, target_length):
    base = normalize_text(source_text)
    if not base:
        return []

    target_words = max(8, (target_length or 180) // 8)
    variants = [
        first_sentence(base) or trim_words(base, target_words),
        trim_words(base, max(8, target_words - 4)),
        trim_words(base, max(7, target_words - 8)),
    ]
    while len(variants) < variant_count:
        variants.append(trim_words(base, max(6, target_words - 10 - len(variants))))
    return variants[:variant_count]


def _generate_reply_variants(*, source_text, context_text, defaults, style_variants, variant_count):
    prompt = _build_reply_prompt(
        source_text=source_text,
        context_text=context_text,
        defaults=defaults,
        style_variants=style_variants,
        variant_count=variant_count,
        language=defaults["language"],
    )
    raw = _call_gemini_text(
        prompt=prompt,
        max_output_tokens=650,
        temperature=0.55,
        top_p=0.9,
    )
    if raw:
        parsed = _parse_numbered_items(raw, variant_count)
        if len(parsed) >= variant_count:
            return parsed[:variant_count], "gemini"

    return _fallback_reply_variants(
        source_text,
        context_text,
        defaults["language"],
        defaults["tone"],
        variant_count,
    ), "fallback"


def _generate_shorten_variants(*, source_text, language, tone, variant_count, target_length):
    prompt = _build_shorten_prompt(
        source_text=source_text,
        language=language,
        variant_count=variant_count,
        target_length=target_length,
    )
    raw = _call_gemini_text(
        prompt=prompt,
        max_output_tokens=420,
        temperature=0.2,
        top_p=0.7,
    )
    if raw:
        parsed = _parse_numbered_items(raw, variant_count)
        if len(parsed) >= variant_count:
            return parsed[:variant_count], "gemini"

    return _fallback_shorten_variants(source_text, variant_count, target_length), "fallback"


def create_generation_record(*, user, kind, source_text, tone, request_data, results):
    generation_request = GenerationRequest.objects.create(
        user=user,
        kind=kind,
        source_text=source_text,
        tone=tone,
        request_data=request_data,
    )
    GenerationResult.objects.bulk_create(
        [
            GenerationResult(
                request=generation_request,
                content=content,
                position=index,
            )
            for index, content in enumerate(results, start=1)
        ]
    )
    generation_request.refresh_from_db()
    return generation_request


def build_shorten_generation(*, source_text, tone=None, language=None, variant_count=1, target_length=None, profile=None):
    variant_count = coerce_int(variant_count, default=1, minimum=1, maximum=3)
    target_length = target_length if target_length is None else coerce_int(target_length, default=180, minimum=40, maximum=280)
    defaults = _coerce_profile_defaults(profile, source_text, "", tone, language, variant_count)
    results, engine = _generate_shorten_variants(
        source_text=source_text,
        language=defaults["language"],
        tone=defaults["tone"],
        variant_count=variant_count,
        target_length=target_length or 180,
    )
    request_data = _build_request_data(
        source_text=source_text,
        tone=defaults["tone"],
        language=defaults["language"],
        variant_count=variant_count,
        target_length=target_length,
        engine=engine,
        generation_mode=DEFAULT_SHORTEN_MODE,
    )
    return request_data, results


def build_reply_generation(*, source_text, context_text="", tone=None, language=None, variant_count=3, profile=None):
    variant_count = coerce_int(variant_count, default=3, minimum=1, maximum=3)
    defaults = _coerce_profile_defaults(profile, source_text, context_text, tone, language, variant_count)
    style_variants = _style_variants_for_profile(profile)
    results, engine = _generate_reply_variants(
        source_text=source_text,
        context_text=context_text,
        defaults=defaults,
        style_variants=style_variants,
        variant_count=variant_count,
    )
    request_data = _build_request_data(
        source_text=source_text,
        tone=defaults["tone"],
        language=defaults["language"],
        variant_count=variant_count,
        context_text=context_text,
        engine=engine,
        profile_defaults={
            "comment_styles": defaults["comment_styles"],
            "emoji_mode": defaults["emoji_mode"],
            "dash_style": defaults["dash_style"],
            "terminal_punctuation": defaults["terminal_punctuation"],
            "capitalization": defaults["capitalization"],
            "comment_length": defaults["comment_length"],
            "translate_to_language": defaults["translate_to_language"],
        },
    )
    return request_data, results
