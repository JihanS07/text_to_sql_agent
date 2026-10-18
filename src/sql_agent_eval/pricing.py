from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_write_5m: float
    cache_read: float


PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_write_5m=0.125, cache_read=0.01),
    "claude-sonnet-5-5": Price(input=2.0, output=10.0, cache_write_5m=2.50, cache_read=0.10),
    "claude-opus-5-5": Price(input=4.0, output=20.0, cache_write_5m=5.0, cache_read=0.20),
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    calls: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        self.calls += other.calls


def cost_usd(model: str, usage: Usage) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_creation_input_tokens * price.cache_write_5m
        + usage.cache_read_input_tokens * price.cache_read
    ) / 1_000_000
