# Tower Battleship

A local Flask + SQLite game for RA one-on-ones. Requires Python 3.10 or newer.

## Launch on Windows

Open PowerShell in this folder:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**. Leave the terminal running; Ctrl+C stops the server. Run `python app.py` again to resume saved progress.

## First-time setup

1. Open **http://127.0.0.1:5000/organizer** and create an organizer password (8+ characters). The first password becomes the saved password.
2. Set South’s opening date before any shots are taken. North opens seven days later, using the computer’s local date.
3. Select South and place all five ships by clicking their starting squares. Toggle horizontal/vertical as needed. Save the fleet, then repeat for North. Each board is 8×8; fleet sizes are 5, 4, 3, 3, and 2. Ships may touch but cannot overlap. Clear placement to redo an unsaved arrangement. Fleets become immutable after that tower’s first shot.
4. Click **Lock organizer**, then **Player board** before handing the screen to an RA. Close any other organizer tabs.
5. The RA enters a new name and picks an unused color, or selects a returning name from the name field. Start the meeting and click three unused squares. Hits show × and misses show a dot, in that RA’s color. A new meeting can then begin. Returning RAs retain their color. There are 16 colors per tower.

Each tower has independent players, fleets, and turns. An interrupted meeting resumes with its remaining shots. The shot that finishes a ship is labeled **SUNK**, and a line connects that ship’s hit markers while preserving each RA’s color. The log runs from oldest to newest, opens at the bottom, and shows each move’s date and time in the browser’s local timezone. These details also appear for previously saved moves. Only fully sunk ships are revealed.

Sinking the last ship ends the current meeting immediately. The winner is announced once both towers finish, based on total shots including misses; equal totals are a tie. There is no calendar-based score adjustment.

The organizer?s **Reset board** button asks ?Are you sure?? before clearing the selected tower?s shots, players, color assignments, and turns. It keeps the saved fleet and start date, and does not affect the other tower. Cancel leaves all progress intact.

## Saved data and privacy

All progress is stored in `instance/game.sqlite`; the session signing secret is in `instance/secret`. Back up the entire `instance` folder while the server is stopped. Keep this folder private: the database contains the fleet coordinates and hashed organizer password. The player page and player API never receive hidden ship coordinates. Organizer fleet access requires a password session. This is a trusted, shared-computer game; player identities are selected without individual passwords.

The server listens only on this computer at `127.0.0.1`, with debug mode disabled. No external services or frontend downloads are required. Set up the organizer password before letting others use the game. To start a new competition, stop the server and move the `instance` folder to a backup location; restarting creates a fresh game.

## Checks

```powershell
python -m unittest -v test_game.py
```

The integration test uses a temporary database and checks private fleet access, ship validation, staggered dates, turn limits, duplicate shots, color ownership, persistence across requests, and fleet completion.

## Password changes and finishing a game

After unlocking the organizer screen, use Change organizer password to enter your current password, a new password of at least eight characters, and its confirmation. This keeps game progress intact.

When a tower sinks its fleet, Your meeting becomes Game stats with total moves, accuracy, hits/misses, ships sunk, participating RAs, best hit streak, and top scorers. The final shot opens a You won! popup; Close and view board dismisses it without changing saved progress. Reloading a finished game keeps the stats visible without replaying the popup. The overall tower winner is still decided by total shots.
