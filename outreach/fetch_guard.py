"""Shared, persistent public-fetch pacing; never used for SMTP or AI calls."""
import contextlib
import random
import threading
import time


class DeferredFetch(Exception):
    def __init__(self, until):
        self.retry_at = until
        super().__init__('官网请求等待限流窗口结束')


class FetchGuard:
    def __init__(self, load=lambda: {}, save=lambda state: None, clock=time.time,
                 sleep=time.sleep, jitter=lambda: random.uniform(0, .25)):
        self.load, self.save = load, save
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.lock = threading.RLock()
        self.shared = threading.BoundedSemaphore(2)
        self.domains, self.next_request = {}, {}
        self.state = None

    def _state(self):
        if self.state is None:
            self.state = self.load() or {}
            self.state.setdefault('domains', {})
            self.state.setdefault('recent_429', {})
            if self.state.get('scope_version') != 2:
                # Narrow only the local aggregate circuit; never shorten a site's deadline.
                self.state['global_until'] = min(self.state.get('global_until', 0), self.clock() + 30)
                self.state['recent_429'] = {}
                self.state['scope_version'] = 2
                self.save(self.state)
        return self.state

    def wait_seconds(self, domain=None):
        with self.lock:
            state = self._state()
            # A burst on failed sites must not hold unrelated customer research.
            until = state.get('global_until', 0) if domain in state.get('burst_domains', []) else 0
            if domain:
                until = max(until, state['domains'].get(domain, {}).get('until', 0))
            return max(0, until - self.clock())

    def check(self, domain):
        wait = self.wait_seconds(domain)
        if wait:
            raise DeferredFetch(self.clock() + wait)

    @contextlib.contextmanager
    def request(self, domain):
        self.check(domain)
        with self.lock:
            gate = self.domains.setdefault(domain, threading.Lock())
        with gate:
            self.check(domain)
            delay = max(0, self.next_request.get(domain, 0) - self.clock())
            if delay:
                self.sleep(delay)
            with self.shared:
                self.check(domain)
                self.next_request[domain] = self.clock() + 1.0
                with self.lock:
                    state = self._state()
                    stats = state.setdefault('stats', {})
                    stats['requests'] = stats.get('requests', 0) + 1
                    stats['last_request_at'] = self.clock()
                    self.save(state)
                yield

    def failed(self, domain, code, retry_after=0):
        with self.lock:
            state = self._state()
            now = self.clock()
            old = state['domains'].get(domain, {})
            failures = min(old.get('failures', 0) + 1, 8)
            base = 300 if code == 429 else 60 if code == 503 else 30
            delay = max(retry_after, min(base * 2 ** (failures - 1), 3600) * (1 + self.jitter()))
            until = max(old.get('until', 0), now + delay)
            state['domains'][domain] = {'until': until, 'failures': failures}
            stats = state.setdefault('stats', {})
            key = str(code) if code is not None else 'transport'
            stats[key] = stats.get(key, 0) + 1
            recent = {d: t for d, t in state['recent_429'].items() if t >= now - 60}
            if code == 429:
                recent[domain] = now
                # Conservative burst circuit, not a claim of a shared upstream gateway.
                if len(recent) >= 5:
                    if state.get('global_until', 0) <= now:
                        state['global_until'] = now + 30
                        state['burst_domains'] = list(recent)
                    recent = {}
            state['recent_429'] = recent
            self.save(state)
            return until

    def succeeded(self, domain):
        with self.lock:
            state = self._state()
            stats = state.setdefault('stats', {})
            stats['success'] = stats.get('success', 0) + 1
            if domain in state['domains']:
                state['domains'].pop(domain)
            self.save(state)
