# Tower Battleship

## Public viewer and automatic publishing

`docs/index.html`, `docs/viewer.js`, and `docs/viewer.css` are the static read-only viewer. `docs/public-state.json` is its only data source. Both towers are shown with recorded hits/misses, RA display names and colors, dated logs, and leaderboards. No hidden fleet geometry, unshot occupancy, schedules, active turns, database IDs, passwords, or session data is exported.

After a third shot (or an earlier fleet-winning shot), the game queues a publication in the same database transaction as the shot. Only after commit does a background thread export, check, commit, and push `docs/public-state.json` to `IanKelley05/OneOnOneBattleship`, branch `main`. Players do not wait for GitHub. Git has a timeout and cannot open interactive login windows. Run one `python app.py` server process at a time.

The publisher uses a separate bare Git repository and index inside ignored `instance/publisher.git`. It starts from the latest remote branch, constructs a commit changing only `docs/public-state.json`, verifies the changed-path list, and pushes without force. It never stages the local worktree or pushes unrelated local commits. GitHub's existing remote history is retained. Your normal Git checkout is not automatically merged or modified by publication; fetch/reconcile remote updates before your next source-code push.

Publishing status and **Retry publishing** appear in Organizer. Offline, credential, and rejected-push errors leave the game saved and the job pending. Retry exports the latest saved board. Pending jobs also resume when `python app.py` restarts. Multiple completed turns are coalesced; a turn arriving during a push stays queued. Use **Publish board** to publish organizer changes such as resets or moved ships. **Preview public export** still creates only a local standalone preview in `exports/preview/index.html`.

GitHub Pages is configured to use **main /docs** as its publishing source, and OneOnOneBattleship is public. The initial viewer assets are a one-time setup; automatic updates commit only the state file. The public URL is https://iankelley05.github.io/OneOnOneBattleship/. GitHub may take a few moments to build after a push. This requires existing Git credentials with repository push access. The app does not store a GitHub token.

For a local viewer without Flask:

```powershell
python -m http.server 8001 --bind 127.0.0.1 --directory docs
```

Open http://127.0.0.1:8001. This viewer fetches its JSON from a relative URL, so it works under the GitHub Pages repository path too. It does not call Flask or provide game controls.

Before every publication an exact allowlist check compares all public fields against recorded shots in a consistent database snapshot. Any additional field, unshot coordinate, or mismatched player total blocks publication. To check the current file locally:

```powershell
python check_public_state.py
python -m unittest -v test_game.py test_public_export.py test_publishing.py
```

If the local state file is older than your game, regenerate it with Publish board before checking. Tests include unshot-coordinate injection, private-field rejection, offline recovery, database writes while Git is blocked, and verifying that a staged private file never reaches the publishing commit.

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
