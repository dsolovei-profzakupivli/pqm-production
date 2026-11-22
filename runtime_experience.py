"""Bounded ownership for existing contract searches; no database or HTTP policy."""
from collections import deque
import logging
import threading
import uuid

LOG = logging.getLogger(__name__)


class ExperienceQueue:
    def __init__(self, executor, handler, *, limit=128, batch=32, workers=2,
                 retry_limit=2, retry_delay=60, timer_factory=threading.Timer,
                 pending=None):
        if min(limit, batch, workers) < 1:
            raise ValueError('Positive queue limits required')
        self.executor, self.handler = executor, handler
        self.limit, self.batch, self.workers = limit, batch, workers
        self.retry_limit, self.retry_delay = retry_limit, retry_delay
        self.timer_factory = timer_factory
        self.epoch = uuid.uuid4().hex  # Baseline retry budgets reset on process restart.
        self.pending = pending if pending is not None else set()
        self._condition = threading.Condition()
        self._records = {}
        self._ready = deque()
        self._waiters = deque()
        self._pumps = 0
        self._closed = False
        self._dispatch_error = False
        self.peak_owned = self.peak_pumps = self.peak_waiting = 0

    def owns(self, sid):
        with self._condition:
            return sid in self._records

    def restore_attempts(self, sid, state):
        """Use existing result JSON as bounded-RAM process-lifetime bookkeeping."""
        if not isinstance(state, dict) or state.get('epoch') != self.epoch:
            return
        attempts = state.get('attempts')
        if type(attempts) is not int or not 0 <= attempts <= self.retry_limit:
            attempts = self.retry_limit
        with self._condition:
            if sid in self._records:
                record = self._records[sid]
                record['attempts'] = max(record['attempts'], attempts)

    def result_retry_state(self, sid, unavailable):
        with self._condition:
            record = self._records.get(sid)
            if record is None:
                return None
            attempts = min(record['attempts'] + 1, self.retry_limit) if unavailable else 0
            return {'epoch': self.epoch, 'attempts': attempts}

    def enqueue(self, identifiers):
        """Backpressure outside DB transactions; never silently drop an ID.

        Callers retain their existing input, not a second unbounded executor
        queue. FIFO admission tickets give competing sync producers a turn.
        """
        admitted = 0
        self._kick()
        for identifier in identifiers:
            if not identifier:
                continue
            sid = str(identifier)
            ticket = object()
            with self._condition:
                if self._closed:
                    raise RuntimeError('Contract queue is closed')
                if sid in self._records:
                    continue
                self._waiters.append(ticket)
                try:
                    while True:
                        if self._closed:
                            raise RuntimeError('Contract queue is closed')
                        if self._dispatch_error:
                            raise RuntimeError('Contract dispatch failed; admitted IDs retained')
                        if sid in self._records:
                            break
                        if self._waiters[0] is ticket and len(self._records) < self.limit:
                            self._records[sid] = dict(active=False, retry=False,
                                                      due=False, attempts=0, token=None, timer=None)
                            self.pending.add(sid)
                            self._ready.append(sid)
                            self.peak_owned = max(self.peak_owned, len(self._records))
                            admitted += 1
                            break
                        self._condition.wait()
                finally:
                    self._waiters.remove(ticket)
                    self._condition.notify_all()
            self._kick()
        return admitted

    def _kick(self):
        with self._condition:
            if self._closed:
                return
            count = min(self.workers - self._pumps, len(self._ready))
            self._pumps += count
            self.peak_pumps = max(self.peak_pumps, self._pumps)
        for index in range(count):
            try:
                self.executor.submit(self._pump)
                with self._condition:
                    self._dispatch_error = False
            except BaseException:
                with self._condition:
                    self._pumps -= count - index
                    self._dispatch_error = True
                    self._condition.notify_all()
                # Retain ready ownership for an explicit later admission/restart.
                # Do not spin against a broken executor or pretend dispatch succeeded.
                raise

    def _pump(self):
        try:
            for _ in range(self.batch):
                with self._condition:
                    if self._closed or not self._ready:
                        return
                    sid = self._ready.popleft()
                    record = self._records[sid]
                    record['active'] = True
                try:
                    self.handler(sid)
                except Exception:
                    LOG.exception('Contract queue handler failed submission=%s', sid)
                finally:
                    with self._condition:
                        record = self._records[sid]
                        record['active'] = False
                        if record['retry'] and not self._closed:
                            if record['due']:
                                record.update(retry=False, due=False)
                                self._ready.append(sid)
                        else:
                            self._records.pop(sid)
                            self.pending.discard(sid)
                        self._condition.notify_all()
        finally:
            with self._condition:
                self._pumps -= 1
                self._condition.notify_all()
            try:
                self._kick()
            except Exception:
                LOG.exception('Contract queue dispatch failed; ready IDs retained')

    def retry(self, sid):
        with self._condition:
            record = self._records.get(sid)
            if self._closed or record is None or not record['active']:
                return False
            if record['retry']:
                return True
            if record['attempts'] >= self.retry_limit:
                return False
            token = object()
            record.update(attempts=record['attempts']+1, retry=True, due=False, token=token)
            self.peak_waiting = max(self.peak_waiting,
                                    sum(item['retry'] for item in self._records.values()))

        def ready():
            with self._condition:
                current = self._records.get(sid)
                if self._closed or current is None or current['token'] is not token or not current['retry']:
                    return
                current.update(timer=None, token=None, due=True)
                if not current['active']:
                    current.update(retry=False, due=False)
                    self._ready.append(sid)
                self._condition.notify_all()
            try:
                self._kick()
            except Exception:
                LOG.exception('Contract retry dispatch failed; ready ID retained')

        try:
            timer = self.timer_factory(self.retry_delay, ready)
            timer.daemon = True
            with self._condition:
                if self._closed:
                    return False
                record['timer'] = timer
            timer.start()
        except Exception:
            LOG.exception('Contract retry timer failed; reserved retry retained')
            ready()
        return True

    def snapshot(self):
        with self._condition:
            return dict(owned=len(self._records), ready=len(self._ready),
                        active=sum(item['active'] for item in self._records.values()),
                        waiting=sum(item['retry'] for item in self._records.values()),
                        timers=sum(item['timer'] is not None for item in self._records.values()),
                        pumps=self._pumps, producers=len(self._waiters), closed=self._closed,
                        dispatch_failed=self._dispatch_error,
                        peak_owned=self.peak_owned, peak_pumps=self.peak_pumps,
                        peak_waiting=self.peak_waiting)

    def close(self):
        """Release waiting state; running handler retains its ownership until exit."""
        with self._condition:
            self._closed = True
            timers = [item['timer'] for item in self._records.values() if item['timer'] is not None]
            for sid in list(self._records):
                if not self._records[sid]['active']:
                    self._records.pop(sid)
                    self.pending.discard(sid)
            self._ready.clear()
            self._condition.notify_all()
        for timer in timers:
            timer.cancel()
