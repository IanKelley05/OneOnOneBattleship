import os
import secrets
import sqlite3
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, session, send_file
from public_export import write_public_export
from publishing import Publisher, SCHEMA as PUBLISH_SCHEMA, enqueue
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).parent
DATA = Path(os.environ.get('BATTLESHIP_DATA', ROOT / 'instance'))
DATA.mkdir(parents=True, exist_ok=True)
secret_file = DATA / 'secret'
if not secret_file.exists():
    secret_file.write_text(secrets.token_hex(32))
app = Flask(__name__)
app.secret_key = secret_file.read_text()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
app.config['EXPORT_ROOT'] = ROOT / 'exports'
app.config['PUBLISH_ENABLED'] = True
publisher = Publisher(ROOT, DATA)
COLORS = ['#f87171', '#fb923c', '#facc15', '#a3e635', '#34d399', '#22d3ee', '#60a5fa', '#818cf8', '#c084fc', '#f472b6', '#e2e8f0', '#a78b71', '#14b8a6', '#e879f9', '#fda4af', '#bef264']
FLEET = [5, 4, 3, 3, 2]


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATA / 'game.sqlite', timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


@app.teardown_appcontext
def close_db(error):
    if 'db' in g:
        g.db.close()


with app.app_context():
    db().executescript('''
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS towers (name TEXT PRIMARY KEY, start TEXT NOT NULL, ready INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS ships (id INTEGER PRIMARY KEY, tower TEXT NOT NULL REFERENCES towers(name), cells TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS players (id INTEGER PRIMARY KEY, tower TEXT NOT NULL REFERENCES towers(name), name TEXT NOT NULL COLLATE NOCASE, color TEXT NOT NULL, UNIQUE(tower,name), UNIQUE(tower,color));
    CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, tower TEXT NOT NULL REFERENCES towers(name), player INTEGER NOT NULL REFERENCES players(id), remaining INTEGER NOT NULL DEFAULT 3);
    CREATE TABLE IF NOT EXISTS shots (id INTEGER PRIMARY KEY, tower TEXT NOT NULL REFERENCES towers(name), player INTEGER NOT NULL REFERENCES players(id), turn INTEGER NOT NULL REFERENCES turns(id), cell INTEGER NOT NULL, hit INTEGER NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(tower,cell));
    ''')
    for name, offset in [('South', 0), ('North', 7)]:
        db().execute('INSERT OR IGNORE INTO towers(name,start) VALUES (?,?)', (name, (date.today() + timedelta(days=offset)).isoformat()))
    db().commit()
    db().executescript(PUBLISH_SCHEMA)


def fail(message, status=400):
    return jsonify(error=message), status


def wake_publisher():
    if app.config['PUBLISH_ENABLED']:
        try:
            publisher.wake()
        except Exception:
            app.logger.exception('Publisher could not start; durable job remains queued')


def sunk_ships(tower):
    """Expose a ship only after every square was hit; derive history for old saves too."""
    hits = {r['cell']: r['id'] for r in db().execute(
        'SELECT id,cell FROM shots WHERE tower=? AND hit=1', (tower,))}
    sunk = []
    for row in db().execute('SELECT cells FROM ships WHERE tower=? ORDER BY id', (tower,)):
        cells = sorted(map(int, row['cells'].split(',')))
        if all(c in hits for c in cells):
            sunk.append({'cells': cells, 'shot_id': max(hits[c] for c in cells)})
    return sunk


def organizer(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('organizer'):
            return fail('Organizer login required.', 403)
        return fn(*args, **kwargs)
    return wrapper


@app.before_request
def csrf():
    if request.method == 'POST' and not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', 'missing')):
        return fail('Refresh the page and try again.', 403)


@app.get('/')
@app.get('/organizer')
def index():
    session.setdefault('csrf', secrets.token_hex(24))
    return render_template('index.html', admin=request.path == '/organizer', csrf=session['csrf'])


@app.get('/api/state/<tower>')
def state(tower):
    t = db().execute('SELECT * FROM towers WHERE name=?', (tower,)).fetchone()
    if not t:
        return fail('Unknown tower.', 404)
    shots = [dict(r) for r in db().execute('SELECT s.id,s.cell,s.hit,s.created,p.name,p.color FROM shots s JOIN players p ON p.id=s.player WHERE s.tower=? ORDER BY s.id', (tower,))]
    sunk = sunk_ships(tower)
    finishing_shots = {ship['shot_id'] for ship in sunk}
    for shot in shots:
        shot['sunk'] = shot['id'] in finishing_shots
    players = [dict(r) for r in db().execute('SELECT p.*, COUNT(s.id) shots, COALESCE(SUM(s.hit),0) hits FROM players p LEFT JOIN shots s ON s.player=p.id WHERE p.tower=? GROUP BY p.id ORDER BY p.id', (tower,))]
    turn = db().execute('SELECT t.id,t.remaining,p.name,p.color FROM turns t JOIN players p ON t.player=p.id WHERE t.tower=? AND remaining>0 ORDER BY t.id DESC LIMIT 1', (tower,)).fetchone()
    standings = []
    for r in db().execute('SELECT t.name,t.start,t.ready,COUNT(s.id) shots,COALESCE(SUM(s.hit),0) hits FROM towers t LEFT JOIN shots s ON s.tower=t.name GROUP BY t.name ORDER BY t.name DESC'):
        standings.append(dict(r))
    return jsonify(tower=dict(t), shots=shots, sunk_ships=sunk, players=players, turn=dict(turn) if turn else None, colors=COLORS, standings=standings, today=date.today().isoformat())


@app.post('/api/turn/<tower>')
def start_turn(tower):
    data = request.get_json(silent=True) or {}
    conn = db()
    conn.execute('BEGIN IMMEDIATE')
    t = conn.execute('SELECT * FROM towers WHERE name=?', (tower,)).fetchone()
    if not t or not t['ready'] or t['start'] > date.today().isoformat():
        return fail('This tower is not open yet.')
    if conn.execute('SELECT SUM(hit) FROM shots WHERE tower=?', (tower,)).fetchone()[0] == 17:
        return fail('This fleet is already sunk.')
    if conn.execute('SELECT 1 FROM turns WHERE tower=? AND remaining>0', (tower,)).fetchone():
        return fail('Finish the current three-shot meeting first.')
    name = str(data.get('name', '')).strip()
    if not name or len(name) > 60:
        return fail('Enter an RA name, up to 60 characters.')
    player = conn.execute('SELECT * FROM players WHERE tower=? AND name=?', (tower, name)).fetchone()
    if not player:
        color = data.get('color')
        if color not in COLORS:
            return fail('Choose an available color.')
        try:
            cursor = conn.execute('INSERT INTO players(tower,name,color) VALUES (?,?,?)', (tower, name, color))
            player_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return fail('That color is already in use.')
    else:
        player_id = player['id']
    conn.execute('INSERT INTO turns(tower,player) VALUES (?,?)', (tower, player_id))
    conn.commit()
    return jsonify(ok=True)


@app.post('/api/shot/<tower>')
def shoot(tower):
    data = request.get_json(silent=True) or {}
    cell = data.get('cell')
    if type(cell) is not int or not 0 <= cell < 64:
        return fail('Choose a square on the board.')
    conn = db()
    conn.execute('BEGIN IMMEDIATE')
    t = conn.execute('SELECT * FROM towers WHERE name=?', (tower,)).fetchone()
    if not t or not t['ready'] or t['start'] > date.today().isoformat():
        return fail('This tower is not open yet.')
    turn = conn.execute('SELECT * FROM turns WHERE tower=? AND remaining>0 ORDER BY id DESC LIMIT 1', (tower,)).fetchone()
    if not turn or data.get('turn') != turn['id']:
        return fail('The turn has changed. Refresh and try again.')
    hit = any(str(cell) in r['cells'].split(',') for r in conn.execute('SELECT cells FROM ships WHERE tower=?', (tower,)))
    try:
        shot_id = conn.execute('INSERT INTO shots(tower,player,turn,cell,hit) VALUES (?,?,?,?,?)', (tower, turn['player'], turn['id'], cell, int(hit))).lastrowid
    except sqlite3.IntegrityError:
        return fail('That square has already been fired on.')
    won = conn.execute('SELECT SUM(hit) FROM shots WHERE tower=?', (tower,)).fetchone()[0] == 17
    conn.execute('UPDATE turns SET remaining=? WHERE id=?', (0 if won else turn['remaining'] - 1, turn['id']))
    sunk = any(ship['shot_id'] == shot_id for ship in sunk_ships(tower))
    finished = won or turn['remaining'] == 1
    if finished:
        enqueue(conn)
    conn.commit()
    if finished:
        wake_publisher()
    return jsonify(hit=hit, sunk=sunk, won=won, publication_queued=finished)


@app.get('/api/organizer')
def admin_status():
    configured = db().execute("SELECT 1 FROM settings WHERE key='password'").fetchone() is not None
    return jsonify(configured=configured, authenticated=bool(session.get('organizer')))


@app.post('/api/login')
def login():
    password = str((request.get_json(silent=True) or {}).get('password', ''))
    conn = db()
    conn.execute('BEGIN IMMEDIATE')
    row = conn.execute("SELECT value FROM settings WHERE key='password'").fetchone()
    if not row:
        if len(password) < 8:
            return fail('Use at least eight characters.')
        conn.execute('INSERT INTO settings VALUES (?,?)', ('password', generate_password_hash(password)))
        conn.commit()
    elif not check_password_hash(row['value'], password):
        return fail('Incorrect password.', 403)
    session['organizer'] = True
    return jsonify(ok=True)


@app.post('/api/logout')
def logout():
    session.pop('organizer', None)
    return jsonify(ok=True)


@app.post('/api/password')
@organizer
def change_password():
    data = request.get_json(silent=True) or {}
    current = data.get('current', '')
    new = data.get('new', '')
    if not isinstance(current, str) or not isinstance(new, str):
        return fail('Enter valid passwords.')
    conn = db()
    conn.execute('BEGIN IMMEDIATE')
    row = conn.execute("SELECT value FROM settings WHERE key='password'").fetchone()
    if not row or not check_password_hash(row['value'], current):
        return fail('Current password is incorrect.', 403)
    if len(new) < 8:
        return fail('Use at least eight characters for the new password.')
    if new != data.get('confirm'):
        return fail('New passwords do not match.')
    conn.execute("UPDATE settings SET value=? WHERE key='password'", (generate_password_hash(new),))
    conn.commit()
    return jsonify(ok=True)


@app.get('/api/fleet/<tower>')
@organizer
def fleet(tower):
    return jsonify(ships=[[int(c) for c in r['cells'].split(',')] for r in db().execute('SELECT cells FROM ships WHERE tower=? ORDER BY id', (tower,))])


@app.post('/api/setup/<tower>')
@organizer
def setup(tower):
    data = request.get_json(silent=True) or {}
    ships = data.get('ships', [])
    if not isinstance(ships, list) or len(ships) != 5:
        return fail('Place all five ships.')
    occupied = set()
    for ship, length in zip(ships, FLEET):
        if not isinstance(ship, list) or len(ship) != length or any(type(c) is not int or not 0 <= c < 64 for c in ship):
            return fail('Invalid ship size or position.')
        cells = sorted(ship)
        horizontal = len({c // 8 for c in cells}) == 1 and all(b-a == 1 for a,b in zip(cells,cells[1:]))
        vertical = len({c % 8 for c in cells}) == 1 and all(b-a == 8 for a,b in zip(cells,cells[1:]))
        if not (horizontal or vertical) or occupied.intersection(cells):
            return fail('Ships must be straight, contiguous, and cannot overlap.')
        occupied.update(cells)
    conn = db()
    conn.execute('BEGIN IMMEDIATE')
    if not conn.execute('SELECT 1 FROM towers WHERE name=?', (tower,)).fetchone():
        return fail('Unknown tower.', 404)
    conn.execute('DELETE FROM ships WHERE tower=?', (tower,))
    for ship in ships:
        conn.execute('INSERT INTO ships(tower,cells) VALUES (?,?)', (tower, ','.join(map(str, ship))))
    conn.execute('UPDATE towers SET ready=1 WHERE name=?', (tower,))
    for shot in conn.execute('SELECT id,cell FROM shots WHERE tower=?', (tower,)).fetchall():
        conn.execute('UPDATE shots SET hit=? WHERE id=?', (int(shot['cell'] in occupied), shot['id']))
    if conn.execute('SELECT SUM(hit) FROM shots WHERE tower=?', (tower,)).fetchone()[0] == 17:
        conn.execute('UPDATE turns SET remaining=0 WHERE tower=?', (tower,))
    conn.commit()
    return jsonify(ok=True)


@app.post('/api/schedule')
@organizer
def schedule():
    data = request.get_json(silent=True) or {}
    try:
        south = date.fromisoformat(data.get('south', ''))
        north = date.fromisoformat(data.get('north', ''))
    except (ValueError, TypeError, OverflowError):
        return fail('Choose a valid start date.')
    conn = db()
    conn.execute('BEGIN IMMEDIATE')
    for name, start in [('South', south), ('North', north)]:
        conn.execute('UPDATE towers SET start=? WHERE name=?', (start.isoformat(), name))
    conn.commit()
    return jsonify(ok=True)


@app.post('/api/reset/<tower>')
@organizer
def reset(tower):
    if (request.get_json(silent=True) or {}).get('confirmed') is not True:
        return fail('Confirm the board reset first.')
    conn = db()
    conn.execute('BEGIN IMMEDIATE')
    if not conn.execute('SELECT 1 FROM towers WHERE name=?', (tower,)).fetchone():
        return fail('Unknown tower.', 404)
    conn.execute('DELETE FROM shots WHERE tower=?', (tower,))
    conn.execute('DELETE FROM turns WHERE tower=?', (tower,))
    conn.execute('DELETE FROM players WHERE tower=?', (tower,))
    conn.commit()
    return jsonify(ok=True)


@app.post('/api/export/<mode>')
@organizer
def export_board(mode):
    if mode not in ('preview', 'public'):
        return fail('Unknown export option.', 404)
    conn = db()
    conn.execute('BEGIN')
    try:
        path = write_public_export(conn, Path(app.config['EXPORT_ROOT']) / mode)
    except (OSError, ValueError):
        app.logger.exception('Public export failed')
        return fail('Could not generate export. Check the export folder and server log.', 500)
    finally:
        conn.rollback()
    return jsonify(ok=True, path=str(path), url=f'/public-export/{mode}/index.html')


@app.get('/api/publish/status')
@organizer
def publish_status():
    return jsonify(dict(db().execute('SELECT status,message,requested,published,updated FROM publication WHERE id=1').fetchone()))


@app.post('/api/publish')
@organizer
def publish_board():
    enqueue(db())
    db().commit()
    wake_publisher()
    return jsonify(ok=True, message='Game saved. Public update queued for GitHub.')


@app.get('/public-export/<mode>/index.html')
@organizer
def view_public_export(mode):
    if mode not in ('preview', 'public'):
        return fail('Unknown export option.', 404)
    path = Path(app.config['EXPORT_ROOT']) / mode / 'index.html'
    if not path.is_file():
        return fail('Generate an export first.', 404)
    response = send_file(path, mimetype='text/html', max_age=0)
    response.headers['Cache-Control'] = 'no-store'
    return response


if __name__ == '__main__':
    wake_publisher()
    app.run(host='127.0.0.1', port=5000, debug=False)
