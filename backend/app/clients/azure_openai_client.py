import json
import logging

from openai import AzureOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# Without a limit a stalled call can hold a request or a worker round for ten minutes (the library's default).
TIMEOUT_SECONDS = 60

# With TEST_AI_STUB (automated tests only; config.py refuses it unless the database is a *_test one) no real client is made at all.
_client = None if settings.TEST_AI_STUB else AzureOpenAI(
    api_key=settings.AZURE_OPENAI_API_KEY,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_version=settings.AZURE_OPENAI_API_VERSION,
    timeout=TIMEOUT_SECONDS,
    max_retries=2,  # the library retries rate limits and dropped connections itself
)


def _user_message(user_prompt: str, images: list[str] | None) -> object:
    """Plain text, or text plus page pictures (base64 JPEG) for a scanned document."""
    if not images:
        return user_prompt
    parts: list[dict] = [{"type": "text", "text": user_prompt or "Read the attached document."}]
    parts += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "high"}} for image in images]
    return parts


def ask_json(system_prompt: str, user_prompt: str, temperature: float = 0.1, images: list[str] | None = None) -> dict:
    """Send a prompt and force a JSON object back. Every agent's LLM call goes through this. `images` are page pictures
    (base64 JPEG) of a scanned document, shown to the model alongside the text."""
    if settings.TEST_AI_STUB:
        from app.clients import ai_stub
        return ai_stub.ask_json(system_prompt, user_prompt, temperature, images=images)
    last: Exception | None = None
    for attempt in (1, 2):  # the model now and then returns an empty or cut-off answer: ask once more before giving up
        response = _client.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _user_message(user_prompt, images)},
            ],
        )
        try:
            data = json.loads(response.choices[0].message.content or "")
            if isinstance(data, dict):
                return data
            raise ValueError("the AI answered with something other than a JSON object")
        except (ValueError, TypeError, IndexError) as exc:
            last = exc
            logger.warning("The AI gave an unusable answer (try %d of 2): %s", attempt, exc)
    raise ValueError(f"The AI did not return a usable answer: {last}")


def ask_text(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
    """Send a prompt and get plain text back (for summaries/explanations, not structured data)."""
    if settings.TEST_AI_STUB:
        from app.clients import ai_stub
        return ai_stub.ask_text(system_prompt, user_prompt, temperature)
    response = _client.chat.completions.create(
        model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content
