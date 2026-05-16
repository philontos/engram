import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """初始化一个独立的临时数据库，每个测试隔离，不影响生产数据。"""
    import app.lib.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", str(tmp_path / "test.db"))
    db_mod.init_db()
    return db_mod
