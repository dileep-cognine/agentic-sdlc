import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = session
    with TestClient(app) as test_client:
        yield test_client, engine
    app.dependency_overrides.clear()
    engine.dispose()
