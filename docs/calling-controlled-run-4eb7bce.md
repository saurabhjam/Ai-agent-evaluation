# Controlled calling run investigation

Evaluation: `eval_4eb7bce88b994fc8bc88c7bf4f96faf6`.
Provider call: `01a17bfd-dd5f-788e-91a3-aa55f6bdcf2e`.
Sources: read-only `eval_results.db` evaluation_reports payload, persisted provider transcript,
`artifacts/eval_4eb7bce88b994fc8bc88c7bf4f96faf6/full_call.wav`, current calling source and offline replay.
No live call was made. Transcript copies in reports are the same provider evidence, not independent corroboration.

## Request failures reproduced before editing

| Agent question | Old intent | Mentioned | Requested | Policy / Groq / result |
|---|---|---|---|---|
| May I please have your full name? | ACKNOWLEDGE_FACT | name | empty | acknowledge / bypass / Okay. |
| Could you please let me know your preferred appointment date? | ACKNOWLEDGE_FACT | preferred_date | empty | acknowledge / bypass / Okay. |
| When would you like to schedule your appointment, Rahul? | OTHER | empty | empty | acknowledge / bypass / Okay. |
| Is there a specific date you have in mind for your appointment? | ACKNOWLEDGE_FACT | preferred_date | empty | acknowledge / bypass / Okay. |

All configured fact lookups succeed. The regex required the verb immediately after
"May I", omitted "let me know" and existential questions, and had no unambiguous
temporal request inference for "when". Empty requested fields select acknowledgement.
The pending-request list is overwritten with empty fields after these turns. This is a
classification failure before naturalization, not a Groq or TTS fabrication.
Historical local STT text and per-turn PersonaState were not persisted; the above is
reproduction using the recorded provider questions, not a claim that provider text and
local STT were identical. New policy diagnostics capture that boundary.

## Termination

The required set contains all five persona facts. Only fields rendered from placeholders
were marked disclosed. The fixed configured opening communicates appointment reason
without a placeholder, so appointment_reason was never marked disclosed. Therefore
no_further_request stayed false, and the terminal predicate failed on the final farewell.
The closing plan generated the duplicate before TTS and send_audio. Execution is serial;
no queued-response race is needed to reproduce this failure.

The scenario now explicitly maps its opening paraphrase to appointment_reason through
the generic opening_fields setting. This is scenario-owned semantic evidence, not a
global synonym rule or an inference that every opening satisfies every fact.
The runner already hangs up in finally before recorder finalization and before provider
readiness polling. A successful terminal signal uses that existing cleanup path.

## Recording and lifecycle evidence

Full recording duration: 376.261583 seconds. Last 20-ms analysis window with RMS >= 60:
375.980 seconds. Remaining below-threshold tail: 0.281583 seconds. This threshold is an
audio-level measurement, not speech recognition. No audio was changed.

The final unwanted turn consumed STT 15.599s, TTS 0.749s, transport 2.161s, totaling
18.858s by the old stage-sum metric. This proves processing delay before duplicate audio.
It does not prove a long post-audio shutdown wait.

Provider start: 2026-10-27T06:13:17.577Z; terminal: 2026-10-27T06:19:08.942Z.
Pipeline completed event: 2026-10-27T06:19:15.389731+00:00.
Semantic completion, runner exit, transport close and recorder-finalize timestamps are
absent from the historical evidence. Exact alignment of recording and provider clocks
cannot be reconstructed. New persisted conversation_lifecycle timestamps cover these
boundaries; provider terminal time remains the provider's own session ended_at.

## Persisted latency

Milliseconds, rounded. Stop is the actual speech-stop timestamp, which was not persisted.
First/total were calculated by sums in the previous implementation; they are estimates,
not independently captured elapsed intervals. New boundaries measure actual first/final
send times against meaningful-audio end where the transport exposes them.

| Turn | Stop | STT | Policy | Groq | Grounding | TTS | Transport | First audio | Total | Cold |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | unavailable | 34599.3 | 2.6 | 0 | 0.1 | 6158.7 | 3550.9 | 41024.4 | 44569.8 | yes |
| 1 | unavailable | 14028.9 | 0.3 | 0 | 0.2 | 327.4 | 837.7 | 14380.6 | 15215.4 | no |
| 2 | unavailable | 11876.7 | 0.2 | 1635.4 | 0.1 | 201.0 | 1075.3 | 14008.1 | 15082.4 | no |
| 3 | unavailable | 17729.0 | 0.2 | 1841.8 | 0.1 | 842.4 | 3064.9 | 20683.7 | 23745.2 | no |
| 4 | unavailable | 9737.3 | 0.1 | 0 | 0 | 154.7 | 701.8 | 10128.6 | 10829.7 | no |
| 5 | unavailable | 17730.8 | 0.2 | 0 | 0 | 103.7 | 722.2 | 18127.2 | 18848.5 | no |
| 6 | unavailable | 9950.7 | 0.9 | 0 | 0.1 | 698.0 | 1014.1 | 11047.4 | 12054.6 | no |
| 7 | unavailable | 16985.4 | 0.3 | 1184.8 | 0 | 282.4 | 2595.2 | 18765.4 | 21358.6 | no |
| 8 | unavailable | 20128.5 | 0.2 | 1625.5 | 0.1 | 304.3 | 1748.1 | 22316.0 | 24061.3 | no |
| 9 | unavailable | 27023.3 | 0.4 | 0 | 0.1 | 863.6 | 1736.3 | 28188.2 | 29914.3 | no |
| 10 | unavailable | 24964.8 | 0.2 | 0 | 0.2 | 813.4 | 2296.9 | 26085.1 | 28377.0 | no |
| 11 | unavailable | 15599.4 | 0.2 | 0 | 0.1 | 749.0 | 2161.2 | 16701.7 | 18858.4 | no |

STT totals 220.354s. Warm STT ranges 9.737-27.023s; endpoint detection was 0.021-0.391s;
Groq was 0-1.842s. STT is the dominant measured remaining stage. These measurements do
not separate model initialization from inference or prove a CPU contention cause.
No additional model/inference optimization was made.

## Metric evidence

Previously, normalized evidence did not describe who supplied a fact or whether it
remained unresolved. Shared pairwise context includes persona.goal only on the initial
exchange, so instructions attached only to that goal did not constrain later pairs.
Calling now builds chronological requested/supplied/missing/reasked evidence. Evaluation-only
message copies carry labeled evidence, while returned and persisted dialogue retains
the original text. Scores are not raised or overwritten. Calling failure analysis uses
referenced-turn role evidence rather than attributing every repeated question to the agent.

The configured goal is to REQUEST an appointment, confirm correct details and end after
the agent completes the request OR explains why it cannot proceed. It does not require a
confirmed booking. The configured opening explicitly conveys the appointment purpose.
The reason claiming an omitted purpose and mandatory booking confirmation is unsupported
by this scenario contract. Other scenarios retain their own goal requirements.

## Changed files and verification

| File | Functions / purpose |
|---|---|
| app/calling/simulator.py | _explicitly_requested_fields, __call__: request grammar, unambiguous preference inference, opening disclosure state, policy diagnostics |
| app/calling/scenario.py | CallingSimulatorConfig.opening_fields: explicit scenario-owned paraphrase mapping |
| scenarios/appointment_inbound_calling.yaml | Declares opening appointment_reason disclosure |
| app/calling/workflow_evidence.py | build_workflow_evidence, workflow_instructions: chronological role attribution |
| app/calling/evaluation_adapter.py | evaluate: evaluation-only evidence annotations, original text restoration, unchanged RAG path |
| app/calling/failure_analysis.py | analyze: referenced-turn justified reask attribution |
| app/calling/voice_conversation_runner.py | run, _receive_agent_text, _send_user_text: persisted latency boundaries and shutdown lifecycle |
| app/calling/voice_transport.py | receive_audio, send_audio, _set_receive_timing: passive provider-owned timestamp capture |
| app/calling/execution_pipeline.py | _conversation_runtime_metadata: propagate lifecycle evidence |
| tests/test_calling_controlled_replay.py | Request variants, generic collection scenario, refusal, terminal runner/Groq/TTS/audio/recorder replay, role evidence |
| tests/test_calling_evaluation_adapter.py | Pairwise evidence delivery, raw transcript preservation, RAG path isolation |
| tests/test_calling_real_provider_no_mock_fallback.py | Replace stale live-network test boundaries with explicit offline HTTP/WebSocket mocks |
| docs/calling-controlled-run-4eb7bce.md | This evidence report and timing table |

Final combined offline regression: **261 passed**, 16 warnings, 8.72 seconds.
Coverage includes all Calling test modules, Vapi mocks, recorder, persistence/report,
evaluation service, chatbot API and scripted chatbot tests. No shared chatbot, RAG,
evaluator, shared failure-analysis, or audio recorder source was modified.

Three pre-existing provider tests initially attempted unmocked networking using the
literal test-key. DNS resolution failed before reaching Vapi; no live call was created.
Their HTTP and WebSocket boundaries are now explicitly mocked and the final suite is green.
TestClient tests required execution outside the Windows sandbox to complete.

Historical cold-start flags identify first turns only; they do not independently prove
that a model was freshly loaded. No further inference optimization was attempted.
