from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas.quotes import AgentChatRequest, AgentChatResponse, ImportAgentSummaryRequest, ImportAgentSummaryResponse
from app.services.agent_service import AgentUnavailableError, ask_market_agent, summarize_import_agent


router = APIRouter()


@router.post("/chat", response_model=AgentChatResponse)
def chat(request: AgentChatRequest, db: Session = Depends(get_db)) -> AgentChatResponse:
    try:
        answer, sources, tools_used = ask_market_agent(db, request)
    except AgentUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return AgentChatResponse(answer=answer, sources=sources, tools_used=tools_used, model=settings.ollama_model)


@router.post("/import-summary", response_model=ImportAgentSummaryResponse)
def import_summary(request: ImportAgentSummaryRequest) -> ImportAgentSummaryResponse:
    summary, recommendations, generated_by_model = summarize_import_agent(request)
    return ImportAgentSummaryResponse(
        summary=summary,
        recommendations=recommendations,
        generated_by_model=generated_by_model,
        model=settings.ollama_model,
    )
