import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError

from .mock import analyze_mock
from .models import AnalysisRequest, AnalysisResponse, ReasoningResult, Trend, RecommendationKind, HypothesisStatus

# Đọc cấu hình local; environment của terminal/Docker được ưu tiên.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

app = FastAPI(title="TeenCare AI", version="1.0.0")
logger = logging.getLogger("teencare.ai")
PROMPT_VERSION = "state-v6"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")


def validate_references(request: AnalysisRequest, result: ReasoningResult) -> None:
    if not result.overview_summary or not result.overview_summary.strip():
        raise HTTPException(422, "INVALID_AI_OVERVIEW")
    if (len(result.assessments) > 8 or len(result.hypotheses) > 16
            or len(result.recommendations) > 16 or len(result.information_gaps) > 16):
        raise HTTPException(422, "INVALID_AI_RESULT_SIZE")
    dimensions = {item.dimension for item in result.assessments}
    if len(dimensions) != len(result.assessments):
        raise HTTPException(422, "INVALID_AI_DIMENSIONS")
    previous_dimensions = {a.dimension for a in request.previous_state.state.assessments} if request.previous_state else set()
    for item in result.assessments:
        if (item.information_status is None or item.trend is None
                or (item.trend != Trend.unknown and item.dimension not in previous_dimensions)):
            raise HTTPException(422, "INVALID_AI_DIMENSION_STATE")
    allowed = {item.revision_id for item in request.observations}
    change_allowed = allowed | (set(request.previous_state.input_revision_ids) if request.previous_state else set())
    if (request.previous_state is None) != (result.has_meaningful_changes is None):
        raise HTTPException(422, "INVALID_AI_CHANGE_BASELINE")
    if (not set(result.change_evidence_revision_ids) <= change_allowed
            or len(result.change_evidence_revision_ids) != len(set(result.change_evidence_revision_ids))
            or (result.has_meaningful_changes is True and not result.change_evidence_revision_ids)):
        raise HTTPException(422, "INVALID_AI_CHANGE_EVIDENCE")
    keys = {item.key for item in result.hypotheses}
    if len(keys) != len(result.hypotheses) or len({a.key for a in result.assessments}) != len(result.assessments):
        raise HTTPException(422, "INVALID_AI_KEYS")
    if (any(h.is_primary is None or (h.is_primary and h.status == HypothesisStatus.rejected) for h in result.hypotheses)
            or sum(h.is_primary is True for h in result.hypotheses) != int(any(h.status != HypothesisStatus.rejected for h in result.hypotheses))):
        raise HTTPException(422, "INVALID_AI_PRIMARY_HYPOTHESIS")
    for item in [*result.assessments, *result.hypotheses]:
        if item.dimension is None:
            raise HTTPException(422, "INVALID_AI_DIMENSIONS")
        ids = [e.observation_revision_id for e in item.evidence]
        if len(set(ids)) != len(ids) or not set(ids) <= allowed:
            raise HTTPException(422, "INVALID_AI_EVIDENCE")
    by_key = {h.key: h for h in result.hypotheses}
    seen_actions = set()
    for action in result.recommendations:
        if action.dimension is None or action.kind is None:
            raise HTTPException(422, "INVALID_AI_DIMENSIONS")
        target = (action.dimension, action.audience)
        if target in seen_actions:
            raise HTTPException(422, "INVALID_AI_ACTION_COUNT")
        seen_actions.add(target)
        if action.kind == RecommendationKind.support_trial and action.dimension not in dimensions:
            raise HTTPException(422, "INVALID_AI_ACTION_BASIS")
        if action.hypothesis_key is not None:
            hypothesis = by_key.get(action.hypothesis_key)
            if (hypothesis is None or hypothesis.dimension != action.dimension
                    or hypothesis.status == HypothesisStatus.rejected):
                raise HTTPException(422, "INVALID_AI_LINK")


@app.get("/health")
async def health():
    return {"status": "ok", "provider": os.getenv("AI_PROVIDER", "mock")}


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(request: AnalysisRequest) -> AnalysisResponse:
    provider = os.getenv("AI_PROVIDER", "mock")
    if provider == "mock":
        result = analyze_mock(request)
        validate_references(request, result)
        return result
    if provider != "openai":
        raise HTTPException(400, "UNKNOWN_AI_PROVIDER")
    key, model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL")
    if not key or not model:
        raise HTTPException(400, "MISSING_OPENAI_CONFIGURATION")
    try:
        # The .NET worker owns retries; SDK retries are disabled to avoid multiplying attempts.
        async with AsyncOpenAI(api_key=key, timeout=75.0, max_retries=0) as client:
            response = await client.responses.parse(
                model=model,
                instructions=PROMPT,
                input=request.model_dump_json(by_alias=True),
                text_format=ReasoningResult,
                store=False,
            )
        if response.output_parsed is None:
            raise HTTPException(422, "AI_REFUSED_OR_INCOMPLETE")
        result = response.output_parsed
        validate_references(request, result)
        return AnalysisResponse(**result.model_dump(), model_version=response.model, prompt_version=PROMPT_VERSION)
    except (APIConnectionError, APITimeoutError):
        raise HTTPException(503, "OPENAI_UNAVAILABLE") from None
    except APIStatusError as exc:
        status = 429 if exc.status_code == 429 else 503 if exc.status_code >= 500 else 400
        raise HTTPException(status, "OPENAI_REQUEST_FAILED") from None
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Invalid AI response for job %s: %s", request.job_id, type(exc).__name__)
        raise HTTPException(422, "INVALID_AI_RESULT") from None
