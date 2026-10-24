"""Keep location-based shade suggestions inside the supplied campus polygon."""
from shapely.geometry import Point
from shapely.ops import transform

from shadow_model import TO_M


def campus_access(campus, location, max_accuracy_m=100):
    if location is None:
        return {'status': 'unavailable', 'can_recommend': False,
                'message': '내 위치로 찾기를 누르고 도착 건물을 선택해 주세요.'}
    point = transform(TO_M, Point(location['longitude'], location['latitude']))
    boundary = transform(TO_M, campus)
    accuracy = location['accuracy']
    if not boundary.contains(point) and point.distance(boundary.boundary) > accuracy:
        return {'status': 'outside', 'can_recommend': False,
                'message': '글로벌캠퍼스 밖이에요. 캠퍼스 지도 미리보기만 제공해요.'}
    if accuracy > max_accuracy_m:
        return {'status': 'inaccurate', 'can_recommend': False,
                'message': '위치 정확도가 낮아요. 휴대폰이나 야외에서 위치를 갱신해 주세요.'}
    if point.distance(boundary.boundary) <= accuracy:
        return {'status': 'boundary', 'can_recommend': False,
                'message': '캠퍼스 경계 부근이라 위치가 불확실해요. 안쪽에서 위치를 갱신해 주세요.'}
    return {'status': 'inside', 'can_recommend': True, 'message': ''}
