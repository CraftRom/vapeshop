"""Shared secret policy for deployment preflight and API startup.

Only the standard library is used so the host can check .env before building.
Error messages contain variable names and requirements, never secret values.
"""


def unsafe_secrets(jwt_secret: str, dashboard_password: str) -> list[str]:
    invalid = []
    for name, value, minimum in (
        ("JWT_SECRET", jwt_secret, 32),
        ("DASHBOARD_PASSWORD", dashboard_password, 12),
    ):
        value = value.strip().strip('"').strip("'").strip()
        if len(value) < minimum or value.lower().startswith(("change", "your_")):
            invalid.append(name)
    return invalid


def validate_production_security(public_url: str, jwt_secret: str, dashboard_password: str) -> None:
    public_url = public_url.strip().strip('"').strip("'").strip()
    if not public_url.lower().startswith("https://"):
        return
    invalid = unsafe_secrets(jwt_secret, dashboard_password)
    if invalid:
        requirements = {
            "JWT_SECRET": "JWT_SECRET: щонайменше 32 символи, без шаблонного значення",
            "DASHBOARD_PASSWORD": "DASHBOARD_PASSWORD: щонайменше 12 символів, без шаблонного значення",
        }
        raise RuntimeError(
            "Небезпечна production-конфігурація: " + "; ".join(requirements[name] for name in invalid)
            + ". Виправте .env та повторіть deploy/deploy.sh."
        )
