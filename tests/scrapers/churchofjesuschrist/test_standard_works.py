"""Test that the standard works scraping works as expected."""

import pytest

from open_canon_site.scrapers.churchofjesuschrist import standard_works


@pytest.mark.network
@pytest.mark.asyncio
async def test_standard_works(tmp_path) -> None:
    """Test that building the standard works does not raise any errors."""
    paths = await standard_works.build_standard_works(root_dir=tmp_path)
    assert {p.name for p in paths} == set(standard_works.SPEC.outputs)
