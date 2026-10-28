from tests.conftest import auth_header, register


async def test_health(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok", "redis": "ok"}


async def test_register_login_refresh_me(client) -> None:  # type: ignore[no-untyped-def]
    data = await register(client, "Alice@Example.com")
    assert data["user"]["email"] == "alice@example.com"
    r = await client.get("/api/v1/auth/me", headers=auth_header(data))
    assert r.status_code == 200 and r.json()["email"] == "alice@example.com"

    r = await client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "secret123"})
    assert r.status_code == 200
    refresh = r.json()["tokens"]["refresh_token"]
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200 and r.json()["access_token"]

    # an access token is not a refresh token
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["tokens"]["access_token"]})
    assert r.status_code == 401


async def test_register_validation_and_duplicates(client) -> None:  # type: ignore[no-untyped-def]
    await register(client, "bob@example.com")
    r = await client.post("/api/v1/auth/register", json={"email": "BOB@example.com", "password": "secret123"})
    assert r.status_code == 409
    r = await client.post("/api/v1/auth/register", json={"email": "c@example.com", "password": "short"})
    assert r.status_code == 422
    r = await client.post("/api/v1/auth/register", json={"email": "c@example.com", "password": "onlyletters"})
    assert r.status_code == 422
    r = await client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "secret123"})
    assert r.status_code == 422


async def test_login_wrong_password_and_protected_routes(client) -> None:  # type: ignore[no-untyped-def]
    await register(client, "carol@example.com")
    r = await client.post("/api/v1/auth/login", json={"email": "carol@example.com", "password": "wrong123"})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong123"})
    assert r.status_code == 401
    assert (await client.get("/api/v1/portfolio")).status_code == 401
    bad = {"Authorization": "Bearer nonsense"}
    assert (await client.get("/api/v1/portfolio", headers=bad)).status_code == 401
