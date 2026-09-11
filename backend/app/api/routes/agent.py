from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.entities import AgentConversation, AgentConversationMessage
from app.schemas.quotes import (
    AgentChatRequest,
    AgentChatResponse,
    AgentConversationRead,
    AgentMessage,
    CandidateRead,
    ImportAgentSummaryRequest,
    ImportAgentSummaryResponse,
    ReviewBatchApproveSafeRequest,
    ReviewBatchApproveSafeResponse,
    ReviewBatchDiagnosisResponse,
    ReviewDiagnosisApplyRequest,
    ReviewDiagnosisApplyResponse,
    ReviewDiagnosisResponse,
    ReviewQualityStatsResponse,
    ReviewSampleCreateRequest,
    ReviewSampleDecisionRequest,
    ReviewSampleQueueResponse,
    ReviewSampleRead,
)
from app.services.agent_service import AgentUnavailableError, ask_market_agent, summarize_import_agent
from app.services.review_agent_service import (
    ReviewBatchNotFoundError,
    ReviewCandidateNotFoundError,
    ReviewDiagnosisApplyError,
    ReviewDiagnosisConflictError,
    approve_safe_review_batch,
    apply_review_diagnosis,
    diagnose_review_batch,
    diagnose_review_candidate,
    revoke_auto_approval,
)
from app.services.review_quality_service import create_review_sample, decide_review_sample, list_review_samples, review_quality_stats


router = APIRouter()


@router.get("/conversations", response_model=list[AgentConversationRead])
def list_agent_conversations(db: Session = Depends(get_db)) -> list[AgentConversation]:
    return list(db.scalars(select(AgentConversation).order_by(AgentConversation.updated_at.desc()).limit(30)))


@router.post("/conversations", response_model=AgentConversationRead, status_code=status.HTTP_201_CREATED)
def create_agent_conversation(db: Session = Depends(get_db)) -> AgentConversation:
    conversation = AgentConversation(id=str(uuid4()), title="新行情问答", memory={})
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_conversation(conversation_id: str, db: Session = Depends(get_db)) -> None:
    conversation = db.get(AgentConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")
    db.delete(conversation)
    db.commit()


@router.post("/chat", response_model=AgentChatResponse)
def chat(request: AgentChatRequest, db: Session = Depends(get_db)) -> AgentChatResponse:
    conversation = db.get(AgentConversation, request.conversation_id) if request.conversation_id else None
    if request.conversation_id and not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")
    if not conversation:
        conversation = AgentConversation(id=str(uuid4()), title=request.question[:18], memory={})
        db.add(conversation)
        db.flush()
    stored_history = [AgentMessage(role=item.role, content=item.content) for item in conversation.messages[-10:]]
    effective_request = request.model_copy(update={"history": stored_history or request.history})
    try:
        answer, sources, tools_used, memory = ask_market_agent(db, effective_request, conversation.memory)
    except AgentUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if conversation.title == "新行情问答":
        conversation.title = request.question[:18]
    conversation.memory = memory
    conversation.updated_at = datetime.now()
    db.add_all([
        AgentConversationMessage(conversation_id=conversation.id, role="user", content=request.question),
        AgentConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            sources=[item.model_dump() for item in sources],
            tools_used=tools_used,
        ),
    ])
    db.commit()
    return AgentChatResponse(
        answer=answer, sources=sources, tools_used=tools_used, model=settings.ollama_model,
        conversation_id=conversation.id, memory=memory,
    )


@router.post("/import-summary", response_model=ImportAgentSummaryResponse)
def import_summary(request: ImportAgentSummaryRequest) -> ImportAgentSummaryResponse:
    summary, recommendations, generated_by_model = summarize_import_agent(request)
    return ImportAgentSummaryResponse(
        summary=summary,
        recommendations=recommendations,
        generated_by_model=generated_by_model,
        model=settings.ollama_model,
    )


@router.post("/review-diagnose/{candidate_id}", response_model=ReviewDiagnosisResponse)
def review_diagnose(candidate_id: int, db: Session = Depends(get_db)) -> ReviewDiagnosisResponse:
    try:
        return diagnose_review_candidate(db, candidate_id)
    except ReviewCandidateNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/review-diagnose/{candidate_id}/apply", response_model=ReviewDiagnosisApplyResponse)
def review_diagnosis_apply(
    candidate_id: int,
    request: ReviewDiagnosisApplyRequest,
    db: Session = Depends(get_db),
) -> ReviewDiagnosisApplyResponse:
    try:
        return apply_review_diagnosis(db, candidate_id, request)
    except ReviewCandidateNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ReviewDiagnosisConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ReviewDiagnosisApplyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/review-diagnose/batches/{batch_id}", response_model=ReviewBatchDiagnosisResponse)
def review_batch_diagnose(batch_id: int, db: Session = Depends(get_db)) -> ReviewBatchDiagnosisResponse:
    try:
        return diagnose_review_batch(db, batch_id)
    except ReviewBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/review-diagnose/batches/{batch_id}/approve-safe",
    response_model=ReviewBatchApproveSafeResponse,
)
def review_batch_approve_safe(
    batch_id: int,
    request: ReviewBatchApproveSafeRequest,
    db: Session = Depends(get_db),
) -> ReviewBatchApproveSafeResponse:
    try:
        return approve_safe_review_batch(db, batch_id, request)
    except ReviewBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ReviewDiagnosisConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ReviewDiagnosisApplyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/review-diagnose/{candidate_id}/revoke-auto-approval", response_model=CandidateRead)
def review_revoke_auto_approval(
    candidate_id: int,
    db: Session = Depends(get_db),
) -> CandidateRead:
    try:
        return CandidateRead.model_validate(revoke_auto_approval(db, candidate_id))
    except ReviewCandidateNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ReviewDiagnosisApplyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/review-quality/batches/{batch_id}/samples", response_model=ReviewSampleQueueResponse)
def generate_review_samples(
    batch_id: int,
    request: ReviewSampleCreateRequest,
    db: Session = Depends(get_db),
) -> ReviewSampleQueueResponse:
    try:
        return create_review_sample(db, batch_id, request.count)
    except ReviewBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/review-quality/batches/{batch_id}/samples", response_model=list[ReviewSampleRead])
def get_review_samples(batch_id: int, db: Session = Depends(get_db)) -> list[ReviewSampleRead]:
    try:
        return [ReviewSampleRead.model_validate(item) for item in list_review_samples(db, batch_id)]
    except ReviewBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/review-quality/samples/{sample_id}/decision", response_model=ReviewSampleRead)
def submit_review_sample_decision(
    sample_id: int,
    request: ReviewSampleDecisionRequest,
    db: Session = Depends(get_db),
) -> ReviewSampleRead:
    try:
        return ReviewSampleRead.model_validate(decide_review_sample(db, sample_id, request.decision, request.note))
    except ReviewDiagnosisApplyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/review-quality/batches/{batch_id}/stats", response_model=ReviewQualityStatsResponse)
def get_review_quality_stats(batch_id: int, db: Session = Depends(get_db)) -> ReviewQualityStatsResponse:
    try:
        return review_quality_stats(db, batch_id)
    except ReviewBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
