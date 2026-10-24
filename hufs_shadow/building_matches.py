"""Persistent, one-to-one manual links; no inferred PK conversions."""
import csv, copy
from pathlib import Path
from .data_utils import positive

def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def load_matching(root, features):
    titles = read_csv(root/'data/building_register/hufs_all_parcels_title.csv')
    records = {r['관리_건축물대장_PK']: r for r in titles}
    if len(records) != len(titles):
        raise ValueError('표제부 PK 중복: 연결을 중단합니다.')
    ids = {f['properties']['public_id'] for f in features}
    auto = {r['UFID']: r['관리_건축물대장_PK'] for r in read_csv(root/'data/building_register/hufs_all_parcels_match_check.csv')}
    if not set(auto).issubset(ids) or not set(auto.values()).issubset(records) or len(set(auto.values())) != len(auto):
        raise ValueError('자동 매칭 검증표의 식별자를 확인하세요.')
    path = root/'data/manual_matches.csv'
    manual = read_csv(path) if path.exists() else []
    validate(manual, auto, records, ids)
    return records, auto, manual

def validate(manual, auto, records, ids):
    seen_g, seen_r = set(), set()
    for link in manual:
        pk, gid = link['record_pk'], link['gis_id']
        if pk not in records or gid not in ids:
            raise ValueError('저장된 연결의 레코드 또는 GIS ID가 없습니다.')
        if gid in auto or pk in auto.values():
            raise ValueError('확정 자동 매칭은 변경할 수 없습니다.')
        if gid in seen_g or pk in seen_r:
            raise ValueError('한 레코드와 한 GIS 건물은 한 번만 연결할 수 있습니다.')
        t = records[pk]
        if positive(t['높이(m)']) is None and positive(t['지상_층_수']) is None:
            raise ValueError('높이와 층수가 모두 없는 레코드는 연결할 수 없습니다.')
        seen_g.add(gid); seen_r.add(pk)


def apply_matching(features, records, auto, manual):
    output = copy.deepcopy(features)
    links = {x['gis_id']: x['record_pk'] for x in manual}
    for f in output:
        p = f['properties']; gid = p['public_id']
        p['match_status'] = '자동 매칭' if gid in auto else ('사용자 매칭' if gid in links else '미매칭')
        p['record_pk'] = auto.get(gid, links.get(gid, ''))
        if gid in links:
            t = records[links[gid]]
            p['matched_height'] = positive(t['높이(m)'])
            p['matched_floors'] = positive(t['지상_층_수'])
    return output
