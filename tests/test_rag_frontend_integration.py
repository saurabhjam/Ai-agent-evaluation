from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")


def test_evaluation_capabilities_section_replaces_legacy_primary_copy():
    assert "Evaluation Capabilities" in INDEX
    assert "Standard Chatbot Evaluation" in INDEX
    assert "RAG / Knowledge Grounding Evaluation" in INDEX
    assert "Agent exposes retrieval evidence" not in INDEX
    assert "Context JSON Path" not in INDEX


def test_rag_disabled_does_not_require_mapping():
    assert "if (!enabled || [\"rest\", \"browser\", \"websocket\"].indexOf(method) < 0) return null;" in APP_JS


def test_same_response_mode_ui_and_serialization_use_backend_fields():
    assert '<option value="same_response">Included in chatbot API response</option>' in INDEX
    assert "conn-rag-context-path" in INDEX
    assert "conn-rag-citation-path" in INDEX
    assert "context_path: contextPath" in APP_JS
    assert "sameResponseConfig.citation_path = citationPath" in APP_JS
    assert "source_type: \"agent_retrieval\"" in APP_JS


def test_separate_api_mode_uses_phase_one_backend_schema():
    assert '<option value="separate_api">Separate retrieval / trace API</option>' in INDEX
    assert "mode: \"separate_api\"" in APP_JS
    assert "correlation_path: correlationPath" in APP_JS
    assert "evidence_request: evidenceRequest" in APP_JS
    assert "method: evidenceMethod" in APP_JS
    assert "url: evidenceUrl" in APP_JS


def test_evidence_unavailable_is_saved_as_disabled_non_fake_evidence():
    assert '<option value="unavailable">Retrieval evidence unavailable</option>' in INDEX
    assert 'return { enabled: false, mode: "unavailable" };' in APP_JS
    assert "Do NOT create fake RAGEvidence" not in APP_JS


def test_get_and_post_evidence_configuration_are_exposed():
    assert '<option value="GET">GET</option>' in INDEX
    assert '<option value="POST">POST</option>' in INDEX
    assert "conn-rag-evidence-params" in INDEX
    assert "conn-rag-evidence-body" in INDEX
    assert 'evidenceRequest.params = params' in APP_JS
    assert 'evidenceRequest.json = body' in APP_JS


def test_correlation_path_serialization_is_configurable():
    assert "conn-rag-correlation-path" in INDEX
    assert "Correlation field in chatbot response" in INDEX
    assert "request_id" in INDEX
    assert "correlationPath" in APP_JS


def test_evidence_api_auth_modes_map_to_backend_shape():
    assert '<option value="same">Use chatbot connection authentication</option>' in INDEX
    assert '<option value="none">No authentication</option>' in INDEX
    assert '<option value="separate">Configure separately</option>' in INDEX
    assert "evidenceRequest.use_same_auth = false" in APP_JS
    assert "evidenceRequest.auth = { type: authType, value: authValue }" in APP_JS
    assert "evidenceRequest.headers = headers" in APP_JS


def test_separate_bearer_and_api_key_auth_are_exposed():
    assert '<option value="bearer">Bearer Token</option>' in INDEX
    assert '<option value="api_key">API Key</option>' in INDEX
    assert "authType === \"api_key\"" in APP_JS
    assert "evidenceRequest.auth.header_name = headerName" in APP_JS


def test_custom_headers_require_json_object():
    assert '<option value="headers">Custom Headers</option>' in INDEX
    assert "Custom headers JSON must be an object." in APP_JS


def test_mode_specific_required_validation_messages_exist():
    assert "Evidence API URL is required" in APP_JS
    assert "Correlation field in chatbot response is required" in APP_JS
    assert "Retrieved context field/path is required for separate retrieval / trace API mode." in APP_JS
    assert "Retrieved context field/path is required for included response mode." in APP_JS


def test_add_connection_save_keeps_rag_config_inside_options():
    assert "options.rag_config = ragConfig" in APP_JS
    assert "connection: {" in APP_JS
    assert "options" in APP_JS


def test_edit_connection_restores_legacy_same_response_config():
    assert "App._restoreRagConfig(ragConfig" in APP_JS
    assert "ragConfig.context_path || ragConfig.contexts_path || ragConfig.retrieved_context_path" in APP_JS
    assert "ragConfig.citation_path || ragConfig.citations_path" in APP_JS


def test_edit_connection_restores_separate_api_config():
    assert 'ragConfig.mode === "separate_api" ? "separate_api" : "same_response"' in APP_JS
    assert "ragConfig.evidence_request || {}" in APP_JS
    assert "req.params ? JSON.stringify(req.params, null, 2)" in APP_JS
    assert "(req.json || req.body) ? JSON.stringify(req.json || req.body, null, 2)" in APP_JS


def test_switching_modes_uses_one_rag_config_builder():
    assert APP_JS.count("options.rag_config = ragConfig") == 1
    assert APP_JS.count("_buildRagConfig(method)") >= 1


def test_browser_uses_selector_model_not_rest_separate_api_fields():
    assert "conn-rag-browser-panel" in INDEX
    assert "conn-rag-browser-context-selector" in INDEX
    assert "context_selector: browserContextSelector" in APP_JS
    assert 'opt.value === "separate_api" && !isRest' in APP_JS
    assert "Visible evidence selector is required for Browser RAG evaluation." in APP_JS


def test_websocket_only_exposes_final_response_payload_mapping():
    assert "conn-rag-websocket-panel" in INDEX
    assert "final WebSocket response" in INDEX
    assert "WebSocket currently supports evidence included in the final response payload only." in INDEX
    assert "Retrieved context field/path is required for WebSocket RAG evaluation." in APP_JS


def test_scenario_reference_context_remains_distinct():
    assert "Scenario reference context remains configured separately in scenarios." in INDEX
    assert "scenario reference" not in APP_JS.lower()


def test_test_connection_flow_is_preserved():
    assert "async testNewConnection()" in APP_JS
    assert "var saved = await App._doSaveConnection();" in APP_JS
    assert "var res = await API.testConnection(id);" in APP_JS


def test_no_secret_console_logging_added():
    assert "console.log" not in APP_JS
    assert "conn-rag-evidence-auth-value" in INDEX
    assert 'type="password"' in INDEX
