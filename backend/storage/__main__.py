"""Offline inspection and retry/rebuild of the derived vector index."""
import argparse
import json

from backend.config import Settings
from backend.storage.memory import make_memory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['reconcile', 'history'])
    parser.add_argument('--session-id')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--reindex', action='store_true', help='Mark all SQLite messages pending before rebuilding')
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error('--limit must be between 1 and 10000')
    if args.command == 'history' and not args.session_id:
        parser.error('history requires --session-id')
    memory = make_memory(Settings())
    if args.command == 'history':
        print(json.dumps(memory.messages.history(args.session_id, args.limit), indent=2))
    else:
        if args.reindex:
            memory.messages.reset_index()
        count = memory.reconcile(args.session_id, args.limit)
        remaining = bool(memory.messages.pending(args.session_id, 1))
        print(json.dumps({'indexed': count, 'pending_remaining': remaining}))
        return 1 if remaining else 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
