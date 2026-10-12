# Home Accounts Project Completion Report

## Project overview

**Home Accounts is a local web application for tracking household income and expenses, setting optional budgets, and making informed financial decisions through clear charts.**

Inspired by my habit of recording expenses by category, the project brings tracking, budgeting and planning into one interface. Users can identify spending patterns, compare actual expenses with their plans, and explore how recorded surplus could support future goals.

The deliverable is a working single-user application with fictional demonstration data, guided help, automated tests and optional AI assistance.

## Key features and value

| Feature | Value to the user |
| --- | --- |
| **Detailed transaction tracking** | Record income, expenses, refunds and transfers by category and subcategory; search, filter, sort and edit records. |
| **Optional budgeting** | Set monthly limits and compare them with actual expenses. Shared categories keep budgets and transactions consistent. |
| **Monthly and yearly reporting** | View daily or monthly expense bars, budget comparisons and category splits, with exact values and links to underlying records. |
| **Planning tools** | Explore savings goals, compound growth and financial independence scenarios with explicit assumptions. |
| **Flexible entry and import** | Add transactions in a dialog or full-page form, or import CSV, TSV and XLSX files with a review before saving. |
| **Confirmation and undo** | Review proposed financial changes, confirm them explicitly, and undo previous changes, including clearing transactions. |
| **Usability and guidance** | Use centralized currency selection, read-only currency fields elsewhere, responsive layouts, three visual themes and interactive page tours. |
| **Chat and speech options** | Open an expandable chat panel for supported local questions and proposals; optionally use connected AI, dictation, spoken replies or voice conversation. |

Monthly charts show daily net expenses, expenses versus budget, and category spending. Yearly charts show monthly expenses, budget comparisons, category spending, and expenses versus recorded surplus.

**Financial accuracy is a key differentiator.** Refunds reduce spending, transfers are excluded from income and expenses, and missing budgets are distinct from zero limits. Currency selection does not convert historical records. Recorded surplus means income minus net expenses; it does not establish actual savings or investments.

## Technology and architecture

| Layer | Implementation |
| --- | --- |
| Interface | HTML, CSS and JavaScript modules with responsive SVG charts |
| Server and calculations | Python local HTTP server, JSON API, validation and exact money arithmetic |
| Storage | Local CSV revisions with import tracking and undo |
| Optional AI | OpenAI Responses, transcription and Realtime integrations; browser speech capabilities |
| Testing | Python tests and Playwright functional and visual checks |

The initial Streamlit interface evolved into a routed browser application; Streamlit remains available as a fallback. Financial changes follow a **prepare → review → confirm → save** workflow. The server validates proposals and rejects stale revisions, while API keys remain server-side.

Core features work without API access. Connected services process the disclosed request context or audio externally. The current application runs on one computer and does not include public hosting, user accounts or automatic bank connections.

## Dataset and demonstration

The synthetic dataset was inspired by my expense-tracking practice rather than sourced from a public dataset. It contains **462 fictional US household transactions and 324 monthly budgets**, covering **November 2025–October 2026**, with **27 budget category and subcategory pairs across 11 expense categories**.

Examples include salary, freelance income, bonuses, recurring bills, groceries, healthcare, travel and refunds. Seasonal variation and months above and below budget make the data useful for demonstrating comparisons. A reproducible generator creates the CSV files; smaller mixed-currency fixtures support additional tests.

**Suggested demonstration:** import and confirm the sample transactions and budgets, review a month, inspect an over-budget category, switch to yearly charts, add a transaction, and demonstrate undo and guided help.

## Vibe coding process and prompts

I began with voice-based ideation in ChatGPT Codex, describing the requirements and initial technology preferences. I then tested the application and refined it through concrete feedback.

1. **Initial prototype:** GPT 6.1 Sol with Medium reasoning produced a basic application. Its visual design needed improvement.

2. **Usability iterations:** I requested clearer typography, better layouts, entry dialogs, searchable controls, filters, sorting and improved charts.

3. **Deeper review:** After summarizing progress, I continued in a new chat with GPT 6 Astra using Extra High reasoning. This stage identified and corrected additional bugs and design flaws.

4. **Guidance and AI:** I added a WalkMe-style tour and explored OpenAI chat and voice features. Connected testing encountered an API credit limitation.

These are condensed examples of the prompts used, not verbatim transcripts:

- **Concept:** “Build a home accounts application to track income and expenses by category and subcategory, with optional budgets and visual comparisons.”

- **Consistency and usability:** “Use shared categories for budgets and expenses. Set currency in one place. Open Add transaction in a dialog and refresh the parent page after saving.”

- **Reporting and assistance:** “Add monthly and yearly charts, a guided page tour, and an expandable chat with text, dictation, spoken replies and voice conversation.”

## Testing and completion status

The core local workflow covers entry, imports, budgets, reporting, planning and guided help. Validation completed with **96 passing portable Python tests and 69 passing browser tests**; one optional capture-only test was skipped.

Checks cover financial calculations, persistence, confirmation and undo, currency consistency, chart layouts, chat controls and speech lifecycle behavior. Visual review covers phone, tablet and desktop layouts in Light, Dark and Bright themes. Browser tests use isolated fictional data.

**Connected AI is implemented but not fully validated live.** A real API request returned an exhausted-credit error. Successful connected chat, OpenAI dictation and voice conversation require funded API access. Speech tests use mocks; actual microphone recognition and conversation quality still require hands-on testing.

The walkthrough is an interactive tour with optional narration. Planning tools provide illustrative scenarios, and browser speech availability depends on the browser and its services.

## Learnings and future scope

**Specific feedback produced better results.** Observable issues—small text, overflowing charts or an editable currency field in the wrong place—led to clearer improvements than general requests to improve the application.

**Reliable data mattered as much as visual design.** Shared categories, exact calculations, explicit confirmation and undo made the application more dependable. Human testing and review remained essential throughout the AI-assisted workflow.

**My personal assessment:** I generally use ChatGPT for ideation and prefer Claude for coding. After this project, I still found Claude better suited to my coding workflow. Codex nevertheless provided useful experience with voice-led development and iterative implementation. This reflects my experience, rather than a controlled comparison of the tools.

Future priorities are funded AI and voice validation, broader device and accessibility testing, and persistent goals and chat history. Multi-user access, bank integration and hosted deployment would require an expansion of the local architecture.

**Project outcome:** Home Accounts turns a personal expense-tracking practice into an application that combines consistent records, useful visual comparisons, guided interaction and optional AI assistance.
