"""The LLM gateway: the ONLY module permitted to contact a model provider.

CLAUDE.md invariants 4 and 5, docs/architecture.md §3.4. One public entry point,
Gateway.run(), which for every call:

1. loads the task's route (model, prompt version) from config/models.yaml;
2. loads the versioned prompt file and refuses it if it was edited after running;
3. scrubs identity data from the caller's inputs, renders the prompt, and runs
   the tripwire over exactly what is about to leave;
4. returns a cached, previously validated answer when the same prompt version,
   model, schema and scrubbed input have been seen before;
5. otherwise calls the provider and validates the reply against the caller's
   Pydantic model -- invalid means one retry with the errors appended, then a
   review queue item and InvalidModelOutput. There is no fallback that guesses.

Every attempt, including cache hits and failures, writes a model_call row, and
every provider call stores exactly what was sent in model_call_payload.

Audit rows and review items are written in the gateway's own transaction, not
the caller's: if the caller rolls back after InvalidModelOutput, the record of
the failure must survive.
"""

import hashlib
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import anthropic
import yaml
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.prompts import Prompt, load_prompt
from app.ai.scrub import Scrubber
from app.models import ModelCall, ModelCallPayload, PromptVersion, ReviewQueueItem
from app.models.enums import ReviewKind

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROUTING = ROOT / "config" / "models.yaml"
DEFAULT_PROMPTS = ROOT / "prompts"

MAX_ATTEMPTS = 2  # the first try and one retry, never more


# --- configuration --------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    model: str
    prompt_version: str
    max_tokens: int = 16000


@dataclass(frozen=True)
class Routing:
    tasks: dict[str, Route]
    pricing: dict[str, tuple[float, float]]

    @classmethod
    def load(cls, path: Path = DEFAULT_ROUTING) -> "Routing":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            tasks={name: Route(**route) for name, route in (raw.get("tasks") or {}).items()},
            pricing={
                model: (float(p["input"]), float(p["output"]))
                for model, p in (raw.get("pricing_usd_per_mtok") or {}).items()
            },
        )

    def route(self, task: str) -> Route:
        if task not in self.tasks:
            raise KeyError(f"task {task!r} has no route in config/models.yaml")
        return self.tasks[task]

    def cost_usd(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        if model not in self.pricing:
            return None
        per_input, per_output = self.pricing[model]
        return (input_tokens * per_input + output_tokens * per_output) / 1_000_000


# --- providers ------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    system: str
    user: str
    max_tokens: int
    json_schema: dict

    def audit_json(self) -> dict:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "user": self.user,
            "json_schema": self.json_schema,
        }


@dataclass(frozen=True)
class ProviderReply:
    text: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    def complete(self, request: ProviderRequest) -> ProviderReply: ...


class AnthropicProvider:
    """Claude via the official SDK. Credentials come from the environment."""

    def __init__(self, client: anthropic.Anthropic | None = None):
        self._client = client or anthropic.Anthropic()

    def complete(self, request: ProviderRequest) -> ProviderReply:
        response = self._client.messages.create(
            model=request.model,
            max_tokens=request.max_tokens,
            system=request.system,
            messages=[{"role": "user", "content": request.user}],
            # Constrains the reply to the schema. The gateway still validates with
            # Pydantic: the API relaxes some constraints (bounds, patterns) into
            # descriptions, and a constraint that is only asked for is not enforced.
            output_config={"format": {"type": "json_schema", "schema": request.json_schema}},
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return ProviderReply(
            text=text,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


# --- the gateway ----------------------------------------------------------------------


class InvalidModelOutput(RuntimeError):
    """The model failed validation twice. The item is in the review queue; nothing was published."""

    def __init__(self, task: str, review_item_id: int, errors: list[str]):
        super().__init__(f"{task}: output failed validation twice; review item {review_item_id}")
        self.task = task
        self.review_item_id = review_item_id
        self.errors = errors


class PromptChanged(RuntimeError):
    """A prompt version file was edited after it ran. Make a new version instead."""


@dataclass(frozen=True)
class GatewayResult[T: BaseModel]:
    output: T
    model_call_id: int
    cache_hit: bool


class Gateway:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        provider: Provider,
        routing: Routing | None = None,
        prompts_dir: Path = DEFAULT_PROMPTS,
    ):
        self._session_factory = session_factory
        self._provider = provider
        self._routing = routing or Routing.load()
        self._prompts_dir = prompts_dir

    def run[T: BaseModel](
        self,
        task: str,
        *,
        variables: dict[str, str],
        response_model: type[T],
        on_invalid: ReviewKind,
        known_identifiers: Iterable[str] = (),
        call_id=None,
        match_run_id=None,
    ) -> GatewayResult[T]:
        """Run one task. `on_invalid` is required: every call says where its failures go."""
        route = self._routing.route(task)
        prompt = load_prompt(self._prompts_dir, task, route.prompt_version)

        scrubber = Scrubber(known_identifiers=known_identifiers)
        clean_variables = {name: scrubber.scrub(value) for name, value in variables.items()}
        system, user = prompt.render(clean_variables)
        scrubber.assert_clean(system)
        scrubber.assert_clean(user)

        request = ProviderRequest(
            model=route.model,
            system=system,
            user=user,
            max_tokens=route.max_tokens,
            json_schema=anthropic.transform_schema(response_model),
        )
        input_hash = _input_hash(prompt, request)
        links = {"call_id": call_id, "match_run_id": match_run_id}

        with self._session_factory() as session:
            self._record_prompt(session, prompt)
            cached = self._from_cache(
                session, task, prompt, request, input_hash, response_model, links
            )
            session.commit()
        if cached is not None:
            return cached

        errors: list[str] = []
        call_ids: list[int] = []
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if errors:
                request = _with_retry_note(request, errors[-1])
            output, error, model_call_id = self._attempt(
                task, prompt, request, input_hash, response_model, links
            )
            call_ids.append(model_call_id)
            if output is not None:
                return GatewayResult(output=output, model_call_id=model_call_id, cache_hit=False)
            errors.append(f"attempt {attempt}: {error}")

        review_item_id = self._send_to_review(task, prompt, on_invalid, call_ids, errors, links)
        raise InvalidModelOutput(task, review_item_id, errors)

    # -- steps ---------------------------------------------------------------------------

    def _attempt(self, task, prompt, request, input_hash, response_model, links):
        started = time.monotonic()
        try:
            reply = self._provider.complete(request)
        except Exception as exc:
            # Recorded, then re-raised: a provider outage is not a validation failure
            # and must not be retried here or turned into a review item.
            self._write_call(
                task,
                prompt,
                request,
                input_hash,
                links,
                ok=False,
                cache_hit=False,
                latency_ms=_ms_since(started),
                error=f"provider error: {type(exc).__name__}",
            )
            raise

        output, error = _validate(reply, response_model)
        model_call_id = self._write_call(
            task,
            prompt,
            request,
            input_hash,
            links,
            ok=output is not None,
            cache_hit=False,
            latency_ms=_ms_since(started),
            error=error,
            reply=reply,
        )
        return output, error, model_call_id

    def _from_cache(self, session, task, prompt, request, input_hash, response_model, links):
        hit = session.execute(
            select(ModelCallPayload.response_json)
            .join(ModelCall, ModelCall.id == ModelCallPayload.model_call_id)
            .where(ModelCall.input_hash == input_hash, ModelCall.ok.is_(True))
            .order_by(ModelCall.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if hit is None:
            return None
        try:
            output = response_model.model_validate_json(hit["text"])
        except ValidationError:
            # A cached answer that no longer validates is not an answer. Call again.
            return None
        row = ModelCall(
            task=task,
            prompt_version_id=prompt.id,
            model=request.model,
            cache_hit=True,
            input_hash=input_hash,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0,
            latency_ms=0,
            ok=True,
            **links,
        )
        session.add(row)
        session.flush()
        return GatewayResult(output=output, model_call_id=row.id, cache_hit=True)

    def _write_call(
        self,
        task,
        prompt,
        request,
        input_hash,
        links,
        *,
        ok,
        cache_hit,
        latency_ms,
        error,
        reply: ProviderReply | None = None,
    ) -> int:
        with self._session_factory() as session:
            row = ModelCall(
                task=task,
                prompt_version_id=prompt.id,
                model=request.model,
                cache_hit=cache_hit,
                input_hash=input_hash,
                input_tokens=reply.input_tokens if reply else None,
                output_tokens=reply.output_tokens if reply else None,
                cost_usd=(
                    self._routing.cost_usd(request.model, reply.input_tokens, reply.output_tokens)
                    if reply
                    else None
                ),
                latency_ms=latency_ms,
                ok=ok,
                validation_error=error,
                **links,
            )
            session.add(row)
            session.flush()
            session.add(
                ModelCallPayload(
                    model_call_id=row.id,
                    request_json=request.audit_json(),
                    response_json=(
                        {"text": reply.text, "stop_reason": reply.stop_reason} if reply else None
                    ),
                )
            )
            session.commit()
            return row.id

    def _send_to_review(self, task, prompt, kind, call_ids, errors, links) -> int:
        with self._session_factory() as session:
            item = ReviewQueueItem(
                kind=kind,
                reason=f"{task}: model output failed validation twice",
                payload={
                    "task": task,
                    "prompt_version": prompt.id,
                    "model_call_ids": call_ids,
                    "errors": errors,
                },
                call_id=links["call_id"],
                match_run_id=links["match_run_id"],
            )
            session.add(item)
            session.commit()
            return item.id

    def _record_prompt(self, session: Session, prompt: Prompt) -> None:
        existing = session.get(PromptVersion, prompt.id)
        if existing is None:
            session.add(
                PromptVersion(
                    id=prompt.id,
                    task=prompt.task,
                    file_path=str(prompt.path.relative_to(self._prompts_dir.parent)),
                    content_sha256=prompt.content_sha256,
                )
            )
            session.flush()
        elif existing.content_sha256 != prompt.content_sha256:
            raise PromptChanged(
                f"{prompt.id} was edited after it ran. Copy it to a new version instead "
                "(prompts/README.md)."
            )


# --- helpers --------------------------------------------------------------------------


def _validate[T: BaseModel](reply: ProviderReply, model: type[T]) -> tuple[T | None, str | None]:
    if reply.stop_reason == "refusal":
        return None, "the model declined the request"
    if reply.stop_reason == "max_tokens":
        return None, "the reply was cut off at max_tokens"
    try:
        return model.model_validate_json(reply.text), None
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors()
        )
        return None, f"schema validation failed: {details}"[:2000]


def _with_retry_note(request: ProviderRequest, error: str) -> ProviderRequest:
    note = (
        "\n\nYour previous reply was rejected: "
        f"{error}\nReply again with JSON that matches the schema exactly."
    )
    return ProviderRequest(
        model=request.model,
        system=request.system,
        user=request.user + note,
        max_tokens=request.max_tokens,
        json_schema=request.json_schema,
    )


def _input_hash(prompt: Prompt, request: ProviderRequest) -> str:
    """Cache key: prompt version and content, model, schema, and the scrubbed input."""
    key = json.dumps(
        {
            "prompt": prompt.id,
            "prompt_sha256": prompt.content_sha256,
            "model": request.model,
            "max_tokens": request.max_tokens,
            "schema": request.json_schema,
            "system": request.system,
            "user": request.user,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
