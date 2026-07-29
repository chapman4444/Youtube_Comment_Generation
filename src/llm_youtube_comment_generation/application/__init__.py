"""Use-case orchestration.

Depends on domain objects and ports. Never on a concrete adapter: a handler
that imported `requests` could not be tested without a network.
"""
