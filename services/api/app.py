"""HTTP adapter. Business rules live in engine/data_gate/ai application layers."""
from contextlib import asynccontextmanager
from hmac import compare_digest
import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from data_gate.domain.errors import DataGateError
from data_gate.domain.model import PassportInput
from engine.v1.application.alternatives import search_alternatives
from services.api.contracts import (
    AlternativesRequest, AnalysisResponse, EvaluationResponse, ImportRequest, PortfolioRequest,
    PublishRequest, SearchResponse, ValidationResponse,
)
from services.api.runtime import Runtime


class BodyLimit:
    """Bound memory even for chunked requests, before JSON deserialization."""
    def __init__(self, app, max_bytes=1_200_000):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.max_bytes:
                response = JSONResponse({"error": {"code": "payload_too_large", "field": "body",
                                                    "message": "Request exceeds 1200000 bytes"}}, 413)
                return await response(scope, receive, send)
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        return await self.app(scope, bounded_receive, send)


def create_app(runtime: Runtime | None = None, *, admin_token: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = runtime if runtime is not None else Runtime()
        yield

    app = FastAPI(title="AKIM V1 API", version="0.2.0", lifespan=lifespan,
                  description="Synthetic official V1. AQOL is computed by the deterministic engine, never LLM.")
    app.add_middleware(BodyLimit)
    origins = [s.strip() for s in os.getenv("AKIM_CORS_ORIGINS", "").split(",") if s.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "Authorization"], allow_credentials=False)

    def get_runtime() -> Runtime:
        return app.state.runtime

    RuntimeDependency = Annotated[Runtime, Depends(get_runtime)]

    def require_admin(authorization: Annotated[str | None, Header()] = None):
        expected = admin_token if admin_token is not None else os.getenv("AKIM_ADMIN_TOKEN")
        if not expected or not authorization or not compare_digest(
            authorization.encode(), f"Bearer {expected}".encode()
        ):
            raise HTTPException(403, "Data Gate access requires a configured admin bearer token")

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"error": {"code": "http_error", "field": "", "message": str(error.detail)}},
                            status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def request_error(request, error):
        issues = [{"code": e["type"], "field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                  for e in error.errors()]
        return JSONResponse({"error": {"code": "invalid_request", "field": "body",
                                      "message": "Request does not match the contract"}, "issues": issues}, 422)

    @app.exception_handler(RecursionError)
    async def too_deep(request, error):
        return JSONResponse({"error": {"code": "invalid_request", "field": "body",
                                      "message": "JSON nesting exceeds the supported depth"}}, 422)

    @app.exception_handler(DataGateError)
    async def gate_error(request, error):
        status = 404 if error.code in ("import_not_found", "snapshot_not_found") else 422
        if error.code in ("publish_blocked", "immutability_violation"):
            status = 409
        return JSONResponse({"error": error.to_api_dict()}, status)

    def pin(request, rt):
        if request.versions is not None and request.versions.model_dump() != rt.versions:
            raise HTTPException(409, "Catalog versions changed; reload /catalog")

    def present(result, rt):
        return {**result.to_api_dict(), "aqolScore": result.score, "versions": rt.versions}

    @app.get("/health")
    def health(rt: RuntimeDependency):
        return {"status": "ok", "versions": rt.versions, "dataHash": rt.published.passport.payload_checksum}

    @app.get("/catalog")
    def catalog(rt: RuntimeDependency):
        payload = rt.published.payload
        return {
            "versions": rt.versions, "scoreName": "Astana Quality of Life Score",
            "sourceType": rt.published.passport.input.source_type.value,
            "districts": payload["districts"], "measures": payload["measures"],
            "indicators": payload.get("indicatorCatalog", []), "weights": payload["weights"],
            "rules": {key: payload[key] for key in (
                "budget", "requiredSelectionCount", "maxMeasuresPerDirection", "horizonQuarters",
                "criticalThreshold", "criticalPenalty", "synergies", "globalConflicts", "districtConflicts")},
            "baseline": {"score": rt.service.inspect_baseline().score, "diagnosticOnly": True},
            "dataManifest": rt.published.manifest_api_dict(),
        }

    @app.post("/v1/validate", response_model=ValidationResponse)
    def validate(request: PortfolioRequest, rt: RuntimeDependency):
        pin(request, rt)
        return {**rt.service.validate(request.domain()).to_api_dict(), "versions": rt.versions}

    @app.post("/v1/evaluate", response_model=EvaluationResponse)
    def evaluate(request: PortfolioRequest, rt: RuntimeDependency):
        pin(request, rt)
        return present(rt.service.evaluate(request.domain()), rt)

    @app.post("/v1/alternatives", response_model=SearchResponse)
    def alternatives(request: AlternativesRequest, rt: RuntimeDependency):
        pin(request, rt)
        constraints = request.constraints
        try:
            result = search_alternatives(rt.service, request.domain(),
                                         fixed=[s.to_domain() for s in constraints.fixedSelections],
                                         allowed_districts=constraints.allowedDistricts,
                                         limit=constraints.resultLimit)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {
            "versions": rt.versions, "searchType": "local-one-edit", "isGlobalOptimum": False,
            "evaluatedCandidates": result.evaluated, "validCandidates": result.valid_candidates,
            "results": [{"selections": [{"measureId": s.measure_id, "districtId": s.district_id}
                                        for s in alt.selections],
                         "evaluation": present(alt.evaluation, rt), "replacements": alt.replacements}
                        for alt in result.results],
        }

    @app.post("/v1/analysis", response_model=AnalysisResponse)
    def analysis(request: PortfolioRequest, rt: RuntimeDependency):
        pin(request, rt)
        return {**rt.analysis(request.domain()), "versions": rt.versions}

    @app.get("/datasets", dependencies=[Depends(require_admin)])
    def datasets(rt: RuntimeDependency):
        with rt.gate_lock:
            return {"datasets": [r.to_api_dict() for r in rt.gate.list_datasets()],
                    "snapshots": [s.manifest_api_dict() for s in rt.gate.list_snapshots()]}

    @app.post("/datasets/imports", dependencies=[Depends(require_admin)])
    def create_import(request: ImportRequest, rt: RuntimeDependency):
        if request.passport.datasetId == "official-v1":
            raise HTTPException(403, "official-v1 is reserved; use another datasetId for experiments")
        with rt.gate_lock:
            record = rt.gate.create_import(request.content.encode("utf-8"), request.format,
                                          PassportInput.from_api_dict(request.passport.model_dump()))
            return rt.gate.get_report(record.id)

    @app.get("/datasets/imports/{import_id}/report", dependencies=[Depends(require_admin)])
    def report(import_id: str, rt: RuntimeDependency):
        with rt.gate_lock:
            return rt.gate.get_report(import_id)

    @app.post("/datasets/imports/{import_id}/publish", dependencies=[Depends(require_admin)])
    def publish(import_id: str, request: PublishRequest, rt: RuntimeDependency):
        with rt.gate_lock:
            if rt.gate.get_import(import_id).passport.input.dataset_id == "official-v1":
                raise HTTPException(403, "official-v1 is reserved")
            return rt.gate.publish(import_id, request.acceptedWarnings).manifest_api_dict()

    return app


app = create_app()
