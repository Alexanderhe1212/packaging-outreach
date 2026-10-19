"""Measured pipeline runs; no prompts, credentials, recipient details or invented durations."""
import functools
import time
from . import store


def measured(stage):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(account, *args, **kwargs):
            previous = getattr(store._current_lead, 'run_id', None)
            started = time.time()
            run = store.x("INSERT INTO stage_runs(account,lead,stage,started,outcome) VALUES(?,?,?,?,?)",
                          (account['id'], getattr(store._current_lead, 'id', None), stage, started, 'running'))
            store._current_lead.run_id = run
            tick = time.monotonic()
            outcome, error = 'completed', ''
            try:
                return fn(account, *args, **kwargs)
            except Exception as exc:
                outcome, error = 'failed', type(exc).__name__
                from . import web
                if isinstance(web.transient_failure(exc), web.DeferredFetch):
                    outcome, error = 'deferred', 'DeferredFetch'
                raise
            finally:
                store._current_lead.run_id = previous
                store.x('UPDATE stage_runs SET finished=?,duration=?,outcome=?,error_type=? WHERE id=?',
                        (time.time(), time.monotonic()-tick, outcome, error, run))
        return wrapped
    return decorate
