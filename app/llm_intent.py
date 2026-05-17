from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field


DEFAULT_MODEL = "qwen/qwen3-32b"


@dataclass
class Intent:
    action: str = "recommend"
    current_need: str = ""
    positive_terms: list[str] = field(default_factory=list)
    negative_terms: list[str] = field(default_factory=list)
    comparison_terms: list[str] = field(default_factory=list)
    requested_products: list[str] = field(default_factory=list)
    compare_items: list[str] = field(default_factory=list)
    is_out_of_catalog: bool = False
    out_of_catalog_names: list[str] = field(default_factory=list)
    cumulative_positive_terms: list[str] = field(default_factory=list)
    confidence: float = 0.0
    used_llm: bool = False

    @property
    def search_text(self) -> str:
        return " ".join([self.current_need, " ".join(self.cumulative_positive_terms)]).strip()


def extract_intent(messages: list[dict]) -> Intent:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return Intent()

    clean_messages = [
        {"role": msg.get("role", "user"), "content": msg.get("content", "")[:2000]}
        for msg in messages[-8:]
        if msg.get("role") in {"user", "assistant"}
    ]
    prompt = (
        "You extract the user's CURRENT SHL assessment need from a stateless chat history. "
        "CRITICAL: This is a multi-turn conversation. When the user adds new requirements mid-conversation "
        "(e.g., 'also add X', 'and Y too'), keep ALL previous skills/roles from the chat history and ADD "
        "the new ones to positive_terms. Only drop terms if the user explicitly says 'scratch X', 'drop X', "
        "'not X', or 'remove X'. Put the FULL cumulative set of required skills, roles, and traits in "
        "cumulative_positive_terms (everything ever requested that hasn't been explicitly negated). "
        "Handle corrections and negation carefully. If the user says scratch, drop, remove, "
        "instead of, no longer, or not X, put X in negative_terms and do not keep it in positive_terms. "
        "When the user asks for a direct product comparison (e.g., 'difference between X and Y', 'compare X vs Y'), "
        "set action to 'compare', populate compare_items with the exact product names, and set current_need to empty. "
        "When the user requests a specific test by name (e.g., 'do you have MBTI?', 'I need the NASA test'), "
        "populate requested_products with those names. If any requested name is a known competitor "
        "(MBTI, DISC, Hogan, Caliper, Predictive Index, 16PF, Enneagram) or an obviously fake/out-of-scope test, "
        "set is_out_of_catalog to true and put those names in out_of_catalog_names. "
        "Do not recommend products. Do not invent SHL names. Output JSON only with this schema: "
        '{"action":"recommend|clarify|refine|compare|refuse",'
        '"current_need":"short plain English current need",'
        '"positive_terms":["newly mentioned skill/role/constraint from this turn"],'
        '"negative_terms":["negated skill/product"],'
        '"comparison_terms":["terms related to comparison"],'
        '"requested_products":["specific product names user asked for"],'
        '"compare_items":["exact product names to compare"],'
        '"is_out_of_catalog":false,'
        '"out_of_catalog_names":["competitor or fake test names"],'
        '"cumulative_positive_terms":["ALL required skills/roles/traits from entire conversation history"],'
        '"confidence":0.0}'
    )
    try:
        from groq import Groq

        client = Groq(api_key=api_key, timeout=8)
        completion = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", DEFAULT_MODEL),
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(clean_messages, ensure_ascii=True)},
            ],
            temperature=0,
            top_p=1,
            max_completion_tokens=600,
            stream=False,
        )
        content = completion.choices[0].message.content or ""
        data = _parse_json(content)
        return Intent(
            action=str(data.get("action") or "recommend"),
            current_need=str(data.get("current_need") or ""),
            positive_terms=_string_list(data.get("positive_terms")),
            negative_terms=_string_list(data.get("negative_terms")),
            comparison_terms=_string_list(data.get("comparison_terms")),
            requested_products=_string_list(data.get("requested_products")),
            compare_items=_string_list(data.get("compare_items")),
            is_out_of_catalog=bool(data.get("is_out_of_catalog", False)),
            out_of_catalog_names=_string_list(data.get("out_of_catalog_names")),
            cumulative_positive_terms=_string_list(data.get("cumulative_positive_terms")),
            confidence=float(data.get("confidence") or 0.0),
            used_llm=True,
        )
    except Exception:
        return Intent()


def _parse_json(content: str) -> dict:
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.IGNORECASE).strip()
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM did not return JSON")
    return json.loads(match.group(0))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
