# Home Accounts

Home Accounts is a local household-finance workspace for recording what happened, reviewing a month, setting optional budgets and exploring future scenarios. The current interface is a routed, responsive browser application with Light, Dark and Bright modes, a conventional Overview home or a chat-first Coach home, an expandable top-right chat panel, guided walkthroughs, and separately optional browser speech and OpenAI live voice.

This version is intended to run on your computer at **http://127.0.0.1:8501**. Optional AI can call a remote API; “local” describes the application and its CSV storage, not a technical restriction of AI services. See [the project completion report](PROJECT_REPORT.md) for the purpose, key features, development process and validation results.

## Architecture and project structure

The UI uses native HTML, CSS and JavaScript ES modules. It needs no frontend build server, CDN, remote fonts or runtime Node installation. Python's `ThreadingHTTPServer` serves the UI and JSON API on the same loopback origin. This replaced Streamlit navigation to provide actual paths, direct links, refresh and browser history, while reusing the tested finance logic. The original Streamlit interface remains available as a fallback.

| Location | Purpose |
| --- | --- |
| `local_api.py` | Local HTTP server, API contracts, temporary upload/proposal cache, confirmation gates and same-origin protection |
| `web/index.html`, `web/app.js`, `web/style.css` | Responsive routed screens, icons, forms, charts, themes and navigation |
| `web/live-voice.js`, `live_voice.py` | Opt-in WebRTC audio, server-only OpenAI authentication, scoped local Coach bridge and microphone cleanup |
| `web/overview-charts.js`, `web/overview-charts.css` | Exact currency-scoped monthly/yearly charts with accessible data tables and scoped record links |
| `web/ui-helpers.js` | Currency search, accepted-only history/spelling suggestions and guided walkthroughs |
| `coach_guidance.py` | Shared Home Accounts guide role for text and live voice, grounded in verified facts and explicit assumptions |
| `web/chat-speech.js`, `web/chat-ui.js` | Chat composer, dictation, read-aloud and voice conversation controls |
| `web/voice.js` | Browser speech recognition/synthesis with explicit consent and cancellation |
| `web/dictation.js`, `audio_transcription.py` | In-memory microphone recording and server-side OpenAI transcription |
| `core.py`, `currencies.py` | Exact money validation, import normalization, deterministic totals, CSV revisions and undo |
| `schema.py`, `categories.py` | Shared editable fields, custom types and optional category hierarchy |
| `planning.py` | Compound growth, FIRE target and budget variance calculations |
| `ai_client.py` | Server-side Responses API adapter, strict proposals and verified numeric answers |
| `server.py` | Read-only XLSX cached-value reader; despite its historical name, not the HTTP server |
| `sample_data/` | Fictional mixed-currency and US household fixtures, plus a reproducible US demo generator |
| `tests/` | Python domain, API, persistence and legacy Streamlit tests |
| `e2e/`, `playwright.config.cjs` | Playwright functional/responsive tests and reviewed visual baselines |
| `app.py`, `overview.py`, `planning_ui.py`, `setup_flow.py` | Preserved legacy Streamlit interface |
| `data/`, `data-backups/` | Private local records/settings and reversible first-upgrade backup; ignored by Git |

The browser displays server-calculated financial amounts. Chart scaling and illustrative number formatting occur in the UI; confirmed money arithmetic uses integer minor units in Python. Financial mutations are validated, staged on the server, reviewed with exact records/current-versus-proposed effects, and committed only after explicit confirmation. Stale revisions are rejected. Undo restores both financial CSVs.

The server binds only to `127.0.0.1`, verifies local Host/Origin, requires a per-process token for POST operations, escapes record text in the UI, refuses cross-origin reads and sends a restrictive content-security policy. It is a single-user local course application, without login, bank connections, public hosting or a production deployment configuration. Responsive phone/tablet layouts do not make the PC's loopback address accessible from another device.

## Install and run from a fresh checkout

Prerequisites: **Python 3.12**, a modern browser, and a terminal. **Node.js 22+** and **npm** or **pnpm** are needed only for Playwright tests. The checked visual baselines use Microsoft Edge on Windows. The repository folder is `HomeAccounts`, distinct from the private original sample folder `Home Accounts`.

In Windows PowerShell:

```powershell
cd 'D:\Documents\Code Repos\HomeAccounts'
py -3.12 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
& '.\.venv\Scripts\python.exe' local_api.py --port 8501
```

Open **http://127.0.0.1:8501**. Stop with **Ctrl+C**. Once dependencies are installed, run `./start.ps1` if your script policy permits, or use the Python command above. `requirements.txt` lists direct dependencies; `requirements-lock.txt` records the installed versions. The retained Streamlit, pandas and Plotly dependencies support the legacy interface and existing tests.

There is **no frontend compile/build step**: the Python server serves the files in `web/`. Development and a normal local run use the same command. Refresh the browser after frontend edits; restart the process after Python changes. This is not an internet production server.

The legacy fallback uses a separate port:

```powershell
& '.\.venv\Scripts\python.exe' -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

Or run `./start-legacy.ps1`. It reads the same revisions and field schema. Prefer one UI while changing settings; record writes still enforce expected revisions across tabs/processes.

## Routes, navigation and visual modes

| Route | What it does |
| --- | --- |
| `/` | Opens the saved home preference; sends a fresh workspace to setup |
| `/setup` | Upload or describe fields, edit suggestions and optional taxonomy, then confirm |
| `/overview` | Read-only confirmed income, net expenses, surplus, optional budget remaining and drilldowns |
| `/transactions` | Search, column filters/sorting, filtered CSV export, and previews for edits/removals |
| `/entry` | Traditional form, sentence interpretation, refunds, transfers and two-way expense splits |
| `/budgets` | Optional monthly category/subcategory limits and budget-versus-actual progress |
| `/coach` | Direct full-page chat compatibility, grounded local/optional connected chat and voice controls |
| `/import` | CSV/TSV/XLSX mapping, normalized review and separate import confirmation |
| `/planning` | Savings goals, FIRE, compound growth and budget variance; `?tab=fire`, `growth`, `goals` or `variance` opens a calculator |
| `/learn` | Concepts and educational links |
| `/settings` | Persisted theme and home-screen choice, field setup and undo |

Direct links and refresh work. Sidebar and mobile bottom navigation reflect the active route; browser back/forward works. Drilldown URLs carry month, currency and category filters. The canonical spelling is `/overview`.

Choose **Light**, **Dark** or **Bright** in Settings. Bright has its own purple/rose palette rather than merely increasing brightness. The header also cycles visual modes. In Settings, choose **Overview** or **Coach** as the home screen and save it; opening `/` follows that preference. The menu remains available in chat-first mode.

Desktop uses a sidebar, tablet uses compact navigation and wider cards, and phone layouts use a menu drawer plus bottom navigation. Forms and dialogs fit the screen; wide data tables scroll within their own container. Charts have labelled keyboard/touch controls that open records. Visual tests cover 390px phone, 834px tablet and 1440px desktop layouts, with additional 375px functional checks. These are browser viewport tests, not claims of testing every physical device.

## Everyday controls and guided help

Use **Chat** at the top right to open chat alongside the current page; expand it for more room or collapse it back to a panel. Chat uses this header entry instead of a primary left-navigation item. The full `/coach` route and saved Coach home preference remain available. Typing in chat preserves forms on the parent page. **Local workspace** explains that records and settings live on this computer; it is not a workspace-switching dropdown.

The header currency picker searches country names, currency names and ISO codes using local CLDR data. Choose an option, or press Enter on an exact code or unique match. The month/year control accepts months beyond those already recorded. Changing the reporting selection never changes stored currencies. Theme controls have descriptive hover text and readable status notifications. Table text, helper text and footers use larger type in every visual mode.

**Add transaction** on Overview or Transactions opens a dialog. Review and confirm the proposed transaction; a successful save closes the dialog, refreshes the parent page and highlights new records where they match the filters. A saved-record link helps find records outside the current selection. The left-navigation **Add transaction** entry and `/entry` retain the full-page form. Particulars, merchant and account fields suggest confirmed history. A **Did you mean…?** suggestion changes the entry only when explicitly selected; no spelling is silently corrected.

Transactions offers per-column filtering and sorting in addition to its page filters; amounts sort numerically. Manual transaction and budget forms remain available alongside file-import entry points. Both routes require review and confirmation before financial records change.

**Help** opens a page walkthrough or a full-app tour with highlighted controls and step-by-step explanations. The page tour preserves the current form; the whole-app tour navigates between pages, so finish unsaved work first. Optional narration uses browser speech after an explicit choice. These are built-in interactive instructions, not generated or prerecorded help videos. Starting a tour makes no model API call.

Transactions and budgets use one shared category catalog; budgets use its expense category/subcategory pairs. The server validates the type and exact parent-child relationship. Confirmed and imported pairs appear in the shared choices. New pairs are listed in the financial preview and need a separate acknowledgment before saving. Manual children assigned to the wrong known parent, archived choices and case/spelling variants receive correction guidance. Imports retain their exact classifications for explicit review. Archived historical records remain editable without silent relabeling. Catalog additions travel with financial revisions, survive clearing transactions and are restored by undo.

Overview's **Clear all transactions** is available beside **Add transaction** at the top and in **Start again** at the bottom. Both prepare the same review of every transaction across all months and currencies, independent of the current filters. Nothing is cleared until the scope acknowledgment and final confirmation. Budgets, fields, preferences and shared category choices remain. Clearing resets import provenance so the same file can be imported again. **Review undo** can restore the cleared transactions and previous import tracking. This is a reversible reset, not secure deletion of historical files.

## First-run setup is not an import

The first screen has exactly two paths:

1. **Upload a file:** full history, partial history or a sample as CSV, TSV or XLSX, up to 10 MB. Inspect suggested fields and source meanings.
2. **Describe your fields:** for example, `date, category, particulars, expense amount, income amount, monthly budget, payment method`. Local interpretation is the default; optional connected suggestions require opt-in.

Rename displayed labels, include/exclude/remove optional fields, add custom fields and choose supported custom types. Date, type, amount and currency are required. Choose a default currency to enable **Confirm fields & continue**. No USD default is assumed. Existing file currency codes are preserved; missing codes use the explicitly chosen default.

After confirming uploaded fields, continue in **Import data**: confirm sheet/mapping, defaults and date style; **Prepare import review**; inspect normalized records, issues and possible duplicates, optionally exclude rows and update the preview; **Continue to confirmation**; then **Confirm save**. Invalid rows and conflicting budgets block import. Import budgets separately; repeated limits are deduplicated by month/currency/category/subcategory. Blank/template/total rows are skipped. Excel 1900-calendar serial dates are supported; export a 1904-calendar workbook to CSV first.

An Overview with no confirmed records explains this distinction and offers import/entry actions. Its default month is the latest month with transactions in the selected currency; empty month/currency selections show recovery guidance. Changing a reporting currency never relabels records or applies exchange conversion.

Custom **Text, Number, Date and Boolean** values persist in the CSV `custom_fields` JSON column, appear in entry/edit/review/list screens and survive export/reimport. Custom numbers retain decimal text, dates use ISO format. Optional fields removed from setup keep existing values. Arbitrary formulas, attachments, nested records and custom analytic calculations are not implemented.

In field review, optionally accept **household category suggestions**. Edit category/subcategory/type/active rows before confirming. These are suggestions, not a universal standard. New-entry subcategories depend on type and parent category. Referenced removals are archived for future entry while retaining historical records and classifications. Imported categories are never silently relabelled.

## Financial behavior and planning assumptions

Income records sum to confirmed income. Negative expense records are refunds and reduce net spending. Transfers are excluded from income/spending. Surplus is income minus net expenses, not evidence of saving or investing. Parent category limits include children; parent and child budgets are not summed twice. A zero budget is an explicit limit; missing limits show “not set.” Genuine overspending can be recorded after review; budgets never increase automatically.

Overview and charts are read-only. Category/month chart controls open matching Transactions. Forms, sentence interpretation, chat proposals, edits, removals, budget changes and imports share server-side validation and confirmation. Two-way splits are calculated on the server and require a positive expense with an allocation between zero and the total; refunds cannot be split through that control. Possible duplicates and uncategorized records require acknowledgement. Settings are separate reversible preferences rather than financial revisions.

Updating a proposal's preview retires its previous confirmation token. In Coach, reopening that proposal uses the corrected preview. Correcting an existing budget's month, currency, category or subcategory moves that reviewed limit: the preview includes the old and new scopes, other limits remain in place, and a collision with another limit is rejected before confirmation. Undo can restore the original limit.

Planning is illustrative and does not save transactions/budgets. Inputs and results remain in the current page session. Cash goals, invested portfolio assets, planned contributions and user-entered verified contributions are distinct. Observed FIRE estimates disclose date range and months with entries, exclude transfers and optional transfer-like categories, subtract refunds and annualize observed spending; partial history can distort them, so override the estimate.

FIRE target = annual expenses / withdrawal rate; at 4%, 25× expenses. Rates and horizon are editable, with nominal and inflation-adjusted portfolio scenarios, an inflated horizon target and an optional second return assumption. There is no guarantee or recommendation to retire. Compound growth supports principal, annual/monthly additions, beginning/end timing, 1–365 compounding periods/year, 0–100 years and chosen inflation. Equivalent interval rate is `(1 + annual_rate / periods)^(periods / intervals) - 1`. Zero years adds nothing. Fixed-rate scenarios omit taxes, fees and market variability. Variance = actual − budget; percentage divides by budget and is undefined for zero.

## Optional AI: exact configuration and limitations

Local mode needs no API key and makes no model request. To connect a provider, configure the server's local environment. **Never put credentials in source, the browser bundle, URLs, chat, CSVs, history or screenshots.** The secret-free `.env.example` shows names only; the app does **not** automatically load `.env` or `.streamlit/secrets.toml`.

| Variable | Actual default and behavior |
| --- | --- |
| `OPENAI_API_KEY` | No default. Required to enable connected requests. Read only server-side from process environment, then Windows User `HKCU\Environment` if absent |
| `OPENAI_MODEL` | `gpt-4.1-mini`; process environment, then Windows User variable |
| `OPENAI_TRANSCRIBE_MODEL` | `gpt-4o-mini-transcribe`; recording-to-draft transcription model |
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-2.1`; separate live voice model, read server-side from the same environment sources |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1`; the adapter appends `/responses` |
| `HOMEACCOUNTS_AI_PROVIDER` | `OpenAI`; a display/disclosure label, not an adapter selector |
| `HOMEACCOUNTS_DATA_DIR` | `data` beside `local_api.py`; optional process-environment override for the CSV store |
| `PLAYWRIGHT_CHANNEL` | Test-only: `msedge`; use `chromium` for an installed Playwright Chromium binary |

Use Windows **Environment Variables → User variables** to set `OPENAI_API_KEY`, and save both dialogs with OK. Do not paste the key into a conversation. Open a new PowerShell terminal and restart the server. User-variable fallback helps a process that predates a newly saved variable, but a restricted agent sandbox may not see the actual Windows account; launch from your own terminal in that case. Keys are never returned to the frontend or stored in CSV/settings/history. Status reports availability, not proven billing or model access.

Non-secret overrides can also be supplied in the launching terminal:

```powershell
$env:OPENAI_MODEL = 'gpt-4.1-mini'
$env:OPENAI_BASE_URL = 'https://api.openai.com/v1'
$env:HOMEACCOUNTS_AI_PROVIDER = 'OpenAI'
& '.\.venv\Scripts\python.exe' local_api.py --port 8501
```

Enable connected mode explicitly in Coach or field-description setup. The disclosure names the configured provider/base URL before a request. The server also checks that the request acknowledges that exact endpoint; changing provider configuration requires refreshing and opting in again. Field setup sends only the entered description; file parsing stays local. Coach sends the question, up to six recent messages, deterministic verified totals, chosen hierarchy and up to 50 records from the selected month/currency. API charges and provider data processing may apply. Requests set `store=false`; this does not mean the provider never processes or retains anything under its own policies.

The text adapter is in `ai_client.py`: **POST `https://api.openai.com/v1/responses`** by default, `Authorization: Bearer OPENAI_API_KEY`, JSON instructions/input, strict function schema, fixed function `tool_choice`, `parallel_tool_calls=false`, `max_output_tokens=1800`, `store=false`, 45-second timeout. It requires a completed Responses result containing exactly one matching `function_call` with JSON arguments. Numeric answers select server-computed facts; actions are validated proposals, never model-executed writes. Imported descriptions and chat text are treated as untrusted data. No automatic retries or paid connection probes occur during startup or UI tests.

`OPENAI_BASE_URL` supports **Responses-compatible API substitution**, including HTTPS hosts or an HTTP loopback endpoint such as `http://127.0.0.1:9000/v1`. Embedded URL credentials, query strings/fragments, non-loopback HTTP and redirects are refused. Changing the provider label does not change authentication or request/response formats. A provider offering only Chat Completions, different function schemas, response formats or authentication needs an adapter change. A local compatible endpoint that ignores auth still needs a non-empty configured placeholder key to enable the existing control. Do not promise that arbitrary APIs work by changing a URL.

Local Coach supports monthly/category/subcategory/budget questions, single-record sentence entry, exact-ID amount edits/removals, intentional budget changes and review of undo. Examples: `monthly summary`, `Household spending`, `I spent 45 EUR at a shop yesterday`, `I earned 1000 yesterday`, `set Household budget to 300 for 2026-10`, `change transaction FULL_ID amount to 20`, `delete transaction FULL_ID`. Asking to open imports, export, fields, taxonomy, split entry, goals, FIRE, growth, variance, learning or settings produces working tool links. Complex calculator inputs, file uploads, schema edits and splits use structured screens; the chat is not a free-form substitute for every form. Unknown/ambiguous requests require clarification or the supported tools. Connected chat remains constrained by verified facts and safe proposals rather than arbitrary forecasts or investment advice.

Local entry requests take priority over incidental tool words in descriptions (for example, `Springfield` or `fire insurance`). Explicit split requests still open the structured entry screen. `Total income`, `monthly income` and `How much income did I receive?` use the selected month's income total across categories. Recognized multi-transaction wording such as `I spent 45 and paid 20` asks for separate entries. These are limited rules, not general language understanding; always check dates, amounts, currencies and categories in the review.

A previous small real validation reached OpenAI but returned **HTTP 429**. The UI upgrade uses mocks and local data; live connected success is not claimed. Check API credits, project/organization limits and rate limits. A detected key alone does not establish access. Turn connected mode off to use local rules after a connection/quota failure.

Verified official references for this implemented API:

- [Responses create API reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Developer quickstart, including POST /v1/responses](https://developers.openai.com/api/docs/quickstart)
- [Function calling and strict proposals](https://developers.openai.com/api/docs/guides/function-calling)
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
- [gpt-4.1-mini model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Error codes, quota and HTTP 429](https://developers.openai.com/api/docs/guides/error-codes)

## Browser dictation, spoken replies and OpenAI live voice

The chat composer has three distinct speech actions:

- **Microphone — Dictate a message:** on first use, review the disclosure and choose Start dictation. Allow browser microphone access, speak, then choose Done. The words appear in an editable draft; only Send submits a chat message. Cancel preserves the original draft. Recordings have a two-minute and 8 MiB limit and remain in memory only.
- **Speaker under a reply — Read reply aloud:** opt in once per page session and listen to a chosen reply using browser speech synthesis. Stop reading ends playback. Chat settings also offer Read new replies aloud. The browser’s speech provider may process reply text; a matching installed local voice is preferred.
- **Voice — Voice conversation:** opens a separate dialog. Start voice conversation explicitly permits an OpenAI WebRTC session and requests microphone access. Talk back and forth, mute/unmute the microphone, inspect the transcript, or End conversation. Closing the dialog, closing chat, navigation, page hiding and leaving the page stop audio. If autoplay blocks replies, Play voice replies appears. There is no automatic reconnect.

**Chat settings** select dictation method and speech language (English US/India/UK or Tamil). OpenAI transcription is the default when configured and recording is supported. It captures microphone audio directly with MediaRecorder, then sends the recording through the local server to **POST `https://api.openai.com/v1/audio/transcriptions`** after Done. It requires API credits; the permanent key stays server-side. The server validates consent, provider endpoint, size, MIME and file signature. Audio is never written to disk. Cancelling a request prevents a late transcript from changing the draft; a request already received by the provider may still incur usage.

Browser dictation is an alternative using `SpeechRecognition`/`webkitSpeechRecognition`; availability depends on the browser, its speech provider and microphone policy. Some embedded browsers expose the API but cannot connect to the speech service. Helpful errors direct users to OpenAI transcription or typing. Browser speech may process audio remotely and is not guaranteed offline. See [SpeechRecognition](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition), [SpeechSynthesis](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis), and [OpenAI audio transcription](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create).

The server exchanges an SDP offer for an answer using **POST `https://api.openai.com/v1/realtime/calls`**, with multipart `sdp` and `session` fields. The permanent API key stays on the server; the browser receives an SDP answer and uses WebRTC media/data channels. Live voice requires the official OpenAI provider and endpoint, independently of Responses-compatible substitutions. Its model is configured separately through `OPENAI_REALTIME_MODEL`. The app stores no audio files.

Live voice sends microphone audio, the current page and selected month/currency to OpenAI. When the user asks about account figures or explicitly requests a change, one narrowly defined tool calls local Coach for that captured selection. Only its answer, scope and whether a review is needed are returned to the voice model; raw transaction arrays, history and proposal tokens are excluded from that tool output. Unsupported requests use local clarification or form guidance. Proposed changes open the same on-screen review as typed chat. The model has no save/confirm tool, and a spoken yes cannot commit anything. API audio/transcription usage can incur charges.

Connected text and live voice share the role in `coach_guidance.py`: explain the app, encourage practical budgeting and saving, and discuss planning and long-term investing as education. Responses must distinguish confirmed facts from assumptions and avoid invented totals or promised outcomes. This guidance supplements deterministic calculations and server validation; it does not authorize financial writes.

Automated voice tests use mocked transports, audio and local tools. They check consent, cleanup, stale responses and proposal gates; they do not establish live OpenAI access, microphone behavior or recognition quality. No paid live call was used to validate this implementation. Official references: [Realtime WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc?voice-api=realtime) and [Realtime call creation](https://developers.openai.com/api/reference/resources/realtime/subresources/calls/methods/create).

## Persistence, private originals and fictional samples

`data/revisions/<revision>/transactions.csv` and `budgets.csv` are immutable paired snapshots. Atomic `data/current.json` selects the active complete revision and retains undo/import provenance. A short exclusive write lock and expected revision reject concurrent/stale writes. Failed saves retain the previous active revision. Uploads and staged proposals stay in process memory for one hour; a server restart expires them. Chat messages and planning inputs are browser-page state, not durable records.

`data/schema.json` stores field labels/types/taxonomy. `data/preferences.json` retains the legacy currency preference. `data/ui-settings.json` stores theme, home and currency. On the first upgraded run, existing data is copied to an ignored timestamped `data-backups/` folder before creating UI settings. The financial CSV format is unchanged. For a custom data location, the backup folder is a sibling named `<data-folder-name>-backups`; keep that outside public repositories too. Back up the entire data folder with all app instances stopped. Restore a backup by stopping the app, retaining the current folder elsewhere, and copying the backup into the data path. Undo is not secure erasure; historical private snapshots remain on disk.

File hash + sheet + source row prevents repeat imports even after edits/deletions. The explicit Clear all transactions reset releases this tracking, and undo restores it. Genuine identical rows retain distinct provenance. Other exports are compared by normalized values, not bank-grade transaction IDs. Currencies use Babel/CLDR ISO codes, including some historic codes; crypto, exchange rates and cash rounding rules are unsupported. Accounting precision is enforced, e.g. JPY 0 decimals, EUR/INR 2, KWD 3, CLF 4.

| Bundled file | Fictional contents |
| --- | --- |
| `sample_data/household_demo.csv` | 12 EUR/INR income/expense rows, a refund, custom payment method and 8 distinct monthly limits |
| `sample_data/balances_wishlist_demo.csv` | 6 balance/liability/due/wish snapshot rows; blocked from transaction/budget import |
| `sample_data/us_household_transactions.csv` | 462 fictional USD records, November 2025–October 2026: salary, freelance, bonus and interest income, varied household expenses, seasonality and refunds |
| `sample_data/us_household_budgets.csv` | 324 matching monthly USD budgets for 27 expense category/subcategory pairs over the same 12 months |

The US examples include months above and below budget. Choose the named demo actions or upload their CSV files, and review transactions and budgets as separate imports. Selecting a demo never imports automatically. `sample_data/generate_us_demo.py` reproduces both US files. These amounts and households are fictional, not spending recommendations.

Original household workbooks remain separate and private. The app does not require or automatically import them. Local workbook regression checks and inspection scripts are excluded from Git. Git also ignores real CSV/XLSX/TSV files, private data/backups, credentials, logs, venv, node_modules and test outputs. Only `sample_data/*.csv` is exempt for the fictional fixtures; reviewed PNG baselines contain fictional data only.

## Tests and reviewed visual baselines

Python checks:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -q
```

Install the pinned Playwright test dependency with either package manager:

```powershell
npm install
# Or: pnpm install --frozen-lockfile
npm run test:e2e
npm run test:visual
```

Microsoft Edge on Windows is the default test channel. To use bundled Chromium instead:

```powershell
npx playwright install chromium
$env:PLAYWRIGHT_CHANNEL = 'chromium'
npm run test:e2e
```

Visual rendering differs across browser versions, operating systems and fonts. The checked baselines were reviewed with **Windows Edge**; switching channel/platform requires reviewing corresponding baseline changes rather than blindly accepting them.

Playwright starts an isolated fictional server on **127.0.0.1:8765**, resets only its own temporary fixtures and stops it at teardown. The reset/stop endpoints exist only in `e2e/run_server.py`, not the normal server. Test traffic is blocked from non-local destinations. Connected AI and speech are mocked where tested; there are no paid AI calls or real microphone captures. The live `data/` folder and original samples are not modified.

Functional coverage includes real routes/history, refresh, active navigation, scope/drilldowns, confirmation/correction/undo, custom values/export, first-run setup, snapshot rejection, saved themes/home, grounded chat/tool links and voice control/fallback/opt-in. Visual coverage includes Overview in all three themes across phone/tablet/desktop, Coach in each theme on phone/desktop, a phone confirmation dialog, tablet settings and first-run phone onboarding. Responsive/contrast tests also inspect bounded layouts and text contrast. Only volatile proposed record IDs are masked in dialog screenshots; money values and errors are not masked.

Additional regression checks cover chat merchant/tool-word collisions, total-income questions, selected multi-transaction ambiguities, budget correction across scopes, collision rejection, retired/stale previews, and browser chat edit/delete/budget/undo confirmation. Speech mocks exercise delayed permission events, errors followed by completion, rapid Start clicks, late transcripts after Stop/consent revocation/navigation, and synthesis completion after mute. They do not validate real speech services or microphone hardware.

### Hands-on acceptance checks

For practice without touching your records, start the isolated fictional server in a separate terminal (do not run it alongside Playwright, which uses the same port):

```powershell
cd 'D:\Documents\Code Repos\HomeAccounts'
& '.\.venv\Scripts\python.exe' e2e/run_server.py
```

Open **http://127.0.0.1:8765/coach**. This server disables connected AI and stores disposable fixtures in a temporary folder. Stop it with Ctrl+C after testing.

1. Ask `monthly summary` and `total income` with EUR / 2026-10 selected. The fictional fixture has income **3,250.00** and net expenses **232.75**. Change currency/month and verify the labels and totals follow that selection.
2. Enter `I spent 45 at Springfield yesterday`. Inspect the proposal, correct it, close and reopen its review, then confirm only if intended. Try an exact-ID edit, deletion, budget correction and undo. Closing a review must leave records unchanged; confirming must change only the reviewed records.
3. With your actual browser and microphone, choose Dictate a message, opt in and allow microphone access. Say a short sentence, choose Done and inspect the editable draft before Send. Try Cancel while permission/transcription is pending, denied permission, navigation, and reply playback. On the normal app with funded API access, also try OpenAI transcription and Voice conversation. The fictional server cannot call OpenAI. Record browser, language and behavior; mocks do not establish real device/provider quality.
4. Check phone/tablet layouts in your browser and keyboard navigation, including correction dialogs. Automated viewport/contrast checks do not replace usability or assistive-technology testing.

Live connected-AI success remains unverified. A deliberate live test on the normal app requires its own user opt-in and may incur API charges; the fictional test server cannot perform it. Chat history and planning inputs remain page-session state. Local Coach still has a restricted grammar, and complex inputs require structured screens.

Baseline review workflow:

```powershell
$env:CAPTURE_BASELINES = '1'
npm run test:visual
Remove-Item Env:CAPTURE_BASELINES
```

This captures **candidates** in ignored `test-results/candidates/` without changing baselines. Inspect every changed render, verify expected data and controls, fix any errors/overlap/contrast problems, then copy only approved candidates into `e2e/snapshots/` with the same filenames. Run normal tests again to perform actual comparisons. Never use an automatic snapshot-update command to bless failures. Playwright stores reports/traces in ignored output folders; `npx playwright show-report` opens the test report. See [Playwright visual comparisons](https://playwright.dev/docs/test-snapshots).

## Troubleshooting

- **Port 8501 is in use:** stop the known old app with Ctrl+C, or run `local_api.py --port 8504` and open that exact URL. Both UI and API use the same port. Do not terminate unrelated processes.
- **Overview looks empty:** confirming fields is not importing records. Complete import review and Confirm save, or add an entry. Check reporting month/currency; there is no implicit FX conversion.
- **Confirmation is disabled:** choose a default currency and keep required fields. In record review, acknowledge duplicates, uncategorized rows or new shared categories where shown. Clearing all transactions also requires its explicit scope acknowledgment. Invalid dates, amounts, precision, mappings and conflicting budgets require correction.
- **Preview expired or records changed:** restart/one-hour expiry clears temporary previews; another save changes the revision. Upload or prepare a fresh review instead of retrying an old token.
- **AI is unavailable or returns 401/403/429:** verify local configuration, endpoint/model permissions and API billing/limits. Save Windows variable dialogs and restart from a new terminal. No key should be shared in chat. A malformed endpoint disables connected mode while retaining local functions.
- **Voice unavailable:** use typing; check browser support, provider network access, microphone hardware and permission. Dictation, read-aloud and voice conversation have separate opt-ins. Select dictation provider in Chat settings. OpenAI transcription and conversation require API credits; an exhausted balance cannot be fixed by enabling browser microphone permission. Stop controls remain available; live voice additionally requires OpenAI API access and WebRTC support.
- **PowerShell script policy or stale venv launcher:** invoke `.venv\Scripts\python.exe` directly as shown. Use `python -m` for package commands. Recreate a venv after moving it if necessary.
- **Playwright cannot launch:** install/use Edge, or install Chromium and set `PLAYWRIGHT_CHANNEL`. Make sure port 8765 is free. Use Node 22+ and install the pinned dependency.
- **Visual differences:** use the same OS/browser/fonts, inspect the report and review candidates. Do not hide real data/error/layout changes with broad masks or loose tolerances.
- **A crash leaves `data/write.lock`:** stop every app instance, back up data and inspect the active revision before removing only that empty lock directory. An incomplete inactive revision does not change active totals.

Educational links in Learn are for concepts and assumptions, not product endorsements or promises. Moneychimp was inspiration; its calculation was independently implemented and tested. The app has no debt/asset ledger, bank syncing, arbitrary custom formulas, investment recommendations or automatic cloud backups.


## One currency setting and overview charts

Choose currency in the page header. New transaction and budget forms use this selection as a read-only field, as do the import default and revisited field settings. Initial onboarding asks once before the header exists. Editing existing records and importing currency-labelled rows preserve their original currency; selecting USD never relabels or converts prior EUR/INR amounts.

Overview → Spending patterns provides **Monthly** and **Yearly** controls and a chart-type selector. Monthly views show each calendar day’s net expenses, expenses against the planned monthly budget, and the category split. Yearly views show every calendar month, expenses against monthly budgets, category split, and expenses versus recorded surplus. The header’s month/year picks the reporting period. Exact values and scoped record links are available under View exact chart data.

Refunds retain their sign. Missing budgets are shown as Not set, separately from explicit zero limits. Category-wide budgets include their child limits without double counting. Pie charts use positive portions only; net-refund categories and deficit years receive a signed comparison instead. Recorded surplus means income minus net expenses; it does not establish actual saving or investing. Chart aggregates use integer minor units, and currencies remain separate.
