"""Market-data layer: feed, OHLCV aggregation, collection and cache.

This is the ONLY place external bitFlyer API calls are made. Everything routes
through the mock layer unless ``USE_LIVE_API=true``.
"""
