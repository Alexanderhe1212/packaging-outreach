"""Append-only measured observations; instrumentation must not change research outcomes."""
import functools,time

def measured(stage):
 def decorate(fn):
  @functools.wraps(fn)
  def call(*args,**kwargs):
   start=time.perf_counter();status='completed';reason='COMPLETED';result=None
   try:
    result=fn(*args,**kwargs);return result
   except Exception as exc:
    status='failed';reason=type(exc).__name__;raise
   finally:
    try:
     import customer_store
     lid=(result.get('customer') or {}).get('id') if isinstance(result,dict) else None
     with customer_store.connection() as db:
      db.execute('INSERT INTO lead_events(lead_id,stage,status,reason_code,duration_ms,account,created_at) VALUES(?,?,?,?,?,?,?)',(lid,stage,status,reason,(time.perf_counter()-start)*1000,None,time.time()))
    except Exception:pass  # Observability is never permission to block or repeat work.
  return call
 return decorate
