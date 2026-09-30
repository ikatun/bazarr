# IMDb identity and title ambiguity fork

This fork adds provider identity verification to Bazarr v1.6.2. It is not an
upstream Bazarr release. Original copyright and GPL-3.0 licensing are retained.

## Identity policy

Set `BAZARR_REQUIRE_IMDB` to:

- `ambiguous`: require independently captured provider IMDb identity when another
  production shares a relevant title/alias, or the TMDB check is incomplete.
  For a completed check with no collision, missing provider identity is allowed.
  Actual returned IMDb mismatches are always rejected.
- `true`: require verified identity for every provider download.
- `false`: disable this fork's additional identity gate (native default).

The Docker image defaults to `ambiguous`. This does not use legacy score flags as
proof of identity. Verified adapters currently cover OpenSubtitles.com,
SuperSubtitles and SubSource. Other providers can contribute only where verified
identity is not required. Episode/season checks and exact archive member selection
prevent wrong-episode pack fallbacks. Manual and automatic downloads share the
gate. Direct subtitle uploads are outside provider verification.

TMDB searches compare the managed production's names against the wider catalogue,
including productions outside your library. TV is compared with TV and movies
with movies. Titles are normalized conservatively; fuzzy search results alone do
not establish a collision. Original/library names and relevant country aliases
are included; aliases explicitly marked abbreviations/acronyms are excluded.
A short film with the same name still constitutes a collision. This is metadata
verification, not subtitle-content or translation-quality validation.

A lookup is bounded to 10 search pages and an 80-candidate/90-second candidate
lookup budget. Incomplete lookup, missing identity or request failure is unknown
and requires verified identity. Previously clear results never silently bypass
verification after a failed refresh. Successful checks expire after 30 days;
failed checks retry after one hour. Results and reasons are persisted in SQLite.

## Docker and Dockge

Image: `ghcr.io/ikatun/bazarr:latest` (Linux amd64). Each published build also gets
`sha-<full-commit>` so deployments can be pinned. Use the digest for reproducible
rollbacks. This image runs as UID/GID 1000 by default and includes FFmpeg,
MediaInfo, archive tools and a frontend built from this checkout.

Copy [compose.yaml](compose.yaml) into your Dockge stack. Provide a TMDB API key in
`./secrets/tmdb-api-key`, readable by the configured container UID; do not commit
it. Configure `PUID`, `PGID`, `MEDIA_GID`, `MEDIA_PATH` and `TZ` as needed. An existing
config bind mount must be writable by that UID/GID. When overriding the UID for a
new named volume, initialize its ownership before starting the containers.

Both services share `/config`. The `ambiguity-cache` service has no media mount
and only checks metadata: batches of 25 pending/stale library titles with five
minutes between batches. Bazarr also checks titles on demand. New library items
are checked after Bazarr imports them from Sonarr/Radarr. TMDB credentials are
only needed at runtime and are never supplied to the image build.

Additional environment settings:

| Variable | Default |
| --- | --- |
| `BAZARR_CONFIG_DIR` | `/config` in Docker; otherwise Bazarr's `--config` directory or repository `data/` |
| `BAZARR_AMBIGUITY_CACHE` | `ambiguity.sqlite` under the config directory |
| `BAZARR_TMDB_KEY_FILE` | `tmdb-api-key` under the config directory; Compose overrides to its secret mount |

Start with `docker compose up -d`. UI/API uses port 6767. Configure Sonarr/Radarr
and subtitle providers normally. When migrating, stop the old instance first,
back up its config/database, preserve media mappings, and never run two subtitle
workers against the same database. The image disables the in-app updater; update
by pulling a new image. It otherwise runs Bazarr's normal scheduler and SignalR.
For a search-only experiment, override the app command with
`["serve", "--no-tasks", "--no-signalr"]`.

## CI and local validation

[Docker image workflow](.github/workflows/docker-image.yml) runs on GitHub-hosted
Ubuntu runners for pushes to `master`, version tags, pull requests and manual
runs. It builds the frontend from the lockfile and runs the identity regression
suites during the Docker build. A fresh isolated container must serve its HTML
and JavaScript and shut down before publication. Only successful non-PR builds
publish to GHCR using the repository's temporary `GITHUB_TOKEN`; no personal
registry credential or self-hosted runner is required.

```sh
docker build -t bazarr-fork .
python3 docker/smoke.py bazarr-fork
```

Or, with Python dependencies from `requirements.txt` installed:

```sh
python tests/test_strict_imdb_standalone.py
python tests/test_ambiguity_standalone.py
BAZARR_CONFIG_DIR=/path/to/config python tests/scan_ambiguity.py --limit 25
```

The live library/provider test scripts and their output are private operational
artifacts and are deliberately not included. Upstream release automation is
retained, with its scheduled release job restricted to the upstream repository.


## Archive member identity

Archive extraction checks season and episode independently of score flags.
An explicit episode title must agree with the library title after punctuation
and case normalization, including coordinate-only basenames inside release
folders. Clearly labeled extras folders and unnumbered bonus material are
excluded. Combined members cannot serve a single-episode video. Different
matching versions are rejected as ambiguous; byte-identical duplicates are safe.
A single episode-specific upload may use a generic basename.

`BAZARR_ARCHIVE_GATE=true` (default) enables these additional checks for
SuperSubtitles and the shared provider archive mixin. Set it to `false` to
restore legacy archive selection. Existing IMDb checks are independent.
Other providers with their own extractors are not automatically covered.
The selected archive member is included in the normal download history message.
A rejected archive candidate is remembered for seven days for its provider ID,
language and target media/episode identity; it does not block the whole pack for
other episodes or throttle the provider. Cache defaults to
`archive-identity` under `BAZARR_CONFIG_DIR`; override with `BAZARR_ARCHIVE_CACHE`.

These checks use filenames and metadata only. They do not transcribe audio,
contact an AI service or establish correctness of mislabeled subtitle dialogue.
Separate audio/content auditing can be performed outside Bazarr.
