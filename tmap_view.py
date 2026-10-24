"""TMAP JS V2 지도 위에 기존 계산 결과를 표시. 키는 디스크에 저장하지 않음."""
import base64,io,json,math,html
from urllib.parse import quote
from PIL import Image
import streamlit as st
from shapely.geometry import shape, mapping, MultiLineString
from shapely.ops import transform, substring
from shadow_model import TO_M, TO_G

def js_json(value):
    return json.dumps(value,ensure_ascii=False).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')

def _location_for_map(value):
    """Only finite geographic coordinates enter the map payload."""
    if not isinstance(value,dict):
        return None
    try:
        if isinstance(value.get('latitude'),bool) or isinstance(value.get('longitude'),bool):
            return None
        latitude,longitude=float(value['latitude']),float(value['longitude'])
        if not (math.isfinite(latitude) and math.isfinite(longitude)
                and -85 <= latitude <= 85 and -180 <= longitude <= 180):
            return None
        accuracy=value.get('accuracy')
        if accuracy is not None:
            accuracy=float(accuracy)
            if not math.isfinite(accuracy) or not 0 <= accuracy <= 50000:
                accuracy=None
        return {'latitude':latitude,'longitude':longitude,'accuracy':accuracy}
    except (TypeError,ValueError,KeyError):
        return None


def _campus_dashes(campus):
    """A neutral dashed boundary must never be mistaken for a shaded walkway."""
    boundary=transform(TO_M,shape(campus).boundary)
    parts=list(boundary.geoms) if boundary.geom_type=='MultiLineString' else [boundary]
    dashes=[]
    for part in parts:
        start=0.0
        while start<part.length:
            dash=substring(part,start,min(start+16,part.length))
            if dash.geom_type=='LineString' and dash.length>0:
                dashes.append(list(dash.coords))
            start+=28
    return mapping(transform(TO_G,MultiLineString(dashes)))


def map_html(app_key,center,campus,buildings,shadow=None,terrain=None,trees=None,tree_shadow=None,tree_height=8,
             user_location=None,shaded_walkways=None,nearby_walkways=None,map_height=650,allow_tree_edit=False,
             guidance=None):
    map_height=_map_height(map_height)
    raster=None
    if terrain is not None:
        buffer=io.BytesIO()
        Image.fromarray(terrain['image']).save(buffer,format='PNG')
        raster={'url':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),
                'bounds':terrain['bounds']}
    sdk_url = (
        "https://apis.openapi.sk.com/tmap/jsv2"
        "?version=1&appKey=" + quote(app_key, safe="")
    )
    payload=js_json({'center':center,'campus':campus,'buildings':buildings,'shadow':shadow,'terrain':raster,
                     'trees':trees or {'type':'FeatureCollection','features':[]},'treeShadow':tree_shadow,'treeHeight':tree_height,
                     'userLocation':_location_for_map(user_location),
                     'shadedWalkways':shaded_walkways or {'type':'FeatureCollection','features':[]},
                     'nearbyWalkways':nearby_walkways or {'type':'FeatureCollection','features':[]},
                     'guidance':guidance,
                     'campusBorder':_campus_dashes(campus),
                     'mapHeight':map_height,'allowTreeEdit':bool(allow_tree_edit)})
    tree_editor='''<details class="tree-editor"><summary>나무 수관 추가하기</summary><div class="drawing">
<button id="start" disabled>수관 그리기</button><button id="finish" disabled>완료</button><button id="cancel" disabled>취소</button><button id="download" disabled>수관 GeoJSON 다운로드</button>
</div></details>''' if allow_tree_edit else ''
    template="""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<style>body{margin:0;font:14px system-ui;color:#163d32;background:#f9fcf7}#map{width:100%;height:__MAP_HEIGHT__px}
#status{position:absolute;top:62px;left:12px;right:12px;z-index:10000;width:fit-content;max-width:calc(100% - 48px);padding:9px 12px;border-radius:10px;background:#fffffff2;color:#334155;font-size:13px;box-shadow:0 2px 14px #163d3222}
#status a{display:inline-block;margin-left:7px}#status:empty{display:none}
#credit{padding:7px 10px;font-size:10px;color:#607366;line-height:1.4}
.toolbar{position:relative;z-index:10001;display:flex;gap:8px;align-items:center;padding:8px 10px;border:0;margin:0;min-inline-size:0;background:#f9fcf7}
.toolbar label{display:flex;align-items:center;gap:7px;cursor:pointer;padding:6px 3px}
button,.layers>summary{border:1px solid #c5d9bc;border-radius:9px;padding:7px 11px;background:white;color:#244b3b;font:inherit;cursor:pointer;white-space:nowrap}
button:hover,.layers>summary:hover{background:#e7f1de}button:disabled{cursor:default;opacity:.55}
.layers{position:relative;margin-left:auto}.layers>summary{list-style:none}.layers>summary::-webkit-details-marker{display:none}
.layer-menu{position:absolute;top:39px;right:0;width:160px;padding:7px 10px;background:white;border:1px solid #dce8d8;border-radius:10px;box-shadow:0 5px 16px #163d3222}
.tree-editor{border-top:1px solid #dce8d8;padding:8px 12px}summary{cursor:pointer;color:#49654b}
.drawing{padding:9px 0 0;display:flex;gap:7px;flex-wrap:wrap}
a{color:#1d4ed8}</style></head><body>
<fieldset id="map-controls" class="toolbar" disabled>
<button id="home" type="button" title="캠퍼스 전체 보기">캠퍼스</button>
<button id="my-location" type="button" title="조회한 위치로 지도 중심 이동" disabled>내 위치</button>
<details class="layers"><summary>지도 표시 ▾</summary><div class="layer-menu">
<label><input id="show-buildings" type="checkbox" checked>건물</label>
<label><input id="show-shadows" type="checkbox" checked>그림자</label>
<label><input id="show-walkways" type="checkbox" checked>그늘 안내선</label>
</div></details>
</fieldset>
<div id="status" role="status">지도를 불러오는 중…</div>
<div id="map"></div>
__TREE_EDITOR_HTML__
<div id="credit">그늘은 추정 결과예요. · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap 기여자</a> · <a href="https://doi.org/10.5194/essd-17-6647-2025" target="_blank" rel="noopener" title="GlobalBuildingAtlas, Zhu 외 · CC BY-NC 4.0">GlobalBuildingAtlas</a> · 국토교통부 / VWorld</div>
<script>
const data=__PAYLOAD__;
const status=document.getElementById('status');
function fail(overlay=false){clearTimeout(timeout);status.innerHTML=(overlay?'그늘 표시를 불러오지 못했어요.':'지도를 불러오지 못했어요.')+' <a href="/?map=osm" target="_top">기본 지도로 보기</a>';}
let loaded=false,mapReady=false;
const timeout=setTimeout(()=>{if(!loaded) fail();},15000);
function latlng(p){return new Tmapv2.LatLng(p[1],p[0]);}
function drawGeometry(geometry,style,map,group){
 if(!geometry) return;
 if(geometry.type==='GeometryCollection'){geometry.geometries.forEach(g=>drawGeometry(g,style,map,group));return;}
 const polys=geometry.type==='Polygon'?[geometry.coordinates]:
   geometry.type==='MultiPolygon'?geometry.coordinates:[];
 polys.forEach(rings=>{
   const polygon=new Tmapv2.Polygon(Object.assign({
     paths:rings.length===1?rings[0].map(latlng):rings.map(r=>r.map(latlng)),map:map
   },style));
   if(group)group.push(polygon);
 });
}
function drawLineGeometry(geometry,style,map,group){
 if(!geometry)return;
 if(geometry.type==='GeometryCollection'){
   geometry.geometries.forEach(g=>drawLineGeometry(g,style,map,group));return;
 }
 const lines=geometry.type==='LineString'?[geometry.coordinates]:
   geometry.type==='MultiLineString'?geometry.coordinates:[];
 lines.forEach(line=>{
   if(line.length<2||!line.every(p=>Array.isArray(p)&&Number.isFinite(p[0])&&Number.isFinite(p[1])&&Math.abs(p[0])<=180&&Math.abs(p[1])<=85))return;
   const path=new Tmapv2.Polyline(Object.assign({path:line.map(latlng),map:map},style));
   if(group)group.push(path);
 });
}
function drawWalkways(collection,style,map,group){
 if(!collection||!Array.isArray(collection.features))return;
 collection.features.forEach(feature=>drawLineGeometry(feature.geometry,style,map,group));
}
function initialize(){
 try{
  if(!window.Tmapv2||typeof Tmapv2.Map!=='function'){fail();return;}
  const map=new Tmapv2.Map('map',{center:new Tmapv2.LatLng(data.center[0],data.center[1]),
    width:'100%',height:data.mapHeight+'px',zoom:15});
  mapReady=true;
  const groups={buildings:[],shadows:[],walkways:[]};
  let tileFailed=false;
  document.getElementById('map').addEventListener('error',event=>{
    if(event.target.tagName==='IMG'){
      tileFailed=true;
      fail();
    }
  },true);
  drawLineGeometry(data.campusBorder,{strokeColor:'#94a3b8',strokeWeight:1,strokeOpacity:0.7},map);
  if(data.terrain){
   const b=data.terrain.bounds;
   groups.shadows.push(new Tmapv2.GroundOverlay({url:data.terrain.url,
    bounds:new Tmapv2.LatLngBounds(new Tmapv2.LatLng(b[0][0],b[0][1]),new Tmapv2.LatLng(b[1][0],b[1][1])),
    opacity:0.85,map:map}));
  }
  drawGeometry(data.shadow,{fillColor:'#4ade80',fillOpacity:0.22,strokeWeight:0,strokeOpacity:0},map,groups.shadows);
  drawGeometry(data.treeShadow,{fillColor:'#4ade80',fillOpacity:0.22,strokeWeight:0,strokeOpacity:0},map,groups.shadows);
  data.trees.features.forEach(f=>drawGeometry(f.geometry,{fillColor:'#16a34a',fillOpacity:0.12,strokeColor:'#16a34a',strokeWeight:2},map));
  data.buildings.forEach(b=>{
    drawGeometry(b.geometry,{fillColor:b.color,fillOpacity:0.12,strokeColor:b.color,strokeWeight:1},map,groups.buildings);
    if(b.showLabel===true&&b.position) groups.buildings.push(new Tmapv2.Marker({position:latlng(b.position),map:map,title:b.title,
      iconHTML:'<div style="background:white;border:1px solid #333;border-radius:12px;text-align:center;width:26px">'+Number(b.number)+'</div>'}));
  });
  drawWalkways(data.shadedWalkways,{strokeColor:'#166534',strokeWeight:6,strokeOpacity:0.95},map,groups.walkways);
  drawWalkways(data.nearbyWalkways,{strokeColor:'#fde047',strokeWeight:12,strokeOpacity:1},map,groups.walkways);
  drawWalkways(data.nearbyWalkways,{strokeColor:'#15803d',strokeWeight:7,strokeOpacity:1},map,groups.walkways);
  const guidance=data.guidance;
  if(guidance){
    const destinationGeometry=guidance.destination_geometry;
    drawGeometry(destinationGeometry&&destinationGeometry.type==='Feature'?destinationGeometry.geometry:destinationGeometry,
      {fillColor:'#2563eb',fillOpacity:0.08,strokeColor:'#2563eb',strokeWeight:2,strokeOpacity:0.95},map,groups.walkways);
    drawWalkways(guidance.route,{strokeColor:'#ffffff',strokeWeight:11,strokeOpacity:0.9},map,groups.walkways);
    drawWalkways(guidance.sunny_route,{strokeColor:'#f59e0b',strokeWeight:5,strokeOpacity:0.95},map,groups.walkways);
    drawWalkways(guidance.shaded_route,{strokeColor:'#166534',strokeWeight:7,strokeOpacity:0.95},map,groups.walkways);
    if(guidance.target&&guidance.target.geometry&&guidance.target.geometry.type==='Point'){
      const destinationName=typeof guidance.destination_name==='string'?guidance.destination_name.trim():'';
      const targetLabel=typeof guidance.target_label==='string'?guidance.target_label.trim():'';
      const targetTitle=targetLabel||(destinationName?'도착: '+destinationName:'가까운 그늘');
      groups.walkways.push(new Tmapv2.Marker({position:latlng(guidance.target.geometry.coordinates),map:map,title:targetTitle,
        iconHTML:'<div style="width:24px;height:24px;border:3px solid white;border-radius:50%;background:#166534;color:white;text-align:center;line-height:24px;box-shadow:0 1px 7px #163d3266" aria-label="목적지">🏁</div>'}));
    }
    if(guidance.is_demo&&guidance.origin){
      const origin=guidance.origin;
      groups.walkways.push(new Tmapv2.Marker({position:new Tmapv2.LatLng(origin.latitude,origin.longitude),map:map,title:'시연 시작점',
        iconHTML:'<div style="width:14px;height:14px;background:white;border:4px solid #2563eb;border-radius:50%;box-shadow:0 1px 6px #163d3266" aria-label="시연 시작점"></div>'}));
    }
  }
  const bounds=new Tmapv2.LatLngBounds();
  const limits={west:Infinity,south:Infinity,east:-Infinity,north:-Infinity};
  function extend(coords){
    if(typeof coords[0]==='number'){
      bounds.extend(latlng(coords));
      limits.west=Math.min(limits.west,coords[0]);limits.east=Math.max(limits.east,coords[0]);
      limits.south=Math.min(limits.south,coords[1]);limits.north=Math.max(limits.north,coords[1]);
    }else coords.forEach(extend);
  }
  extend(data.campus.coordinates);map.fitBounds(bounds);
  document.getElementById('home').onclick=()=>map.fitBounds(bounds);
  if(guidance&&guidance.is_demo&&guidance.origin){
    map.setCenter(new Tmapv2.LatLng(guidance.origin.latitude,guidance.origin.longitude));map.setZoom(17);
  }
  const location=data.userLocation;
  if(location){
    const position=new Tmapv2.LatLng(location.latitude,location.longitude);
    if(location.accuracy>0)new Tmapv2.Circle({center:position,radius:location.accuracy,
      fillColor:'#3b82f6',fillOpacity:0.10,strokeColor:'#2563eb',strokeWeight:1,map:map});
    const accuracyText=location.accuracy===null?'':(' · 위치 오차 약 '+Math.round(location.accuracy)+'m');
    new Tmapv2.Marker({position:position,map:map,title:'현재 위치'+accuracyText,
      iconHTML:'<div style="width:18px;height:18px;background:#2563eb;border:4px solid white;border-radius:50%;box-shadow:0 0 0 2px #2563eb,0 2px 8px #163d3266" aria-label="현재 위치"></div>'});
    const focusLocation=()=>{map.setCenter(position);map.setZoom(17);};
    const myLocation=document.getElementById('my-location');
    myLocation.disabled=false;myLocation.onclick=focusLocation;
    const nearestLat=Math.max(limits.south,Math.min(limits.north,location.latitude));
    const nearestLng=Math.max(limits.west,Math.min(limits.east,location.longitude));
    const dx=(location.longitude-nearestLng)*111320*Math.cos(location.latitude*Math.PI/180);
    const dy=(location.latitude-nearestLat)*111320;
    if(Math.hypot(dx,dy)<=1000)focusLocation();
  }
  if(guidance&&guidance.route&&guidance.route.features.length){
    const routeLimits={west:Infinity,south:Infinity,east:-Infinity,north:-Infinity};
    function routeExtent(coords){
      if(typeof coords[0]==='number'){
        routeLimits.west=Math.min(routeLimits.west,coords[0]);routeLimits.east=Math.max(routeLimits.east,coords[0]);
        routeLimits.south=Math.min(routeLimits.south,coords[1]);routeLimits.north=Math.max(routeLimits.north,coords[1]);
      }else coords.forEach(routeExtent);
    }
    guidance.route.features.forEach(feature=>routeExtent(feature.geometry.coordinates));
    map.fitBounds(new Tmapv2.LatLngBounds(
      new Tmapv2.LatLng(routeLimits.south-.00025,routeLimits.west-.0003),
      new Tmapv2.LatLng(routeLimits.north+.00025,routeLimits.east+.0003)));
  }
  function toggle(group,visible){group.forEach(item=>item.setMap(visible?map:null));}
  document.getElementById('show-buildings').onchange=event=>toggle(groups.buildings,event.target.checked);
  document.getElementById('show-shadows').onchange=event=>toggle(groups.shadows,event.target.checked);
  document.getElementById('show-walkways').onchange=event=>toggle(groups.walkways,event.target.checked);
  if(data.allowTreeEdit){
  let drawing=false,points=[],preview=null;
  function reset(){drawing=false;points=[];if(preview) preview.setMap(null);preview=null;}
  document.getElementById('start').onclick=()=>{reset();drawing=true;status.textContent='수관의 꼭짓점을 순서대로 클릭한 후 완료를 누르세요.';};
  document.getElementById('cancel').onclick=()=>{reset();status.textContent='그리기를 취소했습니다.';};
  map.addListener('click',event=>{
    if(!drawing)return;
    points.push([event.latLng.lng(),event.latLng.lat()]);
    if(preview)preview.setMap(null);
    preview=new Tmapv2.Polyline({path:points.map(latlng),strokeColor:'#16a34a',strokeWeight:3,map:map});
    status.textContent=points.length+'개 꼭짓점 선택됨';
  });
  document.getElementById('finish').onclick=()=>{
    if(!drawing||points.length<3){status.textContent='꼭짓점을 세 개 이상 선택하세요.';return;}
    const geometry={type:'Polygon',coordinates:[[...points,points[0]]]};
    data.trees.features.push({type:'Feature',geometry:geometry,properties:{tree_id:'TREE-'+Date.now()+'-'+Math.random().toString(16).slice(2,8),height_m:data.treeHeight}});
    drawGeometry(geometry,{fillColor:'#16a34a',fillOpacity:0.2,strokeColor:'#16a34a',strokeWeight:2},map);
    reset();status.textContent='수관을 추가했습니다. 다운로드 후 앱에서 불러와 저장하세요. 캠퍼스 범위와 도형 유효성은 저장할 때 검사합니다.';
  };
  document.getElementById('download').onclick=()=>{
    if(drawing){status.textContent='먼저 그리기를 완료하거나 취소하세요.';return;}
    const url=URL.createObjectURL(new Blob([JSON.stringify(data.trees)],{type:'application/geo+json'}));
    const a=document.createElement('a');a.href=url;a.download='tree_canopies.geojson';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  ['start','finish','cancel','download'].forEach(id=>document.getElementById(id).disabled=false);
  }
  loaded=true;clearTimeout(timeout);
  document.getElementById('map-controls').disabled=false;
  if(!tileFailed)status.textContent='';
 }catch(error){
    fail(mapReady);
 }
}
</script>
<!-- TMAP v2's loader uses document.write for its dependencies. It must execute
     as a parser-inserted script; dynamic/async injection drops those scripts. -->
<script src="__SDK_URL_HTML__" onerror="fail()"></script>
<script>initialize();</script>
</body></html>"""
    return (
        template
        .replace('__PAYLOAD__', payload)
        .replace('__SDK_URL_HTML__', html.escape(sdk_url,quote=True))
        .replace('__MAP_HEIGHT__',str(map_height))
        .replace('__TREE_EDITOR_HTML__',tree_editor)
    )

def _map_height(value):
    try:
        return max(320,min(1600,int(value)))
    except (TypeError,ValueError,OverflowError):
        return 650


def render_tmap(*args,**kwargs):
    map_height=_map_height(kwargs.get('map_height',650))
    st.iframe(map_html(*args,**kwargs),height=map_height+116,width='stretch')
