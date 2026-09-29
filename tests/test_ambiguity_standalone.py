"""Offline regression tests; execute with Bazarr venv."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'custom_libs'), str(root/'libs')]
from subliminal.video import Episode, Movie
from subliminal_patch.ambiguity import Detector, normalize, requires_identity, title_names, data_dir
from subliminal_patch.identity import authorize

class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.calls = []
        self.collision = True
        self.broken = False
        self.pages = 1
        self.detector = Detector(Path(self.tmp.name)/'cache.sqlite', fetch=self.fetch)
    def fetch(self, path, **params):
        self.calls.append((path, params))
        if self.broken: raise RuntimeError('offline')
        if path.startswith('find/'): return {'tv_results': [{'id':1}], 'movie_results':[{'id':1}]}
        if path.endswith('alternative_titles'): return {'results':[]}
        if path.startswith('search/'):
            return {'results':[{'id': 1}, {'id': 2}], 'total_pages':self.pages}
        return {'id':int(path.split('/')[-1]),'name':'The Killing' if path.endswith('/1') or self.collision else 'Killing Eve','original_name':'Forbrydelsen' if path.endswith('/1') else 'The Killing Again','first_air_date':'2007-01-01'}
    def test_remake_collision(self):
        r=self.detector.check('tv','tt0826760',['The Killing'])
        self.assertEqual(r['status'],'ambiguous');self.assertEqual(r['collisions'][0]['tmdb_id'],2)
        self.assertTrue(all('year' not in p for _,p in self.calls))
    def test_fuzzy_result_not_collision(self):
        self.collision=False
        self.assertEqual(self.detector.check('tv','tt0826760',['The Killing'])['status'],'clear')
    def test_movie_collision(self):
        self.assertEqual(self.detector.check('movie','tt0826760',['The Killing'])['status'],'ambiguous')
    def test_cache_avoids_calls(self):
        self.detector.check('tv','tt0826760');self.calls.clear();self.broken=True
        self.assertEqual(self.detector.check('tv','tt0826760')['status'],'ambiguous');self.assertEqual(self.calls,[])
    def test_refresh_failure_preserves_collision(self):
        self.detector.check('tv','tt0826760');self.broken=True
        r=self.detector.check('tv','tt0826760',force=True)
        self.assertEqual(r['status'],'ambiguous');self.assertTrue(r['lookup_failed'])
    def test_first_failure_unknown(self):
        self.broken=True
        self.assertEqual(self.detector.check('tv','tt0826760')['status'],'unknown')
    def test_incomplete_pagination_unknown(self):
        self.collision=False;self.pages=11
        self.assertEqual(self.detector.check('tv','tt0826760')['status'],'unknown')
    def test_punctuation_preserve_numbers_words(self):
        self.assertEqual(normalize('Spider-Man'), normalize('spider man'))
        self.assertNotEqual(normalize('Alien'),normalize('Aliens'))
        self.assertNotEqual(normalize('Dune'),normalize('Dune 2'))
    def test_alias_collision(self):
        orig=self.fetch
        def alias_fetch(path,**params):
            if path=='tv/2/alternative_titles':return {'results':[{'iso_3166_1':'GB','title':'The Killing'}]}
            return orig(path,**params)
        self.collision=False;self.detector.fetch_override=alias_fetch
        self.assertEqual(self.detector.check('tv','tt0826760')['status'],'ambiguous')
    def test_abbreviations_excluded_but_short_real_titles_preserved(self):
        names=title_names({'name':'Breaking Bad'}, {'results':[
            {'iso_3166_1':'US','title':'BB','type':'abbreviation'},
            {'iso_3166_1':'HR','title':'Na putu prema dolje','type':''}]})
        self.assertNotIn('BB',names);self.assertIn('Na putu prema dolje',names)
        self.assertIn('It',title_names({'title':'It'}))
    def test_new_alias_invalidates_cache_key(self):
        self.detector.check('tv','tt0826760');self.calls.clear()
        self.detector.check('tv','tt0826760',['New alias']);self.assertTrue(self.calls)

class ConfigurationTests(unittest.TestCase):
    def test_config_environment(self):
        with patch.dict(os.environ, BAZARR_CONFIG_DIR='/tmp/bazarr-config'):
            self.assertEqual(data_dir(), Path('/tmp/bazarr-config'))
            d=Detector()
            self.assertEqual(d.cache_path, Path('/tmp/bazarr-config/ambiguity.sqlite'))
            self.assertEqual(d.key_path, Path('/tmp/bazarr-config/tmdb-api-key'))
    def test_existing_bazarr_config_argument(self):
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules,
                {'app.get_args':SimpleNamespace(args=SimpleNamespace(config_dir='/tmp/custom-config'))}):
            self.assertEqual(data_dir(), Path('/tmp/custom-config'))


class PolicyTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,BAZARR_REQUIRE_IMDB='ambiguous');env.start();self.addCleanup(env.stop)
        self.video=Episode('x.mkv','The Killing',3,2,series_imdb_id='tt0826760')
        self.sub=SimpleNamespace(provider_name='test',id='1',identity_imdb_id=None,season=3,episode=2)
    def authorize(self,status='clear',failed=False):
        with patch('subliminal_patch.ambiguity.check_video',return_value={'status':status,'lookup_failed':failed}):
            return authorize(self.sub,self.video)
    def test_clear_allows_missing(self):
        self.assertTrue(self.authorize());self.assertFalse(self.sub.identity_verified)
    def test_ambiguous_rejects_missing(self):self.assertFalse(self.authorize('ambiguous'))
    def test_unknown_rejects_missing(self):self.assertFalse(self.authorize('unknown'))
    def test_stale_clear_error_rejects_missing(self):self.assertFalse(self.authorize('clear',True))
    def test_clear_still_rejects_wrong_imdb(self):
        self.sub.identity_imdb_id='tt1637727';self.assertFalse(self.authorize())
    def test_clear_still_rejects_wrong_episode(self):
        self.sub.identity_imdb_id='tt0826760';self.sub.episode=4;self.assertFalse(self.authorize())
    def test_ambiguous_verified_passes(self):
        self.sub.identity_imdb_id='tt0826760';self.assertTrue(self.authorize('ambiguous'))
    def test_movie_clear_missing_allowed(self):
        self.video=Movie('x.mkv','Example',imdb_id='tt0826760');self.assertTrue(self.authorize())
    def test_cached_candidate_rechecked_for_target(self):
        self.assertTrue(self.authorize('clear'));self.assertFalse(self.authorize('ambiguous'))
if __name__=='__main__':unittest.main()
