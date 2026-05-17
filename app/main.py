from fastapi import FastAPI, HTTPException

from app.agent import answer
from app.catalog import CatalogClient, CatalogError
from app.schemas import ChatRequest, ChatResponse, HealthResponse


catalog = CatalogClient()
app = FastAPI(title="Conversational SHL Assessment Recommender", version="1.0.0")


@app.on_event("startup")
def load_catalog_on_startup() -> None:
    catalog.ready()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    if not catalog.ready():
        raise HTTPException(status_code=503, detail="SHL catalog is not loaded")
    return HealthResponse(status="ok")


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        messages = [message.model_dump() for message in request.messages]
        return answer(messages, catalog)
    except CatalogError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
