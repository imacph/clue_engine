# Changelog

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
