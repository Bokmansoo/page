def test_seeding_and_stats(client):
    headers = {
        "X-Mock-User-Id": "user-ops-test",
        "X-Mock-Workspace-Id": "workspace-ops-test"
    }

    # 1. Initially, stats should be empty
    response = client.get("/api/v1/operations/stats", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_projects"] == 0
    assert data["summary"]["total_ai_jobs"] == 0

    # 2. Seed operations data
    seed_response = client.post("/api/v1/operations/seed", headers=headers)
    assert seed_response.status_code == 201
    seed_data = seed_response.json()
    assert seed_data["status"] == "seeded"

    # 3. Fetch stats again
    stats_response = client.get("/api/v1/operations/stats", headers=headers)
    assert stats_response.status_code == 200
    stats_data = stats_response.json()

    # Verify summary counts based on our seeded configuration
    summary = stats_data["summary"]
    assert summary["total_projects"] == 12
    assert summary["total_ai_jobs"] == 11
    # 10 successes, 1 failure => failure rate = 1/11 = 9.1%
    assert summary["ai_job_failure_rate"] == 9.1
    assert summary["ai_job_success_rate"] == 90.9
    assert summary["total_export_jobs"] == 6
    # 5 completed, 1 failed => failure rate = 1/6 = 16.7%
    assert summary["export_job_failure_rate"] == 16.7
    assert summary["export_job_success_rate"] == 83.3

    # Verify category stats
    category_stats = stats_data["category_stats"]
    assert "Fashion" in category_stats
    assert category_stats["Fashion"]["project_count"] == 3
    assert "Beauty" in category_stats
    assert category_stats["Beauty"]["project_count"] == 3
    assert "Food" in category_stats
    assert category_stats["Food"]["project_count"] == 3
    assert "Living" in category_stats
    assert category_stats["Living"]["project_count"] == 3

    # Check issues count
    # Beauty has 1 blocker (missing ingredients) + 2 blockers (vit c cream claims) + etc.
    assert category_stats["Beauty"]["blocker_count"] >= 2
    
    # 4. Verify Workspace Isolation
    other_headers = {
        "X-Mock-User-Id": "other-user",
        "X-Mock-Workspace-Id": "other-workspace"
    }
    other_stats_res = client.get("/api/v1/operations/stats", headers=other_headers)
    assert other_stats_res.status_code == 200
    other_data = other_stats_res.json()
    # Should be 0 for the other workspace
    assert other_data["summary"]["total_projects"] == 0
