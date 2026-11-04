# Question sets and OMR answer sheets

## Question sets (A, B, C ...)

In **Settings → Questions** choose *Question sets*: 2 to 6 sets, or "No sets".

- Each candidate is dealt one set when they start, evenly (the least-used set next, ties to the earlier letter).
- A set is **one fixed paper**: everyone in Set B sees the same questions in the same order with the same option order. This is deterministic, so Set B is Set B every time and on every server.
- **Set A** keeps the authored order and options. Sets B onward re-order the questions **inside each section** (section order is kept, as on a printed paper) and, if *Shuffle answer options* is on, give each question its own fixed option order. A later set is never identical to an earlier one when the questions allow it.
- *Questions per candidate* still works: the subset is drawn once per test, so every set has the same questions.
- Sets override *Shuffle question order*. Changing the number of sets is blocked while candidates are taking the test.
- Scoring compares option **text**, never position, so every set scores identically.
- The set appears on the candidate's screen and sheet, in the results table and in the CSV export ("Question set").

## OMR answer sheet

**Admin:** *Settings → OMR answer sheet*: switch it on, optionally set the institute name (default: the organization) and a line under it (address, centre ...).

**Candidate (when switched on):** an **OMR sheet** button in the exam room opens a live sheet beside the questions: institute, test, date, candidate details (name, e-mail, phone, your extra fields such as roll number) and the set. Clicking an option on the question screen fills the bubble, and clicking a bubble answers the question: they are the same answers. A filled bubble clicked again is cleared. Clicking a question number jumps to it. The candidate can download the sheet as a PDF, also after submitting. It never contains the answer key.

**Admin downloads (always available, switch or not):**

| What | Where |
|---|---|
| All candidates in **one PDF** (a sheet per candidate, grouped by set then name) | Results → OMR sheets |
| **ZIP** with one PDF per candidate (`001-Set-A-Jane-Doe.pdf`) | Results → OMR sheets |
| **Blank template** to print (one per set) | Results → OMR sheets |
| One candidate's sheet, and an **evaluated** copy | Candidate report → OMR sheet / Evaluated OMR |

An *evaluated* copy colours each mark green (right) or red (wrong), rings the right option and prints score, percentage, correct / wrong / not attempted and PASS/FAIL. It carries the answer key, so only **admins** can get it; reviewers get the plain sheet. Voided attempts are never exported; running attempts only if you tick *include candidates still taking the test*.

API: `GET /attempts/{id}/omr.pdf`, `GET /tests/{id}/omr.pdf`, `GET /tests/{id}/omr.zip`, `GET /tests/{id}/omr/blank.pdf` (query: `evaluated`, `set`, `include_live`, `tz`), and for candidates `GET /attempt/omr.pdf`.

## Calculator and competitive-exam mode

- **Settings → Candidate tools → On-screen calculator**: off, basic, or scientific (powers, roots, logs, trigonometry in degrees or radians, factorial, memory). Candidates get a draggable *Calculator* panel in the exam room; they can type or tap, `%` divides by 100 (`15%*240` = 36), and unclosed brackets close themselves.
- **Settings → Proctoring → Competitive exam**: allows looking down for rough work (see `docs/AI_PROCTORING.md`).
- The sample *[Trial] Aptitude Test with OMR* ships with camera required, AI monitoring on (findings are for human review only), competitive mode on and the scientific calculator.

## Sheet layout

A4 portrait, vector PDF. Corner alignment marks, institute header, details boxes, the set bubbles, instructions, then the bubble grid: questions numbered down each column in blocks of five rows, 4 columns (3 when a question has 6 options). The row height adapts to the number of questions and long tests continue on further pages with a running header. Multi-answer questions are marked `*`, true/false rows have T and F bubbles, short-answer questions are listed under "Written answers". Each sheet ends with candidate and invigilator signature boxes.

## Known limits

- The PDF uses a built-in Latin font: characters outside Latin-1 (for example Hindi or Telugu names) print as `?`. The live sheet on screen shows them correctly.
- Dates on the PDF use the time zone of the browser that asked for the download.
- The paper sheet is a faithful *printout* of the on-screen answers; it is not designed for optical scanning machines (no timing track or roll-number bubble grid).
- A hosted-scale export is capped at 1,000 sheets per request: filter by set.
