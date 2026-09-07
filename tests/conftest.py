import pytest
from kxsurv.db import connect, init_schema


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    yield c
    c.close()
