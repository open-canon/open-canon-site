"""Fixtures providing a tiny offline mock of the churchofjesuschrist.org Study API."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from lds_fake_site import FakeSite


@pytest.fixture
def site() -> FakeSite:
    """Provide an empty `FakeSite` whose ``pages`` tests may override."""
    return FakeSite()


@pytest.fixture
def make_client() -> Callable[[Callable[[httpx.Request], httpx.Response]], httpx.AsyncClient]:
    """Provide a factory building an ``httpx.AsyncClient`` backed by a mock handler."""

    def factory(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
        """Wrap a handler in an async client.

        Args:
            handler: Function answering each request.

        Returns:
            A client that never touches the network.
        """
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory
