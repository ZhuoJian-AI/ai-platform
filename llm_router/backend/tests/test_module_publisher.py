"""Compatibility coverage for the retired module publisher."""


async def test_old_module_publisher_returns_chinese_410(client):
    response = await client.post("/api/v1/module-publisher/repositories", json={})

    assert response.status_code == 410
    detail = response.json()["detail"]
    assert detail["code"] == "feature_retired"
    assert detail["retryable"] is False
    assert "旧 GitHub/Coolify 模块发布器已下线" in detail["message"]
