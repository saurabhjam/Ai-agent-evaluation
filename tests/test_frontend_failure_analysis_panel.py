from __future__ import annotations

from pathlib import Path


APP_JS = Path("frontend/static/app.js").read_text(encoding="utf-8")
STYLES = Path("frontend/static/styles.css").read_text(encoding="utf-8")


def test_failed_metrics_render_failure_analysis_action():
    assert "_renderMetricCard(m, ev)" in APP_JS
    assert "failure-analysis-link" in APP_JS
    assert "View Analysis" in APP_JS
    assert "if (!m.passed)" in APP_JS


def test_failure_panel_reads_from_evaluation_result_failure_analysis():
    assert "ev.failure_analysis" in APP_JS
    assert "_findFailureAnalysis(ev, metric)" in APP_JS
    assert "item.metric_name === metricName" in APP_JS


def test_calling_recordings_use_evalforge_artifact_urls_only():
    recording_renderer = APP_JS.split("_renderCallingRecordings(recordings, status)", 1)[1].split("  _callingRecordingLabel(recording, index, total)", 1)[0]
    assert "recording.playback_url" in recording_renderer
    assert "recording.download_url" in recording_renderer
    assert "providerJson.recordingUrl" not in recording_renderer
    assert "recording.remote_url" not in recording_renderer


def test_failure_panel_empty_state_is_available():
    assert "No failure analysis available." in APP_JS
    assert "openFailureAnalysis(metricName)" in APP_JS


def test_failure_panel_renders_multiple_evidence_items_and_technical_details():
    assert "_renderFailureEvidence(failure.evidence)" in APP_JS
    assert "_renderFailureEvidenceBody(item)" in APP_JS
    assert "_renderFailureTechnicalDetails(failure.technical_details)" in APP_JS
    assert "Technical Details" in APP_JS


def test_failure_panel_has_slide_over_styles():
    assert ".failure-analysis-overlay" in STYLES
    assert ".failure-analysis-panel" in STYLES
    assert "position: fixed" in STYLES
    assert "justify-content: flex-end" in STYLES
    assert "z-index: 10000" in STYLES
    assert "backdrop-filter: blur(6px)" in STYLES


def test_failure_panel_behaves_like_modal_and_restores_dashboard():
    assert "App._lockFailureAnalysisModal();" in APP_JS
    assert "App._unlockFailureAnalysisModal();" in APP_JS
    assert "failure-modal-open" in APP_JS
    assert "document.body.style.overflow = \"hidden\"" in APP_JS
    assert "window.scrollTo(0, scrollY)" in APP_JS
    assert "body.failure-modal-open .toast-container" in STYLES
    assert "display: none" in STYLES
    assert "width: min(860px, 100vw)" in STYLES


def test_jump_to_conversation_action_is_rendered_from_failure_panel():
    assert "Jump To Conversation" in APP_JS
    assert "jumpToFailureConversation" in APP_JS
    assert "failure.conversation_message_id" in APP_JS
    assert "failure.conversation_turn" in APP_JS
    assert "_findConversationByFailureText(failure, false)" in APP_JS
    assert "_findConversationByFailureText(failure, true)" in APP_JS


def test_conversation_turns_have_jump_targets():
    assert "data-conversation-turn" in APP_JS
    assert "data-conversation-message-id" in APP_JS
    assert "data-message-id" in APP_JS
    assert "data-turn" in APP_JS
    assert "data-speaker" in APP_JS
    assert "_conversationMessageId(turn, index)" in APP_JS


def test_jump_to_conversation_matching_order_is_stable_id_first():
    assert "data-message-id" in APP_JS
    assert "data-conversation-message-id" in APP_JS
    assert "data-turn" in APP_JS
    assert "data-conversation-turn" in APP_JS
    assert "conversation_uuid" in APP_JS
    assert "conversation_index" in APP_JS
    assert "_normalizeTranscriptForMatch" in APP_JS
    assert "_fuzzyTranscriptMatch" in APP_JS


def test_jump_to_conversation_dismisses_panel_without_clearing_highlight():
    assert "_dismissFailurePanelForJump" in APP_JS
    assert "App._dismissFailurePanelForJump();" in APP_JS
    assert "App.highlightConversationMessage(target);" in APP_JS


def test_conversation_highlight_helpers_exist():
    assert "scrollToConversationTurn" in APP_JS
    assert "highlightConversationMessage" in APP_JS
    assert "clearConversationHighlight" in APP_JS
    assert "focusConversationMessage" in APP_JS


def test_highlight_styles_and_cleanup_are_present():
    assert ".conversation-failure-highlight" in STYLES
    assert ".conversation-nearby-highlight" in STYLES
    assert ".failure-location-badge" in STYLES
    assert "Failure occurred here" in APP_JS
    assert "App.clearConversationHighlight();" in APP_JS


def test_missing_conversation_evidence_shows_non_throwing_message():
    assert "Conversation mapping failed." in APP_JS
    assert "Failure ID:" in APP_JS
    assert "Conversation Message ID:" in APP_JS
    assert "Conversation Turn:" in APP_JS
    assert "Transcript Match:" in APP_JS
    assert "DOM Match:" in APP_JS
    assert "_failureMatchReason(failure)" in APP_JS


def test_failure_panel_uses_enterprise_debugging_layout():
    assert "Enterprise Debugging Panel" in APP_JS
    assert "_renderExpectedActual(failure)" in APP_JS
    assert "_renderFailureTimeline(failure)" in APP_JS
    assert "_businessImpact(failure)" in APP_JS
    assert "_failureRecommendation(failure.recommendation, failure)" in APP_JS
    assert ".failure-debug-meta" in STYLES
    assert ".failure-compare" in STYLES
    assert ".failure-timeline" in STYLES


def test_failure_panel_does_not_render_metric_scores_inside_analysis():
    assert "failure-kpi-grid" not in APP_JS
    assert "fmtScore(metric.score)" not in APP_JS
    assert "passFailBadge(metric.passed)" not in APP_JS


def test_failure_panel_has_specific_root_cause_and_copy_json_support():
    assert "_specificFailureText(failure.root_cause, failure)" in APP_JS
    assert "likely|probably|may have|might have" in APP_JS
    assert "copyFailureJson" in APP_JS
    assert "Copy JSON" in APP_JS


def test_failure_panel_responsive_and_animated_styles_exist():
    assert "@keyframes failurePanelIn" in STYLES
    assert "position: sticky" in STYLES
    assert ".failure-root-cause" in STYLES
    assert ".failure-recommendation" in STYLES
    assert ".failure-evidence-row" in STYLES


def test_dashboard_failure_panel_remains_separate_from_professional_report():
    assert "openProfessionalReport" in APP_JS
    assert "renderProfessionalReport" in APP_JS
    assert "EvaluationResult.failure_analysis" not in APP_JS
