"""Opaque horizontal canopy at tree-top height, vector shadow on local flat ground."""
import json, math, os, tempfile, uuid
from pathlib import Path
from shapely.geometry import shape, mapping, GeometryCollection
from shapely.affinity import translate
from shapely.ops import transform, unary_union
from shadow_model import TO_M, TO_G

def validate_trees(data, campus):
    if data.get('type') != 'FeatureCollection': raise ValueError('FeatureCollection GeoJSON이 필요합니다.')
    seen=set()
    if len(data['features'])>200: raise ValueError('시험 구역은 수관 200개 이하로 제한합니다.')
    for f in data['features']:
        p=f['properties']; g=shape(f['geometry']); identifier=p['tree_id']
        if not isinstance(identifier,str) or not identifier.startswith('TREE-') or identifier in seen: raise ValueError('TREE-로 시작하는 고유 ID가 필요합니다.')
        seen.add(identifier)
        if g.geom_type not in ('Polygon','MultiPolygon') or not g.is_valid or g.is_empty or not campus.covers(g): raise ValueError('수관은 캠퍼스 안의 유효한 다각형이어야 합니다.')
        height=float(p['height_m'])
        if not math.isfinite(height) or not 0<height<=80: raise ValueError('나무 높이는 0 초과 80m 이하입니다.')
        p['height_m']=height;p['canopy_area_m2']=transform(TO_M,g).area
        p['model']='opaque_horizontal_canopy_local_flat'
    return data

def new_tree(geometry,height,campus):
    f={'type':'Feature','geometry':geometry,'properties':{'tree_id':'TREE-'+uuid.uuid4().hex[:8],'height_m':height,'canopy_shape':'사용자 다각형'}}
    return validate_trees({'type':'FeatureCollection','features':[f]},campus)['features'][0]

def save_trees(path,data,campus):
    data=validate_trees(data,campus);path=Path(path)
    fd,temp=tempfile.mkstemp(dir=path.parent,suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,allow_nan=False)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def load_trees(path,campus):
    return validate_trees(json.loads(Path(path).read_text()),campus) if Path(path).exists() else {'type':'FeatureCollection','features':[]}

def canopy_shadow(data,campus,elevation,azimuth,buildings=()):
    if elevation<3:return GeometryCollection()
    a=math.radians(azimuth);parts=[]
    for f in data['features']:
        g=transform(TO_M,shape(f['geometry']));d=f['properties']['height_m']/math.tan(math.radians(elevation))
        parts.append(translate(g,-d*math.sin(a),-d*math.cos(a)))
    return unary_union(parts).intersection(transform(TO_M,campus)).difference(unary_union([transform(TO_M,g) for g,_ in buildings]))
