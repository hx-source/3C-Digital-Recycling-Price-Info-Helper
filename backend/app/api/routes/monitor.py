from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entities import MarketMonitorRun, MonitorRunStatus
from app.schemas.quotes import MarketFindingActionRequest, MarketFindingApplyRequest, MarketMonitorFindingRead, MarketMonitorRunRead
from app.services.market_monitor_service import create_monitor_run, run_market_monitor
from app.services.market_remediation_service import FindingActionError, apply_finding_price, diagnose_finding, dismiss_finding


router = APIRouter()


@router.get("/runs", response_model=list[MarketMonitorRunRead])
def list_monitor_runs(limit: int = 20, db: Session = Depends(get_db)) -> list[MarketMonitorRun]:
    return list(db.scalars(select(MarketMonitorRun).order_by(MarketMonitorRun.created_at.desc()).limit(min(max(limit, 1), 50))))


@router.get("/runs/latest", response_model=MarketMonitorRunRead | None)
def latest_monitor_run(db: Session = Depends(get_db)) -> MarketMonitorRun | None:
    return db.scalar(select(MarketMonitorRun).order_by(MarketMonitorRun.created_at.desc()).limit(1))


@router.get("/runs/{run_id}", response_model=MarketMonitorRunRead)
def get_monitor_run(run_id: str, db: Session = Depends(get_db)) -> MarketMonitorRun:
    run = db.get(MarketMonitorRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="监控任务不存在")
    return run


@router.post("/runs", response_model=MarketMonitorRunRead, status_code=status.HTTP_202_ACCEPTED)
def start_monitor_run(background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> MarketMonitorRun:
    active = db.scalar(select(MarketMonitorRun).where(
        MarketMonitorRun.status.in_([MonitorRunStatus.QUEUED, MonitorRunStatus.RUNNING])
    ).order_by(MarketMonitorRun.created_at.desc()).limit(1))
    if active:
        return active
    run = create_monitor_run(db, batch_id=None, trigger_type="manual")
    background_tasks.add_task(run_market_monitor, run.id)
    return run


@router.post("/findings/{finding_id}/diagnose", response_model=MarketMonitorFindingRead)
def diagnose_monitor_finding(finding_id: int, db: Session = Depends(get_db)):
    try:
        return diagnose_finding(db, finding_id)
    except FindingActionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/findings/{finding_id}/apply", response_model=MarketMonitorFindingRead)
def apply_monitor_finding(
    finding_id: int,
    payload: MarketFindingApplyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        finding = apply_finding_price(db, finding_id, payload.proposed_price, payload.proposed_price_status, payload.reason)
        rerun = create_monitor_run(db, batch_id=None, trigger_type="remediation")
        background_tasks.add_task(run_market_monitor, rerun.id)
        return finding
    except FindingActionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/findings/{finding_id}/dismiss", response_model=MarketMonitorFindingRead)
def dismiss_monitor_finding(
    finding_id: int,
    payload: MarketFindingActionRequest,
    db: Session = Depends(get_db),
):
    try:
        return dismiss_finding(db, finding_id, payload.reason)
    except FindingActionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
