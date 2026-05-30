"""Signal detectors.

Each detector inherits from :class:`src.signs.base.Sign` and produces directional
fire events on a bar series. Detectors are vectorised (operate on a DataFrame)
so they can be used both for the per-fire benchmark pipeline and, incrementally,
by strategies.

Register new detectors in :mod:`src.signs.registry`.
"""
