from .models import GenerationRequest, GenerationResult


def serialize_generation_result(result: GenerationResult) -> dict:
    return {
        "id": result.id,
        "position": result.position,
        "content": result.content,
    }


def serialize_generation_request(item: GenerationRequest, include_results: bool = True) -> dict:
    payload = {
        "id": item.id,
        "kind": item.kind,
        "kind_label": item.get_kind_display(),
        "tone": item.tone,
        "source_text": item.source_text,
        "request_data": item.request_data,
        "created_at": item.created_at.isoformat(),
    }
    if include_results:
        payload["results"] = [serialize_generation_result(result) for result in item.results.all()]
    return payload
