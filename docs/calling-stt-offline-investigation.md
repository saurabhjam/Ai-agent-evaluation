# Calling STT offline investigation

Controlled evaluation: eval_4eb7bce88b994fc8bc88c7bf4f96faf6.
Sources: read-only evaluation_reports in eval_results.db, existing full_call.wav,
installed FasterWhisper source, application source, local-only benchmarks and mocked tests.
No Vapi or other live call was made in this investigation.

## Proven cause and scope

This is predominantly **inference**, not a 2-second utterance being submitted as a
30-second turn. The historical input durations below were persisted at the transport
return boundary; runner code passes those bytes unchanged to local STT.

With language unset, installed FasterWhisper transcribe.py detects language by encoding
a padded 30-second feature window. Its later lazy generate_segments path separately
encodes the speech window, also padded to 30 seconds. It does not carry the first
language-detection encoder output into this second path. Very short inputs therefore
still incur two large encoder computations on this CPU. The benchmark reproduces this:
a 2-second clip spends 8.155s in invocation and 7.111s in segment iteration, versus only
0.074s decoding audio. With a known English language hint, invocation falls to 0.007s
and materialization to 4.846s on the identical clip.

No evidence proves a historical cache miss on every turn, cross-turn audio accumulation,
an inference-lock wait, GPU fallback, or an asyncio scheduling bottleneck. GPU was not
requested: CPU is the configured device. CPU contention during the historical call
cannot be reconstructed from its available logs.

## Historical per-turn inputs

PCM samples/bytes are reconstructed from persisted duration and the transport's 24kHz,
mono, signed 16-bit PCM contract. WAV container overhead is excluded. They are not
independently retained byte counts. Speech is the provider's duration field in seconds,
not an independent acoustic measurement. Exact original per-turn buffers were not
persisted, so exact acoustic speech duration and internal silence are unavailable.
Subtracting provider duration from buffered duration would not reliably measure silence.

| Turn | Provider duration s | Input s | Samples | PCM bytes | Silence | STT s | RTF | Provider transcript |
|---|---:|---:|---:|---:|---|---:|---:|---|
| 0 | 0.840 | 2.373 | 56945 | 113890 | unavailable | 34.599 | 14.58 | Hello. What kind of help I do? |
| 1 | 1.440 | 3.977 | 95455 | 190910 | unavailable | 14.029 | 3.53 | Of course. I can help with that. May I please have your full name? |
| 2 | 1.320 | 3.105 | 74509 | 149018 | unavailable | 11.877 | 3.83 | Thank you. Could you please tell me your full name? |
| 3 | 1.620 | 3.686 | 88473 | 176946 | unavailable | 17.729 | 4.81 | Thank you, Rahul Sharma. May I have your phone number, please? |
| 4 | 1.860 | 3.395 | 81491 | 162982 | unavailable | 9.737 | 2.87 | Thank you. Could you please let me know your preferred appointment date? |
| 5 | 1.740 | 2.814 | 67527 | 135054 | unavailable | 17.731 | 6.30 | When would you like to schedule your appointment, Rahul? |
| 6 | 1.920 | 3.977 | 95455 | 190910 | unavailable | 9.951 | 2.50 | No problem. Is there a specific date you have in mind for your appointment? |
| 7 | 3.360 | 4.850 | 116400 | 232800 | unavailable | 16.985 | 3.50 | That's fine. Whenever you're ready, please let me know which date you would prefer for your routine dental appointment. |
| 8 | 3.300 | 4.850 | 116400 | 232800 | unavailable | 20.129 | 4.15 | Thank you, Rahul. What time on October 20, 2026 would you prefer for your appointment? |
| 9 | 16.800 | 20.268 | 486436 | 972872 | unavailable | 27.023 | 1.33 | Full name/phone/date/time summary, request collection limitation, correction question. |
| 10 | 12.900 | 16.195 | 388691 | 777382 | unavailable | 24.965 | 1.54 | Request noted, future confirmation promised, anything else question. |
| 11 | 1.080 | 3.686 | 88473 | 176946 | unavailable | 15.599 | 4.23 | You're welcome, Rahul. Thank you for calling. Have a great day. |

Full transcripts for summary turns remain in the persisted evaluation; these are provider
transcripts, not recovered local Whisper outputs. No independent per-turn STT transcript
capture is available for this historical evaluation.

## Buffer and scheduling trace

VapiVoiceTransport.receive_audio creates a new local audio_chunks list on every invocation.
Leading silence is bounded to approximately 0.5 seconds before speech. Binary chunks are
recorded passively and appended for this utterance. The provider speech-stop control
finalizes the joined chunks, wraps PCM as a 24kHz mono WAV and returns. The runner passes
the unchanged WAV to FasterWhisperSTT; its decoder reads the WAV header and resamples to
16kHz for inference. No entire-session recording is passed to STT. No STT buffer is kept
on the provider after transcription.

Control frames and binary frames are consumed serially. A duplicate stop arriving at the
start of the next receive cannot return old chunks: the new list is empty. New offline
tests verify distinct byte patterns across successive utterances, duplicate stops,
24kHz headers and bounded leading silence. Historical network-level duplicate frames,
queued audio while the persona speaks and exact stop ordering cannot be ruled out from
the retained evidence. No speculative transport change was made.

run_calling_evaluation is a synchronous FastAPI endpoint. It is dispatched by FastAPI to
the worker pool rather than running the synchronous STT on the asyncio event-loop thread.
No async worker refactor is warranted by this path. The cache lock covers model lookup
and construction only, and is released before decoding or inference. Concurrent mocked
acquisition constructs one model. Each benchmark process loads one model and reuses it
for all four clips; CTranslate2 is not constructed once per clip.

## Current effective configuration

| Setting | Value |
|---|---|
| model / device / compute | small / cpu / int8 |
| cpu_threads / num_workers | 4 / 1 |
| beam_size / best_of | 1 / 5 (best_of applies to nonzero-temperature fallback) |
| vad_filter | false |
| condition_on_previous_text | true, within each transcription call |
| language before / after | automatic / en for this explicitly configured English scenario |
| temperature | library fallback sequence 0, 0.2, 0.4, 0.6, 0.8, 1.0 |
| word timestamps | false |
| batching | none; synchronous WhisperModel.transcribe |

Machine: Intel Core i5-1235U, 10 cores / 12 logical processors. Sequential one-, four-,
eight- and twelve-thread trials gave average clip times of 32.27s, 14.88s, 11.18s and
10.61s respectively, with inconsistent per-clip improvements at higher counts.
No thread default or search setting was changed. Temperature fallback can add work on
uncertain audio but was retained for accuracy. The language hint avoids an entire encoder
pass without reducing model size, quantization quality, beam search or sample content.

## Optimization and configuration ownership

The English appointment scenario now declares agent.config.stt.language: en. The calling
runner factory merges scenario STT settings with connection STT settings, with explicit
connection settings taking precedence. All providers use this same mechanism. An
unconfigured scenario still uses automatic detection; no global English assumption exists.
Multilingual scenarios should omit the fixed hint. No persona, scoring or termination
behavior was changed for this optimization.

STT now explicitly uses FasterWhisper's own decode_audio before transcribe, preserving its
resampling/channel conversion behavior while allowing preprocessing to be timed separately.
Model acquisition, preprocessing, invocation, lazy iteration, total time and RTF are kept
as numeric diagnostics on the STT instance and propagated into Calling latency metadata.
Input header rate, channels, bit depth, sample count, PCM bytes and measured 20ms-window
RMS-below-60 duration are included. RMS is an amplitude proxy, not a claim of exact speech
detection. No raw audio or transcript text is added to ordinary logs by this instrumentation.

## Same-clip before/after benchmark

Source: existing full_call.wav, beginning at its first RMS>=60 window. The 1-second clip
cuts the first greeting; 2 seconds contains the greeting. The 5/10-second prefixes include
the same greeting and real following pause, not independent 5/10-second spoken sentences.
This controls sample content across configurations and exposes fixed encoder overhead;
it does not establish performance/accuracy across every long utterance or language.
No silence was removed from the original recording. Clips are constructed only in memory.

| Clip s | Before ms | After ms | Before RTF | After RTF | Text before = text after |
|---|---:|---:|---:|---:|---|
| 1 | 15333.4 | 4222.8 | 15.333 | 4.223 | Hello? What kind of- |
| 2 | 15340.4 | 4892.8 | 7.670 | 2.446 | Hello, what kind of help I do? |
| 5 | 14901.4 | 5483.4 | 2.980 | 1.097 | Hello, what kind of help I do? |
| 10 | 13939.0 | 5743.2 | 1.394 | 0.574 | Hello, what kind of help I do? |

All four outputs match exactly, hence also match semantically. Average total STT fell
65.8%. This preserves the baseline wording, including its imperfect greeting transcription;
it does not prove the transcription matches ground truth perfectly.

| Clip s | Decode before/after ms | Invocation before/after ms | Lazy iteration before/after ms |
|---|---|---|---|
| 1 | 80.4 / 31.2 | 6316.7 / 5.0 | 8936.3 / 4186.7 |
| 2 | 73.6 / 39.7 | 8155.4 / 6.9 | 7111.4 / 4846.2 |
| 5 | 72.0 / 55.5 | 7196.9 / 20.6 | 7632.6 / 5407.4 |
| 10 | 76.7 / 70.2 | 6614.2 / 28.4 | 7248.1 / 5644.7 |

Model construction was measured separately: 4206ms in the baseline process, 2818ms in the
English-hint process. That variation is cold acquisition, not an optimization claim. Both
processes reuse one model for all clips. Application cache reuse and concurrency are tested
separately. New live diagnostics measure cache lookup per actual transcription.

Reproduce offline:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_calling_stt.py --threads 4 --output scratch/stt_before_4.json
.\.venv\Scripts\python.exe scripts/benchmark_calling_stt.py --threads 4 --language en --output scratch/stt_after_language_en.json
```

The script loads a cached local model directory with HF_HUB_OFFLINE=1; it cannot create a
provider call. Raw benchmark measurements remain in scratch/stt_*.json.

## Limits and changed files

Short-utterance RTF<1 was not achieved with this model/CPU. Measured warm STT remains
approximately 4-6 seconds on these clips. Additional endpointing, TTS, transmission and
occasional Groq time still contribute to live response latency. A live speedup is expected
from the removed pass but has not been measured or guaranteed. Exact historical silence,
per-turn cache misses, CPU contention and network queueing remain unavailable.

Changed in this task: app/adapters/voice/local.py (_inspect_audio_bytes, transcribe),
app/calling/execution_pipeline.py (_voice_conversation_runner),
app/calling/voice_conversation_runner.py (STT diagnostic propagation),
scenarios/appointment_inbound_calling.yaml (explicit language),
scripts/benchmark_calling_stt.py, tests/test_calling_stt_runtime.py and this report.
Chatbot source, RAG source, persona/scoring/termination and recorder semantics are unchanged.

Final offline regression result: **313 passed**, 16 warnings, 34.45 seconds. This covers
all Calling and mocked Vapi modules, local voice adapter, recording, persistence/report,
evaluation service, chatbot API/scripted steps and Calling RAG. Six new focused tests
cover PCM metadata/silence, lazy inference timing, concurrent cached acquisition,
cross-turn isolation with duplicate stops, bounded leading silence and optional language
configuration with explicit connection override. No asyncio worker test is applicable:
no async scheduling change was made. git diff --check passed with existing line-ending
warnings only. Testing stopped after this run; no live evaluation was run.
