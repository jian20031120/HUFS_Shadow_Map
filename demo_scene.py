"""Keep unresolved geometry in the audit, outside every shadow calculation."""


def resolved_buildings(buildings):
    """Return scene entries with a known height, preserving their input order.

    Passing this same list to planar, terrain and canopy calculations ensures
    unresolved outlines cannot remove otherwise usable ground or shade.
    """
    return [(geometry, height) for geometry, height in buildings if height is not None]
