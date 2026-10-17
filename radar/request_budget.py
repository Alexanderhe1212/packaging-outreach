"""Thread-local request scope: nested readers cannot extend caller deadlines."""
import time
from contextlib import contextmanager
from browser_transport import LOCAL,check_budget

class _AnyCancel:
    def __init__(self,*events):self.events=events
    def is_set(self):return any(e.is_set() if hasattr(e,'is_set') else e() for e in self.events if e)

@contextmanager
def request_scope(seconds=None,cancel=None,deadline=None):
    previous_deadline=getattr(LOCAL,'deadline',None)
    previous_cancel=getattr(LOCAL,'cancel',None)
    limits=[d for d in [previous_deadline,deadline,time.monotonic()+max(0,float(seconds)) if seconds is not None else None] if d is not None]
    LOCAL.deadline=min(limits) if limits else None
    LOCAL.cancel=_AnyCancel(previous_cancel,cancel) if previous_cancel and cancel and previous_cancel is not cancel else cancel or previous_cancel
    try:
        check_budget();yield
    finally:
        LOCAL.deadline=previous_deadline;LOCAL.cancel=previous_cancel
