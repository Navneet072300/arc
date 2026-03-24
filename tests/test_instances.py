import pytest


async def _register_and_token(client, email="inst@example.com", password="pw123"):
    reg = await client.post("/auth/register", json={"email": email, "password": password})
    return reg.json()["access_token"]


@pytest.mark.asyncio
async def test_create_instance(client, mock_provisioner):
    token = await _register_and_token(client, "create@example.com")
    res = await client.post(
        "/instances",
        json={"name": "my-db", "pg_version": "16"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 202
    data = res.json()
    assert data["name"] == "my-db"
    assert data["status"] == "provisioning"
    assert "password" in data  # shown once


@pytest.mark.asyncio
async def test_list_instances(client, mock_provisioner):
    token = await _register_and_token(client, "list@example.com")
    await client.post("/instances", json={"name": "db-one"}, headers={"Authorization": f"Bearer {token}"})
    res = await client.get("/instances", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert len(res.json()) >= 1


@pytest.mark.asyncio
async def test_get_instance(client, mock_provisioner):
    token = await _register_and_token(client, "get@example.com")
    created = await client.post("/instances", json={"name": "db-get"}, headers={"Authorization": f"Bearer {token}"})
    inst_id = created.json()["id"]
    res = await client.get(f"/instances/{inst_id}", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["id"] == inst_id


@pytest.mark.asyncio
async def test_delete_instance(client, mock_provisioner):
    token = await _register_and_token(client, "del@example.com")
    created = await client.post("/instances", json={"name": "db-del"}, headers={"Authorization": f"Bearer {token}"})
    inst_id = created.json()["id"]
    res = await client.delete(f"/instances/{inst_id}", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 202


@pytest.mark.asyncio
async def test_instance_name_validation(client):
    token = await _register_and_token(client, "valid@example.com")
    res = await client.post(
        "/instances",
        json={"name": "INVALID NAME!!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_cannot_access_other_users_instance(client, mock_provisioner):
    token_a = await _register_and_token(client, "usera@example.com")
    token_b = await _register_and_token(client, "userb@example.com")
    created = await client.post("/instances", json={"name": "db-a"}, headers={"Authorization": f"Bearer {token_a}"})
    inst_id = created.json()["id"]
    res = await client.get(f"/instances/{inst_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert res.status_code == 404
