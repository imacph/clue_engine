# Clue Engine

A Clue simulator with player-specific observations and configurable bot policies.
The default card-only game models suggestions, mandatory refutations,
accusations, elimination, and turns. Players may suggest any combination once
per turn and may end a turn without suggesting. An opt-in board engine adds
movement, rooms, passages, and movement-aware bots. Eliminated players still
respond to suggestions in both modes. A game ends after a correct accusation
or when every player has made an incorrect accusation.

This is a personal project and is not intended for commercial redistribution.
No license granting redistribution rights is provided.

## Versions

<!-- component-versions:start -->
The game API and Python distribution are **0.7.0**, the shared browser/desktop
frontend is **0.7.0**, and the Windows desktop wrapper is **0.5.0**.
<!-- component-versions:end -->

These are pre-1.0 versions and do not yet promise a stable public API.

The source of truth is `src/clue_engine/_version.py`. The Python package exposes
its API version as `clue_engine.__version__`. The browser shows the App and Game
API versions; the Windows app also shows the Desktop version. Update each
version independently when its component changes. These numbers do not version
individual HTTP routes or saved game formats. See the [changelog](CHANGELOG.md)
for the changes in each version and the [release process](docs/releasing.md)
for updating versions and producing a portable build.

`deal` supports two or more players and distributes the 18 non-solution cards
in seat order as evenly as possible. The random generator is supplied by the
caller for reproducibility.

The [board rules contract](docs/board-rules.md) describes the board rules and
documented interpretations. Board games are available through the local web
interface, packaged Windows desktop app, and Python API; the Tkinter game and
console play interfaces remain card-only. Batch simulations also accept board
setups as described below. The [card-only baseline](docs/card-only-baseline.md) records
reproducible pre-board measurements.

```python
import random

from clue_engine.engine import Engine
from clue_engine.policies import DeductivePolicy
from clue_engine.simulation import play
from clue_engine.state import deal

engine = Engine(deal(random.Random(1), num_players=4))
policies = [DeductivePolicy(random.Random(i)) for i in range(4)]
play(engine, policies)
print(engine.winner)
```

`Engine.view(player)` exposes that player's hand and visible events. The engine
itself, including its state, full log, and events returned by `step`, is intended
for a trusted controller and can contain the solution or privately shown cards.
Pass views rather than the engine to player policies. `play` requires one policy
per player and raises `RuntimeError` if the game has not ended after `max_steps`;
policies are not guaranteed to terminate every game.

## Board engine

Board games support 3–6 players, with Miss Scarlet starting. The original
25-by-27 layout has all nine rooms, 20 doors, all six suspect tokens, six
weapons, and two secret passages. Its geometry is **not** a reproduction of
the C00045 printed board, so travel distances and balance differ. Unassigned
suspects still block hallways. The default card-only mode continues to support
two or more players.

The engine rolls two dice using a movement RNG separate from the deal and bot
RNGs. Board actions are incremental: `Roll()` starts movement;
`Move(Square(x, y))` moves one hallway square; `Move(RoomPosition(room_id))`
enters a room; and `UsePassage()` takes an available passage instead of
rolling. Entering a room costs one movement step and stops movement; the door
is not an extra square. The engine enforces blockers, no hallway revisits,
no same-turn room re-entry, room-specific suggestions, token relocation, and
summoned-player turns. Players may stop movement before using the entire roll.
If movement cannot continue, the player may end at the last reachable square.
Public board state, rolls, and movements are included in
player views and session snapshots, without exposing future dice or other
players' hands.

To run a board game programmatically:

```python
from copy import deepcopy
from pathlib import Path

from clue_engine.board_record import read_board_record, write_board_record
from clue_engine.session import create_board_game
from clue_engine.simulation import play

engine, policies = create_board_game(4, seed=42, policy_name="strategic")
initial_state = deepcopy(engine.state)
play(engine, policies)
print(engine.winner)

write_board_record(Path("private-board-game.json"), initial_state, engine.history)
replayed = read_board_record(Path("private-board-game.json"))
assert replayed.log == engine.log
```

`create_board_game` also accepts per-seat policy names, optional suspect and
weapon assignments, and a validated custom layout. `Engine.legal_actions()`
supplies the actions legal at the current movement or response phase.
`engine.history` is a trusted-controller record, not a player view.
The replay file contains **the solution, every hand, and private reveals**;
keep it private. Files are created without overwriting existing files. Replay
verifies recorded actors, dice, actions, events, and positions. To continue
an unfinished replay, pass `dice_rng=` to `read_board_record`; to reproduce
the original future rolls, provide an RNG already advanced to the appropriate
state. The recorded dice alone do not reveal future random outcomes.

## Console play and observation

After installing the project, play as seat 0 against three deductive policies:

```text
python -m clue_engine.console --mode play --players 4 --seat 0 --seed 42
```

At your action prompt, enter `suggest`, `accuse`, `reveal`, `pass`, or `end`
when offered. For a suggestion or accusation, select a suspect, weapon, and
room by the displayed card ID or full name. On a reveal prompt, only matching
cards are available. At an action or step prompt, `hand`, `knowledge`, `history`,
`help`, and `quit` are also available. Seats and card IDs are zero-based.

To spectate automated players, use:

```text
python -m clue_engine.console --mode spectate --players 4 --seed 42 --progress step
```

Press Enter to advance one automated action at a time; `--progress auto` runs
automated actions without waiting. Use `--policy strategic` to choose one
profile for all bots, or `--policies random,deductive,probing,strategic` to
choose a profile per seat. In play mode the human seat still needs an entry,
but its bot profile is unused. Use `--max-steps` to limit actions. The limit
returns exit status 1 if the game has not ended; quitting returns status 0.
Run `python -m clue_engine.console --help` for all options.

Ordinary play displays only the human player's hand and visible events.
During spectator stepping, `knowledge` shows every player's knowledge, and
`knowledge 2` shows only Player 2's. These views include each player's private
hand and cards shown to them, so they are not suitable for a player who wants
to preserve hidden information. The ordinary spectator history remains public.
`--debug-omniscient` additionally reveals the actual solution and private events,
including during play. Do not enable it for a fair game.

## Desktop interface

The Windows desktop app uses the same interface as the browser, including both
board and cards-only games. Extract and run the portable `ClueEngine.exe`;
it does not require Python or a separate folder of supporting files. It extracts
its bundled files to a temporary directory on startup, which may take a little
longer than a folder-based build. Windows may show a security warning for a
downloaded executable. The app requires the
[Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
It also requires .NET Framework 4.6.2 or newer. Install any missing runtime if
the app reports it; once installed, the game runs locally without an internet
connection.

Use **Full screen** in the Windows app (or press **F11**) to fill the display.
Select **Exit full screen**, press **F11** again, or press **Escape** to restore
the window. The standard window maximize button remains available separately.

To run the desktop app from source on Windows:

```powershell
python -m pip install -e ".[desktop]"
python -m clue_engine.desktop
```

To build the portable Windows executable on Windows:

```powershell
python -m pip install -e ".[desktop-build]"
python -m PyInstaller ClueEngine.spec
```

Distribute `dist\ClueEngine.exe`, or zip it for transfer. Build
on the Windows architecture you intend to support. The desktop app uses an
automatically assigned loopback port and stops its local server when the
window closes. Its theme and explicitly saved setup profiles are stored in
`%LOCALAPPDATA%\ClueEngine`; games remain in memory and are not saved when the
app closes.

The original card-only desktop interface requires Python's Tkinter support.
Start it with:

```text
python -m clue_engine.gui
```

The setup screen offers play or spectator mode, player count, human seat, seed,
bot policy, action limit, and automatic or step-by-step progression. The bot
policy selector applies to every bot. Optionally enter comma-separated
per-seat profiles, such as `random,deductive,probing,strategic`, to override it.
Include the human seat in play mode; its profile is ignored. Select
**Start game** to open the notebook. Use the card selectors and action buttons
to play; when responding, only legal cards are offered for reveal. An accusation
requires confirmation. The read-only notebook shows deductions from the human
player's view. Spectators can select any player's private hand and notebook; the
history remains public unless omniscient debug is enabled. The console and
Tkinter interfaces show the recorded refutation and incorrect-accusation
clauses, distinguishing unresolved constraints from those already satisfied.

In the game window, history and clause panels have independent **Actor** and
**Type** filters. History filters support multiple selections: matching any
selected actor and any selected event type. History actors are the players who performed
the events (for a shown card, the player who showed it). Clause actors are the
refuting player or the player who made the incorrect accusation. The selected
filters affect only the display, not the knowledge matrix or deductions.
Spectator history remains public even when viewing a player's private notebook;
private shown cards appear in history only when visible to the human player or
when omniscient debug mode is enabled.

**Pause** stops automated actions; **Next action** advances one bot action while
paused, and **Resume** continues. Human actions are always submitted manually.
**New game** returns to setup. The optional omniscient debug setting requires
confirmation and exposes all hands, the solution, and private events.

## Local browser interface

Install the project, then start the local browser app with:

```text
python -m clue_engine.web
```

The app listens only on this computer at `http://127.0.0.1:8765` and opens
your browser automatically. Use `--port` to choose another local port or
`--no-browser` to keep it from opening a browser window. The interface supports
play and spectator modes, pause/step controls, custom card faces, player
notebooks, numbered history with the newest event at the top, and deduction
clauses. The game screen uses a compact dashboard with turn controls inline
alongside the card-based actions. History and deduction clauses are available
in the right-side tabbed panel. The
knowledge matrix groups suspects, weapons, and rooms with matching icons and
colors. A theme toggle follows the system preference by default and remembers
your selection. Pawn moves, new suggestions from the acting pawn, and newly
visible reveals animate in play and replay; animations are disabled when the
system requests reduced motion. A gold outline marks the turn owner's pawn. The card area
switches between your hand, individual card
categories, and the full deck. Click cards to build suggestions or accusations,
or click a matching held card to reveal it; the adjacent card panel identifies
the latest suggestion, accusation, refutation, or visible reveal and its player.
Revealed card faces remain limited to the players who may see them unless
omniscient debug mode is enabled. The
existing Tkinter app remains available with
`python -m clue_engine.gui`; its batch statistics and trace tools are not yet
part of the browser interface.

The browser and Windows app open to a main menu. **Quick play** shows the
current profile before starting; its default is a four-player board game with a
manual notebook and deductive, probing, and strategic bots randomly assigned to
the three bot seats. To change these defaults, select **Edit quickplay defaults**
in the quickplay dialog, adjust the settings, and choose
**Save as quickplay defaults** in the setup navigation bar. Defaults are stored with
setup profiles and use a fresh seed for every game. The menu also offers
**Game setup**, **Load replay**, full screen, and light/dark mode. The game
options menu also contains the display settings. **Quit game** is available
in the Windows app; close the browser tab when using the browser.

The five-step new-game wizard covers game type, seats, bots, rules, and review.
Use **Start game** at any step or **Next** to customize and review them.
On the bots step, **Randomly assign bot styles to seats** shuffles the
configured bot styles among bot seats while keeping the human seat fixed.
The seed determines the shuffle, and **Replay previous setup** restores the
actual assignments used. Wizard navigation stays at the bottom of
the window as you move between steps. Board character selection includes a preview of
all six starting positions before cards are dealt. Miss Scarlet must be
assigned and starts; turns then proceed in seat order. The browser and Windows
interface labels players starting at 1; the Python API, console, and Tkinter
interface continue to use zero-based seat IDs.

Each new setup rolls a seed; use **Roll seed** to change it or enter one
manually. **Replay previous setup** restores the last started setup and seed
while the app remains open. A seed and configuration can reveal the deal and
solution, so share them only after play. Reproducing a game also depends on the
application and Python versions. Expand **Advanced options** for progression,
action limit, and debug settings, or **Saved setup profiles** to manage
profiles. Saved profiles omit the seed, and loading one rolls a fresh seed.
Profiles are stored in browser local storage or, for Windows, in
`%LOCALAPPDATA%\ClueEngine`.

In browser and Windows player games, a completed bot turn waits for **Next
turn**, giving you time to review its suggestion and responses. Your own
**End turn** action starts the next seat without another confirmation.
These actions share the same button, which changes its label when a bot turn
is ready for review.
Passes and reveals within a suggestion do not start a new turn; respond when
prompted. A pending turn confirmation remains in effect if you pause or resume.

The wizard defaults to **Turn-by-turn** progression. Spectators can instead
choose **Automatic** for continuous play or **Step-by-step** to advance one
bot action at a time. In player games, automatic actions still wait after each
bot turn. **Resume** enables automatic actions after a step-by-step start;
**Pause** and **Next action** control individual automated actions while paused.

For local HTTP clients, `POST /api/game` accepts `progress` values `auto`,
`turn`, and `step`; omitting it retains the `auto` default. Player games always
require turn confirmation after a bot turn, while spectator games do so only
with `turn` progression. When `waiting_for_turn` is true in a state response,
`POST /api/next-turn` with an empty JSON object and the session's CSRF token
acknowledges the completed turn without executing another game action.

The browser and Windows player setup defaults to a **Manual** detective
notebook. Facts from your own hand are filled in initially; every
other cell begins unknown. Any cell can be changed. Activate it with the mouse, touch, Enter, or
Space to cycle through unknown (`?`), held (`+`), and not held (`-`). Record
shown cards and other deductions yourself; arrow keys move between editable
cells. Marks appear immediately while they save; a failed save is reported and
reverted unless a later edit supersedes it. Your notes do not affect the bots.
The right-side **Help** tab summarizes action, notebook, and clause controls.
In the browser and Windows app, the notebook highlights the turn owner's column
in blue, the acting player's column in gold, and the cards in the current
suggestion or accusation. Players who passed the current suggestion appear in
purple; those who refuted it appear in green, including when all players respond.
These completed responses are public and remain highlighted through turn review.
An underlined cell marks a card visibly shown to the selected perspective.
While a bot turn awaits **Next turn**, its column and suggestion rows remain
highlighted for review; the board marks the same player and labels the turn as
under review. Highlights follow the current turn and replay position without revealing
another player's private cards. During private responses, the acting column is
highlighted only for the suggester or responder; public and omniscient views
can highlight it for everyone. The legacy Tk notebook highlights the card rows
and labels the turn and acting columns with `T` and `A` in their headers.
To add a clause, select **Clause** above the notebook, then select one suspect,
one weapon, and one room in the appropriate player's column. Select the envelope
column instead for an incorrect accusation, where at least one card is not in
the envelope. Selecting a different column moves the whole clause to that
holder; selecting a different card of the same type replaces the previous card.
Select **Confirm** to save, or **Cancel** to discard the draft. Cell
marks do not change while entering a clause, and any cell can be selected.
Colored dots identify the clauses linked to each cell without increasing its
row height, with separate dots for overlapping clauses and matching dots in
the list. Colors distinguish
clauses within a column and do not depend on selection or list filters. Select
a dot to open its clause in the **Clauses** tab, or select a clause heading to
emphasize its linked cells. Only one clause is selected at a time; select its
heading again to clear the selection. Leaving the **Clauses** tab also clears
the selection and its linked-cell highlighting.
Clause numbers are notebook numbers, not history event numbers.
You can edit clauses using the same notebook interaction, resolve, reopen, or
delete them, and independently exclude
or restore individual card links as you reason through them. Resolving and
reopening a clause preserves those exclusions. Changing a mark does not change
your clauses, and changing a clause does not change marks. Your notes
may therefore disagree; they are not checked against the deal. Manual clauses
are authored by you, not automatically generated from game events.

Choose **Automatic** in setup to use the read-only deduction matrix and clauses
instead. Linked indicators automatically narrow as cards are ruled out and
disappear when a clause is satisfied; the original clause remains in the list.
Refutation clauses and incorrect-accusation clauses express opposite conditions,
as described in the list. Spectator games always use the automatic notebook for
the selected player's view. Actor and type filters affect the clause list only,
not the linked cells; player-authored accusation notes have no actor.

Manual marks and clauses belong to the current game and survive updates and page reloads
while its local server session remains active. Starting a new game, restarting
the server, or allowing the session to expire discards the live session. After
the game ends, save a private replay to preserve its recorded notes. Existing
setup profiles without a notebook setting load
with the manual player default. For compatibility, HTTP callers that omit
`notebook_mode` from `POST /api/game` retain the automatic notebook; send
`"manual"` explicitly to opt in. In manual mode, `PUT /api/notebook` accepts
`card_id`, a zero-based `holder` (the number of players denotes the envelope),
and a `mark` of `?`, `+`, or `-`.
Manual clause notes are created with `POST /api/notebook/clauses` and edited or
deleted at `/api/notebook/clauses/<id>` using `PUT` or `DELETE`. Create and edit
requests contain `kind` (`refute` or `accuse`), a zero-based `holder` (the
envelope is the number of players), a `cards` array containing exactly one ID
of each card type, and a boolean `resolved`. Optional `excluded_cards` contains
distinct IDs from `cards` and defaults to empty. These operations use the same session and CSRF
protection as notebook mark edits. State responses include unfiltered
`notebook_clauses` with their original cards, active links, and status; the
existing textual `clauses` field remains available.

The wizard offers per-bot presets and custom strategy controls, plus categorized
optional rules. In either game type, enable face-up starting cards, public
refutations, responses from every other player, or reverse response order in
any combination. Face-up mode exposes one randomly selected card per player
and requires each player to have at least one card. Board games also offer
suggesting without moving when starting a turn in a room and other movement,
relocation, and accusation options. Independent layout options scramble room
identities, randomize door positions away from corners and outside walls with
at most one door per side and pair doors across adjacent rooms where possible,
with any extra doors placed independently. Each room has at least one door,
and door counts vary by layout. Randomized passages exclude adjacent rooms,
use at most one passage per room, and are limited by the layout's available
non-adjacent pairs (up to four). A seed reproduces the layout, and replays
retain it. The strategy toolkit score describes the
enabled techniques; it is not a predicted win rate. See the
[board rules contract](docs/board-rules.md) for rule defaults and effects.

Choose **Board game** at setup to play or spectate a 3–6 player board game;
**Cards only** remains the default. On larger screens, the notebook is on the
left, the board in the center, and cards and actions on the right. The notebook
has one set of player columns and stacked card categories. The right workspace
has vertically arranged cards and actions, full history, clauses, locations, and help
tabs. Cards and actions also show the latest eight history events matching the
selected Actor and Type filters. Both history filters allow multiple selections;
an event is shown when its actor and type are each selected. The **Card info only**
preset keeps suggestions, passes, refutations, shown and exposed cards, and
accusations while excluding movement, dice, and other non-card events. On smaller
screens these areas
stack vertically and the page scrolls as needed. The cards tab opens when a room suggestion
or response needs your attention. Card choices appear above the combination
and action controls; longer lists scroll within the card area. Cards show an
**In hand** badge for the viewed player's actual hand and at most one positive
player or envelope notebook mark. Board rooms show selected notebook marks and
active clause markers. Game options independently control positive, negative,
unknown, and clause markers for cards and rooms, as well as card hand badges and
room overlays. The default **Hide viewed player's negative marks** option
applies to both cards and rooms; uncheck it to show those marks.
Conflicting
positive marks are reported in the status area and not shown on the affected
card or room. Manual marks update immediately and can differ from the actual hand.
On your turn, roll the
dice or take an available passage. The board header groups the current turn,
dice, movement, and available actions above the map. The dice display animates
new rolls and shows both results and their total; the movement indicator shows steps
remaining. Dice animation respects reduced-motion preferences. Select highlighted board squares
with the mouse, touch, or keyboard. When the board viewport or a highlighted
square is focused, arrow keys move in that direction, including through doors.
If multiple exits share a direction, use that arrow to choose an exit and press
Enter. Entering a room ends movement. The board can be
zoomed and scrolled; the locations tab
describes suspect and weapon positions and identifies your piece, bots, and
unassigned suspects. On the board, player pieces show their seat numbers;
unassigned suspects show initials and a dashed outline. Matching letters on
rooms identify passage pairs; the locations tab also names each destination.
On small screens or when zoomed,
individual panels may scroll without scrolling the game page.

Suggestion cards animate from the suggesting player's pawn, including your own
suggestions. Automatic bot responses and continuous replay give suggestions and
reveals time to be read; manual actions and replay navigation remain available.
Each pass is shown with the suggested cards and a summary of earlier passes,
and receives its own reading pause during automatic play and continuous replay.
Reduced-motion preferences disable the animation.

After entering a room, choose a suspect and weapon in the cards area; the
current room is selected for your suggestion. Accusations may name a different
room. If you select another room, **Use current room** restores the room for a
suggestion. When summoned to a room, you can suggest there or move normally.
When responding, select a matching card to reveal it, or pass if you have none. Board
geometry is original rather than a reproduction of the printed C00045 board.

Spectator mode exposes each player's private hand and notebook; use **View as**
to select the perspective. Omniscient debug mode reveals all hands, the
solution, and private events. Its solution banner expands to show all hands
without covering game controls. Do not use either mode if you need to preserve
hidden information.

### Private game replay

When a game finishes, select **Replay** to step through actions and recorded
notebook edits, jump between turns, or play continuously at a chosen speed.
Playback stops at the end; manual navigation or changing the replay perspective
pauses it. Select a player to see their notebook and automatic deductions
based only on what that player had observed at that point.
Playback speeds range from 0.5× to 16×. At 4× and above, suggestion animations
and reading pauses also shorten; a changed speed takes effect on the next step.
For a human manual notebook, **Original notes** shows the marks and clauses
actually recorded, including intermediate edits. Replay is read-only.
The timeline and playback controls remain at the bottom of the screen. The
player knowledge comparison replaces the card browser in the **Actions** area
during replay. Its rankings animate during playback when players change
position, unless reduced motion is enabled. **Timeline flags** mark the
first replay position where automatic deduction
identified an envelope card or another player's card. Choose the type and
which players' flags to show using the controls below the timeline,
independently of the notebook perspective.
Select a flag to jump there, or use **Previous flag** and **Next flag** when
markers are close together. A flag can represent multiple discoveries; hover,
focus, or select it to see their details. Flags cover the entire replay
including future discoveries. They represent
deductions available from each player's observations, not necessarily what
they noticed; direct card shows do not create inferred-card flags. Flags show
card icons, with player colors and numbers when showing all players, or
category colors when filtering to one player. A `+N` badge indicates
additional discoveries at a crowded position.

**Player knowledge at this point** compares every player at the current replay
position. The prominent counts show card locations known in each category,
including the player's own hand and visible reveals, and the number of
identified envelope cards. Smaller counts show known notebook marks (held or
ruled out) out of all cells in that category. These are automatic deductions,
not the player's recorded manual notes; unresolved clauses are not counted as
known marks.
Select a column heading to sort, and use **Columns** to choose which columns
are shown. Card locations are the primary sort key; known marks break ties.

To reveal an unfinished or action-limited game, open **Game options**, choose
**End and reveal**, and confirm. **Exit game** also requires confirmation,
discards the current game, and returns to the main menu. Ending permanently ends
that game; an action limit alone does not unlock
its secrets. **Save private replay** downloads a JSON file, and **Load replay**
on the main menu opens a saved record. Replay files contain every
hand and the solution: do not share them with anyone who should not see the
answers. Files are not encrypted.
Import also accepts existing private version-1 and version-2 board records, but
they have no historical manual notes. Notes are captured only in newly played
games. A saved replay cannot be used to resume play.

The Player 0 turn counter starts at zero and increases when Player 0 completes
their own turn, including by making an accusation. Refuting another player's
suggestion does not increase it. Once Player 0 is eliminated, the counter
remains unchanged even if they continue to refute.

## Bot profiles

Every player's hand size is public and appears beside their notebook column.
All profiles use only their own player view, including public hand sizes.
Except for the analytical profile, named bots accuse only when the solution is
established and an accusation is legal. They use seeded randomness for choices
and ties.

- `random`: chooses among legal card-only non-accusation actions at random.
- `deductive`: randomly suggests cards still possible in the envelope.
- `probing`: when possible, tests one unknown solution candidate alongside two
  controls known to be in its own hand or the envelope. It otherwise falls
  back to `deductive` suggestions. When revealing, it prefers an already public
  matching card, then one previously shown to that same opponent; otherwise it
  chooses randomly.
- `strategic`: favors possible solution cards, ranks suggestions using reachable
  responders and unresolved clauses, repeats reveals, and analyzes consistent
  deals when the remaining solution candidates and search budget permit. When
  at most 128 consistent deals can be completely enumerated, it also compares
  the expected information in possible suggestion responses, assuming each
  matching reveal is equally likely. This is a strategy model, not a guarantee
  of how opponents will respond.
- `analytical`: adds a larger bounded deal-counting budget and uses opponents'
  suggested cards as tentative evidence when ranking suggestions. It assumes
  opponents are somewhat less likely to suggest their own cards, but allows for
  controlled probes and other strategies. Repeated suggestions by the same
  opponent do not multiply this signal, and fixed board rooms are excluded.
  When a small complete deal space is available, this evidence softly weights
  deals for response planning; otherwise it is a tie-breaker. When a completed
  analysis gives a solution at least 50% estimated support, it may accuse
  without proof, using opponent-weighted deals when available and unweighted
  deal counts otherwise. The estimate is model-dependent, and a wrong
  accusation eliminates the bot. Assumptions are never added to notebook facts.

The shared deduction engine uses hand sizes as well as observed cards and
clauses. Strategic deal analysis can combine overlapping clauses with hand
sizes and eliminate solutions proved impossible by a bounded deal search. It
also counts consistent deals exactly when a separate bounded search completes;
it never treats an incomplete search as proof. These additional deductions are
used by the bot, not added to the automatic notebook.
Suggestion selection remains heuristic and profiles are not guaranteed to win
more often in every matchup. Use batch comparisons to measure their behavior
with different opponents, seeds, and seat positions.
In board mode, all profiles navigate toward reachable rooms while avoiding
recently suggested rooms when practical. Strategic bots consider room usefulness
and movement remaining, compare passages with possible dice rolls, and avoid
summoning an opponent as a tie-breaker. They use summoned-room suggestions and
continue to apply their card and reveal heuristics.
The deductive profile evaluates suspect and weapon candidates even when the
fixed room is known not to be in the solution.

The browser and Windows wizard also provide custom per-bot choices for
candidate suggestions, probes, suggestion ranking, repeat reveals, room
preferences, card-only suggestion priority, and deal analysis. Custom bots can
optionally make a calculated accusation when a completed analysis gives one
solution at least 75% of consistent deals. This assumes consistent deals are
equally likely and does not model how opponents choose actions; it is not a
guaranteed probability and a wrong accusation eliminates the bot. Custom bots
use response analysis when suggestion ranking is enabled together with deal
analysis or calculated accusations, and enhanced routing when candidate-room
preference is enabled. Among named presets, only analytical makes calculated
accusations. The toolkit score is
a weighted summary of applicable
enabled choices, not a measured difficulty or win probability; it excludes
the risky-accusation setting.

## Batch statistics and private traces

Run reproducible card-only simulations with the existing command-line options:

```text
python -m clue_engine.batch_cli --games 100 --players 4 --policies random,deductive,probing,strategic --seed 42 --trace batch-42.jsonl
```

Provide one policy name to use it for every player, or a comma-separated policy
for every seat. Available profiles are `random`, `deductive`, `probing`,
`strategic`, and `analytical`. The default limit is 10,000 actions per game; change it with
`--max-steps`. A game that
reaches the limit is reported as a timeout, not a completed game. The trace
file must be new: existing files are never overwritten. Errors and timeouts
give the CLI a nonzero exit status. Ctrl+C requests cancellation between
actions, saves the partial game and batch summary, and returns status 130.

To run any supported browser/API game setup, provide a JSON setup object:

```text
python -m clue_engine.batch_cli --setup board-setup.json --games 100 --trace board-100.jsonl
```

The file accepts `game_type`, `players`, and one `bots` entry per seat (a
named profile or a custom strategy object), plus `game_rules`, `board_rules`,
`seat_suspects`, `shuffle_bots`, `seed`, and `max_steps`. For example:

```json
{
  "game_type": "board",
  "players": 4,
  "bots": ["deductive", {"candidate_rooms": true, "deal_analysis": true}, "probing", "random"],
  "game_rules": {"all_refute": true},
  "board_rules": {"randomize_rooms": true, "procedural_map": true},
  "seat_suspects": [0, 1, 2, 3],
  "shuffle_bots": false,
  "seed": 42,
  "max_steps": 10000
}
```

The experimental `learned` policy is available for normal board-game play and
board batches, for example `"bots": ["learned", "deductive", "probing", "strategic"]`.
Select **Learned** in the board-game setup wizard, or use the same policy name
in a board batch configuration. It is rejected for card-only games. By default
the policy uses the packaged model to choose suggestions and room goals from the player's
visible hand, deductions, event history, and public board. It also chooses
whether to accuse using bounded counts of deals consistent with that player's
knowledge. A wrong accusation eliminates the bot. Room goals persist across
turns until reached or no longer reachable. This experimental model has not
been established to outperform the existing bots.

Open **Configure learned bot** for independent room, suggestion, and accusation
temperatures (0–5), plus an accusation confidence threshold (0–1). Temperature
0 picks the highest-scoring choice; higher values sample more broadly. With the
packaged model and zero accusation temperature, the default threshold of 0.5
allows an accusation at 50% estimated confidence. Set it to 1 for sound-only
accusations. Nonzero accusation temperature can choose either action above or
below the threshold, and a trained accusation head can shift the effective
threshold; 1 always disables risky accusations. To avoid repeated chances to
gamble on unchanged evidence, a declined accusation is reconsidered only if
the counted solution distribution or threat-adjusted threshold changes.
Estimates use uniformly weighted consistent deals unless the experimental
opponent model can reweight them; they are unavailable if the search exceeds
its budget and are not guarantees. Settings are per bot, can be copied, saved in setup profiles, and
used in both interactive and batch board games. For example:

```json
{"type":"learned","room_temperature":0.5,"suggestion_temperature":1.0,
 "accusation_temperature":0.0,"accusation_threshold":0.75,
 "opponent_model":true,"threat_sensitivity":0.7}
```

Omitted fields use the defaults. The string `"learned"` is shorthand for all
defaults; different settings have separate labels in batch results and traces.

The model is tuned offline from player-visible features and terminal
win/loss outcomes. Suggestion ranking includes the strategic bot's public
information features, such as deal certainty, reachable responders, unresolved
clauses, and deal diversity. Policy decisions never receive the solution or
other players' hands. Schema-1 and schema-2 models remain loadable with zero
weights for newer features and the accusation head. To fine-tune the packaged
model, then evaluate the candidate:

```powershell
python -m clue_engine.learning tune --initial src\clue_engine\learned_model_4.json --games-per-pool 16 --population 8 --generations 4 --seed 42000 --output model.json
python -m clue_engine.learning tune --initial src\clue_engine\learned_model_4.json --games-per-pool 16 --population 8 --generations 4 --seed 43000 --boards mixed --opponents analytical,analytical,analytical --output analytical-model.json
python -m clue_engine.learning benchmark --games 128 --seed 110000 --model model.json --incumbent src\clue_engine\learned_model_4.json
python -m clue_engine.learning evaluate --games 64 --seed 120000 --model model.json --room-temperature 0.5 --suggestion-temperature 1 --accusation-threshold 0.75
```

The packaged learned policy selects separate weights for 3, 4, 5, or 6
players (`learned_model_3.json`, `learned_model_4.json`, `learned_model_5.json`,
and `learned_model_6.json`). Train each variant with `--players`; training,
evaluation, tuning, and benchmarking all use that player count. The older
`learned_model.json` remains available for compatibility. For example:

```powershell
python -m clue_engine.learning train --players 3 --games 501 --seed 45003 --initial src\clue_engine\learned_model_4.json --output learned_model_3.json
python -m clue_engine.learning evaluate --players 3 --games 128 --seed 46003 --model learned_model_3.json
```

`CLUE_LEARNED_MODEL` remains a single-file override and applies that model to
all player counts. The packaged opponent and threat models remain shared.

`tune` uses a common-random-number cross-entropy search: every candidate is
evaluated on the same deals and seats against both the standard
`deductive,probing,strategic` pool and a pool containing `analytical`. All
generations use the same search seeds so their scores are comparable. The
optional `--opponents` replaces those pools with the specified opponents (one
per non-learner seat). Training only against analytical risks overfitting. It
tunes all three heads and writes the best observed candidate, not necessarily the
final population center. Increase `--games-per-pool`, `--population`, and
`--generations` for more search budget.

Policy `train`, `tune`, `evaluate`, and `benchmark` default to the standard
board, as did the packaged policy's original training. Pass `--boards random`
to shuffle room identities, or `--boards mixed` to alternate standard and
randomized layouts in complete rounds of `--players` games, balancing the seats
within each round. Randomized boards keep the board geometry, doors, and
passages rather than generating arbitrary maps. Evaluate on fresh seeds and
both board types.

Both tuning and experimental REINFORCE training optimize wins with a speed
preference: a completed win after `steps` actions earns `1 / (1 + 0.001 *
steps)`, while a loss earns zero. Thus a faster win is worth more, but increasing
the chance of winning can trade off against speed. `train --win-speed 0`
optimizes undiscounted wins instead; other non-negative values adjust the speed
preference. Training explores all three heads, including accuse versus continue,
and skips timeouts. `--initial` continues from a saved model. Evaluation reports
mean winning actions and the speed-adjusted score in addition to win rate.

Use fresh seeds for final model selection, not the tuning seeds. `benchmark`
tests the learned model and all built-in profiles over identical seeds, balanced
across seats and the two opponent pools. It reports Wilson intervals and
paired win-rate differences versus the learned policy, with approximate
95% intervals. Paired comparisons exclude games where either profile timed out
and report both completed and excluded pairs. Pass `--incumbent` to compare a candidate with a previous model
on the same individual games. `evaluate` remains available to assess one model against a
specific fixed opponent pool or compare an existing profile via `--baseline`.
Timeouts are reported separately and never count as wins; the speed-adjusted
score divides by all requested games, treating timeouts as zero. Model files include
the weights, schema, and training metadata and are never overwritten. To try a
candidate in the browser, desktop app, or batch CLI without replacing the packaged
model, set `CLUE_LEARNED_MODEL` to its local JSON path before launching the app:

```powershell
$env:CLUE_LEARNED_MODEL = (Resolve-Path .\model.json).Path
```

The override applies to every learned bot in that process; bot behavior settings
remain independent. Unset the variable before launching to restore the packaged
model. An invalid override is an error, not a fallback. Saving a candidate does
not automatically select it. Overlapping intervals or small seed sets do not
establish which policy is stronger.

Before the accusation and speed changes, a held-out 64-game-per-pool benchmark
(seed 750000; 16 games per seat;
no timeouts), the expanded-feature candidate won 22/64 (34.4%, 95% Wilson
interval 23.9–46.6%) against deductive, probing, and strategic bots. The
packaged incumbent won 19/64 (29.7%), strategic 20/64 (31.3%), and analytical
25/64 (39.1%). Against the pool containing analytical, the candidate won
14/64 (21.9%, interval 13.5–33.4%); the incumbent won 15/64 (23.4%),
strategic 18/64 (28.1%), and analytical 16/64 (25.0%). Paired confidence
intervals include zero for comparisons with the incumbent, strategic, and
analytical in both pools. The candidate therefore has not shown a reliable
improvement and was not promoted; the packaged model remains unchanged.
Those historical results used sound-only learned accusations and do not measure
the current behavior. A later exploratory comparison on 24 fresh games per
pool (seed 1910000; six per seat; no timeouts) found 8 versus 9 wins for the
default 50% threshold versus sound-only in the standard pool, and 7 versus 6
against the analytical pool. Analytical won 8 and 9 respectively. These small
samples do not establish an improvement; run larger held-out comparisons before
promoting a newly trained model. A small four-candidate, eight-game-per-pool
search (seed 1930000), tested on another 24 games per pool (seed 1940000),
produced 11 versus 8 and 10 versus 6 wins for candidate versus incumbent.
Those exploratory results are also too small to justify replacing the packaged
weights.

#### Experimental opponent behavior model

The learned bot can optionally use a separate, supervised model of opponents'
suggestions and card reveals. Training simulates four bots sampled with
replacement from the requested profiles and learns to predict their observed
choices given hypothetical hands and solutions. It does not use RL. At play
time, it weights only deals already consistent with the player's deductions,
using visible suggestions and cards revealed to that player. It never uses
another player's private reveal; the actual hands and solution are used only
to generate training labels, not supplied to the playing bot.

This model is **off by default**. Its likelihoods are tempered and bounded so
behavioral guesses cannot rule out a legal deal. They influence suggestion
certainty and risky accusation confidence only when the existing bounded
search can enumerate all consistent deals (at most 128); otherwise the
original policy is used. It is not a calibrated guarantee of correctness,
does not learn individual player identities or predict individual movements.
Other players' room choices can be
constrained by movement and should not be treated as unconstrained guesses.
Enable **Use trained opponent behavior model** separately for any learned seat
in **Configure learned bot**, including in batch setup.

Train and evaluate on separate seeds, then compare identical policy weights
with and without the opponent model:

```powershell
python -m clue_engine.opponent_model train --games 500 --seed 2100000 --output opponent.json
python -m clue_engine.opponent_model evaluate --games 128 --seed 2200000 --model opponent.json
python -m clue_engine.learning benchmark --games 128 --seed 2300000 --model src\clue_engine\learned_model.json --incumbent src\clue_engine\learned_model.json --opponent-model opponent.json
$env:CLUE_OPPONENT_MODEL = (Resolve-Path .\opponent.json).Path
```

The environment variable optionally replaces the packaged behavior model for
enabled seats in the browser, desktop app, or batch CLI; it does not enable
the model by itself. Unset it to restore the packaged model. Invalid model
files are errors when enabled. `--opponents` accepts a
comma-separated pool; the default is random, deductive, probing, strategic, and
analytical. Evaluate on opponents excluded from training as well as fresh
seeds, and do not assume bots reflect human behavior. Prediction reports
include average log loss versus a uniform-choice baseline for suggestions and
reveals with multiple eligible cards. Lower is better, but predictive accuracy
alone does not demonstrate improved game outcomes. The `train` report is
in-sample; use `evaluate` with disjoint game seeds for a meaningful check.
Game evaluation and benchmark reports also show `opponent_model_choices` and
`opponent_model_weightings`. The latter counts weighting operations, not
distinct decisions: a single decision can perform more than one.

The policy weights shipped with the app were trained without an opponent
model. To train or tune those weights with a particular opponent model, pass
`--opponent-model opponent.json` to `learning train` or `learning tune` as
well. Keep their evaluation seeds separate from both opponent-model and policy
training seeds. If `learned` is included in the opponent-training pool, its
behavior also depends on the configured learned and opponent model environment
variables where the relevant model is enabled.

In one exploratory trial, training on 80 mixed-profile games and evaluating
on 32 fresh games gave suggestion log loss 1.601 versus 1.792 uniform and
reveal log loss 0.698 versus 0.746 uniform. In 24 paired games per opponent
pool, the model won 10 versus 9 in the standard pool and 7 versus 7 in the
analytical pool. The sample is too small to establish an improvement.
In a separate 16-game standard-pool sample the model performed 36 weightings
across 538 learned-policy choices; its impact is presently concentrated in
small endgame deal spaces.
Another model trained without analytical opponents achieved suggestion log loss
1.554 versus 1.792 uniform and reveal log loss 0.734 versus 0.738 uniform on
24 analytical-only games. These results do not establish human generalization.

The packaged behavior model was trained on 160 mixed-board games (seed
3100000) with an analytical-heavy pool: analytical appears three times and
strategic, probing, and deductive once each in the sampling pool. On 64 fresh
mixed-board, all-analytical games (seed 3500000), suggestion log loss was
1.490 versus 1.792 uniform; reveal log loss was 0.731 versus 0.733 uniform.
Both supervised model CLIs default to mixed boards and accept `--boards` and
`--opponents`. These prediction scores do not establish improved win rates.

#### Experimental opponent threat forecast

The **Opponent threat sensitivity** slider (0–1) controls a separate supervised
forecast of an opponent winning before this bot's next turn. Zero (the default)
disables it. Based only on visible suggestions, passes, turns, and movement,
the forecast reduces the risky-accusation threshold by the factor
`1 - sensitivity * predicted_threat`; it never overrides sound-only threshold
1. It only affects choices when bounded deal counts are available. It is not
an individual opponent identity model or a guarantee of calibration.

```powershell
python -m clue_engine.threat_model train --games 500 --seed 3300000 --boards mixed --output threat.json
python -m clue_engine.threat_model evaluate --games 128 --seed 3400000 --boards mixed --opponents analytical --model threat.json
```

The app uses the packaged threat model; training a new file does not
automatically select it. The packaged model used 200 mixed-board games with the
same analytical-heavy pool. On 64 fresh all-analytical mixed-board games (seed
3400000), its Brier score was 0.109 versus 0.123 for a constant event-rate
baseline (1,160 examples, 167 events). Lower is better, but this is a small,
distribution-specific prediction test.

In exploratory 32-game comparisons against three analytical bots, the default
learned bot and behavior-plus-threat configuration each won 8 standard games,
while an analytical seat won 6; on shuffled rooms they won 5 and 7 versus 10
for analytical. A separately tuned analytical-focused candidate won 4 versus
9 for the incumbent and 6 for analytical on 32 held-out standard games; on
32 shuffled games it won 6 versus 4 and 9. These small tests do **not** show
consistent superiority over analytical, and the candidate was not promoted.

The shared browser and desktop app also provide **Batch simulation** from the
main menu, or by selecting **Spectate bots** and **Run a batch of games** in
the normal setup wizard. The wizard exposes game type, player count, per-seat named or
custom bots, game and board rules, suspect assignments, bot shuffling, seed,
action limit, and game count. Bot cards show toolkit scores by default; open
strategy details to read descriptions or edit a custom bot. The results view
reports progress, policy comparisons, and interactive distributions. The
relative win rate is each profile's completed-seat win rate divided by observed
wins per completed seat: 100% is the equal-share reference, not a causal
strength estimate. Completed games without a winner lower that reference; it is
unavailable when there are no observed wins or no completed seats.

Filter browser/desktop distributions by profile, seat, or both. Game-level
measures select games containing that profile in the selected seat, counting
each game once even if the profile appears more than once. The Player 1 turn
measure always refers to Player 1, not the filtered seat. Turns per seat, bot
seat outcomes, and first-solution distributions instead count matching seat
appearances. Turns per seat pools completed seat appearances across all seats
unless filtered. First-solution action and turn histograms include only
appearances recorded as learned and report the number not learned, including
incomplete games. Knowledge graphs show the fraction that learned the
solution or mean remaining envelope candidates against each seat's own
completed-turn count, using the last snapshot at that count. Later points
include only seats still observed; the exact data lists sample counts and
ranges. Game-length and
board-event measures exclude incomplete games; outcomes include them. Numeric
statistics are calculated from the original observations, not histogram bins.
The distribution selector groups measures by subject and includes per-seat
comparisons of mean turns, win rate, learned-solution rate, and mean first
solution action. Each bar shows its sample count; seat and profile filters
apply to the underlying seat appearances. Turns and win rate use completed
appearances, learned-solution rate includes incomplete appearances, and first
solution action uses only appearances recorded as learned. An unavailable value
is distinct from a measured zero.
The fixed-height distribution graph plots numeric bins on a continuous axis,
including gaps. Hover or focus a bar for its count, percentage, and cumulative
share. When bins are too numerous to display individually, adjacent bins are
combined for the graph; **View exact bin data** retains and pages through the
original bins.
Use the workspace tabs to switch between the distribution, summary, and runs.
The individual-runs table can be filtered, paged, and sorted by outcome, action
count, turns, winner, learned seats, earliest solution action, and event counts.
Open a run in the replay
viewer, then use **Back to batch results** to continue the analysis. Replays
include completed and recorded incomplete games, and expose private hands and
the solution. The app retains compact per-game observations in memory and
private traces in a temporary directory while the batch is available. Inactive
batches expire after one hour when a subsequent batch is started; temporary
traces are also cleaned up on normal app exit. Very large batches therefore use more
memory and temporary disk space. The results view can be revisited from a batch
replay, but is not restored after a page reload or a return to the main menu.
Export any replay you want to keep.

The Tkinter desktop **Batch statistics** window can also load the same JSON
setup. CLI `--seed` and `--max-steps` and the Tkinter seed/action-limit fields
override values in the file. Human-only setup fields (mode, human seat,
notebook, progression, and debug) do not affect a batch; every seat must have
a bot configuration. Board games support 3–6 players; card-only games support
two or more, subject to the face-up-card rule requiring at least one card per
player. Unsupported fields, invalid rule combinations, and incomplete bot
lists are rejected before creating a trace. Each batch uses one selected setup
across its games; use separate traces for setup comparisons rather than
exhaustively enumerating the configuration space.

The Tkinter desktop **Batch statistics** window also lets you configure a
batch and new trace file, start or cancel it, and inspect progress and summary
while it runs. Its trace controls can open an existing JSONL file and display
one zero-based game at a time. Trace loading and batch work run off the Tk
thread. Closing the window requests cancellation.

After a batch finishes or is cancelled, the **Distributions** tab displays a
histogram. Select actions, Player 0's completed turns, outcomes, the action at
which a player first learned the solution, or board-specific rolls, moves,
room entries, passages, and suspect/weapon relocations. Choose counts or percentages,
set a positive bin width, and use **Refresh chart** (or press Enter in a
setting). Deduction charts can be filtered by policy, seat, or both. To analyze
an existing trace, choose it with **Existing...**, then select **Load trace
distributions** in that tab.

The batch CLI prints an action histogram by default. Change its settings or
analyze an existing trace without running another batch:

```text
python -m clue_engine.batch_cli --games 100 --players 4 --trace batch-turns.jsonl --metric turns --bin-width 2 --display percent
python -m clue_engine.distributions_cli --trace batch-42.jsonl --metric deduction --filter-policy strategic --filter-seat 2 --bin-width 10 --display percent
```

Metrics are `actions`, `turns`, `outcomes`, `deduction`, `rolls`, `moves`,
`room_entries`, `passages`, `suspect_relocations`, and `weapon_relocations`;
display modes are `count` and `percent`. Policy and seat filters apply only to deduction. Numeric
bins are inclusive at both displayed endpoints and empty bins are omitted.
Chart percentages are empirical frequencies, not guaranteed probabilities.
Action and turn charts use completed games only and report excluded timeouts,
errors, and cancellations. Outcome charts use recorded game results. Deduction
charts use only matching seat exposures recorded as having learned the solution
for their percentages; they also report matching exposures not recorded as
learned, including partial games. If a policy occupies multiple seats, each
seat is a separate exposure. A partial trace is flagged when a started game
lacks a result or the batch result is missing; malformed traces are reported
instead of silently skipped.

Batch deduction metrics use the shared automatic-notebook deductions. They do
not include additional deductions or guesses made by a bot's bounded deal
analysis, so a strategic winner need not appear as having learned the solution
in those metrics.

**Traces contain all private information**, including every hand, the solution,
and private shown cards. Keep them in a secure location and do not share them
with players who should not see that information. A trace includes every
started game and can grow large; plan disk space for long batches.

By default, policies rotate across seats. Each cycle of `players` games uses
the same deal seed, `seed + game_index // players`, while policies move one
seat per game. Each seat's policy has an independent deterministic random
generator, seeded from the deal seed, game index, and seat; action randomness
is therefore not paired between games. An incomplete final cycle can give
unbalanced seat exposures, so use a game count divisible by the number of
players for balanced comparisons. `--no-rotate` keeps the supplied seat order
and uses `seed + game_index` as the deal seed. The trace records Python's
version and the seeds; reproducibility across Python versions is not guaranteed.

Summaries count wins, all-eliminated games, timeouts, errors, and cancellations
separately. Only wins and all-eliminated games count as completed. Policy
win rates divide wins by completed seat exposures, including multiple seats
using the same policy; policy-by-seat rates use the corresponding seat
exposures. Mean actions, mean completed turns per seat, suggestions, passes,
and refutations use completed games only. Board runs also report mean rolls,
moves, room entries, passages, and token relocations. The action median averages the two
middle values for an even sample; p90 uses the nearest-rank definition.
Deduction totals use all started seat exposures, including partial games.
Their mean first-solution step is averaged only over players who learned the
solution: step 0 means the initial hand was sufficient, and subsequent steps
count actions, not events. Snapshot candidate counts and solution knowledge
are calculated independently from each player's filtered view.

Board event distributions include completed games with zero occurrences of
the selected event and are unavailable for card-only runs. The newline-delimited
JSON trace uses schema version 2 and begins with `batch_start`, followed by each
`game_start` (deal and policy seeds), `initial_knowledge`, alternating `action`
and `knowledge` records, and `game_result`. An action contains all events it
produced; for example, one reveal may produce both refutation and private-show
events. Board traces additionally record the initial board state and movement
event details. Schema-1 card-only traces remain readable. Expected failures may add `action_error` or `knowledge_error` records.
The final `batch_result` contains the same aggregate data as the displayed
summary, including policy-by-seat breakdowns. Unexpected errors are surfaced
and may leave a partial trace without a final result; successfully applied
actions are written before deduction snapshots. One game's records can be
loaded in Python with `read_game_trace(Path("batch-42.jsonl"), 0)` from
`clue_engine.batch`.

`clue_engine.actions.ACTIONS` retains the fixed card-only action ordering.
Board movement actions are generated dynamically. The project does not yet
define an RL environment, observation encoding, rewards, or action mask.

Install the project with its development dependencies and run the checks:

```text
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

Frontend JavaScript regression tests run with pytest when Node.js 18 or newer is
available; if Node.js is not installed, they are skipped.
Run `node --test tests\test_web_ui.cjs` directly to require those tests.
The [CI workflow](.github/workflows/ci.yml) runs Python 3.11 and 3.13 on Linux
and Python 3.13 on Windows with Node.js 22. Headless systems may skip tests
requiring a Tk display; the skip report makes that visible. Other Python versions
allowed by the package metadata are not individually certified by this matrix.
The layout and WebView2 checks in the release process remain manual.

Batch JSONL traces contain hands, solutions, and private reveals. Store them in
the ignored `output` directory or another private location; Git ignores JSONL
outputs by default. Deliberate test fixtures may be placed under
`tests\fixtures`. Ignoring a file does not remove previously committed data
from Git history.
