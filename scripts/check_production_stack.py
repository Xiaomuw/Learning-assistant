"""Exercise only the disposable la-prod-ci Compose project, including dump/restore."""
import json
import subprocess
import time
import urllib.error
import urllib.request

COMPOSE = ["docker", "compose", "-p", "la-prod-ci", "-f", "docker-compose.prod.yml"]


def request(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
            return response.status, response.read(2048)
    except urllib.error.HTTPError as error:
        return error.code, error.read(2048)


def main():
    expected = {("postgres", "5432"): "127.0.0.1:55432",
                ("backend", "8000"): "127.0.0.1:58000",
                ("frontend", "3000"): "127.0.0.1:53000"}
    for (service, port), binding in expected.items():
        actual = subprocess.check_output(COMPOSE + ["port", service, port], text=True).strip()
        assert actual == binding, (service, actual)
    for attempt in range(100):
        try:
            status, body = request(58000, "/health")
            if status == 200 and json.loads(body)["status"] == "ok" and request(53000, "/login")[0] == 200:
                break
        except (OSError, ValueError):
            pass
        time.sleep(2)
    else:
        raise RuntimeError("Disposable production-image stack never became healthy")
    assert request(53000, "/api/auth/me")[0] == 401
    postgres = COMPOSE + ["exec", "-T", "postgres"]
    sql = postgres + ["psql", "-U", "la_ci", "-d", "la_release_ci", "-v", "ON_ERROR_STOP=1", "-Atc"]
    subprocess.run(sql + ["CREATE TABLE release_restore_fixture (id integer PRIMARY KEY, value text); "
                          "INSERT INTO release_restore_fixture VALUES (1, 'original synthetic arithmetic');"], check=True)
    dump = subprocess.check_output(postgres + ["pg_dump", "-U", "la_ci", "-d", "la_release_ci", "-Fc"])
    subprocess.run(postgres + ["createdb", "-U", "la_ci", "la_restore_ci"], check=True)
    subprocess.run(postgres + ["pg_restore", "-U", "la_ci", "-d", "la_restore_ci", "--exit-on-error"], input=dump, check=True)
    restored = subprocess.check_output(postgres + ["psql", "-U", "la_ci", "-d", "la_restore_ci", "-Atc",
        "SELECT count(*) FROM release_restore_fixture WHERE value='original synthetic arithmetic';"], text=True)
    assert restored.strip() == "1"
    print("PASS: production Dockerfiles, migration, health, proxy auth, loopback ports and synthetic pg_dump/restore")


if __name__ == "__main__":
    main()
