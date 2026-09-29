"""Strict provider identity verification, independent of scoring match flags."""
import logging
import os
import re

from subliminal.video import Episode

logger = logging.getLogger(__name__)


def enabled():
    return os.environ.get("BAZARR_REQUIRE_IMDB", "false").lower() in ("true", "ambiguous")


def required(video):
    if os.environ.get("BAZARR_REQUIRE_IMDB", "false").lower() == "ambiguous":
        from .ambiguity import requires_identity
        return requires_identity(video)
    return enabled()


def normalize_imdb(value):
    if value is None or isinstance(value, bool):
        return None
    match = re.fullmatch(r"(?:tt)?([0-9]+)", str(value).strip())
    if not match or int(match[1]) == 0:
        return None
    return "tt" + match[1].zfill(7)


def verify(subtitle, video):
    """Never infer identity from a score flag, title similarity, or request ID."""
    is_episode = isinstance(video, Episode)
    expected = normalize_imdb(getattr(video, "series_imdb_id" if is_episode else "imdb_id", None))
    if not expected:
        return "missing library IMDb ID"
    actual = normalize_imdb(getattr(subtitle, "identity_imdb_id", None))
    if not actual:
        return "provider supplied no verified IMDb identity"
    if actual != expected:
        return "IMDb mismatch: expected %s, received %s" % (expected, actual)
    if is_episode:
        season = getattr(subtitle, "season", None)
        episode = getattr(subtitle, "episode", None)
        if season != video.season:
            return "season mismatch or unavailable"
        if episode != video.episode:
            if not (getattr(subtitle, "is_pack", False) and episode in (None, 0)
                    and getattr(subtitle, "asked_for_episode", None) == video.episode):
                return "episode mismatch or unavailable"
    return None


def authorize(subtitle, video):
    if not enabled():
        return True
    strict = required(video)
    expected = normalize_imdb(getattr(video, "series_imdb_id" if isinstance(video, Episode) else "imdb_id", None))
    actual = normalize_imdb(getattr(subtitle, "identity_imdb_id", None))
    # Even for clear titles, returned identity must never contradict the library.
    reason = verify(subtitle, video) if strict or (actual and expected) else None
    subtitle.identity_rejection = reason
    subtitle.identity_verified = reason is None and bool(actual and expected and actual == expected)
    subtitle.identity_required = strict
    subtitle._identity_video = video
    logger.info("IMDb gate: provider=%s subtitle=%s target=%s season=%s episode=%s result=%s",
                subtitle.provider_name, subtitle.id,
                getattr(video, "series_imdb_id", None) or getattr(video, "imdb_id", None),
                getattr(video, "season", None), getattr(video, "episode", None), reason or ("verified" if subtitle.identity_verified else "allowed: no title collision detected"))
    return reason is None


def strict_archive_content(subtitle, archive):
    """Select the exact episode from packs; never fall back to an unrelated file."""
    from guessit import guessit
    from subliminal.subtitle import fix_line_ending
    video = getattr(subtitle, "_identity_video", None)
    names = [name for name in archive.namelist()
             if name.lower().endswith((".srt", ".sub", ".ssa", ".ass"))]
    for name in names:
        if isinstance(video, Episode):
            guess = guessit(name, {"type": "episode"})
            # A single episode-specific upload may have a generic filename;
            # a pack must have explicit season and episode metadata.
            pack = getattr(subtitle, "episode", None) in (None, 0) or len(names) > 1
            season, episode = guess.get("season"), guess.get("episode")
            if season is not None and season != video.season:
                continue
            if episode is not None and episode != video.episode:
                continue
            if pack and (season != video.season or episode != video.episode):
                continue
        subtitle.identity_archive_member = name
        logger.info("IMDb gate: selected archive member %s", name)
        return fix_line_ending(archive.read(name))
    logger.warning("IMDb gate: no verified episode member in archive")
    return None
