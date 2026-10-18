from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from .pricing import Usage


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    usage: Usage
    content: list[dict[str, Any]] = field(default_factory=list)


class ChatModel(Protocol):
    name: str

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> Turn: ...


class AnthropicModel:
    def __init__(self, name: str, *, max_retries: int = 6, temperature: float | None = None) -> None:
        import anthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Put it in .env or export it.")
        self.name = name
        self.temperature = temperature
        self._client = anthropic.Anthropic(max_retries=max_retries)

    @staticmethod
    def _with_cache_breakpoint(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        msgs = copy.deepcopy(messages)
        if not msgs:
            return msgs
        last = msgs[-1]
        content: Any = last["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
            last["content"] = content
        if content:
            content[-1]["cache_control"] = {"type": "ephemeral"}
        return msgs

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> Turn:
        kwargs: dict[str, Any] = {
            "model": self.name,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": self._with_cache_breakpoint(messages),
        }
        if tools:
            kwargs["tools"] = tools
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        resp = self._client.messages.create(**kwargs)

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        content: list[dict[str, Any]] = []
        for block in resp.content:
            content.append(block.model_dump(exclude_none=True))
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
        u = resp.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            calls=1,
        )
        return Turn(
            text="".join(text_parts),
            tool_calls=calls,
            stop_reason=resp.stop_reason or "",
            usage=usage,
            content=content,
        )


class ScriptedModel:
    def __init__(self, turns: list[Turn], name: str = "scripted") -> None:
        self.name = name
        self._turns = list(turns)
        self.requests: list[list[dict[str, Any]]] = []

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> Turn:
        self.requests.append(copy.deepcopy(messages))
        if not self._turns:
            return Turn(text="", tool_calls=[], stop_reason="end_turn", usage=Usage(calls=1))
        return self._turns.pop(0)


def tool_turn(name: str, args: dict[str, Any], call_id: str = "t1") -> Turn:
    block = {"type": "tool_use", "id": call_id, "name": name, "input": args}
    return Turn(
        text="",
        tool_calls=[ToolCall(id=call_id, name=name, input=args)],
        stop_reason="tool_use",
        usage=Usage(input_tokens=100, output_tokens=20, calls=1),
        content=[block],
    )


def text_turn(text: str) -> Turn:
    return Turn(
        text=text,
        tool_calls=[],
        stop_reason="end_turn",
        usage=Usage(input_tokens=100, output_tokens=50, calls=1),
        content=[{"type": "text", "text": text}],
    )
