def test_localhost_3001_is_allowed_for_dev_frontend(client):
    response = client.options(
        "/api/v1/projects",
        headers={
            "Origin": "http://localhost:3001",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3001"
