"""Run locally before publishing: python check_public_state.py."""
import json
import sqlite3
from pathlib import Path
from public_export import check_public_state


if __name__ == '__main__':
    root = Path(__file__).parent
    with sqlite3.connect((root / 'instance/game.sqlite').as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        check_public_state(conn, json.loads((root / 'docs/public-state.json').read_text(encoding='utf-8')))
    print('PASS: public state contains only recorded shot locations and allowed public player totals.')
