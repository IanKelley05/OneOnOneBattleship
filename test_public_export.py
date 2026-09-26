"""Standalone export checks: no Flask server or app import is needed."""
import functools
import http.server
import sqlite3
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from public_export import public_snapshot, write_public_export


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript('''
            CREATE TABLE players(id INTEGER, tower TEXT, name TEXT, color TEXT);
            CREATE TABLE shots(id INTEGER, tower TEXT, player INTEGER, cell INTEGER, hit INTEGER, created TEXT);
            CREATE TABLE ships(cells TEXT);
            CREATE TABLE settings(password TEXT);
            CREATE TABLE turns(secret TEXT);
            INSERT INTO players VALUES(1,'South','Alex','#f87171');
            INSERT INTO players VALUES(2,'South','<script>alert("name")</script>','#60a5fa');
            INSERT INTO players VALUES(3,'North','UNPLAYED_PRIVATE_NAME','#34d399');
            INSERT INTO shots VALUES(1,'South',1,0,1,'2026-09-25 12:00:00');
            INSERT INTO shots VALUES(2,'South',2,63,0,'2026-09-25 12:01:00');
            INSERT INTO ships VALUES('PRIVATE_FLEET_8_9_10_11');
            INSERT INTO settings VALUES('PRIVATE_PASSWORD_HASH');
            INSERT INTO turns VALUES('PRIVATE_ACTIVE_TURN');
        ''')

    def test_allowlist_and_every_exported_file(self):
        # Export must succeed even when SQLite rejects all reads of private tables.
        self.conn.set_authorizer(lambda action, table, *args:
            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table not in ('shots', 'players') else sqlite3.SQLITE_OK)
        snapshot = public_snapshot(self.conn)
        self.assertEqual({s['cell'] for s in snapshot[0]['shots']}, {0, 63})
        for tower in snapshot:
            self.assertEqual(set(tower), {'name', 'shots', 'players'})
            for shot in tower['shots']:
                self.assertEqual(set(shot), {'cell', 'hit', 'created', 'name', 'color'})
            for player in tower['players']:
                self.assertEqual(set(player), {'name', 'color', 'shots', 'hits'})
        output = self.root / 'public'
        path = write_public_export(self.conn, output)
        self.assertEqual([p.name for p in output.iterdir()], ['index.html'])
        for file in output.rglob('*'):
            self.assertTrue(file.is_file())
            content = file.read_text(encoding='utf-8')
            for forbidden in ['PRIVATE_', 'UNPLAYED_', 'instance/', 'sqlite', 'password', '/api/', 'sunk_ships', 'csrf', 'fetch(', 'XMLHttpRequest']:
                self.assertNotIn(forbidden, content)
        parsed = Document(path.read_text(encoding='utf-8'))
        self.assertFalse(any(tag in ('form', 'input', 'button', 'iframe') for tag, attrs in parsed.tags))
        self.assertEqual(sum(attrs.get('class') == 'cell fired' for tag, attrs in parsed.tags), 2)
        self.assertEqual(sum(attrs.get('class') == 'cell' for tag, attrs in parsed.tags), 126)
        self.assertEqual(sum(tag == 'script' for tag, attrs in parsed.tags), 1)
        self.assertIn('<script>alert("name")</script>', ''.join(parsed.text))
        for tag, attrs in parsed.tags:
            self.assertNotIn('src', attrs)
            if 'href' in attrs:
                self.assertIn(attrs['href'], ('#south', '#north'))
        # A second export replaces the snapshot and leaves no staging data behind.
        write_public_export(self.conn, output)
        self.assertEqual(sorted(p.name for p in output.iterdir()), ['index.html'])

    def test_plain_static_server_under_repository_path(self):
        folder = self.root / 'ReaBattleship'
        write_public_export(self.conn, folder)
        handler = functools.partial(QuietHandler, directory=str(self.root))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urlopen(base + '/ReaBattleship/') as response:
                html = response.read().decode('utf-8')
            self.assertIn('South Tower', html)
            self.assertIn('North Tower', html)
            self.assertIn('2 shots · 1 hits', html)
            self.assertIn('No shots taken yet.', html)
            self.assertIn('A1 · HIT', html)
            self.assertIn('H8 · MISS', html)
            self.assertIn('2026-09-25 12:00:00', html)
            for route in ('instance/game.sqlite', 'api/state/South', 'app.py'):
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/ReaBattleship/' + route)
                self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_reject_unexpected_files(self):
        folder = self.root / 'public'
        folder.mkdir()
        (folder / 'private.sqlite').write_text('private')
        with self.assertRaises(ValueError):
            write_public_export(self.conn, folder)
        self.assertFalse((folder / 'index.html').exists())


if __name__ == '__main__':
    unittest.main()
