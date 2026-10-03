"""Bounded public-page cache, shared between accounts without hiding source age."""
import hashlib,json,threading,time
from pathlib import Path


class PageCache:
    def __init__(self, root, fetcher, ttl=900):
        self.root = Path(root) / 'page-cache'
        self.root.mkdir(parents=True, exist_ok=True)
        self.fetcher = fetcher
        self.ttl = max(0, min(float(ttl), 3600))
        self.locks = [threading.Lock() for _ in range(32)]

    def __call__(self, url, allowed):
        key = hashlib.sha256(json.dumps([url, sorted(allowed)]).encode()).hexdigest()
        path = self.root / (key + '.json')
        with self.locks[int(key[:4], 16) % len(self.locks)]:
            try:
                value = json.loads(path.read_text())
                if 0 <= time.time() - value['stored_at'] < self.ttl:
                    return value['page']
            except (OSError, ValueError, KeyError):
                pass
            page = self.fetcher(url, allowed)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps({'stored_at': time.time(), 'page': page}))
            temp.replace(path)
            return page
