from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse

from financial_research_agent.api_models import (
    AnalyzeResponse,
    AnalyzeRequest,
    ApiError,
    ErrorResponse,
    HealthComponent,
    HealthResponse,
    RuntimeMetadata,
    ToolStatus,
    MemoryDeleteRequest,
    MemoryListResponse,
    MemoryVersionsResponse,
    PreferenceWriteRequest,
    JobCreateRequest,
    JobCreateResponse,
    JobEventsResponse,
    JobStatusResponse,
    SessionMemoryDeleteRequest,
)
from financial_research_agent.config import Settings, get_settings
from financial_research_agent.domain.models import ToolName
from financial_research_agent.jobs.models import AdmissionRejected
from financial_research_agent.security.identity import (
    require_admin,
    resolve_identity,
)
from financial_research_agent.observability import configure_logging, log_event
from financial_research_agent.orchestration.factory import build_formal_registry
from financial_research_agent.research import ResearchRunResult
from financial_research_agent.research_factory import ResearchRuntime, build_research_service
from financial_research_agent.repositories.iceberg import IcebergRepository

VERSION = "0.1.0"
logger = logging.getLogger("financial_research_agent.api")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="Financial Research Agent", version=VERSION)

    @application.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid4().hex
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except asyncio.CancelledError:
            log_event(logger, "request_cancelled", request_id=request_id, path=request.url.path)
            raise
        response.headers["x-request-id"] = request_id
        if request.url.path != "/health" or response.status_code >= 400:
            log_event(
                logger,
                "request_completed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        run_id = uuid4().hex
        error = ErrorResponse(
            error=ApiError(
                code="REQUEST_VALIDATION_ERROR",
                message="request body is invalid",
                run_id=run_id,
                details={
                    "errors": [
                        {"location": item["loc"], "message": item["msg"], "type": item["type"]}
                        for item in exc.errors()
                    ]
                },
            )
        )
        log_event(logger, "request_validation_failed", run_id=run_id, path=request.url.path)
        return JSONResponse(status_code=422, content=error.model_dump(mode="json"))

    @application.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        active_settings = _settings(request.app)
        if hasattr(request.app.state, "health_override"):
            return request.app.state.health_override
        components = await _health_components(active_settings)
        model_configured = bool(
            active_settings.model_name
            and active_settings.model_api_key
            and active_settings.model_base_url
        )
        ready = all(item.status == "ready" for item in components.values())
        return HealthResponse(
            status="ready" if ready and model_configured else "degraded",
            version=VERSION,
            model_configured=model_configured,
            components=components,
        )

    @application.get("/demo", response_class=HTMLResponse)
    async def demo(request: Request) -> str:
        if not _settings(request.app).demo_ui_enabled:
            raise HTTPException(status_code=404, detail="DEMO_UI_DISABLED")
        from financial_research_agent.demo_ui import DEMO_HTML

        return DEMO_HTML

    @application.get("/tools")
    async def tools(request: Request) -> dict:
        resolve_identity(request, _settings(request.app))
        registry = _registry(request.app)
        return {"tools": registry.schemas()}

    @application.post(
        "/runs", response_model=JobCreateResponse, status_code=202
    )
    async def create_run(
        payload: JobCreateRequest,
        request: Request,
        idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key"
        ),
    ) -> JobCreateResponse:
        identity = resolve_identity(request, _settings(request.app))
        key = idempotency_key or uuid4().hex
        if len(key) > 128:
            raise HTTPException(
                status_code=422, detail="IDEMPOTENCY_KEY_TOO_LONG"
            )
        try:
            job, created = await _job_store(request.app).enqueue(
                question=payload.question,
                tenant_id=identity.tenant_id,
                user_id=identity.user_id,
                session_id=payload.session_id,
                idempotency_key=key,
                queue_class=payload.queue_class,
            )
        except AdmissionRejected as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={
                    "code": exc.code,
                    "retryable": True,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JobCreateResponse(job=job, created=created)

    @application.get(
        "/runs/{run_id}", response_model=JobStatusResponse
    )
    async def get_run(
        run_id: str, request: Request
    ) -> JobStatusResponse:
        identity = resolve_identity(request, _settings(request.app))
        scope = _identity_job_scope(identity)
        job = await _job_store(request.app).get(run_id, **scope)
        if job is None:
            raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
        result_payload = await _job_store(request.app).result(
            run_id, **scope
        )
        return JobStatusResponse(
            job=job,
            result=(
                AnalyzeResponse.model_validate(result_payload)
                if result_payload
                else None
            ),
        )

    @application.get("/runs/{run_id}/events")
    async def stream_run_events(
        run_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(
            default=None, alias="Last-Event-ID"
        ),
    ):
        identity = resolve_identity(request, _settings(request.app))
        scope = _identity_job_scope(identity)
        job = await _job_store(request.app).get(run_id, **scope)
        if job is None:
            raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
        cursor = after
        if last_event_id:
            try:
                cursor = max(cursor, int(last_event_id))
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail="INVALID_LAST_EVENT_ID"
                ) from exc

        async def generate():
            nonlocal cursor
            last_output = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                events = await _job_store(request.app).events(
                    run_id, **scope
                )
                pending = [
                    event for event in events if event.event_id > cursor
                ]
                for event in pending:
                    cursor = event.event_id
                    payload = event.model_dump(mode="json")
                    yield (
                        f"id: {event.event_id}\n"
                        f"event: {event.event_type}\n"
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )
                    last_output = time.monotonic()
                current = await _job_store(request.app).get(
                    run_id, **scope
                )
                if current is None or current.status.value in {
                    "completed",
                    "failed",
                    "cancelled",
                    "interrupted",
                }:
                    return
                if (
                    time.monotonic() - last_output
                    >= _settings(
                        request.app
                    ).job_sse_heartbeat_seconds
                ):
                    yield ": heartbeat\n\n"
                    last_output = time.monotonic()
                await asyncio.sleep(
                    _settings(
                        request.app
                    ).job_sse_poll_interval_seconds
                )

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @application.get(
        "/runs/{run_id}/events.json",
        response_model=JobEventsResponse,
    )
    async def list_run_events(
        run_id: str, request: Request, after: int = Query(default=0, ge=0)
    ) -> JobEventsResponse:
        identity = resolve_identity(request, _settings(request.app))
        try:
            events = await _job_store(request.app).events(
                run_id, **_identity_job_scope(identity)
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JobEventsResponse(
            events=[item for item in events if item.event_id > after]
        )

    @application.post(
        "/runs/{run_id}/cancel", response_model=JobStatusResponse
    )
    async def cancel_run(
        run_id: str, request: Request
    ) -> JobStatusResponse:
        identity = resolve_identity(request, _settings(request.app))
        try:
            job = await _job_store(request.app).request_cancel(
                run_id, **_identity_job_scope(identity)
            )
        except RuntimeError as exc:
            code = 404 if str(exc) == "JOB_NOT_FOUND" else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        return JobStatusResponse(job=job)

    @application.post(
        "/runs/{run_id}/resume",
        response_model=JobStatusResponse,
        status_code=202,
    )
    async def resume_run(
        run_id: str, request: Request
    ) -> JobStatusResponse:
        identity = resolve_identity(request, _settings(request.app))
        try:
            job = await _job_store(request.app).resume(
                run_id, **_identity_job_scope(identity)
            )
        except AdmissionRejected as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={
                    "code": exc.code,
                    "retryable": True,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc
        except RuntimeError as exc:
            code = 404 if str(exc) == "JOB_NOT_FOUND" else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        return JobStatusResponse(job=job)

    @application.get("/runs/{run_id}/trace")
    async def run_trace(run_id: str, request: Request):
        identity = resolve_identity(request, _settings(request.app))
        try:
            return await _job_store(request.app).trace(
                run_id, **_identity_job_scope(identity)
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.get("/skills")
    async def list_skills(request: Request):
        resolve_identity(request, _settings(request.app))
        return {
            "skills": [
                item.model_dump(
                    mode="json",
                    exclude={"prompt_refs"},
                )
                for item in _research_skill_registry(
                    request.app
                ).versions()
                if item.status.value == "ACTIVE"
            ]
        }

    @application.get("/skills/{skill_id}")
    async def get_skill(skill_id: str, request: Request):
        resolve_identity(request, _settings(request.app))
        try:
            item = _research_skill_registry(request.app).get(skill_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return item.model_dump(mode="json", exclude={"prompt_refs"})

    @application.get("/metrics", response_class=PlainTextResponse)
    async def metrics(request: Request) -> str:
        identity = resolve_identity(request, _settings(request.app))
        require_admin(identity)
        values = await _job_store(request.app).metrics()
        lines = [
            "# TYPE financial_agent_jobs gauge",
            *[
                (
                    "financial_agent_jobs"
                    f'{{status="{status}"}} {count}'
                )
                for status, count in sorted(values["jobs"].items())
            ],
            "# TYPE financial_agent_model_calls counter",
            f"financial_agent_model_calls {values['model_calls']}",
            "# TYPE financial_agent_model_tokens counter",
            f"financial_agent_model_tokens {values['model_tokens']}",
            "# TYPE financial_agent_model_cost_microunits counter",
            (
                "financial_agent_model_cost_microunits "
                f"{values['model_cost_microunits']}"
            ),
            "# TYPE financial_agent_tool_calls counter",
            f"financial_agent_tool_calls {values['tool_calls']}",
            "# TYPE financial_agent_admission_total counter",
            *[
                (
                    "financial_agent_admission_total"
                    f'{{outcome="{key}"}} {count}'
                )
                for key, count in sorted(values["admission"].items())
            ],
            "# TYPE financial_agent_oldest_queue_age_seconds gauge",
            (
                "financial_agent_oldest_queue_age_seconds "
                f"{values['oldest_queue_age_seconds']:.3f}"
            ),
            "# TYPE financial_agent_active_workers gauge",
            f"financial_agent_active_workers {values['active_workers']}",
        ]
        return "\n".join(lines) + "\n"

    @application.get("/knowledge/events")
    async def knowledge_events(
        request: Request,
        symbol: str = Query(pattern=r"^\d{6}$"),
        query: str | None = Query(default=None, min_length=2, max_length=200),
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict:
        resolve_identity(request, _settings(request.app))
        if symbol not in _settings(request.app).stock_codes:
            raise HTTPException(status_code=422, detail="STOCK_NOT_ALLOWED")
        records = await _with_knowledge_store(
            _settings(request.app),
            lambda store: store.search_active(
                symbol=symbol,
                query=query,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            ),
        )
        return {
            "records": [item.model_dump(mode="json") for item in records],
            "status_filter": "active",
        }

    @application.get("/memory", response_model=MemoryListResponse)
    async def list_memory(
        request: Request,
        tenant_id: str = "local",
        user_id: str = "local",
        session_id: str = "default",
        kind: str | None = None,
    ) -> MemoryListResponse:
        identity = resolve_identity(request, _settings(request.app))
        from financial_research_agent.memory.models import (
            MemoryKind,
            MemoryScope,
        )

        try:
            resolved_kind = MemoryKind(kind) if kind else None
            records = await _with_memory_manager(
                _settings(request.app),
                lambda manager: manager.list(
                    MemoryScope(
                        tenant_id=identity.tenant_id,
                        user_id=identity.user_id,
                        session_id=session_id,
                    ),
                    kind=resolved_kind,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return MemoryListResponse(records=records)

    @application.post("/memory/preferences")
    async def write_preference(
        payload: PreferenceWriteRequest, request: Request
    ):
        identity = resolve_identity(request, _settings(request.app))
        scope = payload.scope.model_copy(
            update={
                "tenant_id": identity.tenant_id,
                "user_id": identity.user_id,
            }
        )
        try:
            record = await _with_memory_manager(
                _settings(request.app),
                lambda manager: manager.write(
                    scope,
                    payload.candidate(),
                    expected_version=payload.expected_version,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return record

    @application.delete("/memory/{memory_id}")
    async def delete_memory(
        memory_id: str,
        payload: MemoryDeleteRequest,
        request: Request,
    ):
        from financial_research_agent.memory.manager import MemoryNotFound

        identity = resolve_identity(request, _settings(request.app))
        scope = payload.scope.model_copy(
            update={
                "tenant_id": identity.tenant_id,
                "user_id": identity.user_id,
            }
        )

        try:
            return await _with_memory_manager(
                _settings(request.app),
                lambda manager: manager.delete(
                    scope,
                    memory_id,
                    expected_version=payload.expected_version,
                ),
            )
        except MemoryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.get(
        "/memory/{memory_id}/versions",
        response_model=MemoryVersionsResponse,
    )
    async def memory_versions(
        memory_id: str,
        request: Request,
        tenant_id: str = "local",
        user_id: str = "local",
        session_id: str = "default",
    ) -> MemoryVersionsResponse:
        from financial_research_agent.memory.manager import MemoryNotFound
        from financial_research_agent.memory.models import MemoryScope

        identity = resolve_identity(request, _settings(request.app))
        try:
            versions = await _with_memory_manager(
                _settings(request.app),
                lambda manager: manager.versions(
                    MemoryScope(
                        tenant_id=identity.tenant_id,
                        user_id=identity.user_id,
                        session_id=session_id,
                    ),
                    memory_id,
                ),
            )
        except MemoryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return MemoryVersionsResponse(versions=versions)

    @application.post("/memory/cleanup")
    async def cleanup_memory(
        payload: MemoryDeleteRequest, request: Request
    ) -> dict[str, int]:
        identity = resolve_identity(request, _settings(request.app))
        scope = payload.scope.model_copy(
            update={
                "tenant_id": identity.tenant_id,
                "user_id": identity.user_id,
            }
        )
        count = await _with_memory_manager(
            _settings(request.app),
            lambda manager: manager.expire_due(scope=scope),
        )
        return {"expired": count}

    @application.get(
        "/sessions/{session_id}/memory",
        response_model=MemoryListResponse,
    )
    async def session_memory(
        session_id: str,
        request: Request,
        tenant_id: str = "local",
        user_id: str = "local",
    ) -> MemoryListResponse:
        from financial_research_agent.memory.models import MemoryScope

        identity = resolve_identity(request, _settings(request.app))
        records = await _with_memory_manager(
            _settings(request.app),
            lambda manager: manager.list(
                MemoryScope(
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    session_id=session_id,
                )
            ),
        )
        return MemoryListResponse(records=records)

    @application.delete("/sessions/{session_id}/memory")
    async def delete_session_memory(
        session_id: str,
        payload: SessionMemoryDeleteRequest,
        request: Request,
    ) -> dict[str, int]:
        from financial_research_agent.memory.models import MemoryScope

        identity = resolve_identity(request, _settings(request.app))

        scope = MemoryScope(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            session_id=session_id,
        )

        async def delete_all(manager):
            records = await manager.list(scope)
            deleted = 0
            for record in records:
                if record.scope.session_id != session_id:
                    continue
                await manager.delete(
                    scope,
                    record.memory_id,
                    expected_version=record.version,
                )
                deleted += 1
            return deleted

        return {
            "deleted": await _with_memory_manager(
                _settings(request.app), delete_all
            )
        }

    @application.post("/analyze", response_model=AnalyzeResponse)
    async def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
        active_settings = _settings(request.app)
        identity = resolve_identity(request, active_settings)
        if active_settings.analyze_via_jobs:
            key = request.headers.get("idempotency-key") or uuid4().hex
            try:
                job, created = await _job_store(request.app).enqueue(
                    question=payload.question,
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    session_id=payload.session_id,
                    idempotency_key=key,
                    queue_class="interactive",
                )
            except AdmissionRejected as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail={
                        "code": exc.code,
                        "retryable": True,
                        "retry_after_seconds": exc.retry_after_seconds,
                    },
                    headers={"Retry-After": str(exc.retry_after_seconds)},
                ) from exc
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=409, detail=str(exc)
                ) from exc
            deadline = (
                time.monotonic()
                + active_settings.analyze_sync_wait_seconds
            )
            while time.monotonic() < deadline:
                result_payload = await _job_store(request.app).result(
                    job.run_id, **_identity_job_scope(identity)
                )
                if result_payload is not None:
                    return AnalyzeResponse.model_validate(result_payload)
                await asyncio.sleep(
                    min(
                        0.25,
                        active_settings.job_sse_poll_interval_seconds,
                    )
                )
            return JSONResponse(
                status_code=202,
                content=JobCreateResponse(
                    job=(
                        await _job_store(request.app).get(
                            job.run_id, **_identity_job_scope(identity)
                        )
                        or job
                    ),
                    created=created,
                ).model_dump(mode="json"),
                headers={"Location": f"/runs/{job.run_id}"},
            )
        registry = _registry(request.app)
        started = time.perf_counter()
        result = await _service(request.app).analyze(
            payload.question,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            session_id=payload.session_id,
        )
        response = _analyze_response(result, active_settings, registry)
        response.timings["api_total"] = int((time.perf_counter() - started) * 1000)
        log_event(
            logger,
            "research_run_completed",
            run_id=response.run_id,
            success=response.success,
            planner_source=response.planner_source,
            reporting_status=response.reporting_status,
            evidence_count=len(response.evidence),
            tool_status=[item.model_dump() for item in response.tool_status],
            timings=response.timings,
            model_provider=active_settings.model_provider,
            model_name=active_settings.model_name or None,
            orchestration_runtime=active_settings.orchestration_runtime,
            prompt_versions={
                "planner": active_settings.planner_prompt_version,
                "report": active_settings.report_prompt_version,
            },
        )
        return response

    @application.on_event("shutdown")
    async def close_runtime() -> None:
        service = getattr(application.state, "research_service", None)
        close = getattr(service, "aclose", None)
        if close is not None:
            await close()
        job_store = getattr(application.state, "job_store", None)
        if job_store is not None:
            await job_store.close()

    return application


async def _with_memory_manager(settings: Settings, operation):
    if not settings.memory_enabled:
        raise HTTPException(status_code=409, detail="MEMORY_DISABLED")
    from financial_research_agent.memory.manager import MemoryManager
    from financial_research_agent.persistence.database import (
        create_business_engine,
        create_session_factory,
    )

    engine = create_business_engine(settings)
    try:
        manager = MemoryManager(
            create_session_factory(engine),
            session_ttl_seconds=settings.session_memory_ttl_seconds,
            preference_ttl_seconds=settings.preference_memory_ttl_seconds,
            episodic_ttl_seconds=settings.episodic_memory_ttl_seconds,
        )
        return await operation(manager)
    finally:
        await engine.dispose()


async def _with_knowledge_store(settings: Settings, operation):
    from financial_research_agent.knowledge.store import KnowledgeStore
    from financial_research_agent.persistence.database import (
        create_business_engine,
        create_session_factory,
    )

    engine = create_business_engine(settings)
    try:
        return await operation(KnowledgeStore(create_session_factory(engine)))
    finally:
        await engine.dispose()


def _settings(application: FastAPI) -> Settings:
    if not hasattr(application.state, "settings"):
        application.state.settings = get_settings()
    return application.state.settings


def _registry(application: FastAPI):
    if not hasattr(application.state, "registry"):
        application.state.registry = build_formal_registry(_settings(application))
    return application.state.registry


def _service(application: FastAPI) -> ResearchRuntime:
    if not hasattr(application.state, "research_service"):
        application.state.research_service = build_research_service(_settings(application))
    return application.state.research_service


def _job_store(application: FastAPI):
    if not hasattr(application.state, "job_store"):
        from financial_research_agent.jobs.store import JobStore
        from financial_research_agent.persistence.database import (
            create_business_engine,
            create_session_factory,
        )

        settings = _settings(application)
        engine = create_business_engine(settings)
        application.state.job_store = JobStore(
            engine,
            create_session_factory(engine),
            lease_seconds=settings.job_lease_seconds,
            settings=settings,
        )
    return application.state.job_store


def _identity_job_scope(identity) -> dict[str, object]:
    return {
        "tenant_id": identity.tenant_id,
        "user_id": identity.user_id,
        "tenant_admin": identity.role == "admin",
    }


def _research_skill_registry(application: FastAPI):
    if not hasattr(application.state, "research_skill_registry"):
        from financial_research_agent.skills.registry import SkillRegistry

        application.state.research_skill_registry = (
            SkillRegistry.from_builtin_catalog()
        )
    return application.state.research_skill_registry


async def _health_components(settings: Settings) -> dict[str, HealthComponent]:
    async def iceberg_check() -> HealthComponent:
        try:
            repository = IcebergRepository(settings)
            await asyncio.wait_for(asyncio.to_thread(repository.catalog.list_namespaces), timeout=2)
            return HealthComponent(status="ready")
        except Exception as exc:
            return HealthComponent(status="unavailable", detail=type(exc).__name__)

    async def milvus_check() -> HealthComponent:
        try:
            from pymilvus import MilvusClient

            client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
            await asyncio.wait_for(asyncio.to_thread(client.list_collections), timeout=2)
            close = getattr(client, "close", None)
            if close:
                close()
            return HealthComponent(status="ready")
        except Exception as exc:
            return HealthComponent(status="unavailable", detail=type(exc).__name__)

    auth_ready = not (
        settings.identity_mode == "api_key" and not settings.agent_api_key
    )
    components = {
        "configuration": HealthComponent(
            status="ready" if auth_ready else "unavailable",
            detail=None if auth_ready else "AGENT_API_KEY_REQUIRED",
        ),
    }
    checks = [iceberg_check(), milvus_check()]
    names = ["iceberg", "milvus"]
    if settings.checkpoint_backend == "postgres":
        async def postgres_check() -> HealthComponent:
            try:
                from sqlalchemy import text

                from financial_research_agent.persistence.database import (
                    create_business_engine,
                )

                engine = create_business_engine(settings)
                try:
                    async with engine.connect() as connection:
                        await asyncio.wait_for(
                            connection.execute(text("SELECT 1")), timeout=2
                        )
                finally:
                    await engine.dispose()
                return HealthComponent(status="ready")
            except Exception as exc:
                return HealthComponent(status="unavailable", detail=type(exc).__name__)

        names.append("postgres")
        checks.append(postgres_check())
    results = await asyncio.gather(*checks)
    components.update(dict(zip(names, results, strict=True)))
    return components


def _analyze_response(result: ResearchRunResult, settings: Settings, registry) -> AnalyzeResponse:
    orchestration = result.orchestration
    tasks = {task.task_id: task for task in orchestration.plan.tasks} if orchestration.plan else {}
    replan_tool_names = {
        "event": ToolName.EVENT_SEARCH.value,
        "research_report": ToolName.REPORT_SEARCH.value,
    }

    def tool_name_for(task_id: str) -> str:
        if task_id in tasks:
            return tasks[task_id].tool_name.value
        evidence_type = task_id.partition("_replan")[0]
        return replan_tool_names.get(evidence_type, "unknown")

    statuses = [
        ToolStatus(
            task_id=item.task_id,
            tool_name=tool_name_for(item.task_id),
            success=item.success,
            error_code=item.error_code,
            error_message=item.error_message,
            latency_ms=item.latency_ms,
            evidence_count=len(item.evidence),
        )
        for item in orchestration.tool_results
    ]
    reporting = result.reporting
    error = None
    if not result.success:
        if not orchestration.success:
            semantic_failed = any(
                "SEMANTIC_ALIGNMENT_FAILED" in item
                for item in orchestration.errors
            )
            code = (
                "QUERY_SEMANTIC_ALIGNMENT_FAILED"
                if semantic_failed
                else "ORCHESTRATION_FAILED"
            )
            message = (
                "question scope is ambiguous or changed during interpretation"
                if semantic_failed
                else "research orchestration failed"
            )
            details = {"errors": orchestration.errors}
        else:
            code = (
                "REPORT_VALIDATION_FAILED"
                if reporting and reporting.status == "validation_failed"
                else "REPORT_GENERATION_FAILED"
            )
            message = "research report was not completed"
            details = {"errors": reporting.errors if reporting else []}
        error = ApiError(code=code, message=message, run_id=orchestration.run_id, details=details)
    timings = {item.stage.value: item.duration_ms for item in orchestration.timings}
    if reporting:
        timings.update(reporting.timings)
    tool_versions = {
        schema["name"]: registry.get(schema["name"]).definition.version
        for schema in registry.schemas()
    }
    return AnalyzeResponse(
        success=result.success,
        run_id=orchestration.run_id,
        planner_source=orchestration.planner_source,
        selected_skills=orchestration.selected_skills,
        skill_selection_reason=orchestration.skill_selection_reason,
        policy_version=orchestration.policy_version,
        budget=orchestration.budget,
        completion=orchestration.completion,
        memory_scope=orchestration.memory_scope,
        memory_warnings=orchestration.memory_warnings,
        context_manifests=orchestration.context_manifests,
        semantic_alignment=orchestration.semantic_alignment,
        execution_metadata=orchestration.execution_metadata,
        reporting_status=reporting.status if reporting else None,
        query_spec=orchestration.query,
        plan=orchestration.plan,
        tool_status=statuses,
        evidence=orchestration.evidence,
        report=reporting.report if reporting else None,
        validation=reporting.validation if reporting else None,
        timings=timings,
        metadata=RuntimeMetadata(
            model_provider=settings.model_provider,
            model_name=settings.model_name or None,
            planner_prompt_version=settings.planner_prompt_version,
            report_prompt_version=settings.report_prompt_version,
            tool_versions=tool_versions,
            gateway_version=settings.gateway_version,
            policy_version=settings.policy_version,
            model_context_window_tokens=settings.model_context_window_tokens,
            model_max_output_tokens=settings.model_max_output_tokens,
            model_thinking_mode=settings.model_thinking_mode,
        ),
        error=error,
    )


app = create_app()
