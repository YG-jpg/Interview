"""
Създава файловете с паролите и ключовете. Те не се пазят в git.

    python scripts/make_secrets.py

- .env            за Docker Compose: копие на .env.example със случайни пароли
- k8s/secret.env  за Kubernetes: kubectl create secret generic event-booking-secret --from-env-file=k8s/secret.env

Файл, който вече съществува, никога не се презаписва.
"""
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def write_once(path, text):
    """Записва файла само ако още го няма. Връща True, ако го е създал."""
    if path.exists():
        print(f"{path.relative_to(ROOT)} already exists, not changed.")
        return False
    path.write_text(text, encoding="utf-8")
    print(f"Created {path.relative_to(ROOT)}")
    return True


def main():
    # Случайни, криптографски сигурни стойности (модулът secrets, а не random).
    values = {
        "SECRET_KEY": secrets.token_urlsafe(50),
        "DB_PASSWORD": secrets.token_urlsafe(24),
        "DJANGO_SUPERUSER_PASSWORD": secrets.token_urlsafe(12),
    }

    # .env: настройките от .env.example, с попълнени празни пароли.
    lines = ["# Създаден от scripts/make_secrets.py. Не е в git - пази го в тайна."]
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        # Коментарите от .env.example не ги копираме.
        if line.startswith("#"):
            continue
        key = line.partition("=")[0]
        if line == f"{key}=" and key in values:
            line = f"{key}={values[key]}"
        lines.append(line)

    password = values["DJANGO_SUPERUSER_PASSWORD"]
    if write_once(ROOT / ".env", "\n".join(lines) + "\n"):
        print(f"  Docker Compose admin login: admin / {password}")
    # k8s/secret.env: само тайните стойности, за kubectl create secret.
    if write_once(ROOT / "k8s" / "secret.env", "".join(f"{k}={v}\n" for k, v in values.items())):
        print(f"  Kubernetes admin login: admin / {password}")


if __name__ == "__main__":
    main()
