"""평지 벡터 투영 및 고도 격자 광선 검사. 모든 길이 단위는 m."""
import math
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import map_coordinates
from shapely.geometry import Polygon, shape
from shapely.affinity import translate
from shapely.ops import transform, unary_union
from shapely import contains_xy
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

def raster_shadows(campus, buildings, terrain, elevation, azimuth, step=10., reach=600.):
    """10m 격자 중심에서 태양 방향으로 최대 600m까지 검사하는 근사."""
    xs,ys,z=terrain
    x=np.arange(xs[0],xs[-1]+0.01,step)
    y=np.arange(ys[0],ys[-1]+0.01,step)
    xx,yy=np.meshgrid(x,y)
    interpolation=RegularGridInterpolator((ys,xs),z,bounds_error=False,fill_value=np.nan)
    ground=interpolation(np.stack([yy,xx],axis=-1))
    surface=ground.copy()
    building_mask=np.zeros(xx.shape,dtype=bool)
    for footprint,height in buildings:
        polygon=transform(TO_M,footprint)
        mask=contains_xy(polygon,xx,yy)
        building_mask|=mask
        if height is not None and mask.any():
            surface[mask]=np.nanmax(ground[mask])+height
    inside=contains_xy(transform(TO_M,campus),xx,yy)&~building_mask
    terrain_shade=np.zeros_like(inside)
    all_shade=np.zeros_like(inside)
    rows,cols=np.indices(xx.shape,dtype=float)
    az=math.radians(azimuth)
    if elevation>0:
        for distance in np.arange(step,reach+step,step):
            coords=np.array([rows+distance*math.cos(az)/step,cols+distance*math.sin(az)/step])
            ray=ground+distance*math.tan(math.radians(elevation))
            g=map_coordinates(ground,coords,order=1,mode='constant',cval=np.nan)
            s=map_coordinates(surface,coords,order=0,mode='constant',cval=np.nan)
            terrain_shade|=g>ray+0.05
            all_shade|=s>ray+0.05
    terrain_shade &= inside
    all_shade=(all_shade|terrain_shade)&inside
    rgba=np.zeros((*xx.shape,4),dtype=np.uint8)
    rgba[terrain_shade]=[71,85,105,145]
    rgba[all_shade&~terrain_shade]=[124,58,237,150]
    west,south=TO_G(x[0]-step/2,y[0]-step/2)
    east,north=TO_G(x[-1]+step/2,y[-1]+step/2)
    return {'image':np.flipud(rgba),'bounds':[[south,west],[north,east]],
            'shaded_area':float(all_shade.sum()*step*step),
            'ground_area':float(inside.sum()*step*step)}
