"""Offline regression tests; no running Bazarr, provider or GPU required."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'custom_libs'), str(root/'libs')]
from subliminal.video import Episode
from subzero.language import Language
from subliminal_patch.archive_identity import select_member
from subliminal_patch.archive_rejections import previous_rejection, remember_rejection
from subliminal_patch.core import SZProviderPool


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        env = patch.dict(os.environ, BAZARR_REQUIRE_IMDB='false', BAZARR_ARCHIVE_CACHE=self.folder.name)
        env.start(); self.addCleanup(env.stop)
        path = Path(self.folder.name)/'Show.S01E03.mkv'; path.write_bytes(b'video')
        self.video = Episode(str(path), 'Show', 1, 3, title='Parallax')
        self.sub = SimpleNamespace(provider_name='fixture', id='1', language=Language('eng'),
                    episode=None, is_pack=True, _identity_video=self.video)

    def archive(self, files):
        z = ZipFile(io.BytesIO(), 'w')
        for name, content in files.items(): z.writestr(name, content)
        self.addCleanup(z.close)
        return z

    def test_extras_directory_ignored(self):
        z = self.archive({'Extras/Show.S01E03.srt': 'wrong', 'Show.S01E03.srt': 'right'})
        self.assertEqual(select_member(self.sub, z), ('Show.S01E03.srt', None))

    def test_title_conflict(self):
        z = self.archive({'Show.S01E03.Time.And.Again.srt': 'wrong'})
        self.assertIsNone(select_member(self.sub, z)[0])

    def test_title_only_filename_in_release_directory(self):
        z = self.archive({'Show.S01.480p.x265/S1E03 - Time and Again.srt': 'wrong'})
        self.assertIsNone(select_member(self.sub, z)[0])

    def test_matching_title_only_filename(self):
        z = self.archive({'Show.S01.480p.x265/S1E03 - Parallax.srt': 'right'})
        self.assertIsNotNone(select_member(self.sub, z)[0])

    def test_title_matches(self):
        z = self.archive({'Show.S01E03.Parallax.srt': 'right'})
        self.assertIsNotNone(select_member(self.sub, z)[0])

    def test_ambiguous_versions_rejected(self):
        z = self.archive({'Show.S01E03.a.srt': 'one', 'Show.S01E03.b.srt': 'two'})
        self.assertIsNone(select_member(self.sub, z)[0])

    def test_identical_duplicates_allowed(self):
        self.video.title = None
        z = self.archive({'Show.S01E03.a.srt': 'same', 'Show.S01E03.b.srt': 'same'})
        self.assertIsNotNone(select_member(self.sub, z)[0])

    def test_combined_member_rejected_for_single(self):
        z = self.archive({'Show.S01E03E04.srt': 'wrong'})
        self.assertIsNone(select_member(self.sub, z)[0])

    def test_combined_member_allowed_for_combined(self):
        self.video.name = 'Show.S01E03E04.mkv'
        z = self.archive({'Show.S01E03E04.srt': 'right'})
        self.assertIsNotNone(select_member(self.sub, z)[0])

    def test_missing_member_rejected(self):
        z = self.archive({'Show.S01E02.srt': 'wrong'})
        self.assertIsNone(select_member(self.sub, z)[0])

    def test_rejection_scoped_to_candidate_and_video(self):
        remember_rejection(self.sub, 'bad content')
        self.assertEqual(previous_rejection(self.sub), 'bad content')
        self.sub.id = '2'; self.assertIsNone(previous_rejection(self.sub))
        self.sub.id = '1'; Path(self.video.name).write_bytes(b'changed video')
        self.assertIsNone(previous_rejection(self.sub))



if __name__ == '__main__': unittest.main()
