# Workflow and Test Case Coverage

## Architecture

Option C is implemented: `workflows/*.yaml` contains non-executable metadata;
`scenarios/**/*.yaml` continues to contain independent executable cases.
`scenario_id` is the sole case identity. No nested execution or batch calling was
introduced. The current catalog is read-only during reporting.

```yaml
# workflows/example_workflow.yaml (illustrative, not an authored production suite)
workflow_id: example_workflow
name: Example Workflow
description: The capability under test.
coverage: {positive: 3, negative: 3, edge: 2}
agent_keys: ["chatbot:example-connection-id"]
```

Only explicit canonical management `agent_keys` associate an authored suite with
an agent before execution. An empty list leaves it in the global catalog, not in
every agent's report. Coverage minima
cannot be lowered below 3 positive, 3 negative and 2 edge cases.

An independent scenario opts in additively:

```yaml
scenario_id: example_workflow_negative_01
test_case:
  workflow_id: example_workflow
  type: negative
  version: "1"
```

The existing persona, goal, context, behavior, steps and pass threshold remain
the execution inputs. Positive, negative and edge describe input conditions,
not outcomes. Correct rejection/recovery can PASS. Edge never implies ERROR.
`success_criteria` is now preserved by parsing and snapshots. It is deliberately
not newly injected into simulator/judge prompts or used for score overrides.

## Catalog Validation

`GET /scenarios` retains id/channel/path and adds optional metadata and per-entry
issues. `GET /scenarios/catalog` includes workflow definitions and catalog issues.
Malformed definitions, missing references and duplicate IDs are visible. Invalid
or duplicate cases are excluded from authored coverage; no definition wins by
file order. Legacy path-selected execution remains compatible. Opt-in cases reject
ambiguous identity or missing/ambiguous workflow references before execution.
Coverage shortage does not block an otherwise structurally valid individual run.

## Snapshot and Historical Truth

New `/connections/{id}/evaluate` and `/calling/connections/{id}/run` executions
capture metadata before starting the conversation. The JSON payload stores
`scenario_metadata` with workflow ID/name, derived case ID, category, optional
version, deterministic scenario hash and redacted success criteria. The agent
configuration is excluded from the snapshot and hash input. No connection
credentials, environment values or raw scenario context are copied into metadata.
The hash fingerprints the parsed non-agent definition; it is not an evaluator
configuration hash or proof of historical backend configuration.

Historical rows are not rewritten. Reads use persisted metadata only, never the
current YAML to classify an old run. Absent/malformed metadata becomes nullable
workflow/category with the original case identity: Legacy / Unmapped and
Legacy / Unclassified. The legacy `/test-runs` API remains unchanged and is not
silently moved into the management `evaluation_reports` population.

## Coverage and Results

The management agent detail and consolidated report use one workflow projection:

- Authored: distinct valid current catalog cases whose workflow explicitly lists
  the canonical agent key and whose channel matches the agent, by category. Use separate
  workflow identities when different clients require different case contracts.
- COMPLETE: each configured minimum is met; otherwise INCOMPLETE.
- Attempted: distinct case IDs with selected runs.
- Evaluated: distinct case IDs with at least one selected PASS/FAIL result and
  a valid recorded score, reusing existing management score normalization.
- Technical errors: distinct case IDs whose latest selected run is ERROR.
- Outcome counts: all selected evaluation runs, including reruns and UNKNOWN.

Authored coverage is not affected by outcome/date filters. Execution coverage is
explicitly selected-scope data. A case without a matching selected evaluation is
shown as NO SELECTED RUN, not claimed never to have run. Different recorded case
versions/categories remain distinguishable; changing today's catalog cannot
reclassify a historical result. Explicitly applicable zero-case workflows remain visible. Deleted
evaluations and pre-baseline evaluations do not contribute execution coverage.

### Agent Scope and Warning Scope

The global catalog remains global; the agent projection does not establish
ownership from filenames, prefixes, or channel alone. Legacy/unmapped cases are
included only from that agent's selected persisted qualifying reports. Therefore
baseline, deletion, scenario, workflow, type, outcome, and date selection can
remove legacy rows. Persisted mapped runs also remain visible without current
applicability metadata, but do not associate unrun siblings with the agent.

Explicitly applicable authored suites and their channel-matching cases are
independent of selected execution filters (scenario, type, outcome, date); the
workflow filter selects the displayed suite. Execution counts and references
always use the full selected-report filters. This preserves underlying authored
coverage rather than making it fluctuate with run selection.

Agent warnings include duplicate IDs for included selected cases or explicitly
applicable cases, scenario-file issues for those cases, and duplicate workflow
definitions for included/applicable workflows. Invalid duplicate cases remain
excluded from authored counts, while their relevant warnings remain visible.
Explicit applicability on ambiguous workflow definitions is retained only as
warning provenance, never as permission to count invalid authored cases.
Unidentifiable malformed workflow files have no provable agent association and
remain global warnings. `GET /scenarios/catalog` retains all global issues.

For the current Sophia population, Legacy / Unmapped contains only
`sophia_maintenance_portfolio`, `sophia_portfolio_summary`, and
`sophia_property_maintenance`; its qualifying three-run summary is unchanged.
Relevant duplicate warnings remain, unrelated refund/calling warnings do not.

The existing PASS/FAIL/ERROR donut still counts selected runs, not categories,
distinct cases or authored coverage. UNKNOWN remains excluded from its denominator.

## API and UI

`GET /management/agents/{agent_key}/workflows` returns workflow coverage, cases and
catalog issues. Management evaluation history, consolidated JSON and every
consolidated download add optional `workflow_id` and `test_case_type` filters.
Existing scenario/outcome/date/baseline selection remains intact.

Agent details display workflow coverage and case rows. Consolidated filters add
workflow and type controls. Section 2 displays coverage, Section 4 case results
and original latest-valid scenario references, and Section 5 adds persisted
workflow/type context to the existing metric-failure blocks. All eight sections
remain. Technical ERROR and unevaluated metrics remain separate from FAIL.

PDF, HTML, DOCX and CSV consume the normalized projection. ZIP uses the existing
evaluation-ID-to-package-path mapping for the new case references too. Standalone
PDFs do not introduce online/localhost/file-system links.

## Duplicate Audit and Mapping Proposal

The local read-only audit found 187 persisted evaluations. No historical records
were rewritten. All three duplicate ID groups remain untouched:

| Scenario ID | Files | Definitions |
| --- | --- | --- |
| refund_request_voice_v1 | scenarios/refund_request_voice_v1.yaml; scenarios/voice/refund_request.yaml | Different |
| sophia_portfolio_summary | scenarios/Sophia_backend.yaml; scenarios/sophia_portfolio_summary.yaml | Different: backend validation is present in one |
| sophia_property_maintenance | scenarios/sophia_property_maintenance.yaml; scenarios/sophia_property_maintenance1.yaml | Parsed definitions currently identical |

Path-based legacy requests identify the file, but persisted scenario ID alone
cannot establish which duplicate source produced an old evaluation. No files
were automatically renamed, removed or mapped.

Candidate mappings for review, not applied:

| Existing scenario | Proposed workflow | Current intent | Constraint |
| --- | --- | --- | --- |
| appointment_inbound_calling | appointment_booking | Positive: normal booking with requested facts | Current configured date is a fixed test value; do not infer adverse intent from the `edge_case` instruction field |
| sophia_property_maintenance | property_maintenance | Positive: submit a valid maintenance request | Select a canonical file and resolve the duplicate before opting in |
| maintenance_form_filling | property_maintenance | Positive: valid structured submission | Distinct fixture/expectations need review before counting with another integration |
| sophia_portfolio_summary | portfolio_summary | Positive: normal portfolio review | Resolve duplicate backend-validation variants and intended identity |
| sophia_maintenance_portfolio | maintenance_portfolio_review | Positive: normal portfolio maintenance analysis | Separate workflow from maintenance submission |

These are intent-based proposals, not retroactive historical classifications.
That initial audit did not establish explicit negative/adverse production cases.
Ambiguous historical cases remain legacy. The subsequent Property Maintenance
inventory below supplies a new independently identified 3/3/2 suite; it does not
retroactively map or reclassify the historical scenarios.

For each approved workflow, author three distinct valid conditions, three distinct
validation/rejection/recovery conditions and two distinct adverse/boundary/change
conditions. A reviewed existing positive may fill one slot; the remaining cases
must have genuinely different inputs and expected behavior, not cosmetic copies.

Other proposed workflow IDs awaiting mapping review are `appointment_booking`,
`portfolio_summary` and `maintenance_portfolio_review`.
For each future approved ID, the proposed production case inventory is:

```text
<workflow_id>_positive_01.yaml
<workflow_id>_positive_02.yaml
<workflow_id>_positive_03.yaml
<workflow_id>_negative_01.yaml
<workflow_id>_negative_02.yaml
<workflow_id>_negative_03.yaml
<workflow_id>_edge_01.yaml
<workflow_id>_edge_02.yaml
```

Each file must declare its own matching `scenario_id`, approved workflow/category
metadata and explicit scenario conditions. These are proposed authoring slots,
not generated scenarios or a claim that four suites have been authored.

## Property Maintenance Authored Inventory

`workflows/property_maintenance.yaml` now defines the first production suite:
3 positive, 3 negative, and 2 edge cases, version `1`. It explicitly lists
`chatbot:34bb6e09-fe95-4595-9b02-8633638c6948`. This key was resolved from the
stored `agent_connections` identity (Sophia Ai, chatbot, REST) and the existing
management `make_agent_key` convention, not guessed from scenario names.

| Independent scenario ID | Controlled condition |
| --- | --- |
| property_maintenance_positive_01 | Complete urgent, worsening kitchen ceiling leak |
| property_maintenance_positive_02 | Complete stable, non-urgent loose cabinet handle |
| property_maintenance_positive_03 | Sticking bathroom door; available unit withheld until requested |
| property_maintenance_negative_01 | Dripping faucet; unit unavailable throughout |
| property_maintenance_negative_02 | Sticking drawer; explicitly invalid synthetic unit and no correction available |
| property_maintenance_negative_03 | Vague initial issue; loose hinge details revealed only after relevant clarification |
| property_maintenance_edge_01 | Initial non-urgent ceiling drip; one explicit worsening event changes priority to Urgent |
| property_maintenance_edge_02 | Initial Kitchen faucet location corrected once to Bathroom; corrected location stays authoritative |

All eight independent YAMLs are in `scenarios/` with matching scenario/file IDs.
The reference-backed property/unit is Mason & Main - B / B1207; no new supposedly
valid backend unit was invented. The invalid identifier is a visibly synthetic
negative input, not a claim about a remotely verified backend record. Other
maintenance conditions are explicit authored test inputs, not observed tickets.
The edge conflict changes location, not unit, to avoid pretending a second unit
is verified. Each edge defines its initial value, later value, disclosure trigger,
and single-occurrence limit. Unavailable tenant/ticket identity and unproven
submission results must not be invented. Submission expectations remain
capability-conditional: evidenced action if supported, honest reporting guidance
and a clear next step otherwise. Important expectations are also expressed in
persona goals/context/behavior, not only in informational success criteria.

The catalog and Sophia report project 8/8 COMPLETE authored coverage. All eight
cases have NO SELECTED RUN until qualifying evaluations exist. This means authored
coverage, not proven live execution quality or successful evaluations. Negative
input handling may PASS; edge cases do not imply ERROR. The suite is ready for
manual content review before any provider execution. No live evaluations were
run to author or validate it. Existing legacy YAMLs/duplicate IDs remain unchanged,
and the historical three-scenario Sophia population remains Legacy / Unmapped.

`tests/test_property_maintenance_catalog.py` validates the real files, applicability,
schema resolution, uniqueness, category counts, fact constraints, change triggers,
unrun UI rendering, unchanged fixture history/pie/failures, and report exports.

## Verification

New tests cover schemas, catalogs, snapshots, real scoring with mocked judges,
chatbot/Calling persistence boundaries, authored and execution coverage, API
filters, frontend runtime rendering, exports and ZIP links. Broad regression runs
block external DNS/socket connections. No paid provider calls are used.

Implementation modules: `app/workflow_models.py`, `app/scenario_catalog.py`,
`app/scenario_metadata.py`, `app/management/workflow_coverage.py`. Integration
touches only scenario/result schemas, API metadata boundaries, management/report
models/services/renderers and scoped management frontend presentation. Evaluator
definitions, score formulas, simulator decisions, transports, RAG and backend
validation logic are unchanged.

The final relevant regression selection passed 491 tests, including 65 new tests.
An additional existing `tests/test_workflow_metrics.py` run has 1 pass and 3 failures:
its `MagicMock` message identifiers are rejected by the string
`MetricResult.conversation_message_id` field. The test file, workflow metric
implementation and MetricResult class are unchanged from HEAD. These unrelated
failures were not fixed or hidden by changing scoring/schema behavior.

Desktop/mobile fixture checks used 1440px and 390px widths. Page scroll widths
matched viewports, and report icons remained 16px. PDF coverage, case results and
failure pages were rendered for visual inspection. Existing PDF/ZIP link tests
passed. Python compilation, Node syntax and Git whitespace checks passed.

The existing 187 evaluation payloads had the same ordered content digest before
and after regression: `7a421cafe110d3b9458f0513e530ab4c7dd030dc96f5cfd2260e5fcadc0dbf15`.

## Files Changed

Existing files changed for this feature only:

- `app/schemas.py`: optional case relationship and preserved success criteria.
- `app/main.py`: additive discovery/catalog response and opt-in validation.
- `app/connections/api.py`: pre-execution snapshot and post-evaluation attachment.
- `app/evaluation_service.py`: optional result-model metadata field only.
- `app/calling/ui_api.py`: pre-execution snapshot and persistence boundary only.
- `app/evaluations_api.py`: additive persisted metadata in evaluation summaries.
- `app/management/models.py`: additive metadata and workflow projection fields.
- `app/management/service.py`: catalog injection, workflow projection and filters.
- `app/management/api.py`: read-only workflow endpoint and additive filter forwarding.
- `app/management/consolidated_models.py`: metadata and workflow response fields.
- `app/management/consolidated_report.py`: shared workflow data and snapshot context.
- `app/management/consolidated_exporters.py`: workflow coverage/results presentation.
- `app/management/consolidated_package.py`: existing link mapping applied to case rows.
- `frontend/static/app.js`: scoped management views and filters.
- `frontend/static/styles.css`: scoped responsive workflow presentation.

New files:

- `app/workflow_models.py`
- `app/scenario_catalog.py`
- `app/scenario_metadata.py`
- `app/management/workflow_coverage.py`
- `tests/test_workflow_catalog.py`
- `tests/test_workflow_reporting.py`
- `tests/test_workflow_integration.py`
- `workflows/README.md`
- `docs/workflow-test-coverage.md`

Earlier uncommitted Calling fixes and user-authored scenario/connection changes
were preserved. No production YAML, database migration, evaluator, simulator,
adapter, authentication or backend-validation implementation was changed here.
