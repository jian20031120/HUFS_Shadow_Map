"""평지 건물 그림자 투영. 모든 길이 단위는 m."""
import math
from shapely.geometry import Polygon
from shapely.affinity import translate
from shapely.ops import transform, unary_union
from pyproj import Transformer

TO_M = Transformer.from_crs(4326, 32652, always_xy=True).transform
TO_G = Transformer.from_crs(32652, 4326, always_xy=True).transform

def projected_shadow(footprint, height, elevation, azimuth):
    if elevation <= 0:
        return None
    base=transform(TO_M,footprint)
    distance=height / math.tan(math.radians(elevation))
    angle=math.radians((azimuth+180)%360)
    dx,dy=distance*math.sin(angle),distance*math.cos(angle)
    parts=[]
    polygons=list(base.geoms) if base.geom_type=='MultiPolygon' else [base]
    for p in polygons:
        pieces=[p,translate(p,dx,dy)]
        for ring in [p.exterior, *p.interiors]:
            coords=list(ring.coords)
            for a,b in zip(coords,coords[1:]):
                wall=Polygon([a,b,(b[0]+dx,b[1]+dy),(a[0]+dx,a[1]+dy)])
                if wall.area>1e-8:pieces.append(wall)
        parts.append(unary_union(pieces))
    return unary_union(parts).difference(base)

