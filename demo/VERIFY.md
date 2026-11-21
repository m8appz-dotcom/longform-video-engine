# Verification and limits

The five-demo implementation was exercised through the Codex browser MCP in hidden tabs on X. The approved screens remain the baseline. No desktop focus or native keyboard input was used.

Verified for this demo:

- Read and edit the two English chapters.
- Inspect a shot plan and estimate narration duration at a chosen reading pace.
- Lock the script and export its content-bound SHA-256 contract. Editing either chapter resets the lock.

Shared checks: English visible/accessible content; desktop, narrow and intermediate compositions; local persistence; workspace export, compatible restore, invalid-file rejection and undo through the shared recovery UI. Product-specific JSON, CSV and ZIP files were downloaded and read independently. The locked Longform contract's SHA-256 matches its canonical UTF-8 script; the Toolkit ZIP passes a standard ZIP reader and preserves its selected originals.

Corrections during browser review included an editor/navigation overlap in Longform, the narrow JEV status selector, preservation of incomplete JEV review notes and placement of M8 replay controls. Original source images were not modified.

Automated checks reject unsigned workspace access, foreign-origin mutations, invalid registration, replayed challenges and unknown credentials. Real holder registration/login/recovery remains pending. Full accessibility certification, physical mobile-device testing, paid/live AI calls, microphone/audio acceptance and finished-video acceptance are not claimed.

Scope limit: The image is the existing original test frame. The demo does not produce a finished video, narration or selected footage. Timing is an estimate from word count, not measured playback.

## Connected engine update

Uses engine.longform_contract.full_script, script_hash and validate_approved_script. The content hash covers the native joined spoken text. English is explicit; Spanish and omitted-language scripts keep their existing diacritic checks. The preview calls the real Longform Remotion composition using the current locked chapters.

Gateway negative tests cover origin, protected actions, session ownership, unsupported input, invalid service credentials, safe errors and path containment. Physical holder passkey acceptance remains pending; it is never inferred from these tests.
