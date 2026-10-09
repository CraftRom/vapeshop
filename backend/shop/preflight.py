"""Check the effective image environment without DB migrations or services."""


def main() -> None:
    from cryptography.fernet import Fernet
    from shop.config import settings

    settings.validate_production_security()
    missing = settings.missing_required()
    if missing:
        raise SystemExit("В image бракує обов’язкових налаштувань: " + ", ".join(missing))
    if not settings.data_encryption_key:
        raise SystemExit("DATA_ENCRYPTION_KEY порожній")
    try:
        Fernet(settings.data_encryption_key.encode())
    except (ValueError, TypeError):
        raise SystemExit("DATA_ENCRYPTION_KEY має бути коректним ключем Fernet") from None
    import api.main  # noqa: F401 — import contracts, CORS and Host policies
    print("backend pre-start smoke: OK")


if __name__ == "__main__":
    main()
