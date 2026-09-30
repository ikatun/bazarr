"""Conservative selection of episode files, independently of provider scores."""
import re
import unicodedata

from guessit import guessit
from subliminal.video import Episode


EXTRA = re.compile(r"\b(?:extras?|bonus|interviews?|commentary|deleted[ ._-]+scenes?|"
                   r"making[ ._-]+of|behind[ ._-]+the[ ._-]+scenes|featurettes?)\b", re.I)


def title_key(text):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", text).lower())


def select_member(subtitle, archive):
    video = getattr(subtitle, '_identity_video', None)
    names = [n for n in archive.namelist()
             if n.lower().endswith(('.srt', '.sub', '.ssa', '.ass'))]
    candidates = []
    for name in names:
        guess = guessit(name, {'type': 'episode' if isinstance(video, Episode) else 'movie'})
        filename = name.replace('\\', '/').rsplit('/', 1)[-1]
        local_guess = guessit(filename, {'type': 'episode' if isinstance(video, Episode) else 'movie'})
        # An episode may itself be called "The Interview". Exclude labels in
        # directories, or unnumbered extras, rather than matching its title.
        directories, _, basename = name.replace('\\', '/').rpartition('/')
        if EXTRA.search(directories) or (EXTRA.search(basename) and not guess.get('episode')):
            continue
        lang = getattr(subtitle, 'language', None)
        if not getattr(lang, 'forced', False) and re.search(r'\bforced\b', name, re.I):
            continue
        if isinstance(video, Episode):
            season, episode = guess.get('season'), guess.get('episode')
            episodes = episode if isinstance(episode, list) else [episode]
            pack = getattr(subtitle, 'episode', None) in (None, 0) or len(names) > 1
            if season is not None and season != video.season:
                continue
            if episode is not None and video.episode not in episodes:
                continue
            if pack and (season != video.season or video.episode not in episodes):
                continue
            # A multi-episode member cannot serve a single-episode video.
            target = guessit(video.name, {'type': 'episode'}).get('episode', video.episode)
            targets = target if isinstance(target, list) else [target]
            if len(episodes) > 1 and set(episodes) != set(targets):
                continue
            # Only compare explicit episode titles, never series/release labels.
            actual = local_guess.get('episode_title') or guess.get('episode_title')
            # GuessIt calls the trailing title "title" when the basename
            # begins with coordinates (S1E03 - Time and Again.srt).
            if not actual and re.match(r'^(?:s\d+e\d+|\d+x\d+)\b', filename, re.I):
                actual = local_guess.get('title')
            expected = getattr(video, 'title', None)
            if actual and expected and title_key(actual) != title_key(expected):
                continue
        candidates.append(name)
    if not candidates:
        return None, 'no unambiguous member with matching episode identity'
    if len(candidates) > 1:
        # Identical duplicates are safe; different versions require a choice.
        first = archive.read(candidates[0]).replace(b'\r\n', b'\n')
        if any(archive.read(n).replace(b'\r\n', b'\n') != first for n in candidates[1:]):
            return None, 'multiple different members match the requested episode'
    return candidates[0], None
