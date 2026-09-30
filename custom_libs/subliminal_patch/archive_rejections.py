"""Remember rejected archive choices per candidate and target media, for 7 days."""
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import time

logger = logging.getLogger(__name__)


def rejection_path(subtitle):
    video = getattr(subtitle, '_identity_video', None)
    if video is None:
        return None
    path = Path(getattr(video, 'original_path', None) or video.name)
    st = path.stat()
    candidate = [1, str(path), st.st_size, st.st_mtime_ns,
                 getattr(video, 'season', None), getattr(video, 'episode', None), getattr(video, 'title', None),
                 subtitle.provider_name, str(subtitle.id), str(subtitle.language)]
    digest = hashlib.sha256(json.dumps(candidate).encode()).hexdigest()
    root = Path(os.environ.get('BAZARR_ARCHIVE_CACHE',
                str(Path(os.environ.get('BAZARR_CONFIG_DIR', '/config')) / 'archive-identity')))
    root.mkdir(parents=True, exist_ok=True)
    return root / (digest + '.json')


def previous_rejection(subtitle):
    if os.environ.get('BAZARR_ARCHIVE_GATE', 'true').lower() == 'false':
        return None
    try:
        p = rejection_path(subtitle)
        if p and p.exists():
            d = json.loads(p.read_text())
            if time.time() - d['time'] < 7 * 86400:
                return d['reason']
    except (OSError, ValueError, KeyError):
        logger.warning('Archive gate: unable to read candidate rejection cache')
    return None


def remember_rejection(subtitle, reason):
    temporary = None
    try:
        p = rejection_path(subtitle)
        if p:
            with tempfile.NamedTemporaryFile(mode='w', dir=p.parent, delete=False) as f:
                json.dump(dict(time=time.time(), reason=reason,
                          member=getattr(subtitle, 'identity_archive_member', None)), f)
                temporary = Path(f.name)
            temporary.replace(p)
    except (OSError, ValueError):
        logger.warning('Archive gate: unable to save candidate rejection cache')
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
