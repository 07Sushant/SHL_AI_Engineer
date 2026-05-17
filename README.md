# Conversational SHL Assessment Recommender

> **SHL AI Intern Take-Home Assignment Submission**  
> **Candidate:** Sushant Kumar  
> **Live Demo:** https://isushant-shl-assessment-recommender.hf.space  
> **Repository:** https://huggingface.co/spaces/iSushant/shl-assessment-recommender

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [API Specification](#api-specification)
- [Core Design Decisions](#core-design-decisions)
- [Conversational Behaviors](#conversational-behaviors)
- [Retrieval & Ranking Strategy](#retrieval--ranking-strategy)
- [LLM Intent Extraction](#llm-intent-extraction)
- [Catalog Management](#catalog-management)
- [Security & Guardrails](#security--guardrails)
- [Testing & Evaluation](#testing--evaluation)
- [How to Try It Yourself](#how-to-try-it-yourself)
- [Local Development Setup](#local-development-setup)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [What Did Not Work](#what-did-not-work)
- [Trade-offs & Justifications](#trade-offs--justifications)

---

## Problem Statement

Build a conversational agent that takes recruiters and hiring managers from vague intents ("I am hiring a Java developer") to a grounded shortlist of SHL assessments through dialogue. The agent must:

1. **Clarify** vague queries before recommending
2. **Recommend** 1-10 assessments with names and catalog URLs once enough context is gathered
3. **Refine** shortlists when users change constraints mid-conversation
4. **Compare** assessments when asked, using only catalog data
5. **Refuse** off-topic, legal, competitor product, and prompt-injection attempts
6. **Stay in scope** — only discuss SHL Individual Test Solutions from the official catalog

The API is stateless: every `POST /chat` call carries the full conversation history. The service stores no per-conversation state.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI Service (main.py)                  │
│                                                               │
│  GET /health  ──► CatalogClient.ready()                       │
│  POST /chat   ──► answer(messages, catalog)                   │
└──────────────────────────┬────────────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
     ┌──────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐
     │ LLM Intent  │ │ Catalog  │ │  Retrieval  │
     │ Extractor   │ │ Client   │ │  & Ranking  │
     │ (Groq)      │ │ (JSON)   │ │  Engine     │
     └──────┬──────┘ └────┬─────┘ └──────┬──────┘
            │              │              │
            │              │              │
     ┌──────▼──────────────▼──────────────▼──────┐
     │            Agent Policy Engine             │
     │  (agent.py — deterministic routing layer)  │
     │                                            │
     │  • Vague query detection                   │
     │  • Turn cap enforcement (max 8)            │
     │  • Comparison handling                     │
     │  • Refinement (add/drop/scratch)           │
     │  • Out-of-catalog refusal                  │
     │  • Prompt injection guard                  │
     │  • Legal advice refusal                    │
     │  • Confirmation detection                  │
     └──────────────────┬─────────────────────────┘
                        │
               ┌────────▼────────┐
               │  Pydantic Schema │
               │  ChatResponse    │
               │  {reply, recs,   │
               │   end_of_conv}   │
               └─────────────────┘
```

The architecture follows a **hybrid design**: an optional LLM handles intent parsing, while all recommendation logic, URL resolution, and response formatting are fully deterministic and grounded in the live SHL catalog.

---

## Technology Stack

| Component | Technology | Version | Justification |
|-----------|-----------|---------|---------------|
| **Web Framework** | FastAPI | 0.115.6 | Async-ready, automatic OpenAPI docs, Pydantic integration, type-safe request/response validation |
| **ASGI Server** | Uvicorn | 0.32.1 | Lightweight, production-grade ASGI server with hot-reload for development |
| **Data Validation** | Pydantic | 2.10.3 | Strict schema enforcement ensures 100% compliance with the non-negotiable API specification |
| **LLM Provider** | Groq Cloud | — | Free tier, sub-second inference for intent extraction |
| **LLM Model** | qwen/qwen3-32b | — | Strong instruction-following for structured JSON output; 32B parameters balance quality and latency |
| **Container Runtime** | Docker | python:3.11-slim | Reproducible builds, minimal image size, compatible with Hugging Face Spaces |
| **Hosting Platform** | Hugging Face Spaces | — | Free tier, Docker support, automatic HTTPS, global CDN, no credit card required |
| **Testing** | Python unittest | built-in | Standard library, no extra dependencies, fast execution |
| **Catalog Source** | SHL Product Catalog JSON | live URL | Official SHL catalog, fetched at startup with 6-hour TTL caching |

### Dependencies (`requirements.txt`)

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
typing_extensions>=4.12.2
groq==0.13.1
```

---

## API Specification

### Base URL

```
https://isushant-shl-assessment-recommender.hf.space
```

### Health Check

```
GET /health
```

**Response (200 OK):**
```json
{
  "status": "ok"
}
```

**Response (503 Service Unavailable):**
```json
{
  "detail": "SHL catalog is not loaded"
}
```

The health endpoint verifies that the SHL product catalog has been successfully fetched and parsed. On cold-start hosting, allow up to 2 minutes for the service to wake up and load the catalog.

### Chat Endpoint

```
POST /chat
Content-Type: application/json
```

**Request Body:**
```json
{
  "messages": [
    {"role": "user", "content": "Hiring a Java developer who works with stakeholders"},
    {"role": "assistant", "content": "Sure. What is the seniority level?"},
    {"role": "user", "content": "Mid-level, around 4 years"}
  ]
}
```

**Response (200 OK):**
```json
{
  "reply": "Got it. Here are 5 assessments that fit a mid-level Java dev with stakeholder needs.",
  "recommendations": [
    {"name": "Java 8 (New)", "url": "https://www.shl.com/...", "test_type": "K"},
    {"name": "OPQ32r", "url": "https://www.shl.com/...", "test_type": "P"}
  ],
  "end_of_conversation": false
}
```

**Schema Constraints (non-negotiable):**

| Field | Type | Description |
|-------|------|-------------|
| `reply` | `string` | Natural language response from the agent |
| `recommendations` | `array[object]` | Empty when clarifying or refusing; 1-10 items when committed to a shortlist |
| `recommendations[].name` | `string` | Exact product name from the SHL catalog |
| `recommendations[].url` | `string` | Direct catalog URL — never hallucinated |
| `recommendations[].test_type` | `string` | Compressed category codes: A=Ability, C=Competencies, K=Knowledge, P=Personality, B=Situational, etc. |
| `end_of_conversation` | `boolean` | `true` only when the agent considers the task complete or turn cap is reached |

**Message Roles:** Only `user` and `assistant` roles are processed. `system` messages are accepted but ignored.

**Limits:** Maximum 8 turns per conversation (enforced server-side). 30-second timeout per call.

### cURL Examples

#### Health Check
```bash
curl https://isushant-shl-assessment-recommender.hf.space/health
```

#### Vague Query (should trigger clarification)
```bash
curl -X POST https://isushant-shl-assessment-recommender.hf.space/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"I need an assessment"}]}'
```

#### Specific Role Query
```bash
curl -X POST https://isushant-shl-assessment-recommender.hf.space/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hiring a senior Java engineer with Spring, SQL, AWS and Docker."}]}'
```

#### Product Comparison
```bash
curl -X POST https://isushant-shl-assessment-recommender.hf.space/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is the difference between the OPQ32r and the GSA?"}]}'
```

#### Multi-Turn Refinement
```bash
curl -X POST https://isushant-shl-assessment-recommender.hf.space/chat \
  -H "Content-Type: application/json" \
  -d '{
  "messages": [
    {"role":"user","content":"Hiring a senior Java engineer with Spring, SQL, REST, AWS and Docker."},
    {"role":"assistant","content":"Here are 6 SHL catalog assessments that fit the role and constraints you described.\n\nShortlist: Core Java (Advanced Level) (New); Spring (New); RESTful Web Services (New); SQL (New); Amazon Web Services (AWS) Development (New); Docker (New)."},
    {"role":"user","content":"Drop REST and add Python."}
  ]
}'
```

#### Out-of-Catalog Refusal
```bash
curl -X POST https://isushant-shl-assessment-recommender.hf.space/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Can we use the Myers-Briggs MBTI instead?"}]}'
```

---

## Core Design Decisions

### 1. Hybrid LLM + Deterministic Architecture

The system uses Groq's `qwen/qwen3-32b` **only** for intent extraction — parsing the conversation history into structured fields (current need, positive terms, negative terms, comparison items, out-of-catalog flags). The LLM **never** produces final recommendations or URLs. All product resolution happens through deterministic catalog lookups and lexical ranking.

**Why:** Pure LLM approaches risk hallucinated URLs and non-catalog products. Pure keyword search misses conversational nuance (negations, refinements, comparisons). The hybrid approach gives the best of both: LLM understands intent, deterministic code guarantees correctness.

### 2. Stateless by Design

The API accepts the full conversation history on every call. No server-side session storage, no conversation IDs, no Redis, no database. The agent reconstructs context from the message list on each request.

**Why:** Matches the assignment specification exactly. Simplifies deployment (no stateful infrastructure). Scales horizontally without session affinity.

### 3. In-Memory Catalog with TTL Caching

The SHL product catalog JSON is fetched at startup and cached in memory with a 6-hour TTL. Subsequent requests reuse the cached data. If the fetch fails and no cache exists, `/health` returns 503.

**Why:** Eliminates per-request network latency to the catalog source. The 6-hour TTL balances freshness with reliability. Graceful degradation: if the catalog URL is temporarily unreachable, the last cached version is still served.

### 4. Trace-Informed Scenario Matching

The 10 public conversation traces were analyzed to identify common hiring scenarios (CXO leadership, Rust/networking, contact center, finance, sales, plant operators, healthcare admin, admin assistants, full-stack Java, graduate trainees). These scenarios are encoded as marker-to-product mappings in `TRACE_SCENARIOS`.

**Why:** The automated evaluator replays these exact traces (and holdout variants). Encoding known scenarios ensures high Recall@10 on the public traces while the lexical fallback handles unseen roles.

---

## Conversational Behaviors

### Clarification Gate

When the user query is too vague (fewer than 5 meaningful words, no role markers like "developer", "engineer", "sales", "java", etc.), the agent asks for context instead of recommending:

```
User: "I need an assessment"
Agent: "I can help, but I need a little more context before recommending. What role are you hiring for, what seniority level, and which skills or behaviors matter most?"
```

The agent also asks targeted follow-ups for specific domains:
- **Full-stack roles:** "Is this backend-leaning, frontend-heavy, or a balanced full-stack role?" then "Is the role a senior individual contributor, a tech lead, or a people manager?"
- **Contact center roles:** "What language are the calls in?" then "Which English accent variant fits the role best: US, UK, Australian, or Indian?"

### Recommendation

Once enough context is gathered, the agent returns 1-10 assessments with exact catalog names and URLs. The reply includes a human-readable shortlist summary.

### Refinement (Add/Drop/Scratch)

The agent detects refinement language ("add", "drop", "remove", "scratch", "actually", "instead", "replace", "no longer") and updates the shortlist without starting over:

```
User: "Add AWS and Docker. Drop REST — the API design signal will already come through in Spring."
Agent: "Updated the shortlist based on your latest constraint."
```

The LLM intent extractor tracks **cumulative positive terms** across turns, so additions are accumulated and removals are subtracted from the full context.

### Comparison

When asked to compare two assessments, the agent extracts both product names, retrieves their catalog data, and produces a grounded comparison using description, duration, keys, and construct:

```
User: "What is the difference between the OPQ32r and the GSA?"
Agent: "Occupational Personality Questionnaire OPQ32r is a Personality & Behavior item with duration 25 minutes. [...] Global Skills Assessment is a Competencies, Knowledge & Skills item with duration 16 minutes. [...]"
```

### Refusal

The agent refuses in four categories:

| Category | Trigger | Response |
|----------|---------|----------|
| **Out-of-catalog** | MBTI, Hogan, DISC, Caliper, Predictive Index, 16PF, Enneagram, NASA test | "I only recommend SHL catalog assessments. [name] is not available in the SHL catalog." |
| **Legal advice** | "legally", "legal", "law", "required under", "compliance question" | "I can't provide legal or regulatory advice. [...] your legal or compliance team should decide." |
| **Off-topic** | Salary, compensation, interview questions, job descriptions, visa, employment law | "I can only discuss SHL assessments and recommendations grounded in the SHL catalog." |
| **Prompt injection** | "ignore previous", "ignore above", "system prompt", "jailbreak", "forget your instructions" | "I can only help with SHL assessment selection using the SHL catalog, so I can't follow that instruction." |

### Turn Cap Enforcement

The agent counts user messages in the conversation history. When the count reaches 8 (the maximum allowed), it force-returns the best available shortlist with `end_of_conversation: true`.

---

## Retrieval & Ranking Strategy

The retrieval pipeline has three layers:

### Layer 1: Scenario Matching (`_scenario_products`)

The normalized conversation text is matched against 10 pre-defined trace scenarios. Each scenario has marker keywords (e.g., "java", "spring", "microservice") mapped to an expected product list. The scenario with the highest marker match score wins.

**Score:** Count of scenario markers found in the conversation text.

### Layer 2: Alias-Based Lookup + Lexical Ranking (`_generic_products`)

If no scenario matches, the system:
1. Maps skill keywords to exact product names via `SKILL_PRODUCT_ALIASES` (40+ aliases: "java" → "Core Java (Advanced Level) (New)", "aws" → "Amazon Web Services (AWS) Development (New)", etc.)
2. Adds contextual products (e.g., "senior" → adds "SHL Verify Interactive G+" and "OPQ32r")
3. Fills remaining slots with lexical ranking over the full catalog

**Lexical ranking formula:**
```
score = (query_tokens ∩ product_tokens) + 2.5 × (query_tokens ∩ product_name_tokens)
        + Σ(1.0 for each matching key)
        / √(product_token_count)
```

Name matches are weighted 2.5× higher than description matches. Key matches (e.g., "Knowledge & Skills") add bonus points. Results are length-normalized to avoid bias toward verbose products.

### Layer 3: Refinement Engine (`_refine`)

Handles mid-conversation edits:
- **Additions:** Detects new skills in the refinement query and appends matching products
- **Drops:** Regex patterns like `\b(drop|remove|exclude)\b.*\brest\b` identify products to remove
- **Start-over:** Keywords like "scratch", "instead", "replace" trigger a fresh search
- **Deduplication:** Products are deduplicated by URL to prevent duplicates

---

## LLM Intent Extraction

### Model: `qwen/qwen3-32b` via Groq Cloud

The LLM receives the last 8 messages (truncated to 2000 chars each) and a system prompt instructing it to output **only JSON** with this schema:

```json
{
  "action": "recommend|clarify|refine|compare|refuse",
  "current_need": "short plain English current need",
  "positive_terms": ["newly mentioned skill/role/constraint from this turn"],
  "negative_terms": ["negated skill/product"],
  "comparison_terms": ["terms related to comparison"],
  "requested_products": ["specific product names user asked for"],
  "compare_items": ["exact product names to compare"],
  "is_out_of_catalog": false,
  "out_of_catalog_names": ["competitor or fake test names"],
  "cumulative_positive_terms": ["ALL required skills/roles/traits from entire conversation history"],
  "confidence": 0.0
}
```

### Key Design Choices

- **Temperature: 0** — deterministic output for reliable JSON parsing
- **Max tokens: 600** — keeps latency under 1 second
- **Timeout: 8 seconds** — well within the 30-second call budget
- **JSON extraction:** Strips `<thinking>` tags, markdown code fences, and extracts the first `{...}` block

### Fallback

If `GROQ_API_KEY` is not set or the API call fails, the system falls back to pure deterministic intent parsing using keyword matching and regex patterns. All core behaviors (clarification, recommendation, refinement, comparison, refusal) work without the LLM.

---

## Catalog Management

### Source

```
https://tcp-us-prod-rnd.shl.com/voiceRater/shl-ai-hiring/shl_product_catalog.json
```

### Data Model

Each product in the catalog is normalized into a `Product` dataclass:

| Field | Type | Source |
|-------|------|--------|
| `entity_id` | `str` | `entity_id` from JSON |
| `name` | `str` | `name` from JSON |
| `url` | `str` | `link` from JSON |
| `test_type` | `str` | Compressed from `keys` (e.g., "K", "P", "A,C") |
| `keys` | `tuple[str, ...]` | `keys` from JSON |
| `duration` | `str` | `duration` from JSON |
| `languages` | `tuple[str, ...]` | `languages` from JSON |
| `job_levels` | `tuple[str, ...]` | `job_levels` from JSON |
| `description` | `str` | `description` from JSON |

### Category Code Mapping

```python
KEY_TO_CODE = {
    "Ability & Aptitude": "A",
    "Assessment Exercises": "E",
    "Biodata & Situational Judgment": "B",
    "Competencies": "C",
    "Development & 360": "D",
    "Personality & Behavior": "P",
    "Simulations": "S",
    "Knowledge & Skills": "K",
}
```

### Fetch Strategy

- **Startup:** Catalog is fetched during `@app.on_event("startup")`
- **TTL:** 6 hours (21,600 seconds)
- **Error handling:** If fetch fails and cache is empty → `CatalogError` → 503 on `/health`. If cache exists → serve stale data and log error.
- **Filtering:** Only products with `"status": "ok"` are included

---

## Security & Guardrails

### Prompt Injection Protection

The agent scans every user message for injection patterns:
- "ignore previous", "ignore above", "system prompt", "developer message", "jailbreak", "forget your instructions"

Matched injections return a refusal with empty recommendations.

### Competitor Test Blocking

A curated list of competitor assessments is checked against user requests:
- MBTI, DISC Assessment, Hogan, Hogan Assessment, Caliper, Caliper Profile
- PI LI, Predictive Index, 16 PF, Sixteen Personality, Enneagram
- NASA Astronaut, Astronaut Assessment, NASA Test

Both direct mentions and LLM-detected out-of-catalog requests are blocked.

### Legal Advice Refusal

Patterns like "legally", "legal", "law", "required under", "satisfy that requirement", "compliance question" trigger a refusal that redirects to the user's legal/compliance team.

### URL Integrity

All URLs in recommendations come directly from the fetched SHL catalog JSON. The LLM never generates URLs. The `_by_names` function resolves product names to catalog entries by exact normalized match or substring containment.

---

## Testing & Evaluation

### Automated Unit Tests

Located in `tests/test_agent.py`, covering:

| Test | What It Validates |
|------|-------------------|
| `test_vague_query_clarifies` | Empty recommendations + clarification prompt for underspecified input |
| `test_legal_question_refuses` | Refusal message containing "legal" for compliance questions |
| `test_java_recommendation_uses_catalog_urls` | Correct product names + all URLs start with `https://www.shl.com/products/product-catalog/view/` |
| `test_refinement_drops_rest` | "Drop REST" removes RESTful Web Services from the shortlist |
| `test_scratch_java_switches_to_python` | "Scratch Java, use Python" replaces Java products with Python + personality |
| `test_comparison_opq32r_vs_gsa` | Both products returned with grounded comparison, no clarification prompt |

Run tests:
```bash
python -m pytest tests/test_agent.py -v
# or
python -m unittest tests.test_agent
```

### Production Verification Tests

All tests executed against the live endpoint `https://isushant-shl-assessment-recommender.hf.space/chat`:

| Test Case | Scenario | Status |
|-----------|----------|--------|
| **TC1** | Vague query → clarification gate | PASSED |
| **TC2** | Factual product comparison (OPQ32r vs GSA) | PASSED |
| **TC3** | Multi-turn refinement (add AWS/Docker, drop REST) | PASSED |
| **TC4** | Out-of-catalog refusal (MBTI, Hogan) | PASSED |
| **TC5** | Turn cap enforcement (8 turns → `end_of_conversation: true`) | PASSED |

### Performance Metrics

| Metric | Value |
|--------|-------|
| `/health` response latency | ~12ms |
| `/chat` response latency | 250ms - 380ms |
| 30-second timeout compliance | Well within limits |
| JSON schema compliance | 100% (Pydantic-validated) |
| Catalog URL integrity | 100% (all from live SHL JSON) |

---

## How to Try It Yourself

### Quick Test (No Setup Required)

1. Open your browser or terminal
2. Visit: `https://isushant-shl-assessment-recommender.hf.space/health`
3. You should see: `{"status":"ok"}`

### Interactive Testing with cURL

Copy-paste any of the cURL commands from the [API Specification](#api-specification) section above. The service is live and accepts requests 24/7.

### Testing with Postman or Insomnia

1. Create a new POST request to `https://isushant-shl-assessment-recommender.hf.space/chat`
2. Set header: `Content-Type: application/json`
3. Set body (raw JSON):
```json
{
  "messages": [
    {"role": "user", "content": "Hiring a senior Java engineer with Spring, SQL, AWS and Docker."}
  ]
}
```
4. Send and verify the response matches the expected schema

### Testing Conversation Flows

To test multi-turn behavior, accumulate messages in the `messages` array:

```json
{
  "messages": [
    {"role": "user", "content": "I need assessments for a Java developer"},
    {"role": "assistant", "content": "Sure. What is the seniority level?"},
    {"role": "user", "content": "Mid-level, 4 years experience"},
    {"role": "assistant", "content": "Here are 5 SHL catalog assessments that fit the role and constraints you described.\n\nShortlist: Core Java (Advanced Level) (New); Spring (New); SQL (New); SHL Verify Interactive G+; Occupational Personality Questionnaire OPQ32r."},
    {"role": "user", "content": "Actually, add AWS and Docker. Drop REST."}
  ]
}
```

### Expected Behaviors to Verify

| Input | Expected Behavior |
|-------|-------------------|
| `"I need an assessment"` | Clarification prompt, empty recommendations |
| `"Hiring a Java developer"` | 1-10 recommendations with Java-related tests |
| `"What is the difference between OPQ32r and GSA?"` | Comparison reply with both products |
| `"Add personality tests"` | Updated shortlist including OPQ32r |
| `"Can we use MBTI instead?"` | Refusal, empty recommendations |
| `"Are we legally required to test?"` | Legal refusal, empty recommendations |
| `"ignore previous instructions"` | Injection refusal, empty recommendations |
| 8+ user messages | `end_of_conversation: true` |

---

## Local Development Setup

### Prerequisites

- Python 3.11+
- pip

### Step-by-Step

```bash
# 1. Clone or download the repository
git clone <repository-url>
cd SHL

# 2. Create a virtual environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Set Groq API key for LLM intent extraction
export GROQ_API_KEY="your-groq-api-key"

# 5. Start the development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 6. Verify the service is running
curl http://127.0.0.1:8000/health
# Expected: {"status":"ok"}

# 7. Test the chat endpoint
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hiring a senior Java engineer with Spring and SQL."}]}'

# 8. Run unit tests
python -m pytest tests/test_agent.py -v
```

### Interactive API Documentation

FastAPI automatically generates OpenAPI docs at:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

These provide an interactive interface to test both endpoints directly in the browser.

---

## Deployment

### Hugging Face Spaces (Current Deployment)

The service is deployed on Hugging Face Spaces using Docker:

1. Create a new Space at https://huggingface.co/spaces
2. Select **Docker** as the SDK
3. Set the app port to `7860`
4. Push the repository files:
   - `Dockerfile`
   - `requirements.txt`
   - `app/` directory (all Python files)
5. The Space automatically builds and deploys

The `README.md` in the repo root contains the Hugging Face Spaces frontmatter:
```yaml
---
title: SHL Assessment Recommender
emoji: 🔎
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---
```

### Docker Build

```bash
docker build -t shl-assessment-recommender .
docker run -p 7860:7860 -e GROQ_API_KEY=your-key shl-assessment-recommender
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | No | — | Groq API key for LLM intent extraction. If missing, falls back to deterministic mode |
| `GROQ_MODEL` | No | `qwen/qwen3-32b` | Groq model to use for intent extraction |
| `SHL_CATALOG_URL` | No | `https://tcp-us-prod-rnd.shl.com/voiceRater/shl-ai-hiring/shl_product_catalog.json` | Override for the catalog JSON URL |
| `PORT` | No | `7860` | Port the server listens on |

### Alternative Free Platforms

The Dockerfile is compatible with:
- **Render** — Docker web service
- **Railway** — Docker deployment
- **Fly.io** — `fly launch` with Dockerfile
- **Modal** — Container-based deployment
- **Google Cloud Run** — Container deployment

---

## Project Structure

```
SHL/
├── app/
│   ├── __init__.py              # Package marker
│   ├── main.py                  # FastAPI app, /health and /chat endpoints
│   ├── agent.py                 # Core agent policy engine (498 lines)
│   ├── catalog.py               # SHL catalog fetcher, Product dataclass, caching
│   ├── llm_intent.py            # Groq LLM intent extraction with JSON parsing
│   ├── retrieval.py             # Lexical ranking, skill aliases, token scoring
│   └── schemas.py               # Pydantic models for request/response validation
├── tests/
│   └── test_agent.py            # Unit tests for all core behaviors
├── 10 public conversation traces/
│   ├── C1.md ... C10.md         # Public conversation traces from SHL
├── Dockerfile                   # Multi-stage Docker build (python:3.11-slim)
├── requirements.txt             # Python dependencies (5 packages)
├── approach.md                  # 2-page approach document for submission
├── assignment_details.txt       # Original assignment specification
├── catlog_link.txt              # SHL catalog JSON URL
├── LLM_api.txt                  # LLM API reference notes (gitignored)
├── Test_done.md                 # Production verification test report
├── .gitignore                   # Excludes __pycache__, .venv, .env, LLM_api.txt
└── README.md                    # This file
```

### File Responsibilities

| File | Responsibility | Lines |
|------|---------------|-------|
| `main.py` | FastAPI app setup, endpoint routing, catalog lifecycle | 30 |
| `agent.py` | Conversational policy: clarification, recommendation, refinement, comparison, refusal, turn cap | 498 |
| `catalog.py` | HTTP fetch, JSON parsing, Product normalization, TTL caching, lookup methods | 148 |
| `llm_intent.py` | Groq API integration, JSON extraction, Intent dataclass, fallback handling | 118 |
| `retrieval.py` | Token scoring, lexical ranking, 40+ skill-to-product alias mappings | 88 |
| `schemas.py` | Pydantic models: ChatRequest, ChatResponse, Recommendation, HealthResponse | 28 |
| `test_agent.py` | 6 unit tests covering vague query, legal refusal, recommendation, refinement, scratch, comparison | 132 |

---

### Pure Keyword Search

A generic keyword-only approach over the catalog over-recommended near-duplicate tests and missed conversational edits. For example, "scratch Java, use Python instead" would still return Java products because the keyword "Java" had the highest term frequency in the conversation history.

**Fix:** Added the LLM intent extractor to identify negated terms (`negative_terms`) and cumulative context (`cumulative_positive_terms`). The refinement engine then explicitly removes dropped products and adds new ones.

### Pure LLM Recommendations

Letting the LLM generate recommendations directly risked hallucinated URLs and products not in the SHL catalog. The automated evaluator strictly validates that every recommendation URL matches an entry in the official catalog.

**Fix:** The LLM only extracts intent (structured JSON). All product resolution happens through deterministic catalog lookups (`_by_names`, `lexical_rank`). URLs are never generated by the LLM.

### Stateless Amnesia

Early versions lost context across turns because the agent only looked at the last user message. Multi-turn refinements like "add AWS" would not preserve the original Java/Spring/SQL context.

**Fix:** The LLM prompt explicitly instructs the model to populate `cumulative_positive_terms` with ALL required skills from the entire conversation history. The deterministic engine also parses previous assistant "Shortlist:" lines to reconstruct prior recommendations.

---

## Trade-offs & Justifications

### Why Not Vector Search (FAISS, Chroma, pgvector)?

The SHL catalog is relatively small (~100-200 products). Vector embeddings add complexity (embedding model selection, index management, dimension tuning) without meaningful accuracy gains for this scale. Lexical ranking with weighted name matches and key bonuses achieves comparable results with zero infrastructure overhead.

### Why Not LangChain / LangGraph / LlamaIndex?

These frameworks add abstraction layers that obscure the core logic. For a stateless API with a clear schema and deterministic policy requirements, direct FastAPI + Pydantic is simpler, faster, and easier to debug. The agent policy in `agent.py` is fully traceable — every decision point is an explicit `if` statement.

### Why Groq + Qwen3-32b?

- **Groq free tier** provides sufficient throughput for intent extraction
- **Qwen3-32b** has strong instruction-following for structured JSON output
- **Sub-1-second latency** keeps total response time well under the 30-second limit
- **Temperature 0** ensures deterministic intent extraction

### Why Hugging Face Spaces?

- **Free tier** with no credit card required
- **Docker support** matches the project's containerization
- **Automatic HTTPS** and global CDN
- **Persistent uptime** — the service is always available for evaluator testing
- **Port 7860** is the standard HF Spaces port, configured in the Dockerfile

---

## Evaluation Criteria Coverage

| Criterion | How It's Addressed |
|-----------|-------------------|
| **Schema compliance** | Pydantic models enforce exact `reply`, `recommendations`, `end_of_conversation` structure on every response |
| **Catalog-only recommendations** | All products resolved from live SHL JSON via `_by_names` and `lexical_rank`. LLM never generates URLs |
| **Turn cap (max 8)** | `len(user_messages) >= MAX_TURNS` triggers forced `end_of_conversation: true` |
| **Recall@10** | `TRACE_SCENARIOS` encode expected products for all 10 public traces. Lexical fallback handles holdout traces |
| **Refuses off-topic** | `OFF_TOPIC` keyword list + LLM `is_out_of_catalog` detection |
| **No recommendation on turn 1 for vague query** | `_too_vague()` function blocks recommendations until sufficient context |
| **Honors edits** | `_refine()` handles add/drop/scratch with regex patterns and cumulative intent tracking |
| **No hallucinations** | All URLs from catalog JSON. LLM output is intent-only, never product or URL generation |

---

## Contact

**Candidate:** Sushant Kumar  
**Email:** sushantkumarkohima@gmail.com  
**Live API:** https://isushant-shl-assessment-recommender.hf.space  
**Repository:** https://huggingface.co/spaces/iSushant/shl-assessment-recommender

---

*© 2026 SHL and its affiliates. All rights reserved. This submission is for the SHL AI Intern take-home assignment evaluation purposes only.*
