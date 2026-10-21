# Calling Turn Diagnostics

Diagnostics do not change scenario parsing, prompts, model parameters, audio,
turn-taking, or transcript selection. Both flags below default to false.

Set `CALLING_DIAGNOSTICS_ENABLED=true` and restart the backend to enable capture.
Set it to `false` and restart to disable. The existing evaluation log manager
stores the trace in memory; no extra database or file persistence is added.
Download before restarting the backend:

`GET /evaluations/{evaluation_id}/logs/download`

The response's evaluation ID is assigned before execution when debugging is on.
Each diagnostic JSON event contains that ID, the transport session ID, a turn ID
(`session_id:zero_based_exchange_index`), UTC millisecond timestamp, monotonic
nanoseconds, stage, source, and duration for completed stages.
Direct conversation-runner usage without the calling API uses its supplied run
ID as the diagnostic evaluation ID. Logs remain local to the backend worker.

## Personal Data Protection

Ordinary diagnostic data replaces ALL string and numeric payload values with
lengths and HMAC-SHA256 fingerprints using an ephemeral random process key.
This masks names, phone numbers, addresses, dates, free text, and arbitrary
client facts without relying on incomplete name-detection patterns. Equal
fingerprints in one worker establish exact text equality; fingerprints cannot
be compared across backend restarts or workers. Credential fields are omitted.
No API client kwargs, authentication headers, or credentials are captured.

For exact text, explicitly set `CALLING_DIAGNOSTICS_ENCRYPTED_TEXT=true` and
provide `CALLING_DIAGNOSTICS_ENCRYPTION_KEY` with a private Fernet key. Generate
the key using `cryptography.fernet.Fernet.generate_key()` in a secure local
console. This optional mechanism requires the `cryptography` package (already
available in the current environment). Only encrypted payloads enter the log
manager. Possession of the private key controls access to personal text; keep
the key out of source control, shared logs, command arguments, and trace files.
Known configured secrets and credential fields are removed before encryption.
Absent/invalid keys fail closed: masked events remain, with
`encrypted_capture_failed=true`, and calls continue unchanged.

Inspect a downloaded trace:

`python scripts/read_calling_trace.py downloaded-trace.txt`

For an authorized operator, set the private key in the local process environment
and explicitly use `--decrypt` to display private text. This writes personal
data to that operator's console; do not redirect it to ordinary application logs
or shared files. Disable both flags and remove the key after diagnosis.

## Evidence Boundaries

| Stage | Origin |
| --- | --- |
| `agent.simulator_input` | Exact runner text appended before calling the simulator |
| `stt.result` | Local STT return before runner stripping |
| `groq.request` | Actual persona and messages passed to the Groq SDK |
| `groq.response` | Raw Groq message content, before stripping |
| `customer.selected` | Stripped simulator text selected for sending |
| `tts.start` | Exact text argument to `synthesize()` |
| `transport.text_input` | Text-transport alternative; no TTS probe is claimed |
| `utterance.control_observed` | New entries already retained by the transport control buffer |
| `provider.transcript` | Fetched provider transcript; for Vapi this is Vapi transcription |

STT, receive, simulator, Groq, TTS, send, conversation, and evaluation stages have
start/end timing. Exceptions record only their type, never exception text.
Control events are observed after receive returns, not at wire-arrival time;
`event_time_known=false` makes that limitation explicit. Their encrypted data
contains the provider's native event fields; no provider event parsing is added.
An absent control buffer means completion events are unavailable. An audio
receive returning does not prove an utterance was complete.

Provider transcript entries retain their provider turn index. Customer entries
are associated with outbound turns by ordinal position only and labelled
`correlation=ordinal_candidate`; merged, dropped, or split provider turns can
invalidate that association. `exact_text_match` compares that candidate to the
pre-TTS selected text. Provider agent/system entries are unaligned. EvalForge's
stored copy is not emitted as separate evidence. Provider transcript arrival is
not a timestamp for when the audio was spoken or transcribed.

Capture starts only for new debug-enabled calls; historical missing inputs
cannot be reconstructed. These new probes do not redact or change older,
pre-existing transport logging. Use the diagnostics logger's events for this
investigation rather than treating unrelated logs as sanitized evidence.
