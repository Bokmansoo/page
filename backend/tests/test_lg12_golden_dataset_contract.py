"""TASK-12.1 contract coverage for the immutable LG-12 Golden Dataset."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.schemas.lg12_golden_dataset import (
    GOLDEN_CATEGORIES,
    GOLDEN_DATASET_V1_CONTENT_HASH,
    TRUSTED_GOLDEN_DATASET_VERSION_HASHES,
    GoldenDatasetContractError,
    build_golden_dataset_v1,
    load_golden_dataset,
    validate_dataset_successor,
    validate_golden_dataset,
)
from src.services.prompt_intelligence_service import canonical_hash


def _rehashed(document: dict) -> dict:
    document["content_hash"] = canonical_hash({key: value for key, value in document.items() if key != "content_hash"})
    return document


def test_lg12_v1_has_exactly_three_deterministic_cases_for_each_fixed_category():
    first = load_golden_dataset()
    second = load_golden_dataset()

    assert first == second
    assert first["content_hash"] == GOLDEN_DATASET_V1_CONTENT_HASH
    assert tuple(first["categories"]) == GOLDEN_CATEGORIES
    assert len(first["cases"]) == 15
    assert {case["category"] for case in first["cases"]} == set(GOLDEN_CATEGORIES)
    assert all(sum(case["category"] == category for case in first["cases"]) == 3 for category in GOLDEN_CATEGORIES)
    assert len({case["case_id"] for case in first["cases"]}) == 15


def test_lg12_case_contract_pins_frozen_input_assets_expected_output_and_channel_identity():
    dataset = load_golden_dataset()
    rubric_ids = {rubric["rubric_id"] for rubric in dataset["human_rubrics"]}

    for case in dataset["cases"]:
        assert case["source_frozen_version"]["detail_page_version_id"]
        assert len(case["source_frozen_version"]["snapshot_hash"]) == 64
        assert case["human_rubric_id"] in rubric_ids
        assert case["input"]["approved_fact_ids"] and case["input"]["evidence_ids"]
        reference = case["input"]["reference_assets"][0]
        golden = case["expected_output"]["golden_assets"][0]
        manifest_asset = case["expected_output"]["approved_asset_manifest"]["assets"][0]
        assert reference["asset_id"] and reference["asset_content_hash"]
        assert golden["asset_id"] == manifest_asset["asset_id"]
        assert golden["asset_content_hash"] == manifest_asset["asset_content_hash"]
        assert case["source_frozen_version"] == case["expected_output"]["frozen_version"]
        assert case["expected_output"]["frozen_version"]["approved_asset_manifest_hash"] == case["expected_output"]["approved_asset_manifest"]["manifest_hash"]
        assert case["channel"] == case["expected_output"]["channel"]
        assert case["provider_mode"] == "fake"


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda document: document["cases"][0]["input"]["reference_assets"][0].__setitem__("asset_content_hash", "a" * 64), "content hash"),
        (lambda document: document["cases"][0]["expected_output"]["golden_assets"][0].__setitem__("rights_status", "unknown"), "rights-confirmed"),
        (lambda document: document["cases"][1].__setitem__("case_id", document["cases"][0]["case_id"]), "unique"),
        (lambda document: document.__setitem__("categories", tuple(GOLDEN_CATEGORIES[:-1])), "five fixed category"),
    ),
)
def test_lg12_rejects_tampered_hash_rights_duplicate_and_missing_category_contracts(mutate, message):
    dataset = deepcopy(build_golden_dataset_v1())
    mutate(dataset)
    # Exercise the schema-level finding itself. Registered v1 tampering is
    # separately rejected by the trusted-version test below.
    dataset["dataset_version"] = "contract-test-v2"
    _rehashed(dataset)

    with pytest.raises(GoldenDatasetContractError, match=message):
        validate_golden_dataset(dataset)


def test_lg12_registered_v1_rejects_tamper_even_when_attacker_rehashes_payload():
    dataset = deepcopy(build_golden_dataset_v1())
    dataset["cases"][0]["input"]["product_name"] = "변조된 현재 상태"
    _rehashed(dataset)

    with pytest.raises(GoldenDatasetContractError, match="trusted canonical hash"):
        validate_golden_dataset(dataset)
    assert load_golden_dataset()["content_hash"] == GOLDEN_DATASET_V1_CONTENT_HASH


def test_lg12_successor_uses_new_version_without_overwriting_v1():
    v1 = load_golden_dataset()
    v2 = deepcopy(v1)
    v2["dataset_version"] = "v2"
    v2["parent_version"] = "v1"
    v2["previous_dataset_hash"] = v1["content_hash"]
    _rehashed(v2)

    successor = validate_dataset_successor(v2, previous_document=v1)
    assert successor["dataset_version"] == "v2"
    assert load_golden_dataset()["dataset_version"] == "v1"
    assert load_golden_dataset()["content_hash"] == v1["content_hash"]


def test_lg12_load_rejects_tampered_checked_in_v1_fixture(monkeypatch):
    tampered = deepcopy(build_golden_dataset_v1())
    tampered["cases"][0]["input"]["product_name"] = "변조된 fixture"
    _rehashed(tampered)
    monkeypatch.setattr("src.schemas.lg12_golden_dataset.build_golden_dataset_v1", lambda: tampered)

    with pytest.raises(GoldenDatasetContractError, match="trusted canonical hash"):
        load_golden_dataset()


def test_lg12_registered_v1_rejects_rehashed_manifest_content_tamper():
    tampered = deepcopy(build_golden_dataset_v1())
    manifest = tampered["cases"][0]["expected_output"]["approved_asset_manifest"]
    manifest["assets"][0]["section_id"] = "tampered-section"
    manifest["manifest_hash"] = canonical_hash({key: value for key, value in manifest.items() if key != "manifest_hash"})
    _rehashed(tampered)

    with pytest.raises(GoldenDatasetContractError, match="trusted canonical hash"):
        validate_golden_dataset(tampered)


def test_lg12_successor_rejects_rehashed_tampered_parent_document():
    tampered_parent = deepcopy(build_golden_dataset_v1())
    tampered_parent["cases"][0]["input"]["product_name"] = "변조된 parent"
    _rehashed(tampered_parent)
    v2 = deepcopy(build_golden_dataset_v1())
    v2["dataset_version"] = "v2"
    v2["parent_version"] = "v1"
    v2["previous_dataset_hash"] = tampered_parent["content_hash"]
    _rehashed(v2)

    with pytest.raises(GoldenDatasetContractError, match="trusted canonical hash"):
        validate_dataset_successor(v2, previous_document=tampered_parent)


def test_lg12_rejects_manifest_content_or_frozen_manifest_reference_drift():
    manifest_tampered = deepcopy(build_golden_dataset_v1())
    manifest_tampered["dataset_version"] = "contract-test-v2"
    manifest_tampered["cases"][0]["expected_output"]["approved_asset_manifest"]["assets"][0]["section_id"] = "tampered-section"
    _rehashed(manifest_tampered)
    with pytest.raises(GoldenDatasetContractError, match="manifest hash"):
        validate_golden_dataset(manifest_tampered)

    frozen_reference_tampered = deepcopy(build_golden_dataset_v1())
    frozen_reference_tampered["dataset_version"] = "contract-test-v2"
    frozen_reference_tampered["cases"][0]["expected_output"]["frozen_version"]["approved_asset_manifest_hash"] = "a" * 64
    _rehashed(frozen_reference_tampered)
    with pytest.raises(GoldenDatasetContractError, match="must pin its manifest hash"):
        validate_golden_dataset(frozen_reference_tampered)


def test_lg12_v1_trusted_registry_is_external_to_the_dataset_document():
    dataset = load_golden_dataset()
    assert TRUSTED_GOLDEN_DATASET_VERSION_HASHES == {"v1": dataset["content_hash"]}


def test_lg12_loader_is_local_fake_fixture_only_and_never_requires_provider_or_cost_state():
    # The contract is entirely frozen fixture data. Loading it neither accepts
    # a database/session input nor contains an outbox/provider/cost API path.
    dataset = load_golden_dataset()
    assert {case["provider_mode"] for case in dataset["cases"]} == {"fake"}
