"""Test that the standard works scraping works as expected."""

import pytest

import churchstudy_to_osis.standard_works.__main__


@pytest.mark.asyncio
async def test_standard_works() -> None:
    """Test that building the standard works does not raise any errors."""
    await churchstudy_to_osis.standard_works.__main__.build_standard_works()
