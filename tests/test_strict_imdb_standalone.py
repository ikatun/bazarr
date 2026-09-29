"""Run directly with the project's venv; no application/config side effects."""
import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zipfile import ZipFile
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'custom_libs'),str(root/'libs')]
from subliminal.video import Episode, Movie
from subliminal_patch.identity import authorize, normalize_imdb, strict_archive_content
from subliminal_patch.core import SZProviderPool
from subliminal_patch.providers.subsource import SubsourceProvider

class IdentityTests(unittest.TestCase):
 def setUp(self):
  env=patch.dict(os.environ, BAZARR_REQUIRE_IMDB="true");env.start();self.addCleanup(env.stop)
  self.video=Episode('test.mkv','The Killing',3,2,series_imdb_id='tt0826760')
  self.sub=SimpleNamespace(provider_name='test',id='1',identity_imdb_id='tt0826760',season=3,episode=2)
 def test_verified(self): self.assertTrue(authorize(self.sub,self.video))
 def test_wrong_remake(self):
  self.sub.identity_imdb_id='tt1637727';self.assertFalse(authorize(self.sub,self.video))
 def test_missing_identity_despite_score_flag(self):
  self.sub.identity_imdb_id=None;self.sub.matches={'hash','series_imdb_id','episode','season'}
  self.assertFalse(authorize(self.sub,self.video))
 def test_missing_library_id(self):
  self.video.series_imdb_id=None;self.assertFalse(authorize(self.sub,self.video))
 def test_wrong_episode(self):
  self.sub.episode=1;self.assertFalse(authorize(self.sub,self.video))
 def test_wrong_season(self):
  self.sub.season=2;self.assertFalse(authorize(self.sub,self.video))
 def test_normalization(self):
  self.assertEqual(normalize_imdb(826760),'tt0826760')
  for value in (None,False,0,'','garbage','tt0000000'): self.assertIsNone(normalize_imdb(value))
 def test_manual_cross_episode_rejected(self):
  self.assertTrue(authorize(self.sub,self.video));self.video.episode=3
  self.assertFalse(authorize(self.sub,self.video))
 def test_pool_download_blocks_unverified(self):
  pool=SZProviderPool(providers=[])
  self.assertFalse(pool.download_subtitle(self.sub))
 def archive(self,names):
  b=io.BytesIO();z=ZipFile(b,'w')
  for n in names:z.writestr(n,n.encode())
  return z
 def test_pack_exact_episode(self):
  self.sub.episode=None;self.sub.is_pack=True;self.sub.asked_for_episode=2
  self.assertTrue(authorize(self.sub,self.video))
  z=self.archive(['Show.S03E01.srt','Show.S03E02.srt'])
  self.assertEqual(strict_archive_content(self.sub,z),b'Show.S03E02.srt')
 def test_pack_no_fallback(self):
  self.sub.episode=None;self.sub.is_pack=True;self.sub.asked_for_episode=2
  authorize(self.sub,self.video)
  self.assertIsNone(strict_archive_content(self.sub,self.archive(['Show.S03E01.srt'])))
 def test_wrong_single_file(self):
  authorize(self.sub,self.video)
  self.assertIsNone(strict_archive_content(self.sub,self.archive(['Show.S03E01.srt'])))
 def test_generic_single_episode_file(self):
  authorize(self.sub,self.video)
  self.assertEqual(strict_archive_content(self.sub,self.archive(['subtitle.srt'])),b'subtitle.srt')
 def test_movie(self):
  self.assertTrue(authorize(self.sub,Movie('test.mkv','test',imdb_id='tt0826760')))
 def test_subsource_actual_id_required(self):
  provider=SubsourceProvider(api_key='test-only')
  provider.checked=Mock(return_value=Mock(json=lambda:{'data':[{'movieId':1,'imdbId':'tt1637727'}]}))
  method=SubsourceProvider.search_titles.__wrapped__
  self.assertIsNone(method(provider,'The Killing','tt0826760',season=3))
  provider.checked.assert_called_once()
 def test_subsource_verified_alias(self):
  provider=SubsourceProvider(api_key='test-only')
  provider.checked=Mock(return_value=Mock(json=lambda:{'data':[{'movieId':1,'imdbId':'tt0826760','title':'Forbrydelsen'}]}))
  self.assertEqual(SubsourceProvider.search_titles.__wrapped__(provider,'The Killing','tt0826760',season=3),(1,'tt0826760'))
 def test_subsource_no_title_fallback(self):
  provider=SubsourceProvider(api_key='test-only')
  provider.checked=Mock(return_value=Mock(json=lambda:{'data':[]}))
  self.assertIsNone(SubsourceProvider.search_titles.__wrapped__(provider,'The Killing','tt0826760',season=3))
  provider.checked.assert_called_once()

if __name__=='__main__':unittest.main()
