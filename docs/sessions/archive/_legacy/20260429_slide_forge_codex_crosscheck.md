# Slide Forge Codex Cross-Check Handoff

Target repository: `E:\slide-forge`
Checked by: Codex
Checked at: 2026-04-29

## Request To Claude Code

Please use this as the Codex cross-check result for `E:\slide-forge`.
Review the current worktree before editing, because the repository had local uncommitted changes during the check.

Focus areas:

1. Programming quality
2. User experience
3. Security

Recommended fix order:

1. Security hardening: API key storage and CSP
2. `npm run lint` failures
3. Generate/regenerate cancellation and timeout UX
4. Documentation mismatch for dev server port
5. Optional bundle-size cleanup

Do not delete or move files unless explicitly requested.

## Verification Already Run

Commands run from `E:\slide-forge`:

```powershell
npm run lint
npm run build
npm audit --omit=dev
npm audit
```

Result:

- `npm run build`: passed
- `npm audit --omit=dev`: 0 vulnerabilities
- `npm audit`: 0 vulnerabilities
- `npm run lint`: failed with 6 errors

E2E flow was also run with a temporary Vite dev server at `http://127.0.0.1:1420`:

```powershell
py e2e\test_full_flow.py
```

Result:

- Passed
- Ollama auto-detect succeeded
- Default prompt generated a deck
- Result screen loaded
- PPTX download succeeded
- Downloaded `.pptx` was validated as a valid Office Open XML zip
- Observed generation time: about 110 seconds

Rust/Tauri check was attempted:

```powershell
cargo check
```

Result:

- Not run, because `cargo` was not installed or not on PATH in this environment.

## Important Findings

### 1. Security: API Keys Are Stored In Plain localStorage

Files:

- `src/lib/storage.ts`
- `src/types.ts`
- `src/components/Wizard.tsx`

Issue:

Cloud provider API keys are saved as part of `AppSettings` into browser `localStorage` under `slide-forge.settings.v1`.
This is documented in README, but for a distributed Tauri desktop app it is still a meaningful security risk.

Recommended fix:

- Move secret storage to OS keychain/keyring through Tauri.
- Avoid exposing long-lived API keys to frontend state where possible.
- At minimum, add stronger in-app warning and a "clear saved key" control.

### 2. Security: CSP Is Disabled

File:

- `src-tauri/tauri.conf.json`

Observed:

```json
"security": {
  "csp": null
}
```

Issue:

The app currently renders React text safely, but it also handles LLM output, external links, direct API calls, and Tauri permissions.
Leaving CSP disabled increases blast radius if any future UI change introduces HTML rendering or unsafe script injection.

Recommended fix:

- Set a restrictive CSP.
- Start with `default-src 'self'`.
- Add only required `connect-src` entries for:
  - Gemini
  - Groq
  - Anthropic
  - OpenAI
  - `http://localhost:11434` for Ollama
  - GitHub update endpoint if needed by the webview context

### 3. Security: Gemini API Key Is Sent In The URL Query String

File:

- `src/providers/gemini.ts`

Observed:

```ts
const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${encodeURIComponent(cfg.apiKey)}`;
```

Issue:

API keys in query strings can be exposed through logs, proxies, browser tooling, diagnostics, and error reports more easily than authorization headers.

Recommended fix:

- Prefer a backend/Tauri command boundary for provider calls.
- If Gemini supports an auth header for the used API version, use it.
- Otherwise document this risk clearly and avoid additional logging around request URLs.

### 4. PG: lint Currently Fails

Command:

```powershell
npm run lint
```

Observed failures:

- `src/App.tsx`: `react-hooks/set-state-in-effect`
- `src/components/Wizard.tsx`: `react-hooks/set-state-in-effect`
- `src/md/parser.ts`: `no-misleading-character-class`
- `src/pptx/generator.ts`: unused `getTheme`

Recommended fix notes:

- For `App.tsx`, avoid redundant synchronous `setDetecting(false)` when `setupDone` is already true.
- For `Wizard.tsx`, reset provider model/test state through event handlers or derived keyed state instead of synchronous effect state updates.
- For `parser.ts`, add the Unicode `u` flag or avoid emoji surrogate pairs in a character class.
- For `generator.ts`, replace type usage based on `getTheme` with an explicit type alias such as `type Theme = (typeof THEMES)[ThemeId]`, then remove the function.

### 5. UX: Generation Has No Cancel Or Timeout Flow

Files:

- `src/components/Main.tsx`
- `src/components/Result.tsx`
- `src/providers/index.ts`

Issue:

`callLLM` already accepts an optional `AbortSignal`, but the UI does not expose cancellation.
In the E2E run, local Ollama generation took about 110 seconds.
During that time the user can only wait.

Recommended fix:

- Add `AbortController` in `handleGenerate` and `handleRegenerate`.
- Add a visible cancel button while generating.
- Add a timeout with a clear message.
- Preserve partial UI state and avoid losing the prompt.

### 6. UX/Docs: Setup Document Uses Wrong Dev Server Port

Files:

- `docs/setup.md`
- `vite.config.ts`
- `README.md`

Observed:

- `vite.config.ts` uses port `1420`.
- README says `http://localhost:1420`.
- `docs/setup.md` still says `http://localhost:5173`.

Recommended fix:

- Change `docs/setup.md` to `http://localhost:1420`.

### 7. Security: Tauri Capabilities Are Broad For Current UI Needs

File:

- `src-tauri/capabilities/default.json`

Observed permissions:

```json
[
  "core:default",
  "shell:allow-open",
  "updater:default",
  "process:default",
  "process:allow-restart"
]
```

Issue:

The app needs updater and relaunch, and external links currently use anchors.
Still, `shell:allow-open` and `process:default` should be checked against actual usage and reduced if not needed.

Recommended fix:

- Verify whether `shell:allow-open` is required for anchor links in the current Tauri shell.
- Keep only updater and relaunch permissions required by `src/lib/updater.ts`.
- Prefer more scoped Tauri permissions if available.

### 8. Performance: Initial JS Bundle Exceeds Vite Warning Threshold

Observed during build:

- Main JS chunk: about 606 KB minified
- Vite warning: chunk larger than 500 KB

Likely cause:

- `pptxgenjs` is imported in `src/components/Result.tsx` through `generatePptx`.

Recommended fix:

- Dynamically import the PPTX generator only when the user clicks download.
- Consider lazy-loading provider-specific code if bundle growth continues.

## Positive Findings

- Build passes.
- Production and dev dependency audit reports 0 vulnerabilities.
- Existing E2E test covers a valuable happy path:
  - startup
  - Ollama auto-detect
  - generation
  - result rendering
  - PPTX download
  - basic OOXML validation
- Offline sample Markdown split appears reasonable in the current worktree:
  - `src/components/Main.tsx`
  - `src/components/Result.tsx`
  - `src/samples/defaultPrompt.ts`

This change improves AIなし mode because the textarea sample becomes real Markdown instead of an AI task prompt.

## Suggested Claude Code Patch Plan

1. Read the current worktree and avoid overwriting unrelated user changes.
2. Fix lint errors first and rerun `npm run lint`.
3. Fix `docs/setup.md` port mismatch.
4. Add cancellation and timeout UX for generate/regenerate.
5. Add a minimal CSP suitable for current provider calls.
6. If time allows, move PPTX generation behind dynamic import.
7. Run:

```powershell
npm run lint
npm run build
npm audit
py e2e\test_full_flow.py
```

8. If Rust is available, also run:

```powershell
cargo check
```

from `E:\slide-forge\src-tauri`.

