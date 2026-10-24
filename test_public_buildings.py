import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import requests
from shapely.geometry import box, mapping
from shapely.ops import transform
from shadow_model import TO_M, TO_G
from public_buildings import (resolve_height, match_buildings, fetch_campus,
                              load_cache, normalize, PublicDataError)

ORIGIN = transform(TO_M, box(127.26,37.336,127.261,37.337)).centroid

def polygon(x=0, y=0, width=20):
    return mapping(transform(TO_G, box(ORIGIN.x+x,ORIGIN.y+y,ORIGIN.x+x+width,ORIGIN.y+y+20)))

def osm(id='1', x=0):
    return {'type':'Feature','geometry':polygon(x), 'properties':{'osm_id':id,'name':'같은 이름','height':12,'levels':3}}

def public(id='p1',x=0,height=22,levels=6):
    return {'type':'Feature','id':id,'geometry':polygon(x),
            'properties':{'bld_nm':'같은 이름','height':height,'grnd_flr':levels}}

CAMPUS=box(127.255,37.332,127.276,37.341)

def reply(features,page=1,pages=1,total=None):
    return {'response':{'status':'OK','record':{'total':len(features) if total is None else total},
            'page':{'current':page,'total':pages},
            'result':{'featureCollection':{'type':'FeatureCollection','features':features}}}}

def response(body):
    r=Mock(); r.json.return_value=body
    return r

class PublicTests(unittest.TestCase):
    def test_priority_all_six_and_exclusion(self):
        p={'height':12,'levels':3}
        match={'public':{'height_m':22,'aboveground_floors':6}}
        self.assertEqual(resolve_height(p,30,match),(30,'사용자 입력'))
        self.assertEqual(resolve_height(p,0,match),(22,'공공데이터 높이'))
        match['public']['height_m']=0
        self.assertEqual(resolve_height(p,0,match),(18,'공공데이터 층수 기반 추정'))
        match['public']['aboveground_floors']=0
        self.assertEqual(resolve_height(p,0,match),(12,'OSM 높이'))
        p['height']=None
        self.assertEqual(resolve_height(p,0,match),(9,'OSM 층수 기반 추정'))
        p['levels']=None
        self.assertEqual(resolve_height(p,float('nan'),match),(15,'미등록 · 가정 높이'))
        self.assertIsNone(resolve_height(p,0,match,include_unknown=False)[0])

    def test_spatial_match_and_no_name_only(self):
        pubs,_=normalize([public(),public('p2',200)],CAMPUS)
        result=match_buildings([osm(),osm('2',210),osm('3',500)],pubs)
        self.assertEqual(result['1']['status'],'매칭 확인')
        self.assertEqual(result['2']['status'],'매칭 불확실')
        self.assertIsNone(result['2']['public'])
        self.assertEqual(result['3']['status'],'자료 없음')

    def test_ambiguous_one_to_many_and_many_to_one(self):
        pubs,_=normalize([public(),public('p2',1)],CAMPUS)
        self.assertIsNone(match_buildings([osm()],pubs)['1']['public'])
        pubs,_=normalize([public()],CAMPUS)
        result=match_buildings([osm(),osm('2',1)],pubs)
        self.assertTrue(all(m['public'] is None for m in result.values()))

    def test_normalize_missing_values_outside_and_schema(self):
        outside=public('outside'); outside['geometry']=mapping(box(127.1,37.3,127.11,37.31))
        pubs,_=normalize([public(height=0,levels='NaN'),outside],CAMPUS)
        self.assertEqual(len(pubs),1)
        self.assertIsNone(pubs[0]['properties']['height_m'])
        self.assertIsNone(pubs[0]['properties']['aboveground_floors'])
        bad=public(); bad['properties']={'invented_height':20}
        with self.assertRaises(PublicDataError):normalize([bad],CAMPUS)

    def test_pagination_cache_and_no_credentials(self):
        get=Mock(side_effect=[response(reply([public()],1,2,2)),
                              response(reply([public('p2',100)],2,2,2))])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cache.json'
            cache=fetch_campus('secret-test-key','http://localhost:8501',CAMPUS,path,get)
            self.assertEqual(len(cache['normalized']['features']),2)
            self.assertNotIn('secret-test-key',path.read_text())
            self.assertNotIn('domain',cache['metadata']['request_without_credentials'])
            self.assertEqual(load_cache(path,CAMPUS)['normalized'],json.loads(json.dumps(cache['normalized'])))
            self.assertEqual(get.call_count,2)
            self.assertTrue(get.call_args.kwargs['params']['geomFilter'].startswith('POLYGON'))
            original=path.read_text()
            for payload in ({'response':{'status':'ERROR','error':{'text':'secret-test-key'}}},
                            reply([public()],1,1,3), reply([public(),public()])):
                with self.assertRaises(PublicDataError):
                    fetch_campus('secret-test-key','url',CAMPUS,path,Mock(return_value=response(payload)))
                self.assertEqual(path.read_text(),original)
            with self.assertRaises(PublicDataError) as caught:
                fetch_campus('secret-test-key','url',CAMPUS,path,Mock(side_effect=requests.Timeout('secret-test-key')))
            self.assertNotIn('secret-test-key',str(caught.exception))

    def test_empty_query_and_wrong_campus_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cache.json'
            cache=fetch_campus('secret','url',CAMPUS,path,Mock(return_value=response({'response':{'status':'NOT_FOUND'}})))
            self.assertEqual(cache['normalized']['features'],[])
            with self.assertRaises(PublicDataError):load_cache(path,box(127,37,127.1,37.1))

if __name__=='__main__':unittest.main()
