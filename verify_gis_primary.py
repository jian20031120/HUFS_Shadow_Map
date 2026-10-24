from pathlib import Path
from datetime import datetime,time
from zoneinfo import ZoneInfo
from unittest.mock import patch
import json
import pandas as pd
import pvlib
from shapely.geometry import shape
from shapely.ops import transform,unary_union
from streamlit.testing.v1 import AppTest
from gis_buildings import load_gis
from gis_scene import build_scene,flat_shade
from shadow_model import TO_M,TO_G
root=Path(__file__).resolve().parent
c=shape(json.loads((root/'data/campus_boundary.geojson').read_text())['geometry'])
f=load_gis(root/'data/public_buildings',c,root/'data/gis_buildings_cache.json')['normalized']['features']
b,r=build_scene(f,{},3,15)
assert len(f)==75 and all(shape(x['geometry']).intersects(c) for x in f)
for feature,(_,h),row in zip(f,b,r):
 p=feature['properties']
 assert h==(p['height_m'] if p['height_m'] is not None else p['aboveground_floors']*3 if p['aboveground_floors'] is not None else 15)
shades=[]
for hour in (9,15):
 sun=pvlib.solarposition.get_solarposition(pd.DatetimeIndex([datetime(2026,10,4,hour,tzinfo=ZoneInfo('Asia/Seoul'))]),c.centroid.y,c.centroid.x).iloc[0]
 shade=flat_shade(c,b,float(sun.apparent_elevation),float(sun.azimuth));shades.append(shade)
 assert shade.is_valid and not shade.is_empty
 assert shade.difference(transform(TO_M,c)).area<1e-5
 assert shade.intersection(unary_union([transform(TO_M,g) for g,_ in b])).area<1e-5
 assert transform(TO_M,transform(TO_G,shade)).hausdorff_distance(shade)<0.001
assert shades[0].symmetric_difference(shades[1]).area>100
maps=[]
with patch('streamlit_folium.st_folium',side_effect=lambda m,**kwargs:maps.append(m)):
 at=AppTest.from_file(str(root/'app.py'),default_timeout=60).run()
 assert not at.exception,[x.message for x in at.exception]
 assert at.metric[0].value=='75'
 layer=next(x for x in maps[-1]._children.values() if getattr(x,'layer_name','').startswith('GIS 건물 윤곽'))
 assert len(layer._children)==75
 for rendered,original in zip(layer._children.values(),f):
  assert shape(rendered.data['features'][0]['geometry']).equals(shape(original['geometry']))
 at.time_input[0].set_value(time(9)).run()
 html9=maps[-1].get_root().render()
 at.time_input[0].set_value(time(15)).run()
 html15=maps[-1].get_root().render()
 assert not at.exception and html9!=html15
 at.sidebar.radio[0].set_value('지형 고도 반영 (거친 근사)').run()
 assert not at.exception,[x.message for x in at.exception]
 at.session_state['gis_height_overrides']={'edited_rows':{0:{'직접 확인한 높이 (m)':31.}},'added_rows':[],'deleted_rows':[]}
 at.run();assert not at.exception
 table=next(d.value for d in at.dataframe if '최종 높이 (m)' in d.value.columns)
 assert table.iloc[0]['최종 높이 (m)']==31
print('PASS: 75 GIS Folium geometries; A16/A26 actually passed; time changes; clip; footprint removal; CRS roundtrip <1mm; ASTER; manual priority')
print('09/15 shadow areas:',[round(s.area,2) for s in shades])
print('Symmetric difference m2:',round(shades[0].symmetric_difference(shades[1]).area,2))
