from __future__ import annotations

import math
import re

from app.catalog import Product, normalize


STOPWORDS = {
    "a", "an", "and", "are", "as", "for", "from", "in", "is", "it", "of", "on",
    "or", "that", "the", "to", "use", "we", "with", "who", "what", "should",
}

SKILL_PRODUCT_ALIASES = {
    "java": "Core Java (Advanced Level) (New)",
    "core java": "Core Java (Advanced Level) (New)",
    "spring": "Spring (New)",
    "rest": "RESTful Web Services (New)",
    "api": "RESTful Web Services (New)",
    "sql": "SQL (New)",
    "aws": "Amazon Web Services (AWS) Development (New)",
    "docker": "Docker (New)",
    "linux": "Linux Programming (General)",
    "networking": "Networking and Implementation (New)",
    "rust": "Smart Interview Live Coding",
    "python": "Python (New)",
    "communication": "Occupational Personality Questionnaire OPQ32r",
    "client": "Occupational Personality Questionnaire OPQ32r",
    "clients": "Occupational Personality Questionnaire OPQ32r",
    "stakeholder": "Occupational Personality Questionnaire OPQ32r",
    "talking": "Occupational Personality Questionnaire OPQ32r",
    "excel": "MS Excel (New)",
    "word": "MS Word (New)",
    "excel simulation": "Microsoft Excel 365 (New)",
    "word simulation": "Microsoft Word 365 (New)",
    "hipaa": "HIPAA (Security)",
    "medical terminology": "Medical Terminology (New)",
    "finance": "Financial Accounting (New)",
    "accounting": "Financial Accounting (New)",
    "statistics": "Basic Statistics (New)",
    "numerical": "SHL Verify Interactive - Numerical Reasoning",
    "cognitive": "SHL Verify Interactive G+",
    "reasoning": "SHL Verify Interactive G+",
    "sjt": "Graduate Scenarios",
    "situational": "Graduate Scenarios",
    "graduate scenarios": "Graduate Scenarios",
    "personality": "Occupational Personality Questionnaire OPQ32r",
    "opq": "Occupational Personality Questionnaire OPQ32r",
    "opq32r": "Occupational Personality Questionnaire OPQ32r",
    "leadership": "OPQ Leadership Report",
    "gsa": "Global Skills Assessment",
    "global skills": "Global Skills Assessment",
    "sales transformation": "Sales Transformation 2.0 - Individual Contributor",
    "safety": "Dependability and Safety Instrument (DSI)",
    "dependability": "Dependability and Safety Instrument (DSI)",
}


def tokens(text: str) -> set[str]:
    return {tok for tok in normalize(text).split() if tok not in STOPWORDS and len(tok) > 1}


def lexical_rank(products: list[Product], query: str, limit: int = 10) -> list[Product]:
    query_tokens = tokens(query)
    if not query_tokens:
        return []
    ranked: list[tuple[float, Product]] = []
    for product in products:
        product_tokens = tokens(product.text)
        overlap = query_tokens & product_tokens
        if not overlap:
            continue
        name_overlap = query_tokens & tokens(product.name)
        score = len(overlap) + 2.5 * len(name_overlap)
        score += sum(1.0 for key in product.keys if normalize(key) in normalize(query))
        score /= math.sqrt(max(len(product_tokens), 1))
        ranked.append((score, product))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [product for _, product in ranked[:limit]]


def names_from_aliases(text: str) -> list[str]:
    lowered = normalize(text)
    names: list[str] = []
    for alias, product_name in SKILL_PRODUCT_ALIASES.items():
        if re.search(rf"\b{re.escape(normalize(alias))}\b", lowered):
            names.append(product_name)
    return names
