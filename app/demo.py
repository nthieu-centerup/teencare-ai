"""Scripted output for the exact demo observations, never a general reasoning engine."""
import json
from datetime import timedelta
from pathlib import Path

from .models import (AnalysisRequest, AnalysisResponse, Assessment, Audience, Evidence,
                     Hypothesis, HypothesisStatus, Recommendation, Relation, Dimension,
                     InformationStatus, Trend, RecommendationKind, InformationGap)

DEMO = json.loads((Path(__file__).with_name("demo-observations.json")).read_text(encoding="utf-8"))


def analyze_demo(request: AnalysisRequest) -> AnalysisResponse | None:
    # Match the complete input, including sources. Extra or edited reports use the ordinary mock.
    examples = [*DEMO["initial"], DEMO["followUp"]]
    keys = [(item["source"], " ".join(item["content"].split())) for item in examples]
    by_key = {(o.source.value, " ".join(o.content.split())): o for o in request.observations}
    has_follow_up = keys[-1] in by_key
    expected = keys if has_follow_up else keys[:3]
    if set(by_key) != set(expected) or len(request.observations) != len(expected):
        return None
    observations = [by_key[key] for key in expected]
    if len({o.revision_id for o in observations}) != len(observations) or len({o.observation_id for o in observations}) != len(observations):
        return None
    # Thirty days is a demo boundary, not a rule about child development or real-model freshness.
    if any(o.occurred_at is None or o.occurred_at > min(request.as_of_utc, o.recorded_at)
           or request.as_of_utc - o.occurred_at > timedelta(days=30) for o in observations):
        return None
    if has_follow_up and observations[-1].occurred_at <= max(o.occurred_at for o in observations[:3]):
        return None

    def evidence(index: int, relation: Relation, explanation: str) -> Evidence:
        return Evidence(observation_revision_id=observations[index].revision_id,
                        relation=relation, is_stale=False, explanation=explanation)

    baseline_dimensions = {a.dimension for a in request.previous_state.state.assessments} if request.previous_state else set()
    # Scripted comparison only for this exact demo, never inferred for arbitrary observations.
    starting_trend = Trend.unknown
    if has_follow_up and Dimension.self_discipline in baseline_dimensions:
        previous_follow_up = any(o.revision_id in request.previous_state.input_revision_ids for o in observations[3:])
        previous_assessment = next(a for a in request.previous_state.state.assessments if a.dimension == Dimension.self_discipline)
        starting_trend = (previous_assessment.trend or Trend.unknown) if previous_follow_up else Trend.improving
    assessments = [Assessment(
        key="starting", confidence=0.0, dimension=Dimension.self_discipline,
        information_status=InformationStatus.need_more_information, trend=starting_trend,
        content="[Mô phỏng] Phụ huynh và teen báo việc bắt đầu bài còn khó; teen cho biết thường làm xong khi đã bắt đầu.",
        reasoning="Báo cáo của teen gợi một khả năng có thể phát huy, nhưng chưa xác nhận khả năng hoàn thành ở mọi tình huống.",
        evidence=[evidence(0, Relation.supports, "Phụ huynh kể một lần chơi game trước khi làm bài."),
                  evidence(1, Relation.supports, "Teen tự báo khó bắt đầu nhưng thường làm xong khi đã bắt đầu.")],
    )]
    if has_follow_up:
        assessments = [Assessment(
            key="reported-change", confidence=0.0, dimension=Dimension.self_discipline,
            information_status=InformationStatus.need_more_information, trend=starting_trend,
            content="[Mô phỏng] Sau ghi nhận ban đầu về việc khó bắt đầu bài, phụ huynh báo em bắt đầu trong khoảng năm phút ở hai trong ba buổi thử bước nhỏ.",
            reasoning="Đây là tín hiệu tích cực qua vài buổi theo báo cáo của phụ huynh; chưa chứng minh tiến bộ bền vững hay tác dụng của cách hỗ trợ.",
            evidence=[evidence(0, Relation.context, "Ghi nhận trước cho thấy một lần em chưa bắt đầu bài như đã thống nhất."),
                      evidence(3, Relation.supports, "Ghi nhận sau mô tả ba buổi đã thử và vẫn có một buổi cần nhắc.")],
        )]
    assessments.append(Assessment(
        key="finishing", confidence=0.0, dimension=Dimension.follow_through,
        information_status=InformationStatus.need_more_information,
        trend=Trend.unknown,
        content="[Mô phỏng] Teen cho biết thường làm xong bài khi đã bắt đầu; đây là khả năng có thể phát huy.",
        reasoning="Đây là lời tự báo cáo, chưa rõ mức độ hoàn thành với các loại bài khác nhau.",
        evidence=[evidence(1, Relation.supports, "Teen phân biệt việc khó bắt đầu với khả năng làm tiếp và hoàn thành.")],
    ))
    hypotheses = [Hypothesis(
        key="task-initiation", dimension=Dimension.self_discipline, status=HypothesisStatus.under_review, confidence=0.0,
        content="[Mô phỏng] Bước đầu nhỏ và rõ ràng có thể giúp em bắt đầu bài dễ hơn.",
        reasoning=("Mentor báo em bắt đầu tốt hơn khi chia nhỏ nhiệm vụ. Cần quan sát xem em có bắt đầu được khi ít hỗ trợ hơn không."
                   if not has_follow_up else "Báo cáo mới của phụ huynh bổ sung tín hiệu cùng hướng với mentor. Cần quan sát thêm khi em tự chọn bước đầu và ít được nhắc hơn."),
        evidence=[evidence(1, Relation.context, "Teen phân biệt khó bắt đầu với khả năng làm tiếp."),
                  evidence(2, Relation.supports, "Mentor báo một điều kiện em bắt đầu tốt hơn.")]
                 + ([evidence(3, Relation.supports, "Phụ huynh báo kết quả thử ở nhà, còn hạn chế về số buổi.")] if has_follow_up else []),
    )]
    recommendations = [
        Recommendation(hypothesis_key="task-initiation", dimension=Dimension.self_discipline, kind=RecommendationKind.support_trial, audience=Audience.parent,
            action=("[Mô phỏng] Trong ba buổi học tới, cùng em chọn một bước bài tập nhỏ để thử trong năm phút."
                    if not has_follow_up else "[Mô phỏng] Cùng em tự chọn bước nhỏ cho ba buổi học tiếp theo và thống nhất lúc em muốn được nhắc."),
            rationale="Điều chỉnh cách hỗ trợ ở bước bắt đầu, dựa trên điều mentor báo là hữu ích.",
            expected_outcome="Ghi lại em bắt đầu thế nào, có cần nhắc không và bước đã chọn có hoàn thành không."),
        Recommendation(hypothesis_key="task-initiation", dimension=Dimension.self_discipline, kind=RecommendationKind.support_trial, audience=Audience.mentor,
            action="[Mô phỏng] Trong buổi gặp tới, cho em tự chọn bước đầu của một bài và quan sát trước khi hỗ trợ.",
            rationale="Tìm hiểu em cần loại hỗ trợ nào khi bắt đầu, ngoài bối cảnh ở nhà.",
            expected_outcome="Em tự bắt đầu được ở bước nào và cần hỗ trợ cụ thể ở đâu?"),
    ]
    return AnalysisResponse(
        model_version="mock-demo-v3", prompt_version="mock-demo-v3",
        overview_summary=("[Mô phỏng] Phụ huynh báo em bắt đầu dễ hơn trong hai trong ba buổi thử bước nhỏ. Teen cho biết thường làm xong khi đã bắt đầu; cần theo dõi thêm vì vài buổi chưa chứng minh thay đổi bền vững."
            if has_follow_up else "[Mô phỏng] Phụ huynh và teen báo em gặp khó khi bắt đầu bài; mentor thấy em bắt đầu dễ hơn khi nhiệm vụ được chia nhỏ. Teen cho biết thường làm xong khi đã bắt đầu, nhưng chưa rõ điều này có đúng với các loại bài khác nhau không."),
        change_summary="[Mô phỏng] Tạo mốc đánh giá từ bộ ghi nhận mẫu.",
        has_meaningful_changes=None, change_evidence_revision_ids=[],
        assessments=assessments, hypotheses=hypotheses, recommendations=recommendations,
        information_gaps=[InformationGap(question="Khó bắt đầu có xảy ra với hoạt động em thích hay chủ yếu với bài tập?", dimension=Dimension.self_discipline),
                          InformationGap(question="Em thấy bước nhỏ nào dễ bắt đầu nhất, và cách nhắc nào giúp em thấy được hỗ trợ?", dimension=Dimension.self_discipline)],
    )
