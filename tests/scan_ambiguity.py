#!/usr/bin/env python3
"""Populate/report ambiguity for the library only; never search/download subtitles."""
import argparse
import ast
import json
from pathlib import Path
import sqlite3
import sys
import time
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'custom_libs'),str(root/'libs')]
from subliminal_patch.ambiguity import Detector, VERSION, TTL, RETRY, data_dir
parser=argparse.ArgumentParser()
parser.add_argument('--imdb',action='append')
parser.add_argument('--limit',type=int,default=25)
parser.add_argument('--db',default=str(data_dir() / 'db/bazarr.db'))
args=parser.parse_args()
c=sqlite3.connect('file:'+args.db+'?mode=ro',uri=True)
c.row_factory=sqlite3.Row
entries=[]
for kind,table in [('tv','table_shows'),('movie','table_movies')]:
 for row in c.execute('select title,imdbId,alternativeTitles from '+table):
  if args.imdb and row['imdbId'] not in args.imdb:continue
  names=[row['title']]
  try:
   alternatives=ast.literal_eval(row['alternativeTitles'] or '[]')
   names.extend(a if isinstance(a,str) else a.get('title','') for a in alternatives)
  except (ValueError,SyntaxError,TypeError,AttributeError):pass
  names=sorted({n.strip() for n in names if isinstance(n,str) and n.strip()})
  entries.append((kind,row['imdbId'],names))
detector=Detector()
with detector.db() as cache:
 stored={key:(checked,json.loads(data)) for key,checked,data in cache.execute('select key,checked,data from checks')}
def age(entry):
 record=stored.get(json.dumps([VERSION,*entry],ensure_ascii=False))
 return record[0] if record else 0
entries.sort(key=age)
count=0
for kind,imdb,names in entries:
 previous=stored.get(json.dumps([VERSION,kind,imdb,names],ensure_ascii=False))
 if not args.imdb and previous and time.time()-previous[0] < (RETRY if previous[1].get('lookup_failed') else TTL):continue
 result=detector.check(kind,imdb,names)
 print(json.dumps(result,ensure_ascii=False),flush=True)
 count+=1
 if count>=args.limit:break
