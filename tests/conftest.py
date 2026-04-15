"""Shared test fixtures"""
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def mock_db_session():
    """Mock database session for unit tests that don't need real DB"""
    pass


@pytest.fixture
def mock_session():
    """Provide a mock SQLAlchemy session"""
    session = MagicMock()
    session.query.return_value = session
    session.filter.return_value = session
    session.filter_by.return_value = session
    session.all.return_value = []
    session.first.return_value = None
    session.count.return_value = 0
    return session
