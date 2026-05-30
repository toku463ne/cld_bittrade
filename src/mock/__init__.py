"""Mock layer for development and testing.

All development and testing run through this layer. The live bitFlyer API is
reached only when ``USE_LIVE_API=true`` (see :mod:`src.data.feed`). The mock
faithfully reproduces the real REST/WS response schema.
"""
