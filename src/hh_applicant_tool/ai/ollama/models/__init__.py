from __future__ import annotations

from dataclasses import dataclass

from . import (
    gpt_oss_120b_cloud,
    gpt_oss_20b,
    gpt_oss_20b_cloud,
    llava,
    llama3_2,
    qwen2_5,
)


@dataclass(frozen=True)
class OllamaModelSpec:
    key: str
    model: str
    vision: bool | None = None


SUPPORTED_MODELS: dict[str, OllamaModelSpec] = {
    "llama3_2": OllamaModelSpec(
        key="llama3_2",
        model=llama3_2.MODEL,
        vision=llama3_2.VISION,
    ),
    "qwen2_5": OllamaModelSpec(
        key="qwen2_5",
        model=qwen2_5.MODEL,
        vision=qwen2_5.VISION,
    ),
    "gpt_oss_20b": OllamaModelSpec(
        key="gpt_oss_20b",
        model=gpt_oss_20b.MODEL,
        vision=gpt_oss_20b.VISION,
    ),
    "gpt_oss_20b_cloud": OllamaModelSpec(
        key="gpt_oss_20b_cloud",
        model=gpt_oss_20b_cloud.MODEL,
        vision=gpt_oss_20b_cloud.VISION,
    ),
    "gpt_oss_120b_cloud": OllamaModelSpec(
        key="gpt_oss_120b_cloud",
        model=gpt_oss_120b_cloud.MODEL,
        vision=gpt_oss_120b_cloud.VISION,
    ),
    "llava": OllamaModelSpec(
        key="llava",
        model=llava.MODEL,
        vision=llava.VISION,
    ),
}


def get_model_spec(key: str) -> OllamaModelSpec:
    return SUPPORTED_MODELS.get(
        key,
        OllamaModelSpec(key=key, model=key),
    )


def supported_models() -> tuple[str, ...]:
    return tuple(SUPPORTED_MODELS)
