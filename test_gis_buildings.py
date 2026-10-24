import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import geopandas as gpd
from shapely.geometry import box, mapping
from gis_buildings import load_gis, STEMS, COLUMNS
from public_buildings import match_buildings,resolve_height,PublicDataError

class GISTests(unittest.TestCase):
    def test_bbox_crs_cache_and_height_priority(self):
        campus=box(127.25,37.33,127.27,37.35)
        geom=box(127.255,37.335,127.256,37.336)
        rows=[]
        for i in range(3):
            row={c:None for c in COLUMNS}
            row.update(A0=i,A1=f'GIS-{i}',A16=21 if i==0 else 0,A26=5,A24='same name')
            rows.append(row)
        frame=gpd.GeoDataFrame(rows,geometry=[geom,box(127.26,37.34,127.261,37.341),box(127.3,37.4,127.31,37.41)],crs=4326).to_crs(5186)
        info={'crs':'EPSG:5186','fields':COLUMNS,'dtypes':['object']*len(COLUMNS),'features':1000000}
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for stem in STEMS:
                for ext in ('.shp','.shx','.dbf','.prj','.fix'):(folder/(stem+ext)).touch()
            path=folder/'cache.json'
            with patch('gis_buildings.pyogrio.read_info',return_value=info),patch('gis_buildings.pyogrio.read_dataframe',side_effect=[frame,frame.iloc[:0],frame.iloc[:0]]) as read:
                cache=load_gis(folder,campus,path)
                self.assertEqual(read.call_count,3)
                for call in read.call_args_list:
                    self.assertGreater(call.kwargs['bbox'][0],100000)
                    self.assertEqual(call.kwargs['max_features'],10001)
                    self.assertEqual(call.kwargs['columns'],COLUMNS)
                self.assertEqual(len(cache['normalized']['features']),2)
            with patch('gis_buildings.pyogrio.read_dataframe',side_effect=AssertionError('cache must prevent reads')):
                self.assertEqual(load_gis(folder,campus,path)['signature'],cache['signature'])
            osm=[{'type':'Feature','geometry':mapping(geom),'properties':{'osm_id':'1','height':10,'levels':2}}]
            match=match_buildings(osm,cache['normalized']['features'])['1']
            self.assertEqual(resolve_height(osm[0]['properties'],0,match),(21,'GIS 실제 높이'))
            self.assertEqual(resolve_height(osm[0]['properties'],33,match),(33,'사용자 입력'))
            match['public']['height_m']=None
            self.assertEqual(resolve_height(osm[0]['properties'],0,match,4),(20,'GIS 층수 기반 추정'))
            match['public']['aboveground_floors']=None
            self.assertEqual(resolve_height(osm[0]['properties'],0,match),(10,'OSM 높이'))
            original=path.read_bytes()
            (folder/(STEMS[0]+'.dbf')).write_bytes(b'changed')
            with patch('gis_buildings.pyogrio.read_info',return_value={**info,'fields':['A1']}):
                with self.assertRaises(PublicDataError):load_gis(folder,campus,path)
            self.assertEqual(path.read_bytes(),original)

if __name__=='__main__':unittest.main()
