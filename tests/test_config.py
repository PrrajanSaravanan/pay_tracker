from paytracker.config import Settings


def test_settings_defaults():
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql://")
