"""TASK-12I.4 owned-product URL capture contracts on the production graph."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.db.models import (
    AgentRun,
    ImageGenerationCostApprovalRecord,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ProductSourceSnapshotVersion,
    ReferenceInsightVersion,
)
from src.services.product_intake_version_service import (
    OWNED_PRODUCT_URL_CAPTURE_REQUEST_SCHEMA_VERSION,
)
from src.services.url_evidence_collector import (
    OwnedProductURLCapture,
    OwnedURLCaptureError,
    URLCaptureHTTPResponse,
    UnsafeSourceURLError,
    capture_owned_product_url,
    resolve_validated_public_url_target,
)
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers


pytestmark = pytest.mark.lg12i_fake_e2e

_ACTOR_ID = "00000000-0000-0000-0000-000000000001"
_WORKSPACE_ID = "00000000-0000-0000-0000-000000000002"
_URL = "https://store.example.com/products/fan?color=white"


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


@pytest.fixture
def lg12i_runtime(monkeypatch):
    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _metadata(rights_state: str = "seller_owned") -> dict[str, object]:
    return {
        "owned_product_url_capture_request_schema_version": OWNED_PRODUCT_URL_CAPTURE_REQUEST_SCHEMA_VERSION,
        "normalized_url": _URL,
        "rights_state": rights_state,
        "provenance": "seller_submitted_owned_product_url",
    }


def _capture(
    *,
    content: str = "owned-source-v1",
    final_url: str | None = None,
    captured_at: str = "2026-08-18T01:02:03Z",
    capture_version: str = "fake-owned-capture-v1",
    parser_version: str = "fake-url-parser-v1",
    title: str = "FAN PRO JET",
    redirect_chain: tuple[str, ...] | None = None,
) -> OwnedProductURLCapture:
    final = final_url or "https://shop.example.com/product/fan"
    return OwnedProductURLCapture(
        normalized_url=_URL,
        final_url=final,
        redirect_chain=redirect_chain or (_URL, final),
        captured_at=captured_at,
        capture_version=capture_version,
        parser_version=parser_version,
        source_content_hash=sha256(content.encode()).hexdigest(),
        title=title,
        description="Seller-owned compact fan",
        image_urls=("https://cdn.example.com/fan.jpg",),
        specs=({"label": "battery", "value": "3200mAh"},),
    )


def _create_request(client, headers, project_id: str, *, rights_state: str = "seller_owned", source_url: str = _URL):
    response = client.post(
        f"/api/v1/projects/{project_id}/reference-inputs",
        headers=headers,
        json={"input_kind": "url", "source_url": source_url, "source_metadata": _metadata(rights_state)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _payload(request: dict[str, object], *, generation: str = "quick", channels: list[str] | None = None):
    return {
        "input_mode": "owned_product_url",
        "source_payload_refs": [{
            "id": request["id"],
            "kind": "owned_product_url_capture_request",
            "version": request["version"],
            "hash": request["content_hash"],
            "schema_version": OWNED_PRODUCT_URL_CAPTURE_REQUEST_SCHEMA_VERSION,
        }],
        "requested_generation_mode": generation,
        "target_channels": channels or ["smartstore", "coupang"],
    }


def _install_capture(monkeypatch, capture: OwnedProductURLCapture):
    calls: list[str] = []

    def fake(value: str):
        calls.append(value)
        return capture

    monkeypatch.setattr("src.services.product_intake_version_service.capture_owned_product_url", fake)
    return calls


def test_owned_url_capture_graph_creates_reference_only_snapshot_and_preserves_rights(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    before = {
        "jobs": db_session.query(ImageGenerationJobRecord).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).count(),
        "insights": db_session.query(ReferenceInsightVersion).count(),
    }
    request = _create_request(client, auth_headers, source_run.project_id)
    calls = _install_capture(monkeypatch, _capture())

    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json=_payload(request, generation="expert"),
    )
    assert response.status_code == 201, response.text
    # TASK-12I.8 now advances a confirmation-complete run into the frozen
    # Brief stage.  This fixture deliberately has no project Brand Kit, so it
    # stops at the explicit safe recovery state rather than inventing one.
    assert response.json()["current_stage"] == "creative_brief_blocked"
    intake = response.json()["values"]["intake"]
    assert calls == [_URL]
    assert intake["requested_generation_mode"] == "expert"
    assert intake["target_channels"] == ["coupang", "smartstore"]
    assert intake["next_action"] == "task_12i_confirmation_or_brand_recovery"
    assert intake["product_truth"]["truth_version"]["id"]
    source = intake["owned_url_source"]
    assert source["final_url"] == "https://shop.example.com/product/fan"
    assert source["rights"] == {
        "provenance": "seller_submitted_owned_product_url",
        "confirmation_state": "seller_owned",
        "final_use_status": "not_approved",
    }
    # Bounded source-backed title is now a Truth candidate; the raw capture
    # body remains reference-only.
    assert any(
        item["field_id"] == "product_identity" and item["value"] == "FAN PRO JET"
        for item in intake["product_truth"]["fact_candidates"]
    )
    assert "raw_html" not in repr(intake)
    snapshot = db_session.query(ProductSourceSnapshotVersion).filter_by(id=source["source_snapshot"]["id"]).one()
    assert snapshot.input_mode == "owned_product_url"
    assert snapshot.provenance_json["capture_request_ref"]["id"] == request["id"]
    assert snapshot.provenance_json["source_content_hash"] == _capture().source_content_hash
    assert snapshot.source_fidelity_json["content_document_ref"] == source["capture_artifact_ref"]
    assert snapshot.rights_json["final_use_status"] == "not_approved"
    assert db_session.query(ReferenceInsightVersion).count() == before["insights"]
    assert db_session.query(ImageGenerationJobRecord).count() == before["jobs"]
    assert db_session.query(ImageGenerationOutboxRecord).count() == before["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).count() == before["cost"]


def test_owned_url_same_content_reuses_snapshot_but_changed_content_creates_successor(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    first_request = _create_request(client, auth_headers, source_run.project_id)
    _install_capture(monkeypatch, _capture(content="first"))
    first = client.post(endpoint, headers=auth_headers, json=_payload(first_request))
    assert first.status_code == 201, first.text
    first_source = first.json()["values"]["intake"]["owned_url_source"]["source_snapshot"]

    same_request = _create_request(client, auth_headers, source_run.project_id)
    _install_capture(monkeypatch, _capture(content="first"))
    same = client.post(endpoint, headers=auth_headers, json=_payload(same_request, generation="expert"))
    assert same.status_code == 201, same.text
    assert same.json()["values"]["intake"]["owned_url_source"]["source_snapshot"] == first_source

    changed_request = _create_request(client, auth_headers, source_run.project_id)
    _install_capture(monkeypatch, _capture(content="changed"))
    changed = client.post(endpoint, headers=auth_headers, json=_payload(changed_request, channels=["smartstore"]))
    assert changed.status_code == 201, changed.text
    changed_source = changed.json()["values"]["intake"]["owned_url_source"]["source_snapshot"]
    assert changed_source["id"] != first_source["id"]
    assert db_session.query(ProductSourceSnapshotVersion).filter_by(
        project_id=source_run.project_id, input_mode="owned_product_url"
    ).count() == 2


@pytest.mark.parametrize("rights_state", ["seller_owned", "rights_confirmed", "unconfirmed"])
def test_owned_url_rights_are_source_observations_not_final_use(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch, rights_state
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    request = _create_request(client, auth_headers, source_run.project_id, rights_state=rights_state)
    _install_capture(monkeypatch, _capture(content=rights_state))
    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json=_payload(request),
    )
    assert response.status_code == 201, response.text
    rights = response.json()["values"]["intake"]["owned_url_source"]["rights"]
    assert rights["confirmation_state"] == rights_state
    assert rights["final_use_status"] == "not_approved"


def test_owned_url_rejects_tampered_or_reference_url_artifacts_before_graph(
    client, auth_headers, db_session, tmp_path, lg12i_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    request = _create_request(client, auth_headers, source_run.project_id)
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    tampered = _payload(request)
    tampered["source_payload_refs"][0]["hash"] = "0" * 64
    assert client.post(endpoint, headers=auth_headers, json=tampered).status_code == 422
    raw_state = _payload(request)
    raw_state["source_payload_refs"][0]["raw_html"] = "<script>unsafe()</script>"
    assert client.post(endpoint, headers=auth_headers, json=raw_state).status_code == 422

    reference = client.post(
        f"/api/v1/projects/{source_run.project_id}/reference-inputs",
        headers=auth_headers,
        json={"input_kind": "url", "source_url": _URL, "rights_status": "seller_owned"},
    )
    assert reference.status_code == 200
    assert db_session.query(ReferenceInsightVersion).count() == 1
    rejected = client.post(
        endpoint,
        headers=auth_headers,
        json=_payload(reference.json()),
    )
    assert rejected.status_code == 422
    assert db_session.query(ProductSourceSnapshotVersion).filter_by(project_id=source_run.project_id).count() == 0


def test_owned_url_capture_redirect_safety_and_normalized_identity():
    html = b"<html><title>Fan</title><img src='/fan.jpg'></html>"
    responses = {
        "https://store.example.com/p": URLCaptureHTTPResponse(302, {"location": "https://shop.example.com/fan"}, b""),
        "https://shop.example.com/fan": URLCaptureHTTPResponse(200, {"content-type": "text/html"}, html),
    }
    captured = capture_owned_product_url(
        "HTTPS://STORE.EXAMPLE.COM:443/p#ignored",
        fetch=lambda target: responses[target.normalized_url],
        resolve_host=lambda host: ["8.8.8.8"],
        captured_at="2026-08-18T00:00:00Z",
    )
    assert captured.normalized_url == "https://store.example.com/p"
    assert captured.final_url == "https://shop.example.com/fan"
    assert captured.redirect_chain == ("https://store.example.com/p", "https://shop.example.com/fan")

    with pytest.raises(UnsafeSourceURLError):
        capture_owned_product_url(
            "https://store.example.com/p",
            fetch=lambda _: URLCaptureHTTPResponse(302, {"location": "http://127.0.0.1/private"}, b""),
            resolve_host=lambda host: ["8.8.8.8"],
        )
    for unsafe in ("javascript:alert(1)", "data:text/html,x", "file:///tmp/product.html", "http://localhost/x"):
        with pytest.raises(UnsafeSourceURLError):
            capture_owned_product_url(unsafe, fetch=lambda _: responses["https://store.example.com/p"])


def test_owned_url_capture_pins_validated_dns_target_and_rejects_rebinding_addresses():
    html = b"<html><title>Fan</title></html>"
    resolver_calls: list[str] = []
    seen_targets = []

    def rebinding_resolver(host: str):
        resolver_calls.append(host)
        # A legacy hostname fetch would make a second resolver call and could
        # receive this private answer.  Capture must use the first pinned IP.
        return ["8.8.8.8"] if len(resolver_calls) == 1 else ["127.0.0.1"]

    def pinned_transport(target):
        seen_targets.append(target)
        assert target.connect_ip == "8.8.8.8"
        assert target.hostname == "store.example.com"
        assert target.host_header == "store.example.com"
        return URLCaptureHTTPResponse(200, {"content-type": "text/html"}, html)

    captured = capture_owned_product_url(
        "https://store.example.com/product",
        fetch=pinned_transport,
        resolve_host=rebinding_resolver,
        captured_at="2026-08-18T00:00:00Z",
    )
    assert captured.source_content_hash == sha256(html).hexdigest()
    assert len(seen_targets) == 1
    assert resolver_calls == ["store.example.com"]

    for unsafe_address in ("::1", "fc00::1", "fe80::1"):
        with pytest.raises(UnsafeSourceURLError):
            capture_owned_product_url(
                "https://store.example.com/product",
                fetch=pinned_transport,
                resolve_host=lambda _host, value=unsafe_address: [value],
            )
    with pytest.raises(UnsafeSourceURLError):
        capture_owned_product_url(
            "https://store.example.com/product",
            fetch=pinned_transport,
            resolve_host=lambda _host: ["8.8.8.8", "10.0.0.7"],
        )


def test_owned_url_capture_redirect_rebinding_and_https_hostname_contract():
    html = b"<html><title>Fan</title></html>"
    targets = []

    def transport(target):
        targets.append(target)
        if target.hostname == "store.example.com":
            return URLCaptureHTTPResponse(302, {"location": "https://shop.example.com/product"}, b"")
        return URLCaptureHTTPResponse(200, {"content-type": "text/html"}, html)

    captured = capture_owned_product_url(
        "https://store.example.com/start",
        fetch=transport,
        resolve_host=lambda host: ["8.8.8.8"] if host == "store.example.com" else ["1.1.1.1"],
        captured_at="2026-08-18T00:00:00Z",
    )
    assert captured.final_url == "https://shop.example.com/product"
    assert [(target.hostname, target.connect_ip, target.scheme) for target in targets] == [
        ("store.example.com", "8.8.8.8", "https"),
        ("shop.example.com", "1.1.1.1", "https"),
    ]
    https_target = resolve_validated_public_url_target(
        "https://shop.example.com/product", lambda _host: ["1.1.1.1"]
    )
    from src.services.url_evidence_collector import _ValidatedHTTPSConnection

    connection = _ValidatedHTTPSConnection(https_target)
    assert connection.host == "1.1.1.1"
    assert connection._sellform_server_hostname == "shop.example.com"
    assert connection._context.check_hostname is True

    with pytest.raises(UnsafeSourceURLError):
        capture_owned_product_url(
            "https://store.example.com/start",
            fetch=transport,
            resolve_host=lambda host: ["8.8.8.8"] if host == "store.example.com" else ["169.254.169.254"],
        )


def test_owned_url_default_transport_connects_only_to_validated_ip(monkeypatch):
    from src.services import url_evidence_collector

    calls: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def read(self, limit: int):
            assert limit == 2_000_001
            return b"<html></html>"

        def getheaders(self):
            return [("content-type", "text/html")]

    class FakeHTTPConnection:
        def __init__(self, host, port, timeout):
            calls.update({"connect_host": host, "port": port, "timeout": timeout})

        def request(self, method, request_target, headers):
            calls.update({"method": method, "request_target": request_target, "headers": headers})

        def getresponse(self):
            return FakeResponse()

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(url_evidence_collector.http.client, "HTTPConnection", FakeHTTPConnection)
    target = resolve_validated_public_url_target(
        "http://store.example.com/product?size=m", lambda _host: ["8.8.8.8"]
    )
    result = url_evidence_collector._default_capture_fetch(target)
    assert result.status_code == 200
    assert calls == {
        "connect_host": "8.8.8.8",
        "port": 80,
        "timeout": 10.0,
        "method": "GET",
        "request_target": "/product?size=m",
        "headers": {
            "Host": "store.example.com",
            "User-Agent": "SellformOwnedProductCapture/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
        "closed": True,
    }


def test_owned_url_snapshot_provenance_hash_only_reuses_identical_capture_semantics(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    endpoint = f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake"
    request = _create_request(client, auth_headers, source_run.project_id)
    variants = [
        _capture(content="same"),
        _capture(content="same", parser_version="fake-url-parser-v2"),
        _capture(content="same", capture_version="fake-owned-capture-v2"),
        _capture(content="same", captured_at="2026-08-18T01:02:04Z"),
        _capture(content="same", title="FAN PRO JET - revised observation"),
        _capture(
            content="same",
            redirect_chain=(_URL, "https://redirect.example.com/product", "https://shop.example.com/product/fan"),
        ),
    ]
    requests = [
        ("quick", ["smartstore"]),
        ("quick", ["coupang"]),
        ("quick", ["smartstore", "coupang"]),
        ("expert", ["smartstore"]),
        ("expert", ["coupang"]),
        ("expert", ["smartstore", "coupang"]),
    ]
    snapshot_ids = []
    artifact_hashes = []
    source_input_hashes = []
    frozen_first_hash = None
    for capture, (generation, channels) in zip(variants, requests, strict=True):
        _install_capture(monkeypatch, capture)
        response = client.post(endpoint, headers=auth_headers, json=_payload(request, generation=generation, channels=channels))
        assert response.status_code == 201, response.text
        source = response.json()["values"]["intake"]["owned_url_source"]
        snapshot_ids.append(source["source_snapshot"]["id"])
        artifact_hashes.append(source["capture_artifact_ref"]["hash"])
        snapshot = db_session.query(ProductSourceSnapshotVersion).filter_by(id=source["source_snapshot"]["id"]).one()
        assert snapshot.provenance_json["capture_artifact_ref"] == source["capture_artifact_ref"]
        assert snapshot.source_fidelity_json["content_document_ref"] == source["capture_artifact_ref"]
        assert snapshot.provenance_json["source_input_hash"]
        source_input_hashes.append(snapshot.provenance_json["source_input_hash"])
        if frozen_first_hash is None:
            frozen_first_hash = snapshot.canonical_hash
        else:
            first = db_session.query(ProductSourceSnapshotVersion).filter_by(id=snapshot_ids[0]).one()
            assert first.canonical_hash == frozen_first_hash
    assert len(set(snapshot_ids)) == len(variants)
    assert len(set(artifact_hashes)) == len(variants)
    assert len(set(source_input_hashes)) == len(variants)

    rights_request = _create_request(client, auth_headers, source_run.project_id, rights_state="rights_confirmed")
    _install_capture(monkeypatch, variants[0])
    rights_changed = client.post(endpoint, headers=auth_headers, json=_payload(rights_request, generation="expert", channels=["smartstore", "coupang"]))
    assert rights_changed.status_code == 201, rights_changed.text
    assert rights_changed.json()["values"]["intake"]["owned_url_source"]["source_snapshot"]["id"] not in snapshot_ids


def test_owned_url_capture_failure_is_recoverable_and_projection_rebuild_restores_it(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    request = _create_request(client, auth_headers, source_run.project_id, rights_state="unconfirmed")

    def blocked(_url: str):
        raise OwnedURLCaptureError("access_denied", "denied")

    monkeypatch.setattr("src.services.product_intake_version_service.capture_owned_product_url", blocked)
    response = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json=_payload(request),
    )
    assert response.status_code == 201, response.text
    state = response.json()
    assert state["current_stage"] == "owned_url_capture_recovery"
    assert state["values"]["intake"]["owned_url_capture"]["capture_status"] == "access_denied"
    assert state["values"]["intake"]["next_action"] == "task_12i_manual_or_photo_fallback"
    assert db_session.query(ProductSourceSnapshotVersion).filter_by(project_id=source_run.project_id).count() == 0

    run = db_session.query(AgentRun).filter_by(id=state["run_id"]).one()
    expected = deepcopy(run.outputs_json["langgraph_intake"])
    run.outputs_json = {key: value for key, value in run.outputs_json.items() if key != "langgraph_intake"}
    run.status = "running"
    db_session.add(run)
    db_session.commit()
    recovered = client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers)
    assert recovered.status_code == 200, recovered.text
    db_session.refresh(run)
    assert run.outputs_json["langgraph_intake"] == expected


def test_owned_url_snapshot_projection_rebuild_restores_capture_identity(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    request = _create_request(client, auth_headers, source_run.project_id)
    _install_capture(monkeypatch, _capture(content="restart-success"))
    state = client.post(
        f"/api/v1/graph-runs/projects/{source_run.project_id}/unified-intake",
        headers=auth_headers,
        json=_payload(request),
    ).json()
    run = db_session.query(AgentRun).filter_by(id=state["run_id"]).one()
    expected = deepcopy(run.outputs_json["langgraph_intake"])
    run.outputs_json = {key: value for key, value in run.outputs_json.items() if key != "langgraph_intake"}
    run.status = "running"
    db_session.add(run)
    db_session.commit()
    recovered = client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers)
    assert recovered.status_code == 200, recovered.text
    db_session.refresh(run)
    assert run.outputs_json["langgraph_intake"] == expected
    assert recovered.json()["values"]["intake"]["owned_url_source"] == expected["owned_url_source"]
