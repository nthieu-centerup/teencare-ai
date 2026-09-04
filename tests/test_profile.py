from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from openai.lib._pydantic import to_strict_json_schema

from app.main import PROMPT_VERSION, validate_references
from app.models import (AnalysisInputChanges, AnalysisPreviousState, Dimension, InformationStatus,
                        RecommendationKind, ReasoningResult, Trend)
from app.mock import analyze_mock
from test_demo import demo_request


def test_new_profile_is_sparse_and_has_a_grounded_overview():
    request = demo_request()
    result = analyze_mock(request)
    assert PROMPT_VERSION == 'state-v6'
    assert result.overview_summary.startswith('[Mô phỏng]')
    assert {a.dimension for a in result.assessments} == {Dimension.self_discipline, Dimension.follow_through}
    assert all(a.information_status == InformationStatus.need_more_information for a in result.assessments)
    assert all(a.trend == Trend.unknown for a in result.assessments)
    assert all(r.kind == RecommendationKind.support_trial for r in result.recommendations)
    validate_references(request, result)


@pytest.mark.parametrize('invalid', ['overview', 'dimension', 'duplicate', 'information_status', 'trend',
                                    'unjustified_trend', 'hypothesis_dimension', 'action_dimension', 'action_kind',
                                    'action_basis', 'action_link_dimension', 'rejected_hypothesis', 'duplicate_action',
                                    'foreign_evidence', 'too_many_assessments', 'too_many_hypotheses',
                                    'too_many_recommendations', 'too_many_questions'])
def test_profile_validation_rejects_invalid_new_results(invalid):
    request = demo_request()
    result = analyze_mock(request)
    if invalid == 'overview': result.overview_summary = ' '
    if invalid == 'dimension': result.assessments[0].dimension = None
    if invalid == 'duplicate': result.assessments[1].dimension = result.assessments[0].dimension
    if invalid == 'information_status': result.assessments[0].information_status = None
    if invalid == 'trend': result.assessments[0].trend = None
    if invalid == 'unjustified_trend': result.assessments[0].trend = Trend.improving
    if invalid == 'hypothesis_dimension': result.hypotheses[0].dimension = None
    if invalid == 'action_dimension': result.recommendations[0].dimension = None
    if invalid == 'action_kind': result.recommendations[0].kind = None
    if invalid == 'action_basis': result.assessments = []
    if invalid == 'action_link_dimension': result.hypotheses[0].dimension = Dimension.autonomy
    if invalid == 'rejected_hypothesis': result.hypotheses[0].status = 'Rejected'
    if invalid == 'duplicate_action': result.recommendations.append(deepcopy(result.recommendations[0]))
    if invalid == 'foreign_evidence': result.assessments[0].evidence[0].observation_revision_id = uuid4()
    if invalid == 'too_many_assessments': result.assessments *= 5
    if invalid == 'too_many_hypotheses': result.hypotheses *= 17
    if invalid == 'too_many_recommendations': result.recommendations *= 9
    if invalid == 'too_many_questions': result.information_gaps *= 9
    with pytest.raises(HTTPException) as error:
        validate_references(request, result)
    assert error.value.status_code == 422


def test_support_can_use_assessment_directly_and_information_gathering_can_have_no_finding():
    request = demo_request()
    result = analyze_mock(request)
    result.hypotheses = []
    for action in result.recommendations: action.hypothesis_key = None
    validate_references(request, result)
    result.assessments = []
    result.overview_summary = 'Chưa có nhận định, cần hỏi thêm thông tin.'
    for action in result.recommendations: action.kind = RecommendationKind.information_gathering
    validate_references(request, result)


def test_feedback_and_repeat_keep_reported_trend_and_deletion_removes_its_basis():
    request = demo_request()
    first = analyze_mock(request)
    request.previous_state = AnalysisPreviousState(snapshot_id=uuid4(), version=1, created_at=request.as_of_utc,
        input_revision_ids=[o.revision_id for o in request.observations], state=first)
    follow_up = demo_request(True).observations[-1]
    request.observations.append(follow_up)
    request.input_changes = AnalysisInputChanges(added_revision_ids=[follow_up.revision_id], updated_previous_revisions=[], removed_revisions=[])
    second = analyze_mock(request)
    assert second.assessments[0].trend == Trend.improving
    assert second.assessments[1] == first.assessments[1]  # No new report does not erase supported knowledge.
    request.previous_state = AnalysisPreviousState(snapshot_id=uuid4(), version=2, created_at=request.as_of_utc,
        input_revision_ids=[o.revision_id for o in request.observations], state=second)
    request.input_changes = AnalysisInputChanges(added_revision_ids=[], updated_previous_revisions=[], removed_revisions=[])
    repeated = analyze_mock(request)
    assert repeated.overview_summary == second.overview_summary
    assert repeated.assessments == second.assessments
    assert repeated.recommendations == second.recommendations
    assert repeated.has_meaningful_changes is False
    request.observations.pop()
    request.input_changes.removed_revisions = [follow_up]
    after_delete = analyze_mock(request)
    assert after_delete.assessments[0].trend == Trend.unknown
    assert follow_up.revision_id in after_delete.change_evidence_revision_ids
    assert all(e.observation_revision_id != follow_up.revision_id for a in after_delete.assessments for e in a.evidence)
    validate_references(request, after_delete)


def test_legacy_baseline_null_fields_and_long_arrays_are_readable_but_new_state_requires_dimensions():
    request = demo_request()
    legacy = analyze_mock(request)
    legacy.overview_summary = None
    for assessment in legacy.assessments:
        assessment.dimension = assessment.information_status = assessment.trend = None
    for hypothesis in legacy.hypotheses: hypothesis.dimension = hypothesis.is_primary = None
    for action in legacy.recommendations: action.dimension = action.kind = None
    legacy.assessments *= 5
    request.previous_state = AnalysisPreviousState(snapshot_id=uuid4(), version=1, created_at=request.as_of_utc,
        input_revision_ids=[o.revision_id for o in request.observations], state=legacy)
    request.input_changes = AnalysisInputChanges(added_revision_ids=[], updated_previous_revisions=[], removed_revisions=[])
    reread = type(request).model_validate_json(request.model_dump_json(by_alias=True))
    assert reread.previous_state.state.overview_summary is None
    assert reread.previous_state.state.hypotheses[0].is_primary is None
    result = analyze_mock(reread)
    assert all(a.trend == Trend.unknown for a in result.assessments)
    validate_references(reread, result)


def test_wire_schema_carries_typed_dimensions_gaps_and_nullable_legacy_fields():
    result = analyze_mock(demo_request()).model_dump(exclude={'model_version', 'prompt_version'}, by_alias=True)
    result['assessments'][0]['dimension'] = 'InventedDimension'
    with pytest.raises(ValidationError): ReasoningResult.model_validate(result)
    result = analyze_mock(demo_request()).model_dump(exclude={'model_version', 'prompt_version'}, by_alias=True)
    result['informationGaps'] = ['Old wire format is no longer sent by the backend']
    with pytest.raises(ValidationError): ReasoningResult.model_validate(result)
    schema = to_strict_json_schema(ReasoningResult)
    assert schema['additionalProperties'] is False
    assert 'overviewSummary' in schema['required']
    assert len(schema['$defs']['Dimension']['enum']) == 8
    assert 'dimension' in schema['$defs']['Assessment']['required']
    assert 'question' in schema['$defs']['InformationGap']['required']
    assert 'isPrimary' in schema['$defs']['Hypothesis']['required']


@pytest.mark.parametrize('selection', ['missing', 'none', 'multiple', 'rejected'])
def test_primary_hypothesis_selection_is_explicit_and_unique(selection):
    request = demo_request()
    result = analyze_mock(request)
    primary = result.hypotheses[0]
    if selection == 'missing': primary.is_primary = None
    if selection == 'none': primary.is_primary = False
    if selection == 'multiple': result.hypotheses.append(primary.model_copy(update={'key': 'alternative'}))
    if selection == 'rejected': primary.status = 'Rejected'
    with pytest.raises(HTTPException) as error:
        validate_references(request, result)
    assert error.value.detail == 'INVALID_AI_PRIMARY_HYPOTHESIS'


def test_primary_is_not_selected_by_confidence_and_actions_keep_their_basis():
    request = demo_request()
    result = analyze_mock(request)
    primary = result.hypotheses[0]
    alternative = primary.model_copy(update={'key': 'alternative', 'confidence': 0.99, 'is_primary': False})
    result.hypotheses.insert(0, alternative)
    validate_references(request, result)
    assert [h.key for h in result.hypotheses if h.is_primary] == [primary.key]
    assert {r.hypothesis_key for r in result.recommendations} == {primary.key}
    assert {e.observation_revision_id for e in primary.evidence} == {o.revision_id for o in request.observations}
    # No active explanation is also a valid state; do not manufacture one.
    result.hypotheses = [alternative.model_copy(update={'status': 'Rejected'})]
    result.recommendations = []
    validate_references(request, result)
