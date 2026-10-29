from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_migration_roundtrip(tmp_path, monkeypatch):
    # env.py uses the application's engine; swap it for an isolated migration database.
    import app.database

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    monkeypatch.setattr(app.database, "engine", engine)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "projects",
        "requirement_versions",
        "workflow_checkpoints",
        "analysis_versions",
        "clarification_answers",
        "graph_runtime",
    }
    command.check(config)
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_phase_one_data_survives_upgrade(tmp_path, monkeypatch):
    import app.database

    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    monkeypatch.setattr(app.database, "engine", engine)
    config = Config("alembic.ini")
    command.upgrade(config, "0001")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects VALUES "
                "('p1', 'Existing', '', 'INTAKE', 2, '2026-01-01', '2026-01-01')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO requirement_versions VALUES "
                "('r1', 'p1', 'REQ-p1', 1, 'Keep customer input', '2026-01-01')"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT text, source_data FROM requirement_versions")).one()
        assert row.text == "Keep customer input"
        assert row.source_data == "[]"
        assert connection.scalar(text("SELECT version FROM projects")) == 2
    command.check(config)
    engine.dispose()
