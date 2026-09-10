import pytest
from kxsurv.db import connect, init_schema


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    # Most unit tests exercise controls against an explicitly prepared fixture
    # snapshot. Lifecycle tests delete or replace this marker when testing
    # missing/refreshing/failed states.
    c.execute(
        "INSERT INTO snapshot_state (state_id, status, completed_at)"
        " VALUES (1, 'ready', 'fixture')"
    )
    c.commit()
    yield c
    c.close()
