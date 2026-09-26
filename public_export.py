"""Public-only snapshot builder. Never reads ships, settings, or turn state."""
import os
import json
import re
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path

STYLE = '''
:root{color-scheme:dark;font-family:Segoe UI,Arial,sans-serif;background:#0a1420;color:#e6edf5}*{box-sizing:border-box}body{max-width:1500px;margin:auto;padding:30px}h1{font-size:38px;margin:12px 0}h2{margin-top:0}p,.muted{color:#9baec2;line-height:1.6}.eyebrow{color:#67d6cc;font-size:11px;letter-spacing:2px}nav{display:flex;gap:12px;margin:24px 0}a{color:#8ae4d8}nav a{padding:12px 20px;border:1px solid #315057;border-radius:8px;text-decoration:none}.tower{scroll-margin-top:20px;margin:32px 0 50px}.layout{display:grid;grid-template-columns:220px minmax(320px,1fr) 300px;gap:20px}.panel{background:#101e2c;border:1px solid #253648;border-radius:14px;padding:22px}.board{display:grid;grid-template-columns:20px repeat(8,minmax(0,1fr));gap:5px}.axis{display:flex;align-items:center;justify-content:center;color:#829bb2;font-size:11px}.cell{aspect-ratio:1;display:flex;align-items:center;justify-content:center;border:1px solid #2d455a;border-radius:6px;background:#1a3042;font-size:26px;font-weight:bold}.fired{color:var(--shot);border-color:var(--shot);background:color-mix(in srgb,var(--shot) 13%,#172535)}.person{display:flex;align-items:center;gap:8px;padding:11px 0;border-bottom:1px solid #253648;overflow-wrap:anywhere}.dot{width:10px;height:10px;border-radius:50%;background:var(--shot);flex-shrink:0}.score{margin-left:auto;white-space:nowrap;color:#9baec2}.log{max-height:350px;overflow:auto;padding-left:24px}.log li{padding:10px 0;border-bottom:1px solid #253648;font-size:13px}.log time{display:block;color:#9baec2;font-size:11px;margin-top:5px}.summary{color:#8ae4d8}.legend{font-size:12px;text-align:center}.ranking{margin-bottom:28px}footer{color:#9baec2;font-size:12px}@media(max-width:1100px){.layout{grid-template-columns:190px 1fr}.results{grid-column:1/-1}}@media(max-width:650px){body{padding:16px}.layout{grid-template-columns:1fr}.waters{grid-row:1}.panel{padding:16px}.cell{font-size:22px}.results{grid-column:auto}}
'''


def public_snapshot(conn):
    """Explicit column allowlist; shot order needs no exported database identifiers."""
    towers = []
    for tower in ('South', 'North'):
        shots = [dict(row) for row in conn.execute('''
            SELECT s.cell, s.hit, s.created, p.name, p.color
            FROM shots s JOIN players p ON p.id=s.player
            WHERE s.tower=? ORDER BY s.id
        ''', (tower,))]
        # Only people represented in the published shot history are public players.
        players = {}
        for shot in shots:
            key = (shot['name'], shot['color'])
            player = players.setdefault(key, {'name': shot['name'], 'color': shot['color'], 'shots': 0, 'hits': 0})
            player['shots'] += 1
            player['hits'] += shot['hit']
        towers.append({'name': tower, 'shots': shots, 'players': list(players.values())})
    return towers


def public_state(conn):
    return {'version': 1, 'towers': public_snapshot(conn)}


def check_public_state(conn, payload):
    """Exact allowlist comparison to a consistent DB snapshot, not a keyword scan."""
    if not isinstance(payload, dict) or set(payload) != {'version', 'towers'}:
        raise ValueError('Unexpected public state fields.')
    if payload != public_state(conn):
        raise ValueError('Public state must contain only the current recorded shots and public player totals.')
    for tower in payload['towers']:
        recorded = {r['cell'] for r in conn.execute('SELECT cell FROM shots WHERE tower=?', (tower['name'],))}
        if any(shot['cell'] not in recorded for shot in tower['shots']):
            raise ValueError('Public state contains an unshot location.')


def write_public_state(conn, path):
    payload = public_state(conn)
    check_public_state(conn, payload)
    content = json.dumps(payload, ensure_ascii=True, indent=2) + '\n'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Public output must not be a symbolic link.')
    descriptor, temp = tempfile.mkstemp(prefix='public-state-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
            output.write(content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return content.encode('utf-8')


def color(value):
    return value if re.fullmatch(r'#[0-9a-fA-F]{6}', value) else '#e2e8f0'


def render_public(towers):
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>Tower Battleship | Public boards</title>',
             '<style>' + STYLE + '</style></head><body>',
             '<header><span class="eyebrow">MCCUTCHEON COMPETITION · READ-ONLY</span>',
             '<h1>Tower Battleship</h1><p>A snapshot of the shots taken so far.</p>',
             '<p>Updated ' + datetime.now(timezone.utc).strftime('%b %d, %Y at %H:%M UTC') +
             '. Updates appear when a new snapshot is published.</p></header>',
             '<nav aria-label="Tower boards"><a href="#south">South Tower</a><a href="#north">North Tower</a></nav>']
    for tower in towers:
        name, shots, players = tower['name'], tower['shots'], tower['players']
        hits = sum(s['hit'] for s in shots)
        parts.append(f'<section class="tower" id="{name.lower()}"><h2>{name} Tower</h2><p class="summary">{len(shots)} shots · {hits} hits</p><div class="layout"><aside class="panel"><h2>Past players</h2>')
        def player_row(player, score):
            return f'<div class="person"><span class="dot" style="--shot:{color(player["color"])}"></span><span>{escape(player["name"])}</span><span class="score">{score}</span></div>'
        for player in players:
            parts.append(player_row(player, f'{player["shots"]} shots'))
        if not players:
            parts.append('<p>No shots taken yet.</p>')
        parts.append('</aside><section class="panel waters"><h2>Shot board</h2><div class="board" role="group" aria-label="' + name + ' shot board"><span></span>')
        parts.extend(f'<span class="axis">{c}</span>' for c in range(1, 9))
        by_cell = {s['cell']: s for s in shots}
        for row in range(8):
            parts.append(f'<span class="axis">{chr(65+row)}</span>')
            for col in range(8):
                cell = row * 8 + col
                shot = by_cell.get(cell)
                if shot is None:
                    # Identical blank markup: no occupancy or ship information.
                    parts.append('<span class="cell" aria-label="No shot recorded"></span>')
                else:
                    label = f'{chr(65+row)}{col+1}: {"HIT" if shot["hit"] else "MISS"} by {shot["name"]}'
                    parts.append(f'<span class="cell fired" style="--shot:{color(shot["color"])}" aria-label="{escape(label, quote=True)}">{"✕" if shot["hit"] else "•"}</span>')
        parts.append('</div><p class="legend">✕ Hit · • Miss · Color = RA who fired</p></section><aside class="panel results"><h2>Hits leaderboard</h2><div class="ranking">')
        for player in sorted(players, key=lambda p: (-p['hits'], p['shots'], p['name'].casefold())):
            parts.append(player_row(player, f'{player["hits"]} hits'))
        if not players:
            parts.append('<p>No scores yet.</p>')
        parts.append('</div><h2>Shot log</h2><p class="muted">Oldest first · times in UTC</p><ol class="log">')
        for shot in shots:
            coord = f'{chr(65+shot["cell"]//8)}{shot["cell"]%8+1}'
            parts.append(f'<li><span class="dot" style="--shot:{color(shot["color"])};display:inline-block"></span> {escape(shot["name"])} · <b>{coord} · {"HIT" if shot["hit"] else "MISS"}</b><time>{escape(shot["created"])} UTC</time></li>')
        parts.append('</ol></aside></div></section>')
    parts.append('<footer>Read-only snapshot. Blank squares have no recorded shot.</footer><script>document.querySelectorAll(".log").forEach(log => {log.scrollTop = log.scrollHeight;});</script></body></html>')
    return ''.join(parts)


def write_public_export(conn, directory):
    """Create one self-contained file; never copy an application directory."""
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('Export directory must not be a symbolic link.')
    directory.mkdir(parents=True, exist_ok=True)
    if any(p.name != 'index.html' or not p.is_file() or p.is_symlink() for p in directory.iterdir()):
        raise ValueError('Export directory contains unexpected files; choose a clean export directory.')
    html = render_public(public_snapshot(conn))
    # Atomic replacement prevents a viewer from opening a partly written snapshot.
    descriptor, temp = tempfile.mkstemp(prefix='board-', suffix='.tmp', dir=directory.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
            output.write(html)
        os.replace(temp, directory / 'index.html')
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return directory / 'index.html'
