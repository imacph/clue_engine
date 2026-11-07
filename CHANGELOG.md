# Changelog

## Desktop 0.4.0 / App 0.5.1 / API 0.6.0 - 2026-11-07

### Added

- Add a pull-request and branch-push quality gate for tests, lint, version
  checks, and wheel verification across Linux and Windows.
- Record optional source-revision provenance when capturing new card-only
  baselines and warn when it is omitted.

### Changed

- Replace expanding notebook clause tags with compact indicators and
  color-linked highlights, including for overlapping clauses.
- Give cards-only games more notebook space and move omniscient details into
  an expandable panel that does not cover game controls.
- Use one turn button for ending a turn and continuing after bot turns. Move
  game-ending options into a separate menu and use in-app confirmations.
- Clarify board and desktop documentation, historical baseline limitations,
  and the privacy of generated traces. Remove an unused private trace from
  the current tree; it remains in Git history.

### Fixed

- Report useful HTTP status information for failed non-JSON responses and
  surface theme-storage failures without disabling the active theme.
- Clear omniscient details and clause highlights when changing game or
  perspective so stale information does not remain visible.
- Keep the completed turn's notebook highlights in place until the next turn
  is confirmed, while preserving private-card visibility.
- Isolate the simulated Windows platform in desktop tests so it does not
  interfere with the host's SSL implementation.

## Desktop 0.4.0 / App 0.5.0 / API 0.6.0 - 2026-11-07

### Added

- Add linked, numbered notebook clauses for refutations and incorrect
  accusations. Players can create, edit, resolve, and filter manual clauses;
  automatic notebooks update their links as deductions progress.
- Add read-only private game replay with turn navigation, player perspectives,
  original manual notes, and an optional omniscient view. Replays can be
  exported and imported after a game ends. Replay files contain the solution
  and every hand and must be kept private.
- Add combinable house rules for face-up starting cards, public refutations,
  responses from every other player, reverse response order, and suggesting
  from a room without moving. Organize rule choices into categories in setup.
- Add a fullscreen control to the Windows desktop app and activity highlighting
  to the notebook for current players, suggested or accused cards, and
  visible refutations.
- Add public hand sizes and custom bot options for deal analysis and calculated
  accusations. Risky accusations are disabled in named presets.

### Changed

- Strengthen deduction with hand sizes and overlapping clauses; strategic
  bots can use bounded deal analysis and response modeling to inform
  suggestions. Improve board routing, passage decisions, and card reveals.
- Reorganize the board workspace, notebook, clauses, and help; compact the
  setup wizard, keep its navigation controls in a consistent location, and
  allow quick play without visiting every settings page.
- Show both dice and their total separately from movement remaining. Highlight
  a private refutation only for perspectives permitted to see it.
- Include extended rules in version-3 private board records while retaining
  support for older private board records. API state includes notebook clauses,
  activity focus, and public hand sizes.

### Fixed

- Require manual clauses to contain exactly one suspect, one weapon, and one
  room, while allowing players to manage their own deductions independently
  from notebook cell marks.
- Prevent notebook controls and the version bar from obscuring adjacent
  content at constrained window sizes.

## Desktop 0.3.2 / App 0.4.1 / API 0.5.0 - 2026-11-06

### Added

- Add version-update and release tooling, with versioned Windows archives,
  checksums, build manifests, and a GitHub draft release workflow.
- Check the packaged desktop app's assets, versions, window backend, and
  basic game actions before creating release artifacts.
- Include board play, manual detective notebooks, setup profiles, and
  turn-by-turn bot progression in this first tagged release.

### Changed

- Package the Windows portable app as a single executable that extracts its
  bundled runtime on startup, instead of requiring a folder of DLLs.
- Report the actual startup error without implying every failure is caused by
  a missing WebView2 runtime.

### Fixed

- Show the suggestion builder when entering a room after an earlier turn's
  reveal, and preserve the required room selection when restoring a game.

## App 0.4.1 / Desktop 0.3.0 / API 0.5.0 - Unreleased

### Fixed

- Show the suggestion builder when entering a room after an earlier turn's
  reveal, while keeping current-turn reveals visible for review.
- Preserve the required room selection when restoring a game in a room.

## App 0.4.0 / Desktop 0.3.0 / API 0.5.0 - Unreleased

### Added

- Added turn-by-turn bot progression, the default in the browser and Windows
  setup wizard, with a Next turn control for reviewing completed turns.
- Added the `turn` progression option, `waiting_for_turn` state, and
  `POST /api/next-turn` for local web clients.

### Changed

- Player games now wait for confirmation after each bot's completed turn;
  ending your own turn starts the next seat without another confirmation.
  Responses to a suggestion remain part of the same turn.
- Spectators can still choose continuous automation or step through individual
  actions. Resuming a step-by-step game enables automatic actions, while any
  pending turn confirmation remains in effect.

## App 0.3.1 / Desktop 0.3.0 / API 0.4.0 - Unreleased

### Added

- Added notebook and history tabs beneath the board game's card actions, so
  players can consult their notes and game details without leaving the cards.
- Preserved notebook edits, history filters, and spectator selection across
  workspaces, with keyboard navigation and scrolling on smaller screens.

## App 0.3.0 / Desktop 0.3.0 / API 0.4.0 - Unreleased

### Added

- Added a manual detective notebook for browser and Windows play. Hand facts
  are filled in; players can mark the remaining cells themselves.
- Kept notes for the active game across updates and page reloads, and added
  notebook mode to setup profiles, replay, and the review screen.

### Changed

- Manual notebooks are the default for new player setups. Automatic deductions
  remain an explicit option and are always used for spectator views.
- Manual mode does not display calculated deduction clauses. The legacy HTTP
  game setup remains automatic when its notebook mode is omitted.

## App 0.2.1 / Desktop 0.2.1 / API 0.3.0 - Earlier unreleased build

### Changed

- Reorganized the setup wizard into compact, responsive panels, with
  expandable advanced options and saved profiles.
- Improved setup navigation, bot controls, and the board starting-position
  preview. Standard setup steps fit common desktop screen sizes without page
  scrolling; smaller screens and expanded options remain scrollable.
- Updated the Windows portable build to include the polished interface.

### Fixed

- Preserved keyboard focus when changing or copying bot settings.
- Revealed advanced settings when a hidden field needs correction, and disabled
  bot copying when no other bot is available.

## API 0.3.0 / App 0.2.0 / Desktop 0.2.0 - Earlier unreleased build

### Added

- Added a new-game wizard with fresh random seeds, replay, seat and character
  selection, and a board starting-position preview before dealing.
- Added standard and optional board house rules, per-seat bot presets and custom
  strategies, and a strategy toolkit score.
- Added named setup profiles for the browser and Windows desktop application.
- Added separate frontend version tracking alongside the API and desktop
  versions.

### Changed

- Updated board records to version 2 to include house rules; version 1 records
  remain readable with standard rules.
- Changed browser and Windows player labels to start at 1. Python and existing
  console and Tkinter interfaces retain zero-based seat IDs.

## Previous baseline

- API 0.2.0 added the full board engine and board play to the local web
  interface.
- Desktop 0.1.0 introduced the packaged Windows application. These version
  assignments were not previously tagged releases.
