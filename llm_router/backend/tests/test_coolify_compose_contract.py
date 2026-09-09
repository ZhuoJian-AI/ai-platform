from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_coolify_compose_preserves_historical_database_volume_names() -> None:
    """Changing these keys makes Coolify allocate empty replacement volumes."""

    compose = (REPOSITORY_ROOT / "docker-compose.coolify.yml").read_text(encoding="utf-8")

    assert "- postgres-data:/var/lib/postgresql/data" in compose
    assert "- redis-data:/data" in compose
    assert "\n  postgres-data:\n" in compose
    assert "\n  redis-data:\n" in compose
    assert "postgres_data" not in compose
    assert "redis_data" not in compose
