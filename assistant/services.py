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
LANGUAGE_LABELS = {"ru": "Russian", "en": "English", "zh": "Chinese"}
GENERIC_REPLY_PATTERNS = (
    r"^(good|great|nice|interesting|solid|strong)\s+(point|take)\.?$",
    r"^(well said|love this|this is huge|sounds exciting|so true|exactly)\.?$",
    r"^(agreed|true|fair|wow|nice|cool|yep|yeah|totally)\.?$",
    r"^(that makes sense|this makes sense|good point)\.?$",
)
NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+)[\.\)]\s*(?:\[([^\]]+)\]\s*)?(.*)$")
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9']+")
HANGING_COMMENT_ENDINGS = {
    "a", "an", "and", "as", "at", "but", "by", "can", "for",
    "from", "i", "if", "in", "into", "is", "it", "my", "of",
    "on", "or", "our", "so", "still", "that", "the", "their",
    "then", "they", "this", "to", "we", "with", "you", "your",
}
LOW_SIGNAL_COMMENT_PREFIXES = (
    "the real hinge here is",
    "this lands because",
    "the useful part is",
    "the practical implication is",
    "the funny part is",
    "вся развилка здесь",
    "самое полезное здесь",
    "ключевой риск здесь",
)
BROKEN_SYMBOL_RE = re.compile(r"[\\/<>{}\[\]|]{2,}|[Σ∆√§¶]|(?:[^\w\s.,!?;:'\"()\\-–—%$#@/&+]){4,}")

SHORTEN_AMOUNT_RE = re.compile(r"(?:~|≈|about|around)?\s*[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?[kmbKMB])?")
SHORTEN_CASHTAG_RE = re.compile(r"\$[A-Za-z][A-Za-z0-9_]{1,14}")

BUILTIN_STYLE_PROMPTS = {
    UserProfile.STYLE_SHARP: {"label": "Sharp", "prompt": "Be direct, crisp, and opinionated."},
    UserProfile.STYLE_SUPPORTIVE: {"label": "Supportive", "prompt": "Sound warm and constructive without empty praise."},
    UserProfile.STYLE_CURIOUS: {"label": "With a question", "prompt": "Use a concrete question that opens the thread."},
    UserProfile.STYLE_EXPERT: {"label": "Expert", "prompt": "Point at a mechanism, implication, tradeoff, or edge case."},
    UserProfile.STYLE_IRONIC: {"label": "With irony", "prompt": "Use light wit naturally, not try-hard sarcasm."},
}


class GeminiGenerationError(RuntimeError):
    def __init__(self, message, *, code="gemini_error", extra=None):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


def _build_request_data(*, source_text, tone, language, variant_count, context_text="", target_length=None, engine="fallback", generation_mode=None, profile_defaults=None):
    data = {"source_text": source_text, "tone": tone, "language": language, "variant_count": variant_count, "engine": engine}
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
    return any(marker in message for marker in ("timeout", "timed out", "temporar", "rate limit", "unavailable", "connection reset", "internal", "503", "429"))


def _get_gemini_client():
    api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        raise GeminiGenerationError("GEMINI_API_KEY is missing.", code="gemini_missing_api_key")
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai is not installed.")
        raise GeminiGenerationError("google-genai is not installed.", code="gemini_import_error")
    return genai.Client(api_key=api_key), types


def _call_gemini_text(*, prompt, max_output_tokens, temperature, top_p):
    client, types = _get_gemini_client()

    retry_delays = (0.0, 1.0, 2.5)
    last_exc = None
    for attempt, delay in enumerate(retry_delays, start=1):
        if delay:
            time.sleep(delay)
        try:
            response = client.models.generate_content(
                model=getattr(settings, "GEMINI_MODEL", DEFAULT_REPLY_MODEL),
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
            last_exc = GeminiGenerationError(
                "Gemini returned an empty response.",
                code="gemini_empty_response",
                extra={"model": getattr(settings, "GEMINI_MODEL", DEFAULT_REPLY_MODEL)},
            )
        except Exception as exc:
            last_exc = exc
            if attempt == len(retry_delays) or not _is_transient_generation_error(exc):
                break
            logger.warning("Gemini transient error on attempt %s/%s: %s", attempt, len(retry_delays), exc)
    if last_exc:
        logger.exception("Gemini generation failed: %s", last_exc)
        if isinstance(last_exc, GeminiGenerationError):
            raise last_exc
        message = str(last_exc)
        lowered = message.lower()
        if any(marker in lowered for marker in ("api key", "permission", "unauthorized", "authentication", "auth", "403")):
            code = "gemini_auth_error"
        elif any(marker in lowered for marker in ("429", "rate limit", "quota", "resource exhausted")):
            code = "gemini_rate_limited"
        elif any(marker in lowered for marker in ("timeout", "timed out", "503", "unavailable", "connection", "dns", "network", "reset")):
            code = "gemini_network_error"
        else:
            code = "gemini_request_failed"
        raise GeminiGenerationError(
            message or "Gemini request failed.",
            code=code,
            extra={"model": getattr(settings, "GEMINI_MODEL", DEFAULT_REPLY_MODEL)},
        )
    raise GeminiGenerationError(
        "Gemini returned no usable response.",
        code="gemini_empty_response",
        extra={"model": getattr(settings, "GEMINI_MODEL", DEFAULT_REPLY_MODEL)},
    )


def _extract_comment_hooks_from_post(text, limit=4):
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return []
    patterns = (
        r"\bmust\b", r"\bonly if\b", r"\bcannot\b", r"\bcan't\b", r"\bif\b", r"\bunless\b", r"\bmetric\b", r"\bdeadline\b",
        r"\bedge case\b", r"\blaunch\b", r"\bship\b", r"\bapi\b", r"\blatency\b", r"\bretention\b", r"\bscale\b", r"\brisk\b", r"\brollout\b",
    )
    candidates = []
    seen = set()
    for line in re.split(r"\n+|(?<=[.!?])\s+", normalized):
        candidate = normalize_text(line).strip(" -")
        if len(candidate) < 18:
            continue
        lowered = candidate.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        score = 0
        if any(re.search(pattern, lowered) for pattern in patterns):
            score += 4
        if re.search(r"\b\d+[%xkmb]?\b", candidate):
            score += 2
        score += min(len(candidate) // 40, 3)
        candidates.append((score, candidate[:220]))
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

    styles = [value for value in (profile.preferred_comment_styles or []) if value in BUILTIN_STYLE_PROMPTS]
    defaults.update(
        {
            "comment_styles": styles,
            "emoji_mode": profile.preferred_emoji_mode,
            "dash_style": profile.preferred_dash_style,
            "terminal_punctuation": profile.preferred_terminal_punctuation,
            "capitalization": profile.preferred_capitalization,
            "comment_length": profile.preferred_comment_length,
            "variant_count": coerce_int(variant_count or profile.preferred_variant_count, default=profile.preferred_variant_count, minimum=1, maximum=3),
            "translate_to_language": profile.preferred_translate_language,
            "tone": normalize_tone(tone or UserProfile.map_style_to_tone(styles[0] if styles else profile.preferred_tone)),
            "language": normalize_language(language or profile.preferred_translate_language, source_text or context_text),
        }
    )
    return defaults


def _style_variants_for_profile(profile):
    variants = []
    if profile is None:
        return variants
    for style_id in [value for value in (profile.preferred_comment_styles or []) if value in BUILTIN_STYLE_PROMPTS]:
        style_data = BUILTIN_STYLE_PROMPTS.get(style_id)
        if style_data:
            variants.append({"id": style_id, "label": style_data["label"], "prompt": style_data["prompt"]})
    for item in profile.custom_comment_styles:
        variants.append({"id": item["id"], "label": item["label"], "prompt": item["prompt"]})
    return variants


def _reply_shape_instruction(post_shape, variant_count):
    shape_map = {
        "technical": "At least one reply should point to an implementation implication, tradeoff, metric, or failure mode.",
        "question": "At least one reply should sharpen or answer the question instead of just reacting.",
        "provocative": "At least one reply may lightly challenge the premise, but do not sound toxic.",
        "short": "Do not over-explain. Keep at least one reply punchy.",
        "general": "Mix forms when possible: observation, implication, question, or light pushback.",
    }
    base = shape_map.get(post_shape, shape_map["general"])
    if variant_count > 1:
        base += " Variants must feel different, not like paraphrases."
    return base


def _reply_length_instruction(comment_length):
    return {
        "short": "Keep each reply short: usually one sentence and 4-10 words.",
        "medium": "Keep each reply compact: one or two short sentences and 8-18 words.",
        "long": "Replies may be 2 short sentences when needed, but still native to X replies.",
        "mix": "Vary length by fit: one punchy reply, one medium reply, one slightly fuller reply when useful.",
    }.get(comment_length, "Keep every reply compact and social-media natural.")


def _emoji_instruction(mode):
    return {
        "none": "Do not use emojis.",
        "moderate": "Use at most one emoji and only if it genuinely helps.",
        "many": "You may use emojis, but keep them sparse.",
        "mix": "Some variants may use an emoji, some should not.",
    }.get(mode, "Use emojis only when they genuinely help.")


def _dash_instruction(style):
    return {"hyphen": "If you use a dash, prefer '-'.", "ndash": "If you use a dash, prefer '–'.", "mdash": "If you use a dash, prefer '—'."}.get(style, "If you use a dash, prefer '–'.")


def _punctuation_instruction(style):
    return {"none": "Avoid final periods unless the sentence feels awkward without one.", "keep": "Use normal sentence punctuation when it feels natural.", "mix": "Vary final punctuation naturally."}.get(style, "Avoid final periods unless the sentence feels awkward without one.")


def _capitalization_instruction(style):
    return {"upper": "Start naturally with uppercase.", "preserve": "Keep capitalization natural to the voice.", "mix": "Mix capitalization naturally if it helps the tone."}.get(style, "Start naturally with uppercase.")


def _classify_post_shape(source_text, context_text=""):
    text = normalize_text(f"{source_text} {context_text}").lower()
    if not text:
        return "general"
    if re.search(r"\b\d+[%xkmb]?\b", text) or any(token in text for token in ("metric", "kpi", "api", "token", "latency", "rollout", "deadline", "retention")):
        return "technical"
    if "?" in source_text or any(token in text for token in ("why", "how", "what if", "should", "worth it")):
        return "question"
    if any(token in text for token in ("hot take", "unpopular", "wrong", "cope", "insane", "wild")):
        return "provocative"
    if len(normalize_text(source_text).split()) <= 14:
        return "short"
    return "general"


def _style_selection_instruction(style_variants, variant_count):
    style_ids = [item["id"] for item in style_variants if item.get("id")]
    if not style_ids:
        return "Choose the best-fitting style id for each reply."
    if len(style_ids) == 1:
        return f"Use [{style_ids[0]}] for every reply."
    if variant_count <= 1:
        return "Choose the single best-fitting style id from the selected pool."
    return "Choose the best-fitting style id from the selected pool for each reply. Do not repeat a style id until you have used as many different selected styles as possible."


def _build_reply_prompt(*, source_text, context_text, defaults, style_variants, variant_count, language):
    target_language = LANGUAGE_LABELS.get(language, "English")
    post_shape = _classify_post_shape(source_text, context_text)
    style_lines = "\n".join(f"- [{item['id']}] {item['label']}: {item.get('prompt') or ''}".rstrip() for item in style_variants) or "- [supportive] Warm, concrete, human"
    hook_lines = "\n".join(f"- {hook}" for hook in _extract_comment_hooks_from_post(source_text, limit=4)) or "- Focus on the main claim, condition, mechanism, or implication."
    numbered_slots = "\n".join(f"{index}. [style_id] <reply>" for index in range(1, variant_count + 1))
    context_section = f"\nThread context:\n{context_text}\n" if context_text else "\n"
    return (
        "You write publication-ready social replies.\n"
        f"Return exactly {variant_count} numbered replies in {target_language}.\n"
        "Each reply must sound like a real person replying in a social feed, not an assistant, moderator, support agent, or brand account.\n"
        "Silently identify the central subject of the post first. Reply to that central subject, not to side details.\n"
        "Strong replies hook into a specific rule, condition, tradeoff, metric, implication, edge case, mechanism, or tension from the post.\n"
        "Avoid empty praise and dead filler like 'great point', 'well said', 'interesting', 'this is huge', or any comment that could fit under almost any post.\n"
        "Do not open with stiff wrappers like 'the real hinge here is', 'this lands because', 'the useful part is', or anything that sounds like prompt scaffolding.\n"
        "Do not just restate the post in slightly shorter words. A good reply should react, sharpen, question, or push the implication forward.\n"
        "Do not use hashtags, @mentions, links, invented facts, or generic internet slang that does not fit the source.\n"
        "Do not sound polished, corporate, explanatory, or like a thread summary. Sound native to social replies.\n"
        f"{_reply_shape_instruction(post_shape, variant_count)}\n"
        f"{_reply_length_instruction(defaults['comment_length'])}\n"
        f"{_emoji_instruction(defaults['emoji_mode'])}\n"
        f"{_dash_instruction(defaults['dash_style'])}\n"
        f"{_punctuation_instruction(defaults['terminal_punctuation'])}\n"
        f"{_capitalization_instruction(defaults['capitalization'])}\n"
        f"{_style_selection_instruction(style_variants, variant_count)}\n"
        "Output only the numbered list, with a valid style id in brackets for every line.\n\n"
        "Selected styles:\n"
        f"{style_lines}\n\n"
        "Best hooks from the source:\n"
        f"{hook_lines}\n"
        f"{context_section}"
        "Source post:\n"
        f"{source_text[:MAX_SOURCE_TEXT_LENGTH]}\n\n"
        "Output format:\n"
        f"{numbered_slots}"
    )


def _build_reply_repair_prompt(*, source_text, context_text, style_variants, variant_count, language, bad_output):
    target_language = LANGUAGE_LABELS.get(language, "English")
    style_lines = "\n".join(f"- [{item['id']}] {item['label']}: {item.get('prompt') or ''}".rstrip() for item in style_variants) or "- [supportive] Warm, concrete, human"
    numbered_slots = "\n".join(f"{index}. [style_id] <reply>" for index in range(1, variant_count + 1))
    context_section = f"\nThread context:\n{context_text}\n" if context_text else "\n"
    return (
        "Rewrite the bad output below into strong social replies.\n"
        f"Return exactly {variant_count} numbered replies in {target_language}.\n"
        "Fix generic filler, broken formatting, garbage symbols, repeated styles, and weak non-specific phrasing.\n"
        "Every reply must stay concrete, tie itself to the source post, and use a valid selected style id in brackets.\n"
        f"{_style_selection_instruction(style_variants, variant_count)}\n\n"
        "Selected styles:\n"
        f"{style_lines}\n"
        f"{context_section}"
        "Source post:\n"
        f"{source_text[:MAX_SOURCE_TEXT_LENGTH]}\n\n"
        "Bad output to repair:\n"
        f"{bad_output}\n\n"
        "Output format:\n"
        f"{numbered_slots}"
    )


def _build_shorten_prompt(*, source_text, language, variant_count, target_length):
    target_language = LANGUAGE_LABELS.get(language, "English")
    source_word_count = len(WORD_RE.findall(normalize_text(source_text)))
    hard_cap_words = max(8, (target_length or 180) // 8)
    desired_min_words = max(12, int(round(source_word_count * 0.50)))
    desired_max_words = max(desired_min_words, int(round(source_word_count * 0.65)))
    min_words = min(hard_cap_words, desired_min_words)
    max_words = min(hard_cap_words, desired_max_words)
    if max_words < min_words:
        min_words = max_words
    numbered_slots = "\n".join(f"{index}. <compressed thought>" for index in range(1, variant_count + 1))
    list_instruction = ""
    if _source_looks_like_multi_item_list(source_text):
        list_instruction = (
            "The source post is a LIST. You MUST keep it as a LIST in your output.\n"
            "Use the exact same bullet markers or numbering style as the source.\n"
            "Each item in your shortened version MUST be on a new line.\n"
            "Do NOT flatten the list into a single paragraph.\n"
            "Keep the multi-item shape and mention more than one item instead of collapsing the rewrite into only the first example.\n"
            "When space allows, keep a short label or descriptor for each major item.\n"
        )
    compression_instruction = (
        "Shorten the post to roughly 50-60% of its original length.\n"
        "The result should be about 2x shorter, not a tiny summary.\n"
        "CRITICAL: Preserve the original formatting, paragraph breaks, and markdown lists (*, -, >) exactly as they appear in the source. Do NOT flatten lists into a single paragraph.\n"
        "Keep the same visual shape as the original post.\n"
        "Keep the main structure and key concrete details.\n"
        "Cut filler, repetition, and weak transitions first.\n"
        "Merge closely related points, but do not erase an entire section of the post."
    )
    return (
        "You are Pigly, an editor of concise crypto and social briefings.\n"
        f"Return exactly {variant_count} numbered options in {target_language}.\n"
        "Mode: shorten.\n"
        "Rewrite the source into a shorter version of the same post.\n"
        "Compress the source material while preserving meaning, structure, and key facts.\n"
        "Keep important numbers, dates, names, handles, projects, and conditions.\n"
        "Do not invent facts or turn speculation into certainty.\n"
        "Work directly with the source material: remove filler, repetition, weak setup, lyrical detours, and empty transitions.\n"
        "Do not rewrite the post into a vague summary, abstract paraphrase, bullet list (unless original was a list), headline, or title-like fragment.\n"
        "Create a shorter rewrite, not a summary and not a new post.\n"
        "Do not just shorten the opening sentence.\n"
        "Read the full post first, then shorten the whole post.\n"
        f"{list_instruction}"
        "Keep the same core flow as the original post.\n"
        "If the source has multiple sections, keep those sections in compressed form instead of dropping everything after the first block.\n"
        "If you keep names, handles, people, projects, or clans, tie them to a short role, action, or outcome.\n"
        "If one side overtakes, beats, passes, or jumps ahead of another, keep that relationship explicitly.\n"
        "Do not remove concrete facts that materially change the meaning.\n"
        "If the ending adds a meaningful opinion, punchline, or personal stance, keep a shorter version of it when possible.\n"
        f"{compression_instruction}\n"
        "Each option should read like a finished compact post, not notes, not a title, and not broken fragments.\n"
        "The result must feel like the same post, just compressed, not like a new post with a different structure.\n"
        "Do not start with wrappers like 'the point is', 'in short', 'overall', or 'this post says'.\n"
        "Do not add facts or interpretations that are not present in the source.\n"
        "When several variants are requested, vary the cut slightly: one more direct, one more neutral, one slightly more punchy.\n"
        f"Aim for roughly {min_words}-{max_words} words per option.\n"
        "FORMATTING PRIORITY:\n"
        "- Always separate logical points and paragraphs with double newlines (\\n\\n).\n"
        "- If the original post has a list, keep it as a list with markers (-, •, 1.).\n"
        "- Do NOT bundle everything into a single wall of text.\n\n"
        "Return only the numbered list, no notes or commentary.\n\n"
        "Source post:\n"
        f"{source_text[:MAX_SOURCE_TEXT_LENGTH]}\n\n"
        "Output format:\n"
        "Return ONLY the numbered list. Use newlines and original bullet points for every list item.\n"
        f"{numbered_slots}"
    )


def _build_shorten_repair_prompt(*, source_text, language, variant_count, target_length, bad_output):
    target_language = LANGUAGE_LABELS.get(language, "English")
    source_word_count = len(WORD_RE.findall(normalize_text(source_text)))
    hard_cap_words = max(8, (target_length or 180) // 8)
    desired_min_words = max(12, int(round(source_word_count * 0.50)))
    desired_max_words = max(desired_min_words, int(round(source_word_count * 0.65)))
    min_words = min(hard_cap_words, desired_min_words)
    max_words = min(hard_cap_words, desired_max_words)
    if max_words < min_words:
        min_words = max_words
    numbered_slots = "\n".join(f"{index}. <compressed thought>" for index in range(1, variant_count + 1))
    return (
        "You are Pigly, repairing a bad shorten output for a crypto/social post.\n"
        f"Return exactly {variant_count} numbered options in {target_language}.\n"
        "The bad output was too summary-like, too fragmentary, too short, or only kept the first part of the source.\n"
        "Rewrite from the original source, not from the bad output.\n"
        "Keep the post as the same post, just shorter.\n"
        "Preserve the main balance and order of the source.\n"
        "If the source has a 'what still needs fixing' section, keep it in compressed form.\n"
        "If the original post was formatted as a list, keep your output formatted as a list with same bullet markers.\n"
        "DO NOT flatten paragraphs. Keep the original line breaks where possible.\n"
        "If the ending adds conviction, belief, or a call to build, keep a shorter version of that too when space allows.\n"
        "Keep important names, handles, projects, numbers, and concrete examples.\n"
        "Do not return a vague summary, note fragment, headline, or handle roll call.\n"
        "Repair it into a proper shortened post, not a tiny blurb.\n"
        "If the original post was formatted as a list, keep your output formatted as a list.\n"
        f"Aim for roughly {min_words}-{max_words} words per option.\n"
        "Return only the numbered list, no notes or commentary.\n\n"
        "Source post:\n"
        f"{source_text[:MAX_SOURCE_TEXT_LENGTH]}\n\n"
        "Bad output to repair:\n"
        f"{bad_output}\n\n"
        "Output format:\n"
        f"{numbered_slots}"
    )


def _parse_numbered_items(text, expected_count):
    items = []
    for chunk in re.split(r'(?=\b\d+[\.\)])', str(text or "").replace("\r", "\n")):
        line = chunk.strip()
        match = re.match(r"^\s*(\d+)[\.\)]\s*(?:\[([^\]]+)\]\s*)?(.*)$", line, re.DOTALL)
        if not match:
            continue
        value = match.group(3).strip()
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        value = value.strip(" -")
        if value:
            items.append(value)
        if len(items) >= expected_count:
            break
    return items


def _extract_single_shorten_candidate(text):
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*\d+[\.\)]\s*", "", cleaned)
    cleaned = re.sub(r"^\s*-\s*", "", cleaned)
    cleaned = re.sub(r"^\s*option\s*\d*\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" -")


def _parse_numbered_reply_items(text, expected_count):
    items = []
    for chunk in re.split(r'(?=\b\d+[\.\)])', str(text or "").replace("\r", "\n")):
        line = chunk.replace("\n", " ").strip()
        match = NUMBERED_ITEM_RE.match(line)
        if not match:
            continue
        value = normalize_text(match.group(3)).strip(" -")
        if value:
            items.append({"style_id": normalize_text(match.group(2) or "").lower(), "content": value})
        if len(items) >= expected_count:
            break
    return items


def _style_label_map(style_variants):
    labels = {str(item.get("id") or "").strip().lower(): item.get("label") or "" for item in style_variants if item.get("id")}
    for style_id, style_data in BUILTIN_STYLE_PROMPTS.items():
        labels.setdefault(style_id, style_data["label"])
    return labels


def _valid_style_ids(style_variants):
    seen = set()
    result = []
    for item in style_variants:
        style_id = str(item.get("id") or "").strip().lower()
        if style_id and style_id not in seen:
            seen.add(style_id)
            result.append(style_id)
    if not result:
        return list(BUILTIN_STYLE_PROMPTS.keys())
    return result


def _cleanup_reply_candidate(text):
    cleaned = normalize_text(text)
    cleaned = re.sub(r"^['\"`]+|['\"`]+$", "", cleaned).strip()
    cleaned = re.sub(r"^(reply|comment|option)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = BROKEN_SYMBOL_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" -")


def _looks_generic_reply(text):
    lowered = normalize_text(text).lower()
    if len(lowered.split()) <= 2:
        return True
    if lowered.startswith(LOW_SIGNAL_COMMENT_PREFIXES):
        return True
    return any(re.match(pattern, lowered) for pattern in GENERIC_REPLY_PATTERNS)


def _strip_hanging_comment_endings(text):
    value = normalize_text(text)
    if not value:
        return value
    words = value.split(" ")
    while len(words) > 3:
        last = re.sub(r"^[^\w]+|[^\w]+$", "", words[-1]).lower()
        if last and last in HANGING_COMMENT_ENDINGS:
            words.pop()
            continue
        break
    return " ".join(words).strip(" ,;:-")


def _trim_to_complete_comment_end(text):
    value = normalize_text(text)
    if not value or re.search(r"[.!?…]$", value):
        return value

    sentence_positions = [match.end() for match in re.finditer(r"[.!?…]", value)]
    if sentence_positions:
        last_sentence_end = sentence_positions[-1]
        if last_sentence_end >= max(24, int(len(value) * 0.45)):
            return value[:last_sentence_end].strip()

    clause_positions = [match.start() for match in re.finditer(r"\s[-–—]\s|[,;:]\s*", value)]
    if clause_positions:
        last_clause_start = clause_positions[-1]
        if last_clause_start >= max(20, int(len(value) * 0.5)):
            return value[:last_clause_start].strip(" ,;:-")

    return value


def _trim_comment_words(text, max_words):
    raw_text = str(text or "").strip()
    words = [word for word in re.split(r"[ \t]+", raw_text) if word]
    if len(words) <= max_words:
        return raw_text
    return " ".join(words[:max_words]).strip(" ,;:-")


def _trim_comment_to_limit(text, max_chars):
    value = str(text or "").strip()
    if not value or len(value) <= max_chars:
        return value
    shortened = value[: max_chars + 1]
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return shortened.strip(" ,;:-")


def _fit_complete_comment(text, *, max_sentences, max_words, max_chars):
    value = normalize_text(text)
    if not value:
        return value

    sentence_parts = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", value) if part.strip()]
    chosen = []
    for sentence in sentence_parts[:max_sentences]:
        raw_candidate = " ".join(chosen + [sentence]).strip()
        raw_word_count = len([word for word in re.split(r"\s+", raw_candidate) if word])
        if raw_candidate and (len(raw_candidate) > max_chars or raw_word_count > max_words):
            break
        chosen.append(sentence)

    if chosen:
        return " ".join(chosen).strip()

    first_sentence_value = sentence_parts[0] if sentence_parts else value
    clauses = [part.strip(" ,;:-") for part in re.split(r"\s[-–—]\s|[,;:]\s*", first_sentence_value) if part.strip(" ,;:-")]
    if len(clauses) > 1 and len(clauses[0].split()) <= 2:
        clauses = clauses[1:]

    fallback_parts = []
    for clause in clauses:
        raw_candidate = " ".join(fallback_parts + [clause]).strip()
        raw_word_count = len([word for word in re.split(r"\s+", raw_candidate) if word])
        if fallback_parts and (len(raw_candidate) > max_chars or raw_word_count > max_words):
            break
        if len(raw_candidate) > max_chars or raw_word_count > max_words:
            trimmed_clause = _trim_comment_to_limit(_trim_comment_words(clause, max_words), max_chars)
            trimmed_clause = _strip_hanging_comment_endings(trimmed_clause)
            if trimmed_clause:
                fallback_parts.append(trimmed_clause)
            break
        fallback_parts.append(clause)

    fallback = " ".join(fallback_parts).strip() or first_sentence_value or value
    fallback = _trim_comment_to_limit(_trim_comment_words(fallback, max_words), max_chars)
    return _strip_hanging_comment_endings(fallback)


def _resolve_comment_length_mode(source_text, requested_mode):
    mode = (requested_mode or "mix").strip().lower()
    if mode in {"short", "medium", "long"}:
        return mode

    text = normalize_text(source_text)
    if not text:
        return "medium"

    char_count = len(text)
    sentence_count = max(1, len([part for part in re.split(r"[.!?…]+", text) if part.strip()]))
    has_question = "?" in text
    comma_count = text.count(",")
    has_list_like = text.count("\n") >= 3 or text.count(":") >= 2 or comma_count >= 4

    if char_count <= 180 and sentence_count <= 2 and not has_question:
        return "short"
    if char_count >= 520 or sentence_count >= 5 or has_list_like:
        return "long"
    if has_question and (char_count >= 140 or sentence_count >= 2):
        return "long"
    return "medium"


def _enforce_comment_length(text, comment_length):
    value = normalize_text(text)
    if not value:
        return value

    mode = (comment_length or "medium").strip().lower()
    if mode == "short":
        compact = _fit_complete_comment(value, max_sentences=1, max_words=10, max_chars=72)
        return _trim_to_complete_comment_end(_strip_hanging_comment_endings(compact))
    if mode == "medium":
        compact = _fit_complete_comment(value, max_sentences=2, max_words=18, max_chars=120)
        return _trim_to_complete_comment_end(_strip_hanging_comment_endings(compact))
    expanded = _fit_complete_comment(value, max_sentences=3, max_words=32, max_chars=220)
    return _trim_to_complete_comment_end(_strip_hanging_comment_endings(expanded))


def _looks_like_tautological_comment(comment_text, source_text):
    comment = normalize_text(comment_text).lower()
    source = normalize_text(source_text).lower()
    if not comment or not source:
        return False
    if any(mark in comment for mark in ("?", "!", "…")):
        return False

    comment_words = WORD_RE.findall(comment)
    if len(comment_words) < 3 or len(comment_words) > 8:
        return False

    source_words = set(WORD_RE.findall(source))
    meaningful = [
        word for word in comment_words
        if len(word) > 2 and word not in {"the", "and", "for", "with", "that", "this", "season", "over", "just", "very", "это", "так", "как", "для", "при", "над", "или", "что", "еще"}
    ]
    if not meaningful:
        return False

    overlap = sum(1 for word in meaningful if word in source_words)
    if overlap < max(2, len(meaningful)):
        return False

    if comment.startswith(("season ", "rewards ", "stats ", "значит ", "сезон ", "статы ", "награды ")):
        return True
    return len(meaningful) <= 4 and overlap == len(meaningful)


def _language_mismatch(text, language):
    cleaned = normalize_text(text)
    if not cleaned:
        return True
    if language == "ru":
        return re.search(r"[А-Яа-яЁё]", cleaned) is None
    if language == "en":
        return re.search(r"[А-Яа-яЁё]", cleaned) is not None
    return False


def _apply_reply_preferences(text, defaults):
    cleaned = normalize_text(text)
    if not cleaned:
        return ""
    if defaults.get("dash_style") == "hyphen":
        cleaned = cleaned.replace("—", "-").replace("–", "-")
    elif defaults.get("dash_style") == "ndash":
        cleaned = cleaned.replace("—", "–").replace(" - ", " – ")
    elif defaults.get("dash_style") == "mdash":
        cleaned = cleaned.replace("–", "—").replace(" - ", " — ")
    if defaults.get("terminal_punctuation") == "none":
        cleaned = cleaned.rstrip(".")
    elif defaults.get("terminal_punctuation") == "keep" and cleaned[-1].isalnum():
        cleaned += "."
    if defaults.get("capitalization") == "upper":
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned.strip()


def _fallback_templates(style_id, hook, alt_hook, language):
    if language == "ru":
        templates = {
            UserProfile.STYLE_SHARP: [f"Вся развилка здесь в том, выдержит ли это {hook.lower()}", f"Тут всё упирается в {hook.lower()}"],
            UserProfile.STYLE_SUPPORTIVE: [f"Самое полезное здесь то, что ты упёрся именно в {hook.lower()}", f"Это хорошо цепляется за {hook.lower()}"],
            UserProfile.STYLE_CURIOUS: [f"А как {hook.lower()} поведёт себя, когда это пойдёт в масштаб?", f"Если всё держится на {hook.lower()}, где здесь первый слабый узел?"],
            UserProfile.STYLE_EXPERT: [f"Ключевой риск здесь в том, что {hook.lower()} быстро станет ограничением", f"Если система держится на {hook.lower()}, проблема вылезет через {alt_hook.lower()}"],
            UserProfile.STYLE_IRONIC: [f"Да, всё обычно выглядит красиво ровно до момента, пока {hook.lower()} не встречается с реальностью", f"Самое смешное, что весь пафос тут всё равно упирается в {hook.lower()}"],
        }
    else:
        templates = {
            UserProfile.STYLE_SHARP: [f"The real hinge here is {hook.lower()}", f"This only works if {hook.lower()} actually holds"],
            UserProfile.STYLE_SUPPORTIVE: [f"The useful part is that you tied this back to {hook.lower()}", f"This lands because it points straight at {hook.lower()}"],
            UserProfile.STYLE_CURIOUS: [f"How does {hook.lower()} hold up once this scales?", f"If this really hinges on {hook.lower()}, where does it break first?"],
            UserProfile.STYLE_EXPERT: [f"The practical implication is that {hook.lower()} becomes the constraint", f"If the system leans on {hook.lower()}, the failure mode probably shows up in {alt_hook.lower()}"],
            UserProfile.STYLE_IRONIC: [f"Yeah, it always sounds clean until {hook.lower()} meets reality", f"The funny part is how fast the whole story collapses back into {hook.lower()}"],
        }
    return templates.get(style_id) or templates[UserProfile.STYLE_SUPPORTIVE]


def _reply_style_rotation(style_variants, variant_count):
    ids = [item["id"] for item in style_variants if item.get("id")]
    if not ids:
        return [UserProfile.STYLE_SUPPORTIVE, UserProfile.STYLE_EXPERT, UserProfile.STYLE_CURIOUS][:variant_count]
    result = []
    while len(result) < variant_count:
        result.append(ids[len(result) % len(ids)])
    return result


def _build_reply_fallback_pool(source_text, context_text, language, style_variants):
    hooks = _extract_comment_hooks_from_post(source_text, limit=4)
    hook = hooks[0] if hooks else first_sentence(source_text)
    alt_hook = hooks[1] if len(hooks) > 1 else hook
    hook = trim_words(normalize_text(hook).strip(" \"'`-:;,.!?"), 10) or ("главный узел" if language == "ru" else "the core point")
    alt_hook = trim_words(normalize_text(alt_hook).strip(" \"'`-:;,.!?"), 10) or hook
    pool = []
    for index, style_id in enumerate(_reply_style_rotation(style_variants, 5)):
        templates = _fallback_templates(style_id, hook, alt_hook, language)
        pool.append((style_id, templates[index % len(templates)]))
    return pool


def _normalize_reply_candidate_item(item, defaults):
    if isinstance(item, dict):
        style_id = normalize_text(item.get("style_id") or "").lower()
        content = item.get("content") or ""
    else:
        style_id = ""
        content = item
    return {"style_id": style_id, "content": _apply_reply_preferences(_cleanup_reply_candidate(content), defaults)}


def _clean_model_reply_candidates(candidates, *, source_text, language, defaults):
    cleaned = []
    seen = set()
    for item in candidates:
        raw_content = item.get("content") or ""
        if BROKEN_SYMBOL_RE.search(raw_content):
            continue
        normalized_item = _normalize_reply_candidate_item(item, defaults)
        length_mode = _resolve_comment_length_mode(raw_content, defaults.get("comment_length"))
        content = _apply_reply_preferences(_enforce_comment_length(normalized_item["content"], length_mode), defaults)
        normalized_item["content"] = content
        key = re.sub(r"[\W_]+", "", content.lower())
        if not content or not key or key in seen:
            continue
        if _looks_generic_reply(content) or _looks_like_tautological_comment(content, source_text) or _language_mismatch(content, language):
            continue
        seen.add(key)
        cleaned.append(normalized_item)
    return cleaned


def _assign_reply_styles(items, style_variants, variant_count):
    valid_ids = _valid_style_ids(style_variants) or _reply_style_rotation(style_variants, max(variant_count, len(items), 1))
    if not valid_ids:
        return items
    distinct_target = min(len(valid_ids), len(items))
    used = set()
    assigned = []
    for index, item in enumerate(items):
        current_style = normalize_text(item.get("style_id") or "").lower()
        if current_style in valid_ids and (current_style not in used or len(used) >= distinct_target):
            assigned_style = current_style
        else:
            assigned_style = next((style_id for style_id in valid_ids if style_id not in used), None) or valid_ids[index % len(valid_ids)]
        assigned.append({"style_id": assigned_style, "content": item.get("content") or ""})
        used.add(assigned_style)
    return assigned


def _finalize_reply_variants(candidates, *, source_text, context_text, language, variant_count, style_variants, defaults):
    finalized = []
    seen = set()
    length_mode = _resolve_comment_length_mode(source_text, defaults.get("comment_length"))
    for item in candidates:
        normalized_item = _normalize_reply_candidate_item(item, defaults)
        cleaned = _enforce_comment_length(normalized_item["content"], length_mode)
        normalized_item["content"] = _apply_reply_preferences(cleaned, defaults)
        cleaned = normalized_item["content"]
        key = re.sub(r"[\W_]+", "", cleaned.lower())
        if not cleaned or not key or key in seen:
            continue
        if (
            _looks_generic_reply(cleaned)
            or _looks_like_tautological_comment(cleaned, source_text)
            or BROKEN_SYMBOL_RE.search(cleaned)
            or _language_mismatch(cleaned, language)
        ):
            continue
        seen.add(key)
        finalized.append(normalized_item)
        if len(finalized) >= variant_count:
            break
    if len(finalized) < variant_count:
        for style_id, fallback in _build_reply_fallback_pool(source_text, context_text, language, style_variants):
            normalized_item = _normalize_reply_candidate_item({"style_id": style_id, "content": fallback}, defaults)
            cleaned = _enforce_comment_length(normalized_item["content"], length_mode)
            normalized_item["content"] = _apply_reply_preferences(cleaned, defaults)
            cleaned = normalized_item["content"]
            key = re.sub(r"[\W_]+", "", cleaned.lower())
            if cleaned and key and key not in seen:
                seen.add(key)
                finalized.append(normalized_item)
            if len(finalized) >= variant_count:
                break
    return _assign_reply_styles(finalized[:variant_count], style_variants, variant_count)


def _fallback_reply_variants(source_text, context_text, language, variant_count, style_variants=None, defaults=None):
    fallback_pool = [{"style_id": style_id, "content": text} for style_id, text in _build_reply_fallback_pool(source_text, context_text, language, style_variants or [])]
    return _finalize_reply_variants(
        fallback_pool,
        source_text=source_text,
        context_text=context_text,
        language=language,
        variant_count=variant_count,
        style_variants=style_variants or [],
        defaults=defaults or {},
    )


def _fallback_shorten_variants(source_text, variant_count, target_length):
    base = normalize_text(source_text)
    if not base:
        return []
    list_variants = _fallback_multi_item_shorten_variants_generic(source_text, variant_count, target_length)
    if list_variants:
        return list_variants[:variant_count]
    target_words = max(8, (target_length or 180) // 8)
    variants = [trim_words(base, target_words), first_sentence(base) or trim_words(base, max(8, target_words - 4)), trim_words(base, max(7, target_words - 8))]
    while len(variants) < variant_count:
        variants.append(trim_words(base, max(6, target_words - 10 - len(variants))))
    return variants[:variant_count]


def _normalize_shorten_candidate(text, target_length):
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"^(summary|option|rewrite)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(in short|overall|the point is|this post says)\s*,?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = BROKEN_SYMBOL_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip(" -")
    # Soft limits to prevent catastrophic outputs, trusting the prompt mostly
    max_chars = max(400, int(target_length or 180) * 2)
    max_words = max(80, max_chars // 6)
    cleaned = _trim_comment_to_limit(_trim_comment_words(cleaned, max_words), max_chars)
    cleaned = _trim_to_complete_comment_end(_strip_hanging_comment_endings(cleaned))
    if cleaned.endswith("..."):
        cleaned = cleaned.rstrip(". ").rstrip(" ,;:-")
    return cleaned


def _contains_any_phrase(text, phrases):
    return any(phrase in text for phrase in phrases)


def _extract_named_list_markers(text):
    source_text = str(text or "")
    handles = re.findall(r"(?<!\w)@[A-Za-z0-9_]{2,32}", source_text)
    leading_numbers = re.findall(r"(?:^|\n|\s)(?:\d+[.)]|[1-9]\ufe0f?\u20e3)", source_text)
    dash_items = re.findall(r"(?:—|-|\*|•|>)\s*([A-Za-z][^.\n:]{2,40})", source_text)
    markers = [normalize_text(item).lower() for item in handles + dash_items]
    return markers, len(leading_numbers)


def _source_looks_like_multi_item_list(text):
    markers, number_count = _extract_named_list_markers(text)
    return len(set(markers)) >= 2 or number_count >= 2


def _extract_list_handle_items(text):
    items = []
    for raw_line in re.split(r"\n+", str(text or "")):
        line = normalize_text(raw_line)
        if not line:
            continue
        handle_match = re.search(r"(?<!\w)(@[A-Za-z0-9_]{2,32})", line)
        if not handle_match:
            continue
        handle = handle_match.group(1)
        project_match = re.search(r"(?:—|-)\s*([^:.\n]{2,50})", line)
        project = normalize_text(project_match.group(1)) if project_match else ""
        items.append({"handle": handle, "project": project})
    deduped = []
    seen = set()
    for item in items:
        key = (item["handle"].lower(), item["project"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _fallback_multi_item_shorten_variants(source_text, variant_count, target_length):
    items = _extract_list_handle_items(source_text)
    if len(items) < 2:
        return []

    max_chars = max(70, int(target_length or 180))
    title = ""
    for raw_line in re.split(r"\n+", str(source_text or "")):
        line = normalize_text(raw_line)
        if line and "@" not in line and len(line.split()) <= 8 and not re.match(r"^\d", line):
            title = line
            break

    handles = [item["handle"] for item in items[:3]]
    projects = [f"{item['handle']} ({item['project']})" if item["project"] else item["handle"] for item in items[:3]]

    variants = []
    if title:
        variants.append(f"{title}: {', '.join(handles[:-1])}, and {handles[-1]} are making moves on Abstract this week." if len(handles) >= 3 else f"{title}: {' and '.join(handles)} are making moves on Abstract this week.")
    variants.append(f"{', '.join(handles[:-1])}, and {handles[-1]} are featured in this week’s Abstract builder spotlight." if len(handles) >= 3 else f"{' and '.join(handles)} are featured in this week’s Abstract builder spotlight.")
    variants.append(f"Abstract builder spotlight: {'; '.join(projects[:2])}{'; ' + projects[2] if len(projects) >= 3 else ''}.")

    cleaned = []
    seen = set()
    for variant in variants:
        normalized = _normalize_shorten_candidate(variant, max_chars)
        key = re.sub(r"[\W_]+", "", normalized.lower())
        if not normalized or key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
        if len(cleaned) >= variant_count:
            break
    return cleaned





def _fallback_multi_item_shorten_variants_generic(source_text, variant_count, target_length):
    items = _extract_list_handle_items(source_text)
    if len(items) < 2:
        return []

    max_chars = max(70, int(target_length or 180))
    title = ""
    context_line = ""
    for raw_line in re.split(r"\n+", str(source_text or "")):
        line = normalize_text(raw_line)
        if line and "@" not in line and len(line.split()) <= 8 and not re.match(r"^\d", line):
            if not title:
                title = line
                continue
        if not context_line and line and "@" not in line and not re.match(r"^\d", line) and len(line.split()) >= 4:
            context_line = line.rstrip(":")
        if title and context_line:
            break

    handles = [item["handle"] for item in items[:3]]
    projects = [f"{item['handle']} ({item['project']})" if item["project"] else item["handle"] for item in items[:3]]
    handle_line = f"{', '.join(handles[:-1])}, and {handles[-1]}" if len(handles) >= 3 else " and ".join(handles)
    context_phrase = re.sub(r"\s+", " ", (context_line or "this roundup")).strip(" .:")

    variants = []
    if title:
        variants.append(f"{title}: {'; '.join(projects[:2])}{'; ' + projects[2] if len(projects) >= 3 else ''}.")
        variants.append(f"{title}: {handle_line}.")
    variants.append(f"{context_phrase}: {'; '.join(projects[:2])}{'; ' + projects[2] if len(projects) >= 3 else ''}.")
    variants.append(f"{handle_line} stand out in {context_phrase.lower()}.")

    cleaned = []
    seen = set()
    for variant in variants:
        normalized = _normalize_shorten_candidate(variant, max_chars)
        key = re.sub(r"[\W_]+", "", normalized.lower())
        if not normalized or key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
        if len(cleaned) >= variant_count:
            break
    return cleaned


def _extract_list_handle_items(text):
    items = []
    current = None
    number_only_re = re.compile(r"^(?:\d+[.)]?|[1-9]\ufe0f?\u20e3)$")

    for raw_line in str(text or "").splitlines():
        line = normalize_text(raw_line)
        if not line:
            continue
        if number_only_re.match(line):
            if current and current.get("handle"):
                items.append(current)
            current = None
            continue

        handle_match = re.search(r"(?<!\w)(@[A-Za-z0-9_]{2,32})", line)
        if handle_match:
            if current and current.get("handle"):
                items.append(current)
            current = {"handle": handle_match.group(1), "buffer": line}
            continue

        if current and current.get("handle"):
            current["buffer"] = f"{current['buffer']} {line}".strip()

    if current and current.get("handle"):
        items.append(current)

    deduped = []
    seen = set()
    for item in items:
        buffer_text = normalize_text(item.get("buffer") or item["handle"])
        project_match = re.search(r"(?:—|-|вЂ”)\s*([^:.\n]{2,50})(?::\s*([^.\n]{8,180}))?", buffer_text)
        project = normalize_text(project_match.group(1)) if project_match else ""
        summary = normalize_text(project_match.group(2)) if project_match and project_match.lastindex and project_match.group(2) else ""
        normalized_item = {"handle": item["handle"], "project": project, "summary": summary}
        key = (normalized_item["handle"].lower(), normalized_item["project"].lower(), normalized_item["summary"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized_item)
    return deduped


def _format_shorten_list_item(item):
    handle = item.get("handle") or ""
    project = item.get("project") or ""
    summary = trim_words(item.get("summary") or "", 5).rstrip(".")
    if handle and project and summary:
        return f"{handle} — {project}: {summary}"
    if handle and project:
        return f"{handle} — {project}"
    return handle or project or ""


def _fallback_multi_item_shorten_variants_generic(source_text, variant_count, target_length):
    items = _extract_list_handle_items(source_text)
    if len(items) < 2:
        return []

    max_chars = max(180, int(target_length or 240))
    title = ""
    context_line = ""
    for raw_line in re.split(r"\n+", str(source_text or "")):
        line = normalize_text(raw_line)
        if line and "@" not in line and len(line.split()) <= 8 and not re.match(r"^\d", line):
            if not title:
                title = line
                continue
        if not context_line and line and "@" not in line and not re.match(r"^\d", line) and len(line.split()) >= 4:
            context_line = line.rstrip(":")
        if title and context_line:
            break

    labels = [_format_shorten_list_item(item) for item in items[:3]]
    labels = [label for label in labels if label]
    handles = [item["handle"] for item in items[:3] if item.get("handle")]
    handle_line = f"{', '.join(handles[:-1])}, and {handles[-1]}" if len(handles) >= 3 else " and ".join(handles)
    context_phrase = re.sub(r"\s+", " ", (context_line or "this roundup")).strip(" .:")

    variants = []
    if title and labels:
        variants.append(f"{title}: {'; '.join(labels)}.")
    if context_phrase and labels:
        variants.append(f"{context_phrase}: {'; '.join(labels)}.")
    if title and handle_line:
        variants.append(f"{title}: {handle_line}.")
    if handle_line:
        variants.append(f"{handle_line} stand out in {context_phrase.lower()}.")

    cleaned = []
    seen = set()
    for variant in variants:
        normalized = _normalize_shorten_candidate(variant, max_chars)
        key = re.sub(r"[\W_]+", "", normalized.lower())
        if not normalized or key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
        if len(cleaned) >= variant_count:
            break
    return cleaned


def _extract_list_handle_items(text):
    items = []
    current = None
    number_only_re = re.compile(r"^(?:\d+[.)]?|[1-9]\ufe0f?\u20e3)$")

    for raw_line in str(text or "").splitlines():
        line = normalize_text(raw_line)
        if not line:
            continue
        if number_only_re.match(line):
            if current and current.get("handle"):
                items.append(current)
            current = None
            continue

        handle_match = re.search(r"(?<!\w)(@[A-Za-z0-9_]{2,32})", line)
        if handle_match:
            if current and current.get("handle"):
                items.append(current)
            current = {"handle": handle_match.group(1), "buffer": line}
            continue

        if current and current.get("handle"):
            current["buffer"] = f"{current['buffer']} {line}".strip()

    if current and current.get("handle"):
        items.append(current)

    deduped = []
    seen = set()
    for item in items:
        buffer_text = normalize_text(item.get("buffer") or item["handle"])
        project_match = re.search(r"(?:—|-|вЂ”)\s*([^:.\n]{2,50})(?::\s*([^.\n]{8,180}))?", buffer_text)
        project = normalize_text(project_match.group(1)) if project_match else ""
        summary = normalize_text(project_match.group(2)) if project_match and project_match.lastindex and project_match.group(2) else ""
        normalized_item = {"handle": item["handle"], "project": project, "summary": summary}
        key = (normalized_item["handle"].lower(), normalized_item["project"].lower(), normalized_item["summary"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized_item)
    return deduped


def _format_shorten_list_item(item):
    handle = item.get("handle") or ""
    project = item.get("project") or ""
    summary = trim_words(item.get("summary") or "", 9).rstrip(".")
    if handle and project and summary:
        return f"{handle} — {project}: {summary}"
    if handle and project:
        return f"{handle} — {project}"
    return handle or project or ""


def _fallback_multi_item_shorten_variants_generic(source_text, variant_count, target_length):
    items = _extract_list_handle_items(source_text)
    if len(items) < 2:
        return []

    descriptive_items = [item for item in items if item.get("project") or item.get("summary")]
    if len(descriptive_items) < 2:
        return []

    max_chars = max(200, int(target_length or 240))
    title = ""
    context_line = ""
    for raw_line in re.split(r"\n+", str(source_text or "")):
        line = normalize_text(raw_line)
        if line and "@" not in line and len(line.split()) <= 8 and not re.match(r"^\d", line):
            if not title:
                title = line
                continue
        if not context_line and line and "@" not in line and not re.match(r"^\d", line) and len(line.split()) >= 4:
            context_line = line.rstrip(":")
        if title and context_line:
            break

    labels = [_format_shorten_list_item(item) for item in items[:3]]
    labels = [label for label in labels if label]
    handles = [item["handle"] for item in items[:3] if item.get("handle")]
    handle_line = f"{', '.join(handles[:-1])}, and {handles[-1]}" if len(handles) >= 3 else " and ".join(handles)
    context_phrase = re.sub(r"\s+", " ", (context_line or "this roundup")).strip(" .:")

    variants = []
    if title and labels:
        variants.append(f"{title}: {'; '.join(labels)}.")
    if context_phrase and labels:
        variants.append(f"{context_phrase}: {'; '.join(labels)}.")
    if title and handle_line:
        variants.append(f"{title}: {handle_line}.")
    if handle_line:
        variants.append(f"{handle_line} stand out in {context_phrase.lower()}.")

    cleaned = []
    seen = set()
    for variant in variants:
        normalized = _normalize_shorten_candidate(variant, max_chars)
        key = re.sub(r"[\W_]+", "", normalized.lower())
        if not normalized or key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
        if len(cleaned) >= variant_count:
            break
    return cleaned


def _drops_required_shorten_signals(candidate_text, source_text):
    candidate = normalize_text(candidate_text).lower()
    source = normalize_text(source_text).lower()
    if not candidate or not source:
        return False

    source_amounts = {normalize_text(item).lower() for item in SHORTEN_AMOUNT_RE.findall(source_text or "")}
    if source_amounts and not any(amount in candidate for amount in source_amounts):
        return True

    source_cashtags = {item.lower() for item in SHORTEN_CASHTAG_RE.findall(source_text or "")}
    candidate_cashtags = {item.lower() for item in SHORTEN_CASHTAG_RE.findall(candidate_text or "")}
    if source_cashtags and not source_cashtags.intersection(candidate_cashtags):
        return True

    early_phrases = (
        "ahead of schedule",
        "went out early",
        "distributed early",
        "earlier than expected",
        "earlier than planned",
        "ahead of plan",
    )
    partial_phrases = (
        "not a full month",
        "doesn’t reflect a full month",
        "doesn't reflect a full month",
        "does not reflect a full month",
        "full month of rewards",
        "partial month",
        "so far",
    )
    ongoing_phrases = (
        "still many months",
        "still more",
        "still months",
        "left to be distributed",
        "left to distribute",
        "more rewards still",
        "more to come",
        "still to come",
        "remaining to be distributed",
    )
    ranking_phrases = (
        "overtook",
        "overtake",
        "passed",
        "surpassed",
        "beat",
        "jumped ahead",
        "moved ahead",
        "rankings",
        "ranking",
        "leaderboard",
        "leaderboards",
    )
    if _contains_any_phrase(source, early_phrases) and not _contains_any_phrase(candidate, early_phrases):
        return True
    if _contains_any_phrase(source, partial_phrases) and not _contains_any_phrase(candidate, partial_phrases):
        return True
    if _contains_any_phrase(source, ongoing_phrases) and not _contains_any_phrase(candidate, ongoing_phrases):
        return True
    if _contains_any_phrase(source, ranking_phrases) and not _contains_any_phrase(candidate, ranking_phrases):
        return True

    source_markers, source_number_count = _extract_named_list_markers(source_text)
    strict_markers = [m for m in source_markers if len(m) <= 16 or m.startswith("@")]
    if len(set(strict_markers)) >= 2:
        candidate_marker_hits = sum(1 for marker in set(strict_markers) if marker and marker in candidate)
        if candidate_marker_hits < 2:
            return True
    elif source_number_count >= 2 and len(candidate.split()) < max(10, len(source.split()) // 6):
        return True

    return False


def _drops_multi_section_balance(candidate_text, source_text):
    candidate = normalize_text(candidate_text).lower()
    source = normalize_text(source_text).lower()
    if not candidate or not source:
        return False

    action_needed_phrases = (
        "things we still need",
        "what still needs",
        "still need to",
        "stop pushing",
        "not the way",
        "bring more",
        "bring back",
        "hire professional",
    )
    conviction_phrases = (
        "still a massive believer",
        "still bullish",
        "massive believer",
        "believer in",
        "let's build",
        "lets build",
        "thriving ecosystem",
        "who's with me",
        "whos with me",
    )
    candidate_action_markers = (
        "still need",
        "needs fixing",
        "still work to do",
        "work to do",
        "stop",
        "bring",
        "hire",
    )
    candidate_conviction_markers = (
        "still bullish",
        "still a believer",
        "believer",
        "bullish",
        "let's build",
        "lets build",
        "real usage",
        "ecosystem",
    )

    source_has_action_section = _contains_any_phrase(source, action_needed_phrases)
    source_has_conviction_close = _contains_any_phrase(source, conviction_phrases)
    if source_has_action_section and not _contains_any_phrase(candidate, candidate_action_markers):
        return True
    if source_has_action_section and source_has_conviction_close and not _contains_any_phrase(candidate, candidate_conviction_markers):
        return True
    return False


def _is_overcompressed_shorten(candidate_text, source_text):
    source_words = WORD_RE.findall(normalize_text(source_text))
    candidate_words = WORD_RE.findall(normalize_text(candidate_text))
    minimum_words = max(10, int(round(len(source_words) * 0.20)))
    return len(candidate_words) < minimum_words


def _looks_like_weak_shorten(text, source_text):
    cleaned = normalize_text(text).lower()
    if not cleaned or len(cleaned.split()) < 4:
        return True
    if cleaned.startswith(("the point is", "in short", "overall", "this post says")):
        return True
    handles = re.findall(r"(?<!\w)@[A-Za-z0-9_]{2,32}", text or "")
    if len(handles) >= 3:
        without_handles = re.sub(r"(?<!\w)@[A-Za-z0-9_]{2,32}", " ", text or "")
        support_words = re.findall(r"[A-Za-z][A-Za-z'#-]{2,}", normalize_text(without_handles))
        if len(support_words) < 5:
            return True
    source = normalize_text(source_text).lower()
    if cleaned == source:
        return True
    if _drops_required_shorten_signals(text, source_text):
        return True
    if _drops_multi_section_balance(text, source_text):
        return True
    if _is_overcompressed_shorten(text, source_text):
        return True
    return False


def _clean_shorten_candidates(candidates, source_text, target_length, variant_count):
    cleaned_items = []
    seen = set()
    for item in candidates:
        cleaned = _normalize_shorten_candidate(item, target_length)
        key = re.sub(r"[\W_]+", "", cleaned.lower())
        if not cleaned or not key or key in seen:
            continue
        if _looks_like_weak_shorten(cleaned, source_text):
            continue
        seen.add(key)
        cleaned_items.append(cleaned)
        if len(cleaned_items) >= variant_count:
            break
    return cleaned_items


def _looks_like_hard_reject_shorten(text, source_text):
    cleaned = normalize_text(text).lower()
    if not cleaned or len(cleaned.split()) < 4:
        return True
    if cleaned.startswith(("the point is", "in short", "overall", "this post says")):
        return True
    handles = re.findall(r"(?<!\w)@[A-Za-z0-9_]{2,32}", text or "")
    if len(handles) >= 2 and ";" in (text or ""):
        return True
    if _drops_required_shorten_signals(text, source_text):
        return True
    return False


def _salvage_single_shorten_candidate(raw_text, source_text, target_length):
    candidate = _normalize_shorten_candidate(_extract_single_shorten_candidate(raw_text), target_length)
    if not candidate:
        return []
    if _looks_like_hard_reject_shorten(candidate, source_text):
        return []
    return [candidate]


def _generate_reply_variants(*, source_text, context_text, defaults, style_variants, variant_count):
    raw = _call_gemini_text(
        prompt=_build_reply_prompt(source_text=source_text, context_text=context_text, defaults=defaults, style_variants=style_variants, variant_count=variant_count, language=defaults["language"]),
        max_output_tokens=1100,
        temperature=0.6,
        top_p=0.9,
    )
    if raw:
        parsed = _parse_numbered_reply_items(raw, variant_count + 3)
        filtered = _clean_model_reply_candidates(parsed, source_text=source_text, language=defaults["language"], defaults=defaults)
        if len(filtered) >= variant_count:
            return _assign_reply_styles(filtered[:variant_count], style_variants, variant_count), "gemini"

        repaired_raw = _call_gemini_text(
            prompt=_build_reply_repair_prompt(source_text=source_text, context_text=context_text, style_variants=style_variants, variant_count=variant_count, language=defaults["language"], bad_output=raw),
            max_output_tokens=1000,
            temperature=0.45,
            top_p=0.85,
        )
        if repaired_raw:
            repaired_parsed = _parse_numbered_reply_items(repaired_raw, variant_count + 3)
            repaired = _clean_model_reply_candidates(repaired_parsed, source_text=source_text, language=defaults["language"], defaults=defaults)
            if len(repaired) >= variant_count:
                return _assign_reply_styles(repaired[:variant_count], style_variants, variant_count), "gemini"
    raise GeminiGenerationError(
        "Gemini reply generation returned unusable content.",
        code="invalid_gemini_output",
        extra={"kind": "reply"},
    )


def _generate_shorten_variants(*, source_text, language, tone, variant_count, target_length):
    raw = _call_gemini_text(
        prompt=_build_shorten_prompt(source_text=source_text, language=language, variant_count=variant_count, target_length=target_length),
        max_output_tokens=600,
        temperature=0.4,
        top_p=0.8,
    )
    if raw:
        if variant_count == 1:
            single_candidate = _extract_single_shorten_candidate(raw)
            if single_candidate:
                single_norm = _normalize_shorten_candidate(single_candidate, target_length)
                if single_norm and not _looks_like_hard_reject_shorten(single_norm, source_text):
                    return [single_norm], "gemini"
        parsed = _parse_numbered_items(raw, variant_count + 2)
        if not parsed and variant_count == 1:
            single_candidate = _extract_single_shorten_candidate(raw)
            if single_candidate:
                parsed = [single_candidate]
        cleaned = _clean_shorten_candidates(parsed, source_text, target_length, variant_count)
        if len(cleaned) >= variant_count:
            return cleaned[:variant_count], "gemini"
        if variant_count == 1:
            salvaged = _salvage_single_shorten_candidate(raw, source_text, target_length)
            if salvaged:
                return salvaged, "gemini"
        repaired_raw = _call_gemini_text(
            prompt=_build_shorten_repair_prompt(
                source_text=source_text,
                language=language,
                variant_count=variant_count,
                target_length=target_length,
                bad_output=raw,
            ),
            max_output_tokens=420,
            temperature=0.2,
            top_p=0.7,
        )
        if repaired_raw:
            repaired_parsed = _parse_numbered_items(repaired_raw, variant_count + 2)
            if not repaired_parsed and variant_count == 1:
                repaired_single_candidate = _extract_single_shorten_candidate(repaired_raw)
                if repaired_single_candidate:
                    repaired_parsed = [repaired_single_candidate]
            repaired = _clean_shorten_candidates(repaired_parsed, source_text, target_length, variant_count)
            if len(repaired) >= variant_count:
                return repaired[:variant_count], "gemini"
            if variant_count == 1:
                salvaged_repaired = _salvage_single_shorten_candidate(repaired_raw, source_text, target_length)
                if salvaged_repaired:
                    return salvaged_repaired, "gemini"
    raise GeminiGenerationError(
        "Gemini shorten generation returned unusable content.",
        code="invalid_gemini_output",
        extra={"kind": "shorten"},
    )


def create_generation_record(*, user, kind, source_text, tone, request_data, results):
    generation_request = GenerationRequest.objects.create(user=user, kind=kind, source_text=source_text, tone=tone, request_data=request_data)
    GenerationResult.objects.bulk_create([GenerationResult(request=generation_request, content=content, position=index) for index, content in enumerate(results, start=1)])
    generation_request.refresh_from_db()
    return generation_request


def build_shorten_generation(*, source_text, tone=None, language=None, variant_count=1, target_length=None, profile=None):
    variant_count = coerce_int(variant_count, default=1, minimum=1, maximum=3)
    target_length = target_length if target_length is None else coerce_int(target_length, default=220, minimum=80, maximum=420)
    defaults = _coerce_profile_defaults(profile, source_text, "", tone, language, variant_count)
    results, engine = _generate_shorten_variants(source_text=source_text, language=defaults["language"], tone=defaults["tone"], variant_count=variant_count, target_length=target_length or 180)
    request_data = _build_request_data(source_text=source_text, tone=defaults["tone"], language=defaults["language"], variant_count=variant_count, target_length=target_length, engine=engine, generation_mode=DEFAULT_SHORTEN_MODE)
    return request_data, results


def build_reply_generation(*, source_text, context_text="", tone=None, language=None, variant_count=3, profile=None):
    variant_count = coerce_int(variant_count, default=3, minimum=1, maximum=3)
    defaults = _coerce_profile_defaults(profile, source_text, context_text, tone, language, variant_count)
    style_variants = _style_variants_for_profile(profile)
    results, engine = _generate_reply_variants(source_text=source_text, context_text=context_text, defaults=defaults, style_variants=style_variants, variant_count=variant_count)
    style_labels = _style_label_map(style_variants)
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
    request_data["result_styles"] = [
        {"position": index, "style_id": item.get("style_id") or "", "style_label": style_labels.get(item.get("style_id") or "", (item.get("style_id") or "").replace("-", " ").title())}
        for index, item in enumerate(results, start=1)
    ]
    return request_data, [item["content"] for item in results]
