"""导入旧系统的"已联系 / 退订 / 退信 / 回复"名单，避免重复开发。只读打开旧库，不做任何修改。

支持：旧版 GUKA/MTT workflow.sqlite3、known-constraints.json，以及任意 CSV（含 email 或 website 列）。
"""
import csv
import json
import sqlite3
from pathlib import Path

from . import config, store, web


def import_workflow_db(path, account=''):
    c = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    n = {'contacted': 0, 'stops': 0}
    try:
        for r in c.execute("SELECT a.recipient,a.result,j.payload FROM attempts a LEFT JOIN jobs j ON j.id=a.job_id "
                           "WHERE a.result IN ('accepted','received_after_unknown','unknown','in_progress')"):
            try:
                p = json.loads(r['payload'] or '{}')
            except ValueError:
                p = {}
            if p.get('test_kind'):
                continue
            store.suppress(r['recipient'], 'legacy_contacted', account, 'old app ' + r['result'])
            if p.get('company_url'):
                store.suppress(web.host(p['company_url']), 'legacy_contacted', account, r['recipient'])
            n['contacted'] += 1
        for r in c.execute("SELECT recipient,kind,evidence FROM events WHERE kind IN ('unsubscribe','hard_reject','unknown','reply')"):
            store.suppress(r['recipient'], r['kind'], account, (r['evidence'] or '')[:200])
            n['stops'] += 1
    finally:
        c.close()
    return n


def import_constraints(path):
    n = 0
    for rec in json.loads(Path(path).read_text(encoding='utf-8')):
        store.suppress(rec['recipient'], rec.get('kind', 'unknown'), '', rec.get('evidence', ''))
        n += 1
    return n


def import_csv(text, kind='legacy_contacted'):
    """Rows with an email and/or website column become do-not-contact entries."""
    n = 0
    for row in csv.DictReader(text.splitlines()):
        row = {k.strip().lower(): (v or '').strip() for k, v in row.items() if k}
        email = row.get('email') or row.get('邮箱') or ''
        site = row.get('website') or row.get('domain') or row.get('官网') or ''
        if email:
            store.suppress(email, kind, '', 'csv')
            n += 1
        if site:
            store.suppress(web.host(site), kind, '', 'csv')
    return n


def run(force=False):
    if store.get('legacy_imported') and not force:
        return store.get('legacy_imported')
    cfg = config.load()
    report = {'contacted': 0, 'stops': 0, 'sources': [], 'errors': []}
    for item in cfg.get('legacy', {}).get('databases', []):
        path, account = (item['path'], item.get('account', '')) if isinstance(item, dict) else (item, '')
        try:
            if Path(path).exists():
                r = import_workflow_db(path, account)
                report['contacted'] += r['contacted']
                report['stops'] += r['stops']
                report['sources'].append(path)
        except Exception as e:  # iCloud placeholder / locked file: retry next start
            report['errors'].append('%s: %s' % (path, type(e).__name__))
    for path in cfg.get('legacy', {}).get('constraints', []):
        try:
            report['stops'] += import_constraints(path)
        except Exception:
            pass
    if report['sources'] and not report['errors']:
        store.put('legacy_imported', report)
    return report
