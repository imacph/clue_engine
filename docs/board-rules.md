# Board-mode rules contract

This is the contract for the board engine and the local web interface. The reference is the
[Hasbro Clue C00045 instructions (2002)](https://www.hasbro.com/common/instruct/Clue%282002%29.pdf).
The game rules are summarized here; the board artwork and instructions are not
reproduced. Card-only mode keeps its current rules and remains the default.

## Setup

- **BR-01 — Players:** Board games have 3–6 players. Two-player and larger
  games remain supported by card-only mode. Both `BoardSetup` and the board
  game factory validate the board player count.
- **BR-02 — Characters and weapons:** Put all six suspect tokens on their
  starting spaces, including unassigned tokens. Put the six weapon tokens in
  six different rooms. Assign each player a different suspect.
- **BR-03 — Turn order:** Miss Scarlet starts and play proceeds in seat order.
  Character selection and default assignments require Miss Scarlet to be an
  active player.
- **BR-04 — Cards:** Randomly choose one suspect, weapon, and room for the
  solution; deal all remaining cards as evenly as possible. Players keep their
  hands private unless an information variant is enabled.
- **BR-05 — Board:** Use nine rooms, hallways, doors and passages between
  diagonally opposite corner rooms. Use original or appropriately licensed
  artwork and document any topology differences from the reference edition.

## Movement and suggestions

- **BR-06 — Roll:** On a normal movement turn, roll two dice and move
  orthogonally through hallway squares, up to the rolled total. A player may
  stop early, and entering a room ends movement. The engine generates and
  records the roll.
- **BR-07 — Paths:** A token cannot enter an occupied hallway square, visit the
  same square twice during one turn, or re-enter a room it left during that
  turn. A door is an opening, not an additional square. Entering a room costs
  one step and ends movement even when the roll has steps left.
- **BR-08 — Passage:** At the start of a turn in a corner room, a player may
  take its secret passage to the opposite corner room instead of rolling.
- **BR-09 — Blocked movement:** A player trapped in a room by blocked doors
  remains there until an exit is available. If a hallway path cannot continue,
  ending at the last reachable square is the planned interpretation where the
  reference does not specify the outcome.
- **BR-10 — Room suggestions:** After entering a room, make a suggestion naming
  that room, one suspect, and one weapon. A suggestion may include cards in the
  suggester's hand. A player cannot remain in a room just to repeat suggestions;
  after suggesting there, the player must enter another room or leave on a
  later turn and re-enter the previous room on a subsequent turn.
- **BR-11 — Relocation:** Move the suggested suspect and weapon to the named
  room when they are not already there. This includes unassigned suspects and
  eliminated players' tokens.
- **BR-12 — Summoned player:** If another player's suggestion transfers a
  player's token to a room, that player may either move normally or suggest in
  that room on their next turn. Choosing to suggest does not also roll or move.
  Naming a token already in the room does not transfer it.
- **BR-13 — Refutation:** Other players respond in turn order. The first who can
  disprove the suggestion must privately show exactly one matching card; if
  none can, the suggestion is unrefuted.

## Accusations and game end

- **BR-14 — Accusation:** On their turn, a player may accuse any suspect,
  weapon, and room, even if they are elsewhere on the board. A player may
  suggest and then accuse on the same turn. A correct accusation wins and the
  solution cards are revealed to all players.
- **BR-15 — Wrong accusation:** A player who accuses incorrectly cannot take
  further turns or win, but must continue to refute when able. Other players
  may still move that player's token by suggesting it. If the eliminated token
  blocks a doorway, move it into that room. The solution cards remain secret.
- **BR-16 — All eliminated:** End the game without a winner if all players
  are eliminated. This preserves the engine's existing explicit termination
  rule; it is an implementation extension rather than a claimed C00045 rule.

## Existing names and planned differences

Keep the current card IDs and names to preserve card-only compatibility.
The reference edition uses different labels for some equivalent cards
(`Mr. Green`/`Reverend Green`, `Knife`/`Dagger`, and `Pistol`/`Revolver`).
Any edition-specific display aliases must not change card IDs or old traces.

## Optional house rules

The standard configuration implements BR-01–16. Either game type can combine
these independent information and refutation variants:

- **Face-up starting cards:** One randomly selected card from each player's
  hand is public from the beginning. Every player must have at least one card.
- **Public refutations:** Each shown refutation card is visible to everyone.
- **Everyone responds:** Every other player responds, even after a refutation,
  and must show one matching card if able; otherwise they pass.
- **Reverse response order:** Responders proceed in reverse seat order.

Without these variants, starting hands and shown cards are private and the
first player able to refute ends the response sequence. The automatic notebook
uses the public information; in manual mode players record their own notes.

Board games can also opt into suggesting from a room at the start of a turn
instead of moving. Other independent options control suspect relocation,
weapon relocation, summoned-player suggestions, secret passages, requiring the
full movement roll, revisiting hallway squares, optional room suggestions, and
restricting accusations to players currently in a room. Room-only accusations
may still name any room. Disabling suspect relocation leaves all
suspect tokens in place, including unassigned and eliminated tokens, and also
requires summoned-player suggestions to be disabled. Disabling weapon
relocation leaves weapon tokens in place. Disabling summoned-player suggestions
still moves suspects but requires the affected player to move normally on their
next turn. Disabling passages removes passage actions and may leave a player
blocked until the game's action limit. Passing remains mandatory only when no
card matches.

The browser and Windows wizard offer Standard and No relocation presets as well
as custom settings. Rules are fixed when a game starts and are included in
version-2 private board records. Extended variants are saved in version-3 board
records. Older board records preserve their recorded movement defaults.

## Implemented board engine

`clue_engine.board.DEFAULT_BOARD` is an original 25-by-27 layout identified as
`original-25x27-v1`. It has all nine card rooms, connected hallway squares,
20 door openings, a blocked central area, six suspect starts, and the two
opposite-corner passage pairs. Its room shapes, corridors, door positions, and
starting squares are **not a reproduction of the C00045 board**; travel
distances and gameplay balance therefore need separate evaluation.

Coordinates start at the upper left: `x` increases to the right and `y`
increases downward. Room squares, hallway squares, and walls partition the
grid. A door connects one room square to an adjacent hallway square; it is not
a separate movement square. The same layout data drives both movement and web rendering.

```python
from clue_engine.board_setup import BoardSetup
from clue_engine.board_state import create_board

board = create_board(BoardSetup(4))
print(board.layout.layout_id, board.seat_suspects)
print(board.occupied_hallways(), board.blocked_doors())
```

Default seat assignments include Miss Scarlet and `first_player` identifies
her seat. All six suspect tokens remain present, including unassigned tokens,
and occupy distinct hallway starts. The six weapons initially occupy six
different rooms; callers can supply different room and seat assignments.
Positions and layout are immutable, and room occupancy may be shared.
`create_board` creates positions only; `create_board_game` creates an engine
and bots. The engine exposes incremental movement actions and public board
observations, enforces the rules above, and records rolls and relocation.
Full private records can be written and verified with
`clue_engine.board_record`; they contain the hands and solution and must not
be shared with players. Existing card-only actions and trace formats remain
unchanged. The web and Windows interfaces support board play and spectating;
the original Tkinter, console, and batch interfaces remain card-only.

## Acceptance checklist

The engine, bot, and web-interface obligations below are implemented and
covered by tests.

- [x] **BR-01–05:** Reject invalid player counts at every board setup entry
  point; verify assignments, starting tokens, weapon placement, deck partition,
  room connectivity, doors, and passage pairs.
- [x] **BR-06–09:** Test controlled rolls, exact paths, direction changes,
  occupied squares including unassigned tokens, no revisits, room entry and
  exit, door blocking, passages, and blocked/no-continuation cases.
- [x] **BR-10–13:** Test room restrictions, repeat suggestions, all token
  relocations, summoned turns, own-card suggestions, mandatory refutation,
  unrefuted suggestions, and private visibility.
- [x] **BR-14–16:** Test accusations before and after suggestions, both
  outcomes and their solution visibility, eliminated responders, relocated
  eliminated tokens, blocked-door removal, and the all-eliminated extension.
- [x] Preserve card-only defaults, action ordering, seeded behavior, existing
  trace readers, and support for player counts outside the board-mode range.
- [x] Replay board games with recorded rolls and positions; ensure public
  snapshots never expose private cards or future random outcomes.
- [x] Verify all bot profiles through complete board games.
- [x] Add and verify board play in the web interface and shared Windows desktop
  interface; the console and legacy Tk interface remain card-only.
