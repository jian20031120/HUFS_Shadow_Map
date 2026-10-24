"""TMAP JS V2 지도 위에 기존 계산 결과를 표시. 키는 디스크에 저장하지 않음."""
import base64,io,json
from urllib.parse import quote
from PIL import Image
import streamlit.components.v1 as components

def js_json(value):
    return json.dumps(value,ensure_ascii=False).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')

def map_html(app_key,center,campus,buildings,shadow=None,terrain=None):
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
    payload=js_json({'center':center,'campus':campus,'buildings':buildings,'shadow':shadow,'terrain':raster})
    template="""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<script src="__SDK_URL__"></script>
<style>body{margin:0;font:14px system-ui}#map{width:100%;height:575px}
#status{padding:10px;background:#f1f5f9;color:#334155}#credit{padding:5px;font-size:11px}
a{color:#1d4ed8}</style></head><body>
<div id="status" role="status">TMAP 지도 불러오는 중…</div><div id="map"></div>
<div id="credit">건물 윤곽: <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap 기여자 (ODbL)</a> · 지형: ASTER · 높이: 등록·입력·추정값</div>
<script>
const data=__PAYLOAD__;
const status=document.getElementById('status');
function fail(){status.textContent='TMAP을 불러오지 못했습니다. 앱 키의 지도 API 사용 권한·허용 도메인·사용량과 인터넷 연결을 확인해 주세요.';}
let loaded=false;
const timeout=setTimeout(()=>{if(!loaded) fail();},15000);
function latlng(p){return new Tmapv2.LatLng(p[1],p[0]);}
function drawGeometry(geometry,style,map){
 if(!geometry) return;
 if(geometry.type==='GeometryCollection'){geometry.geometries.forEach(g=>drawGeometry(g,style,map));return;}
 const polys=geometry.type==='Polygon'?[geometry.coordinates]:
   geometry.type==='MultiPolygon'?geometry.coordinates:[];
 polys.forEach(rings=>{
   new Tmapv2.Polygon(Object.assign({
     paths:rings.length===1?rings[0].map(latlng):rings.map(r=>r.map(latlng)),map:map
   },style));
 });
}
function initialize(){
 try{
  if(!window.Tmapv2){fail();return;}
  const map=new Tmapv2.Map('map',{center:new Tmapv2.LatLng(data.center[0],data.center[1]),
    width:'100%',height:'575px',zoom:15});
  drawGeometry(data.campus,{fillOpacity:0,strokeColor:'#10b981',strokeWeight:2},map);
  if(data.terrain){
   const b=data.terrain.bounds;
   new Tmapv2.GroundOverlay({url:data.terrain.url,
    bounds:new Tmapv2.LatLngBounds(new Tmapv2.LatLng(b[0][0],b[0][1]),new Tmapv2.LatLng(b[1][0],b[1][1])),
    opacity:0.85,map:map});
  }
  drawGeometry(data.shadow,{fillColor:'#7c3aed',fillOpacity:0.45,strokeWeight:0},map);
  data.buildings.forEach(b=>drawGeometry(b.geometry,{fillColor:b.color,fillOpacity:0.3,
    strokeColor:b.color,strokeWeight:2},map));
  loaded=true;clearTimeout(timeout);
  status.textContent='TMAP 지도 · 건물 높이와 지형의 추정 조건은 위의 안내를 확인해 주세요.';
 }catch(error){
    clearTimeout(timeout);
    console.error(error);
    status.textContent='TMAP 오류: '+error.message;
 }
}
initialize();
</script></body></html>"""
    return (
        template
        .replace('__PAYLOAD__', payload)
        .replace('__SDK_URL__', sdk_url)
    )

def render_tmap(*args,**kwargs):
    components.html(map_html(*args,**kwargs),height=650,scrolling=False)
