"""Durable, asynchronous public-state publishing with a private Git index."""
import os
import sqlite3
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

from public_export import write_public_state

PUBLIC_PATH = 'docs/public-state.json'
REMOTE = 'https://github.com/IanKelley05/OneOnOneBattleship.git'
BRANCH = 'main'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS publication (
 id INTEGER PRIMARY KEY CHECK(id=1), requested INTEGER NOT NULL DEFAULT 0,
 published INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'idle',
 message TEXT NOT NULL DEFAULT 'No publication requested yet.', updated TEXT DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO publication(id) VALUES(1);
'''


def enqueue(conn):
    """Persist this in the same transaction as the final shot."""
    conn.execute("UPDATE publication SET requested=requested+1,status='queued',message='Saved locally; waiting to publish.',updated=CURRENT_TIMESTAMP WHERE id=1")


class PublishError(Exception):
    pass


class GitPublisher:
    def __init__(self, data, remote=REMOTE, branch=BRANCH):
        self.git_dir = Path(data) / 'publisher.git'
        self.remote = remote
        self.branch = branch

    def git(self, *args, input=None):
        env = os.environ.copy()
        # Do not inherit an external index/worktree or interactive credential UI.
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES'):
            env.pop(key, None)
        env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never',
                   GIT_INDEX_FILE=str(self.git_dir.resolve() / 'public-index'))
        command = ['git', '-c', 'core.hooksPath=' + str(self.git_dir.resolve() / 'disabled-hooks'),
                   '-c', 'commit.gpgSign=false', '-c', 'credential.interactive=false',
                   '--git-dir=' + str(self.git_dir.resolve()), *args]
        try:
            result = subprocess.run(command, input=input, capture_output=True, env=env,
                                    timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PublishError('Git is unavailable or timed out. Your game is saved; retry publishing.') from error
        if result.returncode:
            # Git errors may contain credential URLs: never expose stderr to the UI.
            raise PublishError(f'Git {args[0]} failed. Check connection and Git credentials, then retry. Your game is saved.')
        return result.stdout.decode('utf-8').strip()

    def publish_files(self, files, message):
        """A fresh remote tree plus explicitly supplied public files; never git add."""
        if set(files) - {PUBLIC_PATH}:
            raise PublishError('Automatic publishing allows only docs/public-state.json.')
        return self._publish(files, message)

    def _publish(self, files, message):
        self.git_dir.parent.mkdir(parents=True, exist_ok=True)
        if not self.git_dir.exists():
            self.git('init', '--bare', str(self.git_dir.resolve()))
        self.git('fetch', '--no-tags', self.remote, f'refs/heads/{self.branch}')
        parent = self.git('rev-parse', 'FETCH_HEAD')
        self.git('read-tree', parent)
        for path, content in files.items():
            blob = self.git('hash-object', '-w', '--stdin', input=content)
            self.git('update-index', '--add', '--cacheinfo', f'100644,{blob},{path}')
        tree = self.git('write-tree')
        if tree == self.git('rev-parse', parent + '^{tree}'):
            return 'Already up to date on GitHub.'
        commit = self.git('-c', 'user.name=Battleship Publisher', '-c', 'user.email=battleship-publisher@users.noreply.github.com',
                          'commit-tree', tree, '-p', parent, input=message.encode('utf-8'))
        changed = set(self.git('diff-tree', '--no-commit-id', '--name-only', '-r', commit).splitlines())
        if changed != set(files) and not changed.issubset(files):
            raise PublishError('Refusing to publish unexpected paths.')
        self.git('push', self.remote, f'{commit}:refs/heads/{self.branch}')
        return 'Public state pushed to GitHub. The viewer updates when GitHub Pages is enabled.'


class Publisher:
    def __init__(self, root, data, git=None):
        self.root, self.data = Path(root), Path(data)
        self.git = git or GitPublisher(data)
        self.event = threading.Event()
        self.thread = None
        self.lock = threading.Lock()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.data / 'game.sqlite', timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def wake(self):
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.run, name='public-publisher', daemon=True)
                self.thread.start()
        self.event.set()

    def run(self):
        while True:
            self.event.wait()
            self.event.clear()
            self.process_pending()

    def process_pending(self):
        """Coalesce queued turns. Network work never holds a SQLite transaction."""
        while True:
            revision = None
            try:
                with self.connect() as conn:
                    row = conn.execute('SELECT * FROM publication WHERE id=1').fetchone()
                    if row['requested'] <= row['published']:
                        return
                    revision = row['requested']
                    conn.execute("UPDATE publication SET status='publishing',message='Game saved. Publishing in background...',updated=CURRENT_TIMESTAMP WHERE id=1")
                with self.connect() as conn:
                    conn.execute('BEGIN')
                    content = write_public_state(conn, self.root / PUBLIC_PATH)
                    conn.rollback()
                message = self.git.publish_files({PUBLIC_PATH: content}, 'Update public Battleship boards\n')
                with self.connect() as conn:
                    conn.execute("UPDATE publication SET published=?,status=CASE WHEN requested>? THEN 'queued' ELSE 'published' END,message=?,updated=CURRENT_TIMESTAMP WHERE id=1", (revision, revision, message))
            except Exception as error:
                message = str(error) if isinstance(error, PublishError) else 'Public export or publishing failed. Your game is saved; retry from Organizer.'
                with self.connect() as conn:
                    conn.execute("UPDATE publication SET status='failed',message=?,updated=CURRENT_TIMESTAMP WHERE id=1", (message,))
                return
