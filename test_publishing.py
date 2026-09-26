import json
import sqlite3
import subprocess
import tempfile
import threading
import functools
import http.server
import unittest
from pathlib import Path
from urllib.request import urlopen

from publishing import GitPublisher, Publisher, PublishError, SCHEMA, PUBLIC_PATH, enqueue
from public_export import public_state, check_public_state, write_public_state


def git(cwd, *args):
    result = subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com', *args], cwd=cwd, capture_output=True, check=True)
    return result.stdout.decode().strip()


class PublishingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'instance'
        self.data.mkdir()
        conn = sqlite3.connect(self.data / 'game.sqlite')
        conn.executescript('''
          CREATE TABLE players(id INTEGER,name TEXT,color TEXT);
          CREATE TABLE shots(id INTEGER,tower TEXT,player INTEGER,cell INTEGER,hit INTEGER,created TEXT);
          CREATE TABLE ships(cells TEXT);
          INSERT INTO players VALUES(1,'Alex','#f87171');
          INSERT INTO shots VALUES(1,'South',1,0,1,'2026-09-26 01:00:00');
          INSERT INTO ships VALUES('0,1,2,3,4');
        ''' + SCHEMA)
        conn.close()

    def connect(self):
        conn = sqlite3.connect(self.data / 'game.sqlite')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        return conn

    def test_reject_unshot_and_extra_private_fields(self):
        conn = self.connect()
        payload = public_state(conn)
        check_public_state(conn, payload)
        bad = json.loads(json.dumps(payload))
        bad['towers'][0]['shots'][0]['cell'] = 1  # An unshot ship location.
        with self.assertRaises(ValueError):
            check_public_state(conn, bad)
        for field in ('ships', 'secret', 'turn', 'password'):
            bad = json.loads(json.dumps(payload))
            bad['towers'][0][field] = [1, 2, 3, 4]
            with self.assertRaises(ValueError):
                check_public_state(conn, bad)

    def test_docs_viewer_without_flask_under_repo_subpath(self):
        folder = self.root / 'OneOnOneBattleship'
        folder.mkdir()
        source = Path(__file__).parent / 'docs'
        for name in ('index.html', 'viewer.js', 'viewer.css'):
            (folder / name).write_bytes((source / name).read_bytes())
        conn = self.connect()
        write_public_state(conn, folder / 'public-state.json')
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1',0), functools.partial(Quiet,directory=str(self.root)))
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}/OneOnOneBattleship/'
            for name in ('index.html', 'viewer.js', 'viewer.css', 'public-state.json'):
                with urlopen(base + name) as response:
                    content = response.read().decode('utf-8')
                for private in ('instance/', '/api/', 'password', 'sunk_ships'):
                    self.assertNotIn(private, content)
                if name == 'public-state.json':
                    check_public_state(conn,json.loads(content))
                if name == 'viewer.js':
                    self.assertIn("fetch('./public-state.json'", content)
                    self.assertNotIn('innerHTML',content)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_failure_and_restart_retry_preserve_game(self):
        class Offline:
            def publish_files(self, files, message):
                raise PublishError('Offline; retry publishing.')
        class Online:
            def publish_files(self, files, message):
                self.files = files
                return 'Published.'
        conn = self.connect()
        enqueue(conn)
        conn.commit()
        worker = Publisher(self.root, self.data, Offline())
        worker.process_pending()
        self.assertEqual(conn.execute('SELECT status FROM publication').fetchone()[0], 'failed')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM shots').fetchone()[0], 1)
        self.assertTrue((self.root / PUBLIC_PATH).exists())
        online = Online()
        Publisher(self.root, self.data, online).process_pending()
        row = conn.execute('SELECT * FROM publication').fetchone()
        self.assertEqual(row['requested'], row['published'])
        self.assertEqual(row['status'], 'published')
        self.assertEqual(set(online.files), {PUBLIC_PATH})
        check_public_state(conn, json.loads(online.files[PUBLIC_PATH]))

    def test_network_work_does_not_lock_game_and_coalesces_new_jobs(self):
        entered, release = threading.Event(), threading.Event()
        class Slow:
            calls = 0
            def publish_files(self, files, message):
                self.calls += 1
                entered.set()
                if not release.wait(5):
                    raise PublishError('Test timed out')
                return 'Published.'
        conn = self.connect()
        enqueue(conn)
        conn.commit()
        slow = Slow()
        worker = Publisher(self.root, self.data, slow)
        thread = threading.Thread(target=worker.process_pending)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            # This write succeeds while Git is blocked, and the new job is not lost.
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("INSERT INTO shots VALUES(2,'South',1,63,0,'2026-09-26 01:01:00')")
            enqueue(conn)
            conn.commit()
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(slow.calls, 2)
        self.assertEqual(conn.execute('SELECT published FROM publication').fetchone()[0], 2)

    def test_git_push_changes_only_public_state_leaves_user_index_alone(self):
        remote = self.root / 'remote.git'
        git(self.root, 'init', '--bare', str(remote))
        work = self.root / 'work'
        work.mkdir()
        git(work, 'init', '-b', 'main')
        (work / 'README.md').write_text('Initial repo')
        git(work, 'add', 'README.md')
        git(work, 'commit', '-m', 'Initial commit')
        git(work, 'push', str(remote), 'main')
        # Unrelated staged secret must not appear in the publisher commit or change locally.
        (work / 'private.txt').write_text('SECRET_NEVER_PUBLISH')
        git(work, 'add', 'private.txt')
        before = git(work, 'diff', '--cached', '--name-only')
        publisher = GitPublisher(self.data, str(remote))
        publisher.publish_files({PUBLIC_PATH: b'{"version":1,"towers":[]}\n'}, 'Public state')
        changed = git(self.root, '--git-dir='+str(remote), 'diff-tree', '--no-commit-id', '--name-only', '-r', 'main')
        self.assertEqual(changed, PUBLIC_PATH)
        self.assertEqual(git(work, 'diff', '--cached', '--name-only'), before)
        self.assertNotIn('private.txt', git(self.root, '--git-dir='+str(remote), 'ls-tree', '-r', '--name-only', 'main'))
        with self.assertRaises(PublishError):
            publisher.publish_files({'instance/game.sqlite': b'private'}, 'Must fail')
        self.assertIn('Already up to date', publisher.publish_files({PUBLIC_PATH: b'{"version":1,"towers":[]}\n'}, 'Same state'))
        # Remote changes made by someone else survive the next public-state update.
        other = GitPublisher(self.root / 'other-publisher', str(remote))
        other._publish({'README.md': b'Remote change'}, 'Remote change')
        publisher.publish_files({PUBLIC_PATH: b'{"version":1,"towers":[],"test":true}\n'}, 'New state')
        self.assertEqual(git(self.root,'--git-dir='+str(remote),'show','main:README.md'),'Remote change')
        self.assertEqual(git(self.root,'--git-dir='+str(remote),'diff-tree','--no-commit-id','--name-only','-r','main'),PUBLIC_PATH)


if __name__ == '__main__':
    unittest.main()
