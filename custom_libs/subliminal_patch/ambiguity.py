"""Cached TMDB title-collision checks. No application imports or credential logging."""
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

log = logging.getLogger(__name__)
_lock = threading.RLock()
VERSION = 2
TTL = 30 * 86400
RETRY = 3600


def data_dir():
    """Follow Bazarr's config directory without parsing CLI arguments on import."""
    explicit = os.environ.get('BAZARR_CONFIG_DIR')
    if explicit:
        return Path(explicit)
    for module_name in ('app.get_args', 'bazarr.app.get_args'):
        module = sys.modules.get(module_name)
        args = getattr(module, 'args', None)
        if getattr(args, 'config_dir', None):
            return Path(args.config_dir)
    return Path(__file__).resolve().parents[2] / 'data'


def normalize(title):
    title = unicodedata.normalize('NFKC', title).casefold()
    # Apostrophes do not split words; other punctuation separates words.
    title = re.sub(r"['’‘]", '', title)
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in title).split())


def title_names(detail, aliases=None):
    names = {detail.get(k) for k in ('name', 'original_name', 'title', 'original_title')}
    # Focus alternate names on English, Croatian and the production's countries.
    countries = {'US', 'GB', 'HR'} | set(detail.get('origin_country', []))
    countries |= {c['iso_3166_1'] for c in detail.get('production_countries', [])}
    for entry in (aliases or {}).get('results', (aliases or {}).get('titles', [])):
        if entry.get('type', '').casefold() in ('abbreviation', 'acronym'):
            continue
        if entry.get('iso_3166_1') in countries:
            names.add(entry.get('title'))
    return {n.strip() for n in names if isinstance(n, str) and n.strip()}


class LookupIncomplete(Exception):
    pass


class Detector:
    def __init__(self, cache_path=None, key_path=None, fetch=None):
        self.cache_path = Path(cache_path or os.environ.get('BAZARR_AMBIGUITY_CACHE', str(data_dir() / 'ambiguity.sqlite')))
        self.key_path = Path(key_path or os.environ.get('BAZARR_TMDB_KEY_FILE', str(data_dir() / 'tmdb-api-key')))
        self.fetch_override = fetch

    def db(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.cache_path, timeout=30)
        c.execute('CREATE TABLE IF NOT EXISTS checks (key TEXT PRIMARY KEY, checked REAL, data TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, checked REAL, data TEXT)')
        return c

    def get(self, path, **params):
        if self.fetch_override:
            return self.fetch_override(path, **params)
        params = {'language': 'en-US', **params}
        key = path + '?' + urlencode(sorted(params.items()))
        with self.db() as c:
            row = c.execute('SELECT checked,data FROM responses WHERE key=?', (key,)).fetchone()
        if row and time.time() - row[0] < TTL:
            return json.loads(row[1])
        for attempt in range(3):
            try:
                secret = self.key_path.read_text().strip()
                url = 'https://api.themoviedb.org/3/' + path + '?' + urlencode({**params, 'api_key': secret})
                with urlopen(url, timeout=15) as response:
                    data = json.load(response)
                if not isinstance(data, dict) or data.get('success') is False:
                    raise LookupIncomplete('invalid TMDB response')
                break
            except Exception as exc:
                retryable = isinstance(exc, (URLError, TimeoutError))
                if isinstance(exc, HTTPError):
                    retryable = exc.code == 429 or exc.code >= 500
                if retryable and attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                # Never stringify network exceptions: URLs can contain credentials.
                label = type(exc).__name__
                if isinstance(exc, HTTPError):
                    label += ' ' + str(exc.code)
                raise LookupIncomplete('TMDB request failed (' + label + ')') from None
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO responses VALUES (?,?,?)', (key, time.time(), json.dumps(data)))
        time.sleep(0.12)
        return data

    def check(self, kind, imdb_id, names=(), force=False):
        names = sorted({n.strip() for n in names if isinstance(n, str) and n.strip()})
        key = json.dumps([VERSION, kind, imdb_id, names], ensure_ascii=False)
        with _lock:
            with self.db() as c:
                row = c.execute('SELECT checked,data FROM checks WHERE key=?', (key,)).fetchone()
            previous = json.loads(row[1]) if row else None
            if not force and row and time.time()-row[0] < (RETRY if previous.get('lookup_failed') else TTL):
                return previous
            try:
                result = self.lookup(kind, imdb_id, names)
            except Exception as exc:
                # A failed refresh cannot downgrade a previously ambiguous title.
                result = dict(previous or {'status': 'unknown', 'collisions': []})
                result.update(lookup_failed=True, error=str(exc) if isinstance(exc, LookupIncomplete) else type(exc).__name__)
                if previous:
                    result['previous_checked_at'] = previous.get('checked_at')
            result.update(kind=kind, imdb_id=imdb_id, library_names=names, checked_at=time.time())
            with self.db() as c:
                c.execute('INSERT OR REPLACE INTO checks VALUES (?,?,?)', (key, time.time(), json.dumps(result)))
            log.info('Title ambiguity: kind=%s imdb=%s status=%s collisions=%s lookup_failed=%s',
                     kind, imdb_id, result['status'], len(result['collisions']), result.get('lookup_failed', False))
            return result

    def lookup(self, kind, imdb_id, names):
        if kind not in ('tv', 'movie') or not imdb_id:
            raise LookupIncomplete('missing library identity')
        found = self.get('find/' + imdb_id, external_source='imdb_id').get(kind + '_results', [])
        if len(found) != 1:
            raise LookupIncomplete('library identity not uniquely resolved')
        target_id = found[0]['id']
        detail = self.get(f'{kind}/{target_id}')
        aliases = self.get(f'{kind}/{target_id}/alternative_titles')
        target_names = title_names(detail, aliases) | set(names)
        normalized = {normalize(n) for n in target_names}
        if not normalized or '' in normalized:
            raise LookupIncomplete('missing title')
        deadline = time.monotonic() + 90
        seen = {target_id}
        collisions = []
        errors = []
        # Search all selected names, without year constraints or popularity cutoffs.
        primary = detail.get("name") or detail.get("title")
        for name in sorted(target_names, key=lambda n: (n != primary, n)):
            try:
                page = 1
                while True:
                    data = self.get('search/' + kind, query=name, page=page, include_adult='true')
                    if 'results' not in data or 'total_pages' not in data:
                        raise LookupIncomplete('incomplete search response')
                    for candidate in data['results']:
                        cid = candidate['id']
                        if cid in seen:
                            continue
                        if len(seen) >= 80 or time.monotonic() > deadline:
                            raise LookupIncomplete('candidate lookup budget exhausted')
                        seen.add(cid)
                        candidate_detail = self.get(f'{kind}/{cid}')
                        candidate_aliases = self.get(f'{kind}/{cid}/alternative_titles')
                        overlap = normalized & {normalize(n) for n in title_names(candidate_detail, candidate_aliases)}
                        if overlap:
                            collisions.append({'tmdb_id': cid,
                                'title': candidate_detail.get('name') or candidate_detail.get('title'),
                                'date': candidate_detail.get('first_air_date') or candidate_detail.get('release_date'),
                                'shared_titles': sorted(overlap)})
                    if page >= data['total_pages']:
                        break
                    if page >= 10:
                        raise LookupIncomplete('search pagination budget exhausted')
                    page += 1
            except Exception as exc:
                errors.append(type(exc).__name__)
            # A proven collision is sufficient; do not enumerate every competing title.
            if collisions:
                break
        if not collisions and errors:
            raise LookupIncomplete('not all searches completed')
        return {'status': 'ambiguous' if collisions else 'clear', 'tmdb_id': target_id,
                'title': detail.get('name') or detail.get('title'),
                'searched_names': sorted(target_names), 'collisions': collisions,
                'lookup_failed': False}


def check_video(video):
    from subliminal.video import Episode
    is_episode = isinstance(video, Episode)
    names = [getattr(video, 'series' if is_episode else 'title', None)]
    names += list(getattr(video, 'alternative_series' if is_episode else 'alternative_titles', None) or [])
    return Detector().check('tv' if is_episode else 'movie',
        getattr(video, 'series_imdb_id' if is_episode else 'imdb_id', None), names)


def requires_identity(video):
    result = check_video(video)
    # Unknown/error is not evidence that a title is unique, including stale clear results.
    return result['status'] != 'clear' or result.get('lookup_failed', False)
