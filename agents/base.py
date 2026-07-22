"""Async agent runner with coroutine-aware tool dispatch."""

from __future__ import annotations

import inspect
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import structlog
from dotenv import load_dotenv

from core.config import settings

load_dotenv(Path(__file__).parent.parent / ".env")

logger = structlog.getLogger(__name__)

ToolHandler = Callable[..., Any]
MAX_TOOL_ITERATIONS = 50

ANTHROPIC_KEY = settings.ANTHROPIC_API_KEY
OPENAI_KEY = settings.OPENAI_API_KEY


def _provider() -> tuple[str, str]:
    forced = os.getenv("LLM_PROVIDER", "").lower()
    if forced == "openai" and OPENAI_KEY:
        return "openai", settings.OPENAI_MODEL
    if forced == "anthropic" and ANTHROPIC_KEY:
        return "anthropic", settings.ANTHROPIC_MODEL
    if ANTHROPIC_KEY:
        return "anthropic", settings.ANTHROPIC_MODEL
    if OPENAI_KEY:
        return "openai", settings.OPENAI_MODEL
    raise EnvironmentError("No LLM API key found — set ANTHROPIC_API_KEY or OPENAI_API_KEY")


PROVIDER, DEFAULT_MODEL = _provider()

# Tier → model for the active provider. Callers pass tier="cheap"/"smart", never a model ID.
_TIER_MODELS = {
    "smart": DEFAULT_MODEL,
    "cheap": settings.ANTHROPIC_MODEL_CHEAP if PROVIDER == "anthropic" else settings.OPENAI_MODEL_CHEAP,
}


def _wrap(client, kind: str):
    """LangSmith tracing is optional — if it's not installed, return the raw client.
    Wrapping makes each LLM call a run nested under the current question/stage trace
    (set in pipeline.py); it's a no-op at runtime unless LANGSMITH_TRACING=true."""
    try:
        from langsmith.wrappers import wrap_anthropic, wrap_openai
    except ImportError:
        return client
    return (wrap_anthropic if kind == "anthropic" else wrap_openai)(client)


@lru_cache(maxsize=1)
def _get_anthropic_client():
    import anthropic
    return _wrap(anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY), "anthropic")


@lru_cache(maxsize=1)
def _get_openai_client():
    from openai import AsyncOpenAI
    return _wrap(AsyncOpenAI(api_key=OPENAI_KEY), "openai")


def parse_json_result(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        return json.loads(brace.group(0))
    raise json.JSONDecodeError("No JSON object found in response", text, 0)


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
        },
    } for t in tools]


async def _dispatch(handler: ToolHandler, kwargs: dict) -> Any:
    """Dispatch a tool handler — awaits if it's a coroutine function."""
    if inspect.iscoroutinefunction(handler):
        return await handler(**kwargs)
    return handler(**kwargs)


async def _run_anthropic(
    system_prompt: str,
    user_message: str,
    tools: list,
    tool_handlers: dict,
    max_tokens: int,
    model: str,
    max_iterations: int,
) -> tuple[str, int]:
    client = _get_anthropic_client()
    messages = [{"role": "user", "content": user_message}]
    total_tokens = 0
    retried = False

    # Cache breakpoints on the system prompt and tool defs — identical across
    # every iteration of this call's tool loop.
    system_blocks = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    cached_tools = tools
    if tools:
        cached_tools = [*tools[:-1], {**tools[-1], "cache_control": {"type": "ephemeral"}}]

    for iteration in range(1, max_iterations + 1):
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            tools=cached_tools,
            messages=messages,
        )
        usage = response.usage
        total_tokens += (
            usage.input_tokens
            + usage.output_tokens
            + getattr(usage, "cache_creation_input_tokens", 0)
            + getattr(usage, "cache_read_input_tokens", 0)
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text, total_tokens
            logger.warning("agent_empty_response", stop_reason=response.stop_reason, iteration=iteration)
            return "", total_tokens

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                handler = tool_handlers.get(block.name)
                if handler:
                    try:
                        result = await _dispatch(handler, block.input)
                        content = result if isinstance(result, str) else json.dumps(result, default=str)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": content,
                        })
                    except Exception as exc:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error in {block.name}: {exc}",
                            "is_error": True,
                        })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Unknown tool: {block.name}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text, total_tokens
            if not retried:
                retried = True
                max_tokens *= 2
                logger.warning(
                    "agent_truncated_retry",
                    stop_reason=response.stop_reason,
                    iteration=iteration,
                    new_max_tokens=max_tokens,
                )
                continue
            logger.warning(
                "agent_truncated_response",
                stop_reason=response.stop_reason,
                iteration=iteration,
                max_tokens=max_tokens,
            )
            return "", total_tokens

    return (
        f'{{"status": "failed", "error": "aborted: exceeded {max_iterations} tool iterations"}}',
        total_tokens,
    )


async def _run_openai(
    system_prompt: str,
    user_message: str,
    tools: list,
    tool_handlers: dict,
    max_tokens: int,
    model: str,
    max_iterations: int,
) -> tuple[str, int]:
    client = _get_openai_client()
    openai_tools = _to_openai_tools(tools) if tools else []
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    total_tokens = 0
    retried = False

    for iteration in range(1, max_iterations + 1):
        kwargs: dict = dict(model=model, max_completion_tokens=max_tokens, messages=messages)
        if openai_tools:
            kwargs["tools"] = openai_tools
        response = await client.chat.completions.create(**kwargs)
        total_tokens += response.usage.prompt_tokens + response.usage.completion_tokens
        choice = response.choices[0]

        if choice.finish_reason == "stop":
            if not choice.message.content:
                logger.warning("agent_empty_response", stop_reason=choice.finish_reason, iteration=iteration)
            return choice.message.content or "", total_tokens

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                handler = tool_handlers.get(name)
                if handler:
                    try:
                        result = await _dispatch(handler, args)
                        content = result if isinstance(result, str) else json.dumps(result, default=str)
                    except Exception as exc:
                        content = f"Error in {name}: {exc}"
                else:
                    content = f"Unknown tool: {name}"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
        else:
            if not choice.message.content and not retried:
                retried = True
                max_tokens *= 2
                logger.warning(
                    "agent_truncated_retry",
                    stop_reason=choice.finish_reason,
                    iteration=iteration,
                    new_max_tokens=max_tokens,
                )
                continue
            if not choice.message.content:
                logger.warning(
                    "agent_truncated_response",
                    stop_reason=choice.finish_reason,
                    iteration=iteration,
                    max_tokens=max_tokens,
                )
            return choice.message.content or "", total_tokens

    return (
        f'{{"status": "failed", "error": "aborted: exceeded {max_iterations} tool iterations"}}',
        total_tokens,
    )

# ------------------ PUBLIC API ------------------

# Hard questions produce more files/code than easy ones — scale token budgets.
_DIFFICULTY_TOKEN_SCALE = {"easy": 0.65, "medium": 1.0, "hard": 1.25}


def scaled_max_tokens(base: int, difficulty: str) -> int:
    return int(base * _DIFFICULTY_TOKEN_SCALE.get(difficulty, 1.0))


async def run_agent(
    system_prompt: str,
    user_message: str,
    tools: list,
    tool_handlers: dict,
    max_tokens: int = 8096,
    model: str | None = None,
    tier: str = "smart",
    max_tool_iterations: int | None = None,
) -> tuple[str, int]:
    """Run an LLM agent with tool-use loop. Returns (final_text, total_tokens).

    tier selects the model ("smart" default, "cheap" for brush-up work); an explicit
    model overrides the tier. max_tool_iterations overrides the default iteration
    ceiling for file-heavy stages that need more headroom."""
    model = model or _TIER_MODELS[tier]
    iterations = max_tool_iterations or MAX_TOOL_ITERATIONS
    if PROVIDER == "openai":
        text, tokens = await _run_openai(
            system_prompt, user_message, tools, tool_handlers, max_tokens, model, iterations)
    else:
        text, tokens = await _run_anthropic(
            system_prompt, user_message, tools, tool_handlers, max_tokens, model, iterations)
    logger.info("agent_llm_done", tier=tier, model=model, tokens=tokens)
    return text, tokens
