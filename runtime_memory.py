"""Bound transient runtime state without changing persisted verification results."""
from collections import OrderedDict
import heapq
import itertools
import json
import sqlite3
import threading
import time


class ClosingConnection(sqlite3.Connection):
    """Keep SQLite commit/rollback semantics, close at the outer context exit."""

    def __enter__(self):
        result = super().__enter__()
        self._context_depth = getattr(self, '_context_depth', 0) + 1
        return result

    def __exit__(self, *exception):
        try:
            return super().__exit__(*exception)
        finally:
            self._context_depth = max(0, getattr(self, '_context_depth', 1) - 1)
            if not self._context_depth:
                self.close()


def payload_bytes(value):
    # A serialization budget supplements the entry limit; not an RSS estimate.
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


class ContractCache:
    def __init__(self, max_entries=1024, max_bytes=16 * 1024 * 1024, clock=time.monotonic):
        self.max_entries, self.max_bytes, self.clock = max_entries, max_bytes, clock
        self._entries = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()
        self._expiry = []
        self._sequence = itertools.count()

    def _remove(self, key):
        self._bytes -= self._entries.pop(key)[2]

    def _prune(self):
        now = self.clock()
        while self._expiry and self._expiry[0][0] <= now:
            expires, _, key = heapq.heappop(self._expiry)
            entry = self._entries.get(key)
            if entry is not None and entry[1] == expires:
                self._remove(key)

    def get(self, key, default=None):
        with self._lock:
            self._prune()
            item = self._entries.get(key)
            if item is None:
                return default
            self._entries.move_to_end(key)
            return item[0]

    def put(self, key, value, ttl):
        size = payload_bytes(value) + payload_bytes(key)
        with self._lock:
            self._prune()
            if key in self._entries:
                self._remove(key)
            if size > self.max_bytes:
                return  # Return the search result normally, just do not cache it.
            expires = self.clock() + ttl
            self._entries[key] = (value, expires, size)
            heapq.heappush(self._expiry, (expires, next(self._sequence), key))
            self._bytes += size
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                self._remove(next(iter(self._entries)))
            # Overwrites/evictions leave tombstones; bound that structure too.
            if len(self._expiry) > max(1, 2 * self.max_entries):
                self._expiry = [(entry[1], next(self._sequence), key)
                                for key, entry in self._entries.items()]
                heapq.heapify(self._expiry)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._expiry.clear()
            self._bytes = 0

    def __len__(self):
        with self._lock:
            self._prune()
            return len(self._entries)


class DocumentJobs:
    """Running jobs never evict; terminal RAM entries contain metadata only."""
    def __init__(self, max_active=16, max_completed=256, ttl=3600,
                 max_bytes=16 * 1024 * 1024, clock=time.monotonic):
        self.max_active = max_active
        self._active = {}
        self._completed = ContractCache(max_completed, max_bytes, clock)
        self.ttl = ttl
        self._lock = threading.RLock()

    def start(self, job_id, submission_id):
        with self._lock:
            if len(self._active) >= self.max_active:
                return False
            self._active[job_id] = {'job_id': job_id, 'submission_id': submission_id, 'status': 'running'}
            return True

    def finish(self, job_id, update):
        with self._lock:
            job = self._active.pop(job_id, None)
            if job is not None:
                # Completed evidence lives only in SQLite, never in the job cache.
                metadata = {key: value for key, value in update.items() if key != 'result'}
                self._completed.put(job_id, {**job, **metadata}, self.ttl)

    def get(self, job_id):
        with self._lock:
            job = self._active.get(job_id) or self._completed.get(job_id)
            return dict(job) if job else None

    def __len__(self):
        with self._lock:
            return len(self._active) + len(self._completed)
