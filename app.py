from datetime import datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path
import json, copy, html, os
from urllib.parse import quote
import numpy as np
import pandas as pd
import pvlib
import folium
from folium.plugins import Draw
from tree_model import load_trees, save_trees, new_tree, canopy_shadow
from shapely.geometry import shape, mapping
from shapely.ops import transform
from streamlit_folium import st_folium
import streamlit as st
from shadow_model import raster_shadows, TO_G
from gis_buildings import load_gis
from building_matches import load_matching, save_matching, apply_matching
from gis_scene import build_scene, flat_shade, select_major_buildings
from public_buildings import PublicDataError, save_json

ROOT=Path(__file__).parent
KST=ZoneInfo('Asia/Seoul')
st.set_page_config(page_title='HUFS 캠퍼스 GIS 그늘지도',page_icon='🌳',layout='wide')
st.title('🌳 HUFS 캠퍼스 GIS 그늘지도')
st.info('건물 데이터 소스: GIS건물통합정보')
campus=shape(json.loads((ROOT/'data/campus_boundary.geojson').read_text())['geometry'])
center=[campus.centroid.y,campus.centroid.x]
with st.sidebar:
    st.header('배경지도')
    vworld_key=st.text_input('VWorld API 키',value=os.environ.get('VWORLD_API_KEY',''),type='password',help='세션 입력 또는 VWORLD_API_KEY 환경변수. 파일에는 저장하지 않습니다.')
    if not vworld_key.strip():
        st.info('항공영상은 VWorld API 키 입력 후 지도 오른쪽 레이어 메뉴에서 선택할 수 있습니다.')
        st.markdown('[VWorld 개발자 안내](https://www.vworld.kr/dev/v4dv_wmtsguide2_s001.do)에서 키를 발급하고, 사용 URL에 현재 접속 주소(http://127.0.0.1:8501)를 등록하세요.')
    else:
        st.caption('지도 오른쪽 레이어 메뉴 → VWorld Satellite 항공영상. 영상이 안 나오면 키의 사용 URL·권한·사용 한도를 확인하세요.')
    st.header('계산 조건')
    day=st.date_input('날짜',datetime.now(KST).date())
    clock=st.time_input('시간',time(12),step=900)
    mode=st.radio('지형 처리',['평지 건물 그림자','지형 고도 반영 (거친 근사)'])
    include_unknown=st.checkbox('높이 미등록 건물도 가정값으로 계산',value=True)
    fallback=st.number_input('미등록 건물 가정 높이 (m)',1.,200.,15.,1.)
    floor_height=st.number_input('층당 높이 (m)',2.,6.,3.,0.1)
    refresh=st.button('SHP 자료 다시 읽기')
    st.caption('A16 등록 높이 → A26 × 층당 높이 → 가정값. 사용자 연결 시 표제부 높이 또는 층수가 적용됩니다.')
try:
    cache=load_gis(ROOT/'data/public_buildings',campus,ROOT/'data/gis_buildings_cache.json',refresh=refresh)
except (PublicDataError,OSError) as error:
    st.error(f'GIS 자료를 읽을 수 없습니다: {error}')
    st.stop()
features=[f for f in cache['normalized']['features'] if shape(f['geometry']).intersects(campus)]
if not features:
    st.error('캠퍼스와 겹치는 GIS 건물이 없습니다.')
    st.stop()
all_features=features
_,filter_audit=select_major_buildings(all_features)
small=[r for r in filter_audit if not r['기본 포함']]
labels={r['GIS ID']:f"{r['건물']} · {r['면적 (m²)']:.1f} m² · {r['GIS ID']}" for r in small}
with st.expander('작은 건물 다시 포함'):
    st.caption('EPSG:5186 면적 100 m² 미만의 이름 없는 건물만 기본 제외합니다. 원본 건물은 보존됩니다.')
    restored=st.multiselect('다시 포함할 건물',options=list(labels),format_func=lambda key:labels[key],key='restored_gis_buildings')
features,filter_audit=select_major_buildings(all_features,included_ids=restored)
for col,label,value in zip(st.columns(3),['필터 적용 전','제외된 건물','최종 사용 건물'],
                           [len(all_features),len(all_features)-len(features),len(features)]):
    col.metric(label,value)
default_features,_=select_major_buildings(all_features)
number_order=sorted(default_features,key=lambda f:f['properties']['public_id'])+sorted([f for f in all_features if f['properties']['public_id'] not in {x['properties']['public_id'] for x in default_features}],key=lambda f:f['properties']['public_id'])
numbers={f['properties']['public_id']:i+1 for i,f in enumerate(number_order) if f['properties']['public_id'] in {x['properties']['public_id'] for x in features}}
try:
    title_records, automatic, manual_links=load_matching(ROOT,all_features)
except (ValueError,OSError,KeyError) as error:
    st.error(f'건물 연결 자료 오류: {error}')
    st.stop()
with st.expander('미매칭 자료 → 지도 건물 번호 연결',expanded=True):
    st.caption('자동 매칭 6개는 기존 GIS 높이·층수를 유지하며 잠깁니다. PNU와 이름의 유일 일치 검증표 기준이며 PK 전환 매칭이 아닙니다.')
    used_records=set(automatic.values()) | {x['record_pk'] for x in manual_links}
    remaining={pk:t for pk,t in title_records.items() if pk not in used_records}
    st.dataframe(pd.DataFrame([{'PK':pk,'건물명':t['건물_명'],'동명칭':t['동_명'],'높이(m)':t['높이(m)'],'지상층수':t['지상_층_수']} for pk,t in remaining.items()]),hide_index=True)
    occupied=set(automatic) | {x['gis_id'] for x in manual_links}
    available=[gid for gid in numbers if gid not in occupied]
    usable=[pk for pk,t in remaining.items() if float(t['높이(m)'] or 0)>0 or float(t['지상_층_수'] or 0)>0]
    if usable and available:
        chosen=st.selectbox('미매칭 데이터 레코드',usable,format_func=lambda pk:f"{title_records[pk]['건물_명']} {title_records[pk]['동_명']} · {pk}")
        target=st.selectbox('연결할 GIS polygon 번호',available,format_func=lambda gid:f"{numbers[gid]}번 · {gid}")
        if st.button('선택한 연결 저장'):
            try:
                save_matching(ROOT/'data/manual_matches.csv',manual_links+[{'record_pk':chosen,'gis_id':target}],automatic,title_records,{f['properties']['public_id'] for f in all_features})
                st.rerun()
            except (ValueError,OSError) as error: st.error(str(error))
    if manual_links:
        st.dataframe(pd.DataFrame([dict(x,지도번호=numbers.get(x['gis_id'],'현재 제외')) for x in manual_links]),hide_index=True)
        remove=st.selectbox('해제할 사용자 연결',[x['gis_id'] for x in manual_links],format_func=lambda gid:f"{numbers.get(gid,'제외')}번 · {gid}")
        if st.button('사용자 연결 해제'):
            save_matching(ROOT/'data/manual_matches.csv',[x for x in manual_links if x['gis_id']!=remove],automatic,title_records,{f['properties']['public_id'] for f in all_features})
            st.rerun()
features=apply_matching(features,title_records,automatic,manual_links)
buildings,records=build_scene(features,{},floor_height,fallback,include_unknown)
for record in records: record['지도 번호']=numbers[record['GIS ID']]
st.write(' · '.join(f"{status} {sum(r['매칭 상태']==status for r in records)}개" for status in ['자동 매칭','사용자 매칭','미매칭']))
table=pd.DataFrame(records)
counts={source:sum(r['높이 근거']==source for r in records) for source in ('A16 실제 높이','A26 층수 기반','fallback','사용자 입력','계산 제외')}
for col,label,value in zip(st.columns(4),['GIS 건물 수','A16 사용 수','A26 기반 수','fallback 수'],
                           [len(features),counts['A16 실제 높이'],counts['A26 층수 기반'],counts['fallback']]):
    col.metric(label,value)
st.caption(f"표제부 실제높이 {sum(r['높이 근거']=='표제부 실제높이' for r in records)}개 · 표제부 층수 기반 {sum(r['높이 근거']=='표제부 층수 기반' for r in records)}개 · 사용자 입력 {counts['사용자 입력']}개 · 계산 제외 {counts['계산 제외']}개 · 캠퍼스 polygon과 교차하는 GIS 도형만 표시")
moment=datetime.combine(day,clock,tzinfo=KST)
solar=pvlib.solarposition.get_solarposition(pd.DatetimeIndex([moment]),*center).iloc[0]
elevation,azimuth=float(solar.apparent_elevation),float(solar.azimuth)
st.write(f'**{moment:%Y-%m-%d %H:%M} KST** · 태양 고도 **{elevation:.1f}°** · 방위각 **{azimuth:.1f}°**')
tree_path=ROOT/'data/tree_canopies.geojson'
try:
    trees=load_trees(tree_path,campus)
except (ValueError,KeyError,OSError,TypeError) as error:
    st.error(f'수관 자료 오류: {error}')
    st.stop()
with st.expander('시험 구역 나무 수관 입력',expanded=True):
    st.caption('지도 왼쪽 다각형 도구로 수관 윤곽을 그린 뒤 저장하세요. 윤곽이 형태와 크기를 정합니다. 수관을 나무 꼭대기의 불투명한 수평 면으로 가정합니다.')
    tree_height=st.number_input('새 나무 높이 (m)',0.5,80.0,8.0,0.5)
    if trees['features']:
        st.dataframe(pd.DataFrame([f['properties'] for f in trees['features']]),hide_index=True)
        tree_id=st.selectbox('수정할 나무 ID',[f['properties']['tree_id'] for f in trees['features']])
        updated_height=st.number_input('선택한 나무의 새 높이 (m)',0.5,80.0,8.0,0.5)
        if st.button('선택한 나무 높이 저장'):
            for f in trees['features']:
                if f['properties']['tree_id']==tree_id:f['properties']['height_m']=updated_height
            save_trees(tree_path,trees,campus);st.rerun()
        if st.button('선택한 수관 삭제'):
            trees['features']=[f for f in trees['features'] if f['properties']['tree_id']!=tree_id]
            save_trees(tree_path,trees,campus);st.rerun()
    upload=st.file_uploader('수관 GeoJSON 불러오기',type=['geojson','json'])
    if upload is not None and st.button('불러온 수관으로 교체 저장'):
        try:save_trees(tree_path,json.loads(upload.getvalue()),campus);st.rerun()
        except (ValueError,KeyError,TypeError) as error:st.error(str(error))
    st.download_button('수관 GeoJSON 다운로드',json.dumps(trees,ensure_ascii=False),'tree_canopies.geojson','application/geo+json')
    st.caption('나무 그림자는 벡터 방식의 국소 평지 근사입니다. ASTER 모드에서도 나무 그림자의 경사·지형 차폐는 아직 반영하지 않습니다. ASTER에 수목 영향이 포함되면 이중 계산될 수 있습니다.')
m=folium.Map(location=center,zoom_start=16,tiles='OpenStreetMap',max_zoom=19)
if vworld_key.strip():
    folium.TileLayer(
        tiles='https://api.vworld.kr/req/wmts/1.0.0/'+quote(vworld_key.strip(),safe='')+'/Satellite/{z}/{y}/{x}.jpeg',
        name='VWorld Satellite 항공영상',
        attr='&copy; <a href="https://www.vworld.kr/">VWorld</a> · 국토교통부',
        overlay=False,control=True,show=False,max_zoom=19,max_native_zoom=19,
    ).add_to(m)
west,south,east,north=campus.bounds
m.fit_bounds([[south,west],[north,east]])
folium.GeoJson(mapping(campus),name='캠퍼스 경계',style_function=lambda _:{
    'color':'#10b981','fillOpacity':0,'weight':2,'dashArray':'6 4'}).add_to(m)
if elevation<3:
    st.info('태양 고도가 3° 미만이므로 그림자를 표시하지 않습니다.')
elif mode.startswith('지형'):
    path=ROOT/'data/terrain.npz'
    if not path.exists():
        st.error('지형 자료가 없습니다. 평지 건물 그림자를 선택하세요.')
    else:
        with np.load(path) as dem:
            terrain=(dem['x'],dem['y'],dem['z'])
        @st.cache_data(max_entries=12,show_spinner='GIS 건물과 ASTER 지형 그늘 계산 중…')
        def terrain_result(campus_json,geometries,heights,terrain,elev,az):
            return raster_shadows(shape(campus_json),[(shape(g),h) for g,h in zip(geometries,heights)],terrain,elev,az)
        result=terrain_result(mapping(campus),[f['geometry'] for f in features],
                              [h for _,h in buildings],terrain,elevation,azimuth)
        folium.raster_layers.ImageOverlay(result['image'],bounds=result['bounds'],
            name='지형·건물 그늘 (근사)',opacity=0.85,mercator_project=True).add_to(m)
        st.caption(f'지형 모드 추정 그늘 면적 {result["shaded_area"]:,.0f} m²')
        st.caption('ASTER 원자료 약 30m, 조회 간격 60m, 계산 격자 10m, 탐색 거리 최대 600m. 좁은 길·계단 분석에는 부족합니다.')
else:
    @st.cache_data(max_entries=24,show_spinner=False)
    def planar_result(campus_json,geometries,heights,elev,az):
        shade=flat_shade(shape(campus_json),[(shape(g),h) for g,h in zip(geometries,heights)],elev,az)
        return mapping(transform(TO_G,shade)),shade.area
    shade_geojson,shade_area=planar_result(mapping(campus),[f['geometry'] for f in features],
                                          [h for _,h in buildings],elevation,azimuth)
    if not shape(shade_geojson).is_empty:
        folium.GeoJson(shade_geojson,name='평지 건물 그림자',style_function=lambda _:{
            'color':'#7c3aed','weight':0,'fillOpacity':0.45}).add_to(m)
    st.caption(f'평지 그늘 면적 {shade_area:,.0f} m² · 건물 바닥 제외 · 캠퍼스 범위로 자름')
tree_shade=canopy_shadow(trees,campus,elevation,azimuth,buildings)
if not tree_shade.is_empty:
    folium.GeoJson(mapping(transform(TO_G,tree_shade)),name='나무 그림자 · 벡터',style_function=lambda _:{'color':'#166534','weight':0,'fillOpacity':0.5}).add_to(m)
    if not mode.startswith('지형') and elevation>=3:
        from shapely.ops import unary_union
        combined=unary_union([shape(shade_geojson),transform(TO_G,tree_shade)])
        folium.GeoJson(mapping(combined),name='건물+나무 통합 그늘',show=False,style_function=lambda _:{'color':'#334155','weight':0,'fillOpacity':0.5}).add_to(m)
if trees['features']:
    folium.GeoJson(trees,name='나무 수관',style_function=lambda _:{'color':'#16a34a','weight':2,'fillOpacity':0.12},tooltip=folium.GeoJsonTooltip(fields=['tree_id','height_m','canopy_area_m2'])).add_to(m)
Draw(export=False,draw_options={'polyline':False,'rectangle':False,'circle':False,'circlemarker':False,'marker':False,'polygon':{'allowIntersection':False}},edit_options={'edit':False,'remove':False}).add_to(m)
layer=folium.FeatureGroup(name=f'GIS 건물 윤곽 ({len(features)}개)')
for f,r in zip(features,records):
    point=shape(f['geometry']).representative_point()
    folium.Marker([point.y,point.x],icon=folium.DivIcon(html=f'<div style="background:white;border:1px solid #333;border-radius:10px;text-align:center;font-weight:bold;width:24px;">{numbers[r["GIS ID"]]}</div>')).add_to(layer)
    props={'지도 번호':numbers[r['GIS ID']],'매칭 상태':r['매칭 상태'],'표제부 PK':r['표제부 PK'],'건물':html.escape(r['건물']),'GIS ID':r['GIS ID'],
           'A16':r['A16'] if r['A16'] is not None else '미등록',
           'A26':r['A26'] if r['A26'] is not None else '미등록',
           '최종 높이 (m)':r['최종 높이 (m)'] if r['최종 높이 (m)'] is not None else '계산 제외',
           '높이 근거':r['높이 근거']}
    color='#2563eb' if r['높이 근거'] in ('A16 실제 높이','사용자 입력') else '#d97706'
    folium.GeoJson({'type':'Feature','id':f['id'],'geometry':f['geometry'],'properties':props},
        style_function=lambda _,c=color:{'color':c,'weight':1,'fillColor':c,'fillOpacity':0.3},
        tooltip=folium.GeoJsonTooltip(fields=list(props))).add_to(layer)
layer.add_to(m)
folium.LayerControl(collapsed=False).add_to(m)
drawing=st_folium(m,height=610,use_container_width=True,returned_objects=['all_drawings'],key='gis_primary_campus')
if st.button('지도에 그린 새 수관 저장'):
    drawings=(drawing or {}).get('all_drawings') or []
    try:
        known={json.dumps(f['geometry'],sort_keys=True) for f in trees['features']}
        added=0
        for item in drawings:
            geom=item['geometry'];signature=json.dumps(geom,sort_keys=True)
            if signature not in known:
                trees['features'].append(new_tree(geom,tree_height,campus));known.add(signature);added+=1
        if added:save_trees(tree_path,trees,campus);st.rerun()
        else:st.info('새 수관 다각형을 그려주세요. 이미 저장된 윤곽은 중복 저장하지 않습니다.')
    except (ValueError,KeyError,TypeError) as error:st.error(str(error))
st.caption('파랑: A16·직접 입력 / 주황: 층수 추정·가정값 / 보라: 그림자. GIS와 배경지도는 제작 시점·정확도가 달라 일부 윤곽 차이가 있을 수 있습니다.')
enriched={'type':'FeatureCollection','features':copy.deepcopy(features),'campus':mapping(campus),
          'metadata':dict(cache['metadata'],floor_height_m=floor_height,fallback_m=fallback,minimum_footprint_m2=100,area_crs='EPSG:5186',included_ids=restored,filter_audit=filter_audit)}
for f,r in zip(enriched['features'],records):f['properties']['height_result']=r
with st.expander('GIS 건물 자료 · 다운로드'):
    st.dataframe(table,hide_index=True,width='stretch')
    st.download_button('건물별 높이·근거 CSV 다운로드',table.to_csv(index=False).encode('utf-8-sig'),'hufs_gis_heights.csv','text/csv')
    st.download_button('GIS 윤곽·적용 높이 GeoJSON 다운로드',json.dumps(enriched,ensure_ascii=False,allow_nan=False),'hufs_gis_buildings.geojson','application/geo+json')
    if st.button('현재 GIS 결과 저장'):
        save_json(ROOT/'data/gis_buildings_applied.geojson',enriched)
        st.success('저장했습니다.')
    st.caption('등록 높이는 현장 실측 보증이 아닙니다. 건물은 수직 벽·평평한 지붕으로 단순화하며 구름과 수관의 빛 투과율·계절 변화는 계산하지 않습니다.')
