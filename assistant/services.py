from history.models import GenerationRequest, GenerationResult

from .utils import coerce_int, first_sentence, normalize_language, normalize_text, normalize_tone, trim_words


def _build_request_data(*, source_text, tone, language, variant_count, context_text="", target_length=None):
    data = {
        "source_text": source_text,
        "tone": tone,
        "language": language,
        "variant_count": variant_count,
    }
    if context_text:
        data["context_text"] = context_text
    if target_length is not None:
        data["target_length"] = target_length
    return data


def _generate_shorten_variants(source_text, language, tone, variant_count, target_length):
    base = normalize_text(source_text)
    if not base:
        return []

    target_words = max(8, target_length // 8) if target_length else 24
    shorter_words = max(6, target_words - 4)
    shortest_words = max(5, target_words - 8)

    lead = first_sentence(base)
    variants = [
        lead or trim_words(base, target_words),
        trim_words(base, shorter_words),
        trim_words(base, shortest_words),
    ]

    if language == "ru" and tone == "concise":
        variants = [
            trim_words(base, max(8, target_words - 2)),
            trim_words(base, max(6, shorter_words - 2)),
            trim_words(base, max(5, shortest_words - 2)),
        ]
    elif tone == "confident":
        variants = [
            lead or trim_words(base, target_words),
            trim_words(base, shorter_words) + " Для X/Twitter это звучит сильнее.",
            trim_words(base, shortest_words) + " Четко и без лишнего шума.",
        ]

    while len(variants) < variant_count:
        variants.append(trim_words(base, max(5, shortest_words - len(variants))))
    return variants[:variant_count]


def _reply_templates(language, tone):
    if language == "ru":
        if tone == "confident":
            return [
                "Да, это в точку. {summary}",
                "Согласен. {summary} и это хорошо держит фокус.",
                "Верно. {summary} - сильная формулировка.",
            ]
        if tone == "concise":
            return [
                "Согласен. {summary}",
                "Да, именно так. {summary}",
                "Точно. {summary}",
            ]
        if tone == "neutral":
            return [
                "Хорошая мысль. {summary}",
                "Понятно и по делу. {summary}",
                "Да, это звучит логично. {summary}",
            ]
        return [
            "Согласен, {summary}",
            "Хорошая мысль. {summary}",
            "Да, это действительно в точку. {summary}",
        ]

    if tone == "confident":
        return [
            "Absolutely. {summary}",
            "Exactly. {summary} keeps the point sharp.",
            "That's right. {summary} is a strong angle.",
        ]
    if tone == "concise":
        return [
            "Agreed. {summary}",
            "Yep. {summary}",
            "Right on. {summary}",
        ]
    if tone == "neutral":
        return [
            "Good point. {summary}",
            "Makes sense. {summary}",
            "That sounds reasonable. {summary}",
        ]
    return [
        "Totally agree. {summary}",
        "Good take. {summary}",
        "Yep, that makes sense. {summary}",
    ]


def _generate_reply_variants(source_text, context_text, language, tone, variant_count):
    base = normalize_text(context_text or source_text)
    summary = first_sentence(base) or trim_words(base, 18)
    summary = trim_words(summary, 18)
    if not summary:
        summary = "this"

    templates = _reply_templates(language, tone)
    variants = []
    for template in templates[:variant_count]:
        variants.append(template.format(summary=summary))

    while len(variants) < variant_count:
        variants.append(templates[len(variants) % len(templates)].format(summary=summary))
    return variants[:variant_count]


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


def build_shorten_generation(*, source_text, tone=None, language=None, variant_count=3, target_length=None):
    tone = normalize_tone(tone)
    language = normalize_language(language, source_text)
    variant_count = coerce_int(variant_count, default=3, minimum=1, maximum=5)
    target_length = target_length if target_length is None else coerce_int(target_length, default=180, minimum=40, maximum=280)
    request_data = _build_request_data(
        source_text=source_text,
        tone=tone,
        language=language,
        variant_count=variant_count,
        target_length=target_length,
    )
    results = _generate_shorten_variants(source_text, language, tone, variant_count, target_length or 180)
    return request_data, results


def build_reply_generation(*, source_text, context_text="", tone=None, language=None, variant_count=3):
    tone = normalize_tone(tone)
    language = normalize_language(language, source_text or context_text)
    variant_count = coerce_int(variant_count, default=3, minimum=1, maximum=5)
    request_data = _build_request_data(
        source_text=source_text,
        tone=tone,
        language=language,
        variant_count=variant_count,
        context_text=context_text,
    )
    results = _generate_reply_variants(source_text, context_text, language, tone, variant_count)
    return request_data, results
