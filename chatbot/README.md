# Orbital Health Copilot

An isolated Gemini adapter for Health Copilot in the main Next.js interface. The chat page lives in `frontend/my-hub/src/app/chat`; this Python service provides a protected local API only and does not create a separate UI.

## What makes it different

The **evidence-first, mission-aware copilot** does not reduce the data to an abstract index. For each response, it retrieves the latest telemetry, signal quality and freshness, personal baselines, and report findings; Gemini receives this current context. The response includes cited sources and can surface only next steps already proposed by the report. NASA references are provided separately from personal data.

Analytical values are not interpreted as diagnoses: a detector score is not a probability, a change from baseline is not a medical threshold, and a model contribution is not a cause. If a value is missing or has low quality, it remains unknown rather than being presented as "normal."

## Data and safety boundaries

- The Gemini API key is stored only in the local Python service environment; the browser never receives it.
- Chat sends profile data to Google AI Studio. The sign-in screen discloses this and requires confirmation before use. Use only a synthetic profile for demonstrations.
- The service **blocks real telemetry from being sent**. Connecting real measurements would require a separate privacy, data-protection, and external-processing decision; this prototype has no switch to bypass the safeguard.
- The mission API token is held only in the browser tab's memory and is not written to `localStorage` or a URL. Signing out clears the conversation and token.
- The service listens only on `127.0.0.1`. Do not expose it to a public network.
- This is a situational-awareness prototype, not a medical device, clinical decision-support system, or replacement for an onboard physician. For serious or sudden symptoms, follow the mission emergency protocol and contact a medical professional immediately.

## Run the local demo

Requirements: Python 3.10+ and a running Django API and simulator with a crew profile created. Create `chatbot/.env` from the template if it does not exist, then add your own key. Do not commit the local `.env` file.

From the repository root in Windows PowerShell:

```powershell
if (-not (Test-Path chatbot\.env)) { Copy-Item chatbot\.env.example chatbot\.env }
# Edit chatbot\.env and set GEMINI_API_KEY before starting the service.
python -m chatbot.server
```

On macOS/Linux, the equivalent template setup is:

```bash
test -f chatbot/.env || cp chatbot/.env.example chatbot/.env
# Edit chatbot/.env and set GEMINI_API_KEY before starting the service.
python -m chatbot.server
```

The adapter reads `chatbot/.env` at startup. Terminal environment variables take precedence. Restart the Python service after changing `.env`.

The service listens only on `127.0.0.1:8766`. Set the proxy URL in `frontend/my-hub/.env.local`:

```dotenv
CHATBOT_API_URL=http://127.0.0.1:8766
```

Start the Next.js app from `frontend/my-hub` with `npm run dev`, sign in to mission control, and open **Health Copilot**. It reuses the active session and selected crew profile; no second sign-in or separate browser chat is needed. The default Gemini model is `gemini-3.5-flash-lite`, selected for low latency and high throughput. If necessary, set `GEMINI_MODEL` to a model available to your Google AI Studio API key.

The backend API defaults to `http://127.0.0.1:8000`. Set `MISSION_API_BASE_URL` to override it. Create a Google AI Studio key at [Google AI Studio](https://aistudio.google.com/app/apikey); never add a real key to project files or presentation materials. See [.env.example](./.env.example) for the environment-variable template. The Python module uses only the standard library; no extra packages are required.

## Request flow

1. The user signs in to Django through the main frontend. Next.js keeps the token in the tab's session and passes it to a same-origin route handler only for a chat request.
2. Next.js proxies the message to the local Python service without exposing the Gemini API key to the browser. The service reads `GET /dashboard/` and `GET /insights/?limit=120` using the authenticated token.
3. Gemini receives current measurements, quality, mission context, report metrics and baselines, the last 12 points for each metric, findings, and permitted actions. The model must return structured JSON.
4. The service validates every evidence/action ID against that request's context. Unknown IDs are not shown as sources or recommendations.
5. The main frontend displays the response, sources, report-proposed actions, and quality/analysis state. Switching profiles clears the chat so crew data cannot be mixed.

This adapter separates the UI, telemetry source, and context construction. If the analytics contract changes, adapt `build_grounded_context`; the Next.js chat API and interface remain stable. The interface reinterprets general chat patterns from Open WebUI without copying its source code.

## Checks

From the repository root:

```powershell
python -m unittest chatbot.tests.test_server -v
python -m py_compile chatbot/server.py chatbot/tests/test_server.py
```

Tests check that quality and baselines are carried into evidence context, fabricated model references are filtered out, and empty responses are rejected. These are software checks, not medical validation.
