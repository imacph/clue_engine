# Post-release technical debt and polish plan

## Scope and baseline

Audit of the tracked repository at commit `be2e66a`
(`desktop-0.4.0-app-0.5.0-api-0.6.0`), before this plan was added. The
working tree was clean. The review covered gameplay and batch logic, the web
and desktop surfaces, tests, release tooling, and documentation. This is a
polish plan, not a proposal to change game rules or add features.

Checks performed on Windows with CPython 3.13.3 and Node.js 22.20.0:

- `python -m pytest -q`: **725 passed**, including the pytest wrapper for the
  JavaScript suite. Running `node --test tests\test_web_ui.cjs` separately
  passed all 20 JavaScript cases; these are not additional pytest cases.
- `python -m ruff check .`: passed. `python -m tools.versioning check
  --release`: passed.
- `python -m pip check`: passed. A wheel built with `python -m build --wheel
  --no-isolation` passed the release tool's metadata and web-asset checks.
- Browser smoke: started a cards-only game and ended a turn; separately started
  a board game, rolled and moved one square. The temporary server was stopped.
- Eight local Markdown file links were checked and all targets existed.

The local editable install reports distribution metadata `0.3.0` even though
the checked-out API and built wheel are `0.6.0`. This is the documented
editable-install behavior, not a source-version mismatch; see
[release preparation](releasing.md). Reinstall when installed metadata matters.
Coverage percentages were not measured: the coverage package was not installed.
No full portable-executable build, real WebView2 smoke, supported-Python
matrix, exhaustive browser/accessibility testing, dependency vulnerability
scan, or dedicated security audit was performed. Green checks are not proof
that these areas are free of defects.

## Implementation status

The follow-up adds the proposed routine workflow, removes the approved trace
from the current tree, updates the interface and baseline documentation,
and improves HTTP and theme-storage error reporting. Focused JavaScript tests
cover additional profile, clause, replay-related presentation, and error paths.
Cards-only and omniscient layouts and compact clause indicators received a
manual browser pass, including spectator perspective and replay visibility.

The new CI matrix has not yet been verified on GitHub. Browser interactions
are manual rather than automated in CI, and the historical baseline has not
been reproduced from a verified source and tool combination. Full keyboard
and accessibility testing, the real WebView2 smoke, and broader UI integration
coverage remain follow-up work. No large module extraction was undertaken:
the existing focused tests do not yet justify a behavior-preserving split.
These limitations mean that not all of the plan's original completion
criteria have been met.

Existing strengths include extensive engine and board tests, explicit
private-replay warnings, frozen card-only regression cases, version consistency
checks, and a release workflow with pinned build dependencies, a packaged
self-check, and a manual desktop smoke checklist. No high-confidence defect in
currently supported gameplay was identified in the inspected code. Batch
simulation is deliberately card-only, and unexpected errors are documented to
surface; neither should be treated as a bug or expanded in this project solely
to satisfy this plan.

## Findings and priorities

| ID | Priority | Finding | Evidence and impact |
|---|---|---|---|
| F1 | P1 | Ordinary changes lack an automated project quality gate. | The only tracked workflow is [release.yml](../.github/workflows/release.yml#L3), triggered by release tags. It runs the checks late, after a tag is pushed. [pyproject.toml](../pyproject.toml#L9) declares Python 3.11 and newer, while the release job checks 3.13.3 only. This is a coverage gap, not evidence that other versions fail. |
| F2 | P1 | An apparently unreferenced private batch trace was tracked. | At the audited revision, `test.json` was about 5.46 MB and 18,218 JSONL records despite its extension. Its header marked it private; game-start records included hands and solutions. No tracked references were found. It was removed from the current tree with owner approval; it remains in Git history. |
| F3 | P2 | Board documentation contains historical wording that conflicts with the current UI. | [BR-03](board-rules.md#L15) still refers to a character-selection flow as future work, although the [README](../README.md#L253) describes it. The [acceptance checklist](board-rules.md#L171) says not to add board controls to desktop interfaces, while the Windows desktop app supports board play. The distinction between the legacy Tk interface and the Windows wrapper needs to be explicit. |
| F4 | P2 | The historical baseline's reproduction instructions lack a pinned executable source state. | [card-only-baseline.md](card-only-baseline.md#L3) attributes measurements to `fd6813a`, but its [reproduction command](card-only-baseline.md#L65) uses a capture tool that does not exist at that revision. The tool was added later and current engine/policy code has changed. The aggregate JSON does not record a source revision. Do not assume a current run will reproduce the historical numbers. |
| F5 | P2 | UI tests leave important integration paths unprotected. | The [Node harness](../tests/test_web_ui.cjs) uses sliced functions and synthetic DOM state. It does test a wizard payload path, but profile persistence, setup initialization, interactive transitions and rendered responsive/accessibility behavior need more integration coverage. The [pytest wrapper](../tests/test_frontend.py#L10) skips JavaScript tests if Node is missing. |
| F6 | P2 | Failed non-JSON HTTP responses can obscure the useful error. | [requestJson](../src/clue_engine/webapp/static/app.js#L65) parses the body as JSON; HTML or empty error responses can instead surface a JSON parsing error. Reproduce this against the actual caller flows before changing error handling. |
| F7 | P3 | The web stack has large, tightly coupled files, making future changes harder to isolate. | [app.js](../src/clue_engine/webapp/static/app.js), [setup.js](../src/clue_engine/webapp/static/setup.js), and [webapp/__init__.py](../src/clue_engine/webapp/__init__.py) combine several responsibilities. Size alone is not a defect; extract only seams justified by tests and the work below. |
| F8 | P3 | Restricted browser storage is an untested theme-initialization edge case. | The inline [theme initializer](../src/clue_engine/webapp/templates/index.html#L7) reads `localStorage` directly. A thrown storage exception stops that script block, although subsequent page scripts can still run. Establish actual behavior with a browser test before deciding on a narrowly scoped recovery. |
| F9 | Decision | Contribution and licensing expectations are not stated in tracked project metadata. | No tracked license or contributor guide was found; [pyproject.toml](../pyproject.toml) does not declare a license. This is not a presumed licensing defect: the owner should decide whether the project is intended for external reuse or contributions before selecting terms. |

## Ordered work

### 1. Establish a routine quality gate (F1, F5)

**Size:** M. Do this before structural refactoring. Add a pull-request and
branch-push workflow that installs declared development dependencies and runs
pytest, Ruff, and the Node suite with Node explicitly provisioned. Include a
Python 3.11 job and the release's 3.13 line; agree and document a tested upper
version and operating-system policy rather than implying all future Python
versions are certified. Include Windows where desktop/Tk coverage requires it.
Keep the existing pinned release workflow and manual WebView2 gate intact.

**Done when:** a clean checkout runs the documented commands; required CI jobs
run on pull requests and pushes, report failures and skips visibly, and cannot
pass because Node is absent. Version checks and wheel asset verification run
in at least one appropriate job. Document local prerequisites and the exact
tested matrix. Confirm how headless Tk tests behave rather than silently
claiming GUI coverage.

### 2. Resolve trace retention and accidental-commit risk (F2)

**Size:** S, pending owner decision. Determine whether the checked-in trace
is needed for a reproducibility fixture, is safe synthetic data, or is an
accidental output. If needed, replace it with a minimal documented synthetic
fixture or keep it with a stated purpose; if not, remove it in a normal
forward commit after approval. Add an appropriate output-location or ignore
convention and a check for unwanted generated traces without excluding
intentional fixtures. Preserve existing `docs/card-only-baseline.json`, which
is an aggregate, unless separately justified.

**Done when:** the trace's disposition is explicit; tests do not depend on an
unidentified private dump; newly generated traces are less likely to be
committed accidentally; and the contributor guidance explains their private
contents. Removing a tracked file does not erase it from Git history; do not
rewrite history without an explicit decision.

### 3. Repair documentation and reproducibility drift (F3, F4, F9)

**Size:** S-M. Correct board character-selection and desktop/Tk language and
review the remaining rule-contract checklist against the implemented surfaces.
Distinguish reproducing the *historical* baseline from capturing a *current*
comparison. Identify and validate the exact source/tool revision and
environment that reproduce the historical aggregate, or state clearly that
the exact procedure is not yet verified. Include revision, interpreter,
configuration and trace-privacy guidance in future baseline outputs.
Update contributor and release instructions to match the CI actually added;
ask the owner to decide licensing/contribution policy rather than inventing it.

**Done when:** rule and interface descriptions agree with current behavior;
historical and current baseline commands are unambiguous and verified or
explicitly marked unverified; relative documentation links resolve; and
versioning/changelog conventions continue to pass their existing checks.

### 4. Strengthen UI behavior and failure tests (F5, F6, F8)

**Size:** M-L. Add focused DOM or browser-level coverage for quick play and
wizard initialization, profile save/load/delete, seat and rule transitions,
invalid input, and browser versus desktop storage. Preserve the existing
focused Node payload tests. Cover cards-only and board startup, a legal move,
manual notebook editing, private replay import/export and perspective
visibility, and responsive keyboard/ARIA basics. Use stable functional
assertions rather than broad screenshot-only tests; keep the real WebView2
smoke manual unless reliable infrastructure is available.

Reproduce non-JSON/empty HTTP error handling and storage exceptions first.
For confirmed defects, report actionable HTTP/network errors without hiding
status or discarding retryable user input, and handle storage unavailability
with explicit, appropriate user-visible feedback where persistence is
affected. Preserve normal theme and profile behavior.

**Done when:** regressions cover successful and failing storage and request
paths, a failed action can be retried without losing unsaved work, and the
key browser flows run in CI with no private information visible to an
unauthorized perspective. Record any intentionally manual desktop and
accessibility checks separately.

### 5. Make targeted maintainability improvements (F7)

**Size:** M-L, after tasks 1 and 4. Inventory responsibilities and identify
the parts most affected by defects or frequent edits. Extract small,
well-named boundaries for independently testable setup/profile handling,
request/error handling, replay/notebook presentation, or server routes as
evidence warrants. Preserve public route payloads, replay formats, versioning,
privacy boundaries and the look and feel. Avoid a wholesale framework
rewrite, speculative abstractions, or large unrelated formatting churn.

**Done when:** each extraction has behavior-preserving tests at its boundary,
existing public contracts and compatibility fixtures still pass, changes can
be reviewed in small slices, and documentation reflects any intentional
interface change. Track concrete before/after ownership and testability, not
an arbitrary line-count target.

## Completion criteria and sequencing

1. Establish task 1 first. Task 2 and the fact-gathering for task 3 can proceed
   independently; apply the owner's trace and license decisions before taking
   irreversible action.
2. Land focused UI tests and fixes before splitting affected modules. Keep
   each behavior change separate from mechanical extraction when practical.
3. Before declaring polish complete, run the documented CI matrix, pytest,
   JavaScript tests, Ruff, version checks and wheel verification. Confirm the
   release self-check and perform the documented Windows WebView2 smoke when
   producing the next portable release.
4. Record outstanding skips and manual checks, verify replay and hidden-card
   boundaries, and check that docs and packaging match the shipped behavior.
   Do not claim security, performance, accessibility or compatibility
   certification without a dedicated assessment and evidence.
