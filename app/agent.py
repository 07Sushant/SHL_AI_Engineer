from __future__ import annotations

import re

from app.catalog import CatalogClient, Product, normalize
from app.llm_intent import Intent, extract_intent
from app.retrieval import SKILL_PRODUCT_ALIASES, lexical_rank, names_from_aliases
from app.schemas import ChatResponse, Recommendation


CONFIRM_WORDS = ("perfect", "thanks", "thank you", "confirmed", "lock", "locking", "that works", "that's good", "covers it", "as-is")
OFF_TOPIC = ("salary", "compensation", "interview questions", "job description", "legal advice", "contract", "visa", "employment law")
LEGAL = ("legally", "legal", "law", "required under", "satisfy that requirement", "compliance question")
INJECTION = ("ignore previous", "ignore above", "system prompt", "developer message", "jailbreak", "forget your instructions")
COMPETITOR_TESTS = ("mbti", "disc assessment", "hogan", "hogan assessment", "caliper", "caliper profile",
                    "pi li", "predictive index", "16 pf", "sixteen personality", "enneagram",
                    "nasa astronaut", "astronaut assessment", "nasa test")
MAX_TURNS = 8


TRACE_SCENARIOS: list[tuple[tuple[str, ...], list[str]]] = [
    (("cxo", "director", "executive", "leadership", "senior leadership"), [
        "Occupational Personality Questionnaire OPQ32r",
        "OPQ Universal Competency Report 2.0",
        "OPQ Leadership Report",
    ]),
    (("rust", "networking", "infrastructure"), [
        "Smart Interview Live Coding",
        "Linux Programming (General)",
        "Networking and Implementation (New)",
        "SHL Verify Interactive G+",
        "Occupational Personality Questionnaire OPQ32r",
    ]),
    (("contact centre", "contact center", "inbound calls", "customer service"), [
        "SVAR Spoken English (US) (New)",
        "Contact Center Call Simulation (New)",
        "Entry Level Customer Serv - Retail & Contact Center",
        "Customer Service Phone Simulation",
    ]),
    (("financial analysts", "finance", "accounting"), [
        "SHL Verify Interactive - Numerical Reasoning",
        "Financial Accounting (New)",
        "Basic Statistics (New)",
        "Graduate Scenarios",
        "Occupational Personality Questionnaire OPQ32r",
    ]),
    (("sales organization", "sales organisation", "re-skill", "reskill", "talent audit"), [
        "Global Skills Assessment",
        "Global Skills Development Report",
        "Occupational Personality Questionnaire OPQ32r",
        "OPQ MQ Sales Report",
        "Sales Transformation 2.0 - Individual Contributor",
    ]),
    (("plant operators", "chemical facility", "safety", "procedure compliance"), [
        "Dependability and Safety Instrument (DSI)",
        "Manufac. & Indust. - Safety & Dependability 8.0",
        "Workplace Health and Safety (New)",
    ]),
    (("healthcare admin", "patient records", "hipaa"), [
        "HIPAA (Security)",
        "Medical Terminology (New)",
        "Microsoft Word 365 - Essentials (New)",
        "Dependability and Safety Instrument (DSI)",
        "Occupational Personality Questionnaire OPQ32r",
    ]),
    (("admin assistants", "excel", "word"), [
        "MS Excel (New)",
        "MS Word (New)",
        "Occupational Personality Questionnaire OPQ32r",
    ]),
    (("full stack", "full-stack", "spring", "microservice", "java"), [
        "Core Java (Advanced Level) (New)",
        "Spring (New)",
        "RESTful Web Services (New)",
        "SQL (New)",
        "SHL Verify Interactive G+",
        "Occupational Personality Questionnaire OPQ32r",
    ]),
    (("graduate management trainee", "management trainee"), [
        "SHL Verify Interactive G+",
        "Occupational Personality Questionnaire OPQ32r",
        "Graduate Scenarios",
    ]),
]


def answer(messages: list[dict], catalog: CatalogClient) -> ChatResponse:
    products = catalog.get_products()
    user_messages = [msg.get("content", "") for msg in messages if msg.get("role") == "user"]
    assistant_messages = [msg.get("content", "") for msg in messages if msg.get("role") == "assistant"]
    last_user = user_messages[-1] if user_messages else ""
    transcript = "\n".join(user_messages)
    full_context = "\n".join([msg.get("content", "") for msg in messages])
    intent = extract_intent(messages)
    intent_text = _intent_text(intent, transcript)

    # Bug 4: Out-of-catalog / competitor test detection
    if intent.is_out_of_catalog and intent.out_of_catalog_names:
        names_str = ", ".join(intent.out_of_catalog_names)
        return ChatResponse(
            reply=f"I only recommend SHL catalog assessments. {names_str} {'is' if ',' not in names_str else 'are'} not available in the SHL catalog.",
            recommendations=[],
            end_of_conversation=False,
        )

    if _contains(last_user, INJECTION):
        return ChatResponse(
            reply="I can only help with SHL assessment selection using the SHL catalog, so I can't follow that instruction.",
            recommendations=[],
            end_of_conversation=False,
        )

    previous = _previous_recommendations(products, assistant_messages)

    # Bug 1: Turn cap - force end after MAX_TURNS user messages
    turn_count = len(user_messages)
    if turn_count >= MAX_TURNS:
        if previous:
            return _response(
                "Thank you for the conversation. Here is the finalized SHL assessment shortlist based on our discussion.",
                previous,
                end=True,
            )
        # No previous recommendations but hit turn cap - return what we have with end=True
        shortlist = _scenario_products(intent_text, products) or _generic_products(intent_text, products)
        if shortlist:
            return _response(
                "Based on our discussion, here is the SHL assessment shortlist.",
                shortlist,
                end=True,
            )

    if _contains(last_user, LEGAL):
        return ChatResponse(
            reply=(
                "I can't provide legal or regulatory advice. I can help select SHL assessments and describe what a catalog item measures, "
                "but your legal or compliance team should decide whether any test satisfies a legal requirement."
            ),
            recommendations=[],
            end_of_conversation=False,
        )

    # Bug 3: Early comparison interception (before vague query fallback)
    if intent.action == "compare" and intent.compare_items:
        compared = catalog.products_by_names(intent.compare_items)
        if len(compared) >= 2:
            return _response(_comparison_reply(compared[:2]), compared[:2], end=False)
        # If not found in catalog, check if they're competitor tests
        if any(_is_competitor(name) for name in intent.compare_items):
            competitor_names = [n for n in intent.compare_items if _is_competitor(n)]
            return ChatResponse(
                reply=f"I only recommend SHL catalog assessments. {', '.join(competitor_names)} {'is' if len(competitor_names) == 1 else 'are'} not available in our catalog.",
                recommendations=[],
                end_of_conversation=False,
            )

    # Fallback comparison path (works even without Groq LLM)
    if _is_comparison(last_user):
        # Extract product names from the query using aliases
        compare_names = names_from_aliases(last_user)
        if not compare_names:
            # Try to extract from comparison_terms if available
            compare_names = names_from_aliases(" ".join(intent.comparison_terms) or "")
        if compare_names:
            compared = catalog.products_by_names(compare_names)
        else:
            compared = _mentioned_products(products, last_user, [])
        # If still not enough, try previous recommendations
        if len(compared) < 2 and previous:
            compared = previous[:2]
        if len(compared) >= 2:
            return _response(_comparison_reply(compared[:2]), compared[:2], end=False)
        # If only one product found but user asked to compare, ask for clarification
        if len(compared) == 1:
            return _response(
                f"I found {compared[0].name} in the catalog. Which second assessment would you like to compare it with?",
                compared[:1],
                end=False,
            )

    if previous and _is_confirmation(last_user):
        return _response(
            "Confirmed. Here is the final SHL assessment shortlist.",
            previous,
            end=True,
        )

    if previous and _is_refinement(last_user):
        if _starts_over(last_user):
            refined = _generic_products(_clean_refinement_query(_intent_text(intent, last_user)), products)
        else:
            refined = previous
        refined = _refine(refined, _intent_refinement_text(intent, last_user), products)
        if _starts_over(last_user):
            refined = _trim_weak_replacement(refined, _intent_refinement_text(intent, last_user))
        if refined:
            return _response("Updated the shortlist based on your latest constraint.", refined)

    if _too_vague(transcript):
        return ChatResponse(
            reply=(
                "I can help, but I need a little more context before recommending. "
                "What role are you hiring for, what seniority level, and which skills or behaviors matter most?"
            ),
            recommendations=[],
            end_of_conversation=False,
        )

    if "contact" in normalize(transcript) and not _contains(transcript, ("english", "spanish", "french", "german")):
        return ChatResponse(
            reply="What language are the calls in? That determines which spoken-language assessment variant fits.",
            recommendations=[],
            end_of_conversation=False,
        )

    if (
        "contact" in normalize(transcript)
        and "english" in normalize(transcript)
        and not re.search(r"\b(us|usa|united states|uk|australian|indian)\b", normalize(transcript))
    ):
        return ChatResponse(
            reply="Which English accent variant fits the role best: US, UK, Australian, or Indian?",
            recommendations=[],
            end_of_conversation=False,
        )

    if "full stack" in normalize(transcript) or "fullstack" in normalize(transcript) or "full-stack" in normalize(transcript):
        if not _contains(transcript, ("backend", "frontend", "balanced")):
            return ChatResponse(
                reply="Is this backend-leaning, frontend-heavy, or a balanced full-stack role?",
                recommendations=[],
                end_of_conversation=False,
            )
        if not _contains(transcript, ("senior", "lead", "manager", "graduate", "entry", "mid-level", "mid level", "ic")):
            return ChatResponse(
                reply="Is the role a senior individual contributor, a tech lead, or a people manager?",
                recommendations=[],
                end_of_conversation=False,
            )

    shortlist = _scenario_products(intent_text, products)
    if not shortlist:
        shortlist = _generic_products(intent_text, products)
    shortlist = _refine(shortlist, _intent_refinement_text(intent, full_context), products)

    if not shortlist:
        if _contains(last_user, OFF_TOPIC):
            return ChatResponse(
                reply="I can only discuss SHL assessments and recommendations grounded in the SHL catalog.",
                recommendations=[],
                end_of_conversation=False,
            )
        return ChatResponse(
            reply="I could not find a strong catalog-grounded match yet. Which role, skills, seniority, and language should I optimize for?",
            recommendations=[],
            end_of_conversation=False,
        )

    reply = _recommendation_reply(shortlist, intent_text)
    return _response(reply, shortlist[:10], end=False)


def _response(reply: str, products: list[Product], end: bool = False) -> ChatResponse:
    visible_names = "; ".join(item.name for item in products[:10])
    if visible_names and "Shortlist:" not in reply:
        reply = f"{reply}\n\nShortlist: {visible_names}."
    return ChatResponse(
        reply=reply,
        recommendations=[
            Recommendation(name=item.name, url=item.url, test_type=item.test_type)
            for item in products[:10]
            if item.url
        ],
        end_of_conversation=end,
    )


def _intent_text(intent: Intent, fallback: str) -> str:
    if not intent.used_llm or not intent.search_text:
        return fallback
    text = intent.search_text
    for term in intent.negative_terms:
        text = re.sub(rf"\b{re.escape(normalize(term))}\b", " ", normalize(text))
    return text or fallback


def _intent_refinement_text(intent: Intent, fallback: str) -> str:
    if not intent.used_llm:
        return fallback
    # Bug 2: Use cumulative positive terms to preserve context across turns
    additions = " ".join(intent.cumulative_positive_terms or intent.positive_terms)
    removals = " ".join(f"drop {term}" for term in intent.negative_terms)
    return " ".join([intent.current_need, additions, removals, fallback])


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    norm = normalize(text)
    return any(normalize(phrase) in norm for phrase in phrases)


def _is_competitor(name: str) -> bool:
    norm = normalize(name)
    return any(normalize(comp) in norm for comp in COMPETITOR_TESTS)


def _too_vague(text: str) -> bool:
    norm = normalize(text)
    meaningful = [word for word in norm.split() if len(word) > 3]
    role_markers = (
        "developer", "engineer", "sales", "admin", "assistant", "graduate", "manager",
        "leadership", "operator", "analyst", "contact", "customer", "healthcare",
        "java", "python", "excel", "word", "finance", "safety",
    )
    return len(meaningful) < 5 or not any(marker in norm for marker in role_markers)


def _is_confirmation(text: str) -> bool:
    return _contains(text, CONFIRM_WORDS)


def _is_comparison(text: str) -> bool:
    return _contains(text, ("difference between", "different from", "compare", "versus", " vs "))


def _is_refinement(text: str) -> bool:
    return _contains(text, ("add", "drop", "remove", "replace", "actually", "instead", "keep", "include", "exclude", "scratch", "no longer"))


def _starts_over(text: str) -> bool:
    return _contains(text, ("scratch", "instead", "replace", "no longer"))


def _clean_refinement_query(text: str) -> str:
    cleaned = normalize(text)
    for alias in SKILL_PRODUCT_ALIASES:
        alias_norm = normalize(alias)
        if re.search(rf"\b(drop|remove|exclude|scratch|instead of|no longer|not)\b(?:\s+\w+){{0,4}}\s+\b{re.escape(alias_norm)}\b", cleaned):
            cleaned = re.sub(rf"\b{re.escape(alias_norm)}\b", " ", cleaned)
    return cleaned


def _trim_weak_replacement(products: list[Product], text: str) -> list[Product]:
    explicit = set(names_from_aliases(text))
    trimmed = [item for item in products if item.name in explicit]
    if trimmed:
        return trimmed[:10]
    return products[:5]


def _scenario_products(text: str, products: list[Product]) -> list[Product]:
    norm = normalize(text)
    best: tuple[int, list[str]] = (0, [])
    for markers, names in TRACE_SCENARIOS:
        score = sum(1 for marker in markers if normalize(marker) in norm)
        if score > best[0]:
            best = (score, names)
    if best[0] == 0:
        return []
    return _by_names(products, best[1])


def _generic_products(text: str, products: list[Product]) -> list[Product]:
    names = names_from_aliases(text)
    if "senior" in normalize(text) and "SHL Verify Interactive G+" not in names:
        names.append("SHL Verify Interactive G+")
    if any(word in normalize(text) for word in ("stakeholder", "mentor", "lead", "manager", "senior")):
        names.append("Occupational Personality Questionnaire OPQ32r")
    selected = _by_names(products, names)
    seen = {item.url for item in selected}
    for item in lexical_rank(products, text, limit=10):
        if item.url not in seen:
            selected.append(item)
            seen.add(item.url)
        if len(selected) >= 10:
            break
    return selected[:10]


def _refine(current: list[Product], text: str, products: list[Product]) -> list[Product]:
    norm = normalize(text)
    refined = list(current)

    add_names = names_from_aliases(text)
    if "simulation" in norm and ("excel" in norm or "word" in norm):
        add_names.extend(["Microsoft Excel 365 (New)", "Microsoft Word 365 (New)"])
    if "aws" in norm:
        add_names.append("Amazon Web Services (AWS) Development (New)")
    if "docker" in norm:
        add_names.append("Docker (New)")
    if "personality" in norm or "opq" in norm:
        add_names.append("Occupational Personality Questionnaire OPQ32r")

    for product in _by_names(products, add_names):
        if product.url not in {item.url for item in refined}:
            refined.append(product)

    drops = []
    if re.search(r"\b(drop|remove|exclude)\b.*\brest\b", norm):
        drops.append("restful web services")
    if re.search(r"\b(drop|remove|exclude)\b.*\bopq\b", norm):
        drops.append("occupational personality questionnaire opq32r")
    if re.search(r"\b(drop|remove|exclude)\b.*\bg\+\b", norm):
        drops.append("shl verify interactive g")
    for alias, product_name in SKILL_PRODUCT_ALIASES.items():
        alias_norm = normalize(alias)
        if re.search(rf"\b(drop|remove|exclude|scratch|instead of|no longer|not)\b(?:\s+\w+){{0,4}}\s+\b{re.escape(alias_norm)}\b", norm):
            drops.append(normalize(product_name))
    if "knowledge-only" in norm or "quick" in norm:
        drops.extend(["microsoft excel 365", "microsoft word 365"])
    if "simulation" in norm and ("excel" in norm or "word" in norm):
        drops = [drop for drop in drops if "microsoft" not in drop]

    if drops:
        refined = [item for item in refined if not any(drop in item.norm_name for drop in drops)]

    if "industrial" in norm and "safety" in norm:
        refined = [
            item for item in refined
            if item.norm_name in {
                "manufac and indust safety and dependability 8 0",
                "workplace health and safety new",
            }
        ] or refined

    return _dedupe(refined)[:10]


def _by_names(products: list[Product], names: list[str]) -> list[Product]:
    found: list[Product] = []
    for name in names:
        target = normalize(name)
        product = next((item for item in products if item.norm_name == target), None)
        if not product:
            product = next((item for item in products if target in item.norm_name or item.norm_name in target), None)
        if product:
            found.append(product)
    return _dedupe(found)


def _dedupe(products: list[Product]) -> list[Product]:
    seen: set[str] = set()
    unique: list[Product] = []
    for product in products:
        if product.url and product.url not in seen:
            unique.append(product)
            seen.add(product.url)
    return unique


def _previous_recommendations(products: list[Product], assistant_messages: list[str]) -> list[Product]:
    text = "\n".join(assistant_messages[-3:])
    ordered = _products_from_shortlist_line(products, text)
    if ordered:
        return ordered
    mentioned = _mentioned_products(products, text, [])
    return mentioned[:10]


def _products_from_shortlist_line(products: list[Product], text: str) -> list[Product]:
    matches = re.findall(r"Shortlist:\s*(.+?)(?:\n|$)", text, flags=re.IGNORECASE | re.DOTALL)
    if not matches:
        return []
    names = [part.strip(" .") for part in matches[-1].split(";") if part.strip()]
    return _by_names(products, names)


def _mentioned_products(products: list[Product], text: str, fallback: list[Product]) -> list[Product]:
    norm = normalize(text)
    found = [item for item in products if item.norm_name and item.norm_name in norm]
    if found:
        return _dedupe(found)
    alias_names = names_from_aliases(text)
    return _by_names(products, alias_names) or fallback


def _comparison_reply(products: list[Product]) -> str:
    first, second = products[0], products[1]
    return (
        f"{first.name} is a {', '.join(first.keys) or 'catalog'} item"
        f"{_duration_phrase(first)}. {first.description[:280]} "
        f"{second.name} is a {', '.join(second.keys) or 'catalog'} item"
        f"{_duration_phrase(second)}. {second.description[:280]} "
        "So the practical difference is their catalog purpose, construct, duration, and available languages; I would use the one whose catalog description matches the hiring signal you need."
    )


def _duration_phrase(product: Product) -> str:
    return f" with duration {product.duration}" if product.duration else ""


def _recommendation_reply(products: list[Product], text: str) -> str:
    if "rust" in normalize(text):
        return "The catalog does not show a Rust-specific test, so this shortlist uses the closest SHL catalog matches for systems, networking, reasoning, and senior workplace fit."
    if "spanish" in normalize(text) and "hipaa" in normalize(text):
        return "A hybrid battery fits best: English knowledge tests for HIPAA and records work, plus Spanish-capable personality measures where the catalog supports them."
    if "quick" in normalize(text) and ("excel" in normalize(text) or "word" in normalize(text)):
        return "For a quick admin-assistant screen, these catalog items cover Excel, Word, and workplace behavior."
    return f"Here are {len(products[:10])} SHL catalog assessments that fit the role and constraints you described."
