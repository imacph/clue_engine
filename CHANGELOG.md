# Changelog

## App 0.2.1 / Desktop 0.2.1 / API 0.3.0 - Unreleased

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
