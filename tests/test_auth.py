import pytest


@pytest.mark.asyncio
async def test_register(client):
    res = await client.post("/auth/register", json={
        "email": "test@example.com",
        "password": "password123",
        "full_name": "Test User",
    })
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_register_duplicate(client):
    await client.post("/auth/register", json={"email": "dup@example.com", "password": "pw"})
    res = await client.post("/auth/register", json={"email": "dup@example.com", "password": "pw"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_login(client):
    await client.post("/auth/register", json={"email": "login@example.com", "password": "pw123"})
    res = await client.post("/auth/login", json={"email": "login@example.com", "password": "pw123"})
    assert res.status_code == 200
    assert "access_token" in res.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/auth/register", json={"email": "wp@example.com", "password": "correct"})
    res = await client.post("/auth/login", json={"email": "wp@example.com", "password": "wrong"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client):
    reg = await client.post("/auth/register", json={"email": "me@example.com", "password": "pw123"})
    token = reg.json()["access_token"]
    res = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["email"] == "me@example.com"


@pytest.mark.asyncio
async def test_refresh_token(client):
    reg = await client.post("/auth/register", json={"email": "refresh@example.com", "password": "pw"})
    rt = reg.json()["refresh_token"]
    res = await client.post("/auth/refresh", json={"refresh_token": rt})
    assert res.status_code == 200
    assert "access_token" in res.json()
