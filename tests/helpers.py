"""Deterministic campus coordinates used only by tests."""
from shapely.ops import transform, unary_union

from hufs_shadow.shadow_model import TO_G, TO_M


def campus_origin(scene):
    ground = transform(TO_M, scene['campus']).difference(unary_union([
        transform(TO_M, geometry) for geometry in scene['all_building_footprints']]).buffer(.1))
    point = transform(TO_G, ground.representative_point())
    return {'latitude': point.y, 'longitude': point.x}
