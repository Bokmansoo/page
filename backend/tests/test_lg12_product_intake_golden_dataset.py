"""TASK-12.1R coverage for the immutable Product Intake Golden Dataset v2."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.schemas.lg12_golden_dataset import (
    GOLDEN_CATEGORIES,
    GOLDEN_DATASET_V1_CONTENT_HASH,
    load_golden_dataset,
)
from src.schemas.lg12_product_intake_golden_dataset import (
    PRODUCT_INTAKE_GOLDEN_DATASET_V2_CONTENT_HASH,
    PRODUCT_INTAKE_GOLDEN_DATASET_VERSION,
    PRODUCT_INTAKE_GOLDEN_INPUT_MODES,
    TRUSTED_PRODUCT_INTAKE_GOLDEN_DATASET_VERSION_HASHES,
    ProductIntakeGoldenDatasetContractError,
    build_product_intake_golden_dataset_v2,
    load_product_intake_golden_dataset,
    validate_product_intake_dataset_successor,
    validate_product_intake_golden_dataset,
)
from src.services.product_intake_version_service import canonical_unified_intake_input_hash
from src.services.prompt_intelligence_service import canonical_hash


def _rehash_case(case: dict) -> None:
    case["case_hash"] = canonical_hash({key: value for key, value in case.items() if key != "case_hash"})


def _rehash_dataset(dataset: dict) -> None:
    dataset["content_hash"] = canonical_hash({key: value for key, value in dataset.items() if key != "content_hash"})


def _unregistered(dataset: dict) -> dict:
    dataset["dataset_version"] = "v2-contract-test"
    _rehash_dataset(dataset)
    return dataset


def test_lg12i_v2_loads_with_v1_without_rewriting_the_v1_trust_anchor():
    v1 = load_golden_dataset()
    v2 = load_product_intake_golden_dataset()

    assert v1["dataset_version"] == "v1"
    assert v1["content_hash"] == GOLDEN_DATASET_V1_CONTENT_HASH
    assert v2["dataset_version"] == PRODUCT_INTAKE_GOLDEN_DATASET_VERSION
    assert v2["parent_version"] == "v1"
    assert v2["parent_trusted_hash"] == GOLDEN_DATASET_V1_CONTENT_HASH
    assert v2["previous_dataset_hash"] == GOLDEN_DATASET_V1_CONTENT_HASH
    assert TRUSTED_PRODUCT_INTAKE_GOLDEN_DATASET_VERSION_HASHES == {
        "v2": PRODUCT_INTAKE_GOLDEN_DATASET_V2_CONTENT_HASH
    }
    assert load_product_intake_golden_dataset() == v2


def test_lg12i_v2_has_the_complete_five_category_three_mode_matrix():
    dataset = load_product_intake_golden_dataset()
    matrix = {(case["category"], case["input_mode"]) for case in dataset["cases"]}

    assert len(dataset["cases"]) == 15
    assert len({case["case_id"] for case in dataset["cases"]}) == 15
    assert matrix == {(category, mode) for category in GOLDEN_CATEGORIES for mode in PRODUCT_INTAKE_GOLDEN_INPUT_MODES}
    assert {case["provider_mode"] for case in dataset["cases"]} == {"fake"}


def test_lg12i_v2_cases_pin_reference_only_mode_specific_intake_contracts():
    dataset = load_product_intake_golden_dataset()

    for case in dataset["cases"]:
        envelope = case["unified_intake_envelope_expectation"]
        source = case["source_expectation"]
        truth = case["truth_expectation"]
        confirmation = case["seller_confirmation_expectation"]
        master = case["commerce_creative_master_expectation"]

        assert envelope["input_hash"] == canonical_unified_intake_input_hash(envelope)
        assert envelope["target_channels"] == sorted(envelope["target_channels"])
        assert set(envelope["target_channels"]).issubset({"smartstore", "coupang"})
        assert all("fixture_bytes_b64" not in reference for reference in envelope["source_payload_refs"])
        assert all(material["hash"] for material in source["fixture_materials"])
        assert truth["unknown_facts"] and truth["prohibited_inferences"]
        assert confirmation["max_clarification_questions"] <= 3
        assert master["downstream_output_refs"] == []
        assert set(master["references"]) == {
            "source", "truth", "confirmation", "creative_brief", "brand_kit", "evidence",
            "approved_fact_snapshot", "approved_asset_manifest", "copy_artifact", "page_plan_artifact",
        }

        mode = case["input_mode"]
        expectation = case["mode_specific_expectation"]
        source_ref = envelope["source_payload_refs"][0]
        if mode == "owned_product_url":
            assert source_ref["kind"] == "url_capture_request"
            assert expectation["actual_url_fetch"] is False
        elif mode == "photo_only":
            assert source_ref["kind"] == "asset_ref"
            assert source_ref["rights_status"] == "rights_confirmed"
            assert expectation["actual_ocr_or_vlm_call"] is False
        else:
            assert source_ref["kind"] == "manual_payload_artifact"
            assert expectation["actual_manual_normalization"] is False
            assert expectation["creative_direction_is_fact"] is False


def test_lg12i_v2_channel_set_order_is_identity_independent_but_channels_and_generation_mode_are_not():
    dataset = load_product_intake_golden_dataset()
    manual = next(case for case in dataset["cases"] if case["input_mode"] == "manual")
    quick = deepcopy(manual["unified_intake_envelope_expectation"])
    reverse = deepcopy(quick)
    reverse["target_channels"] = list(reversed(reverse["target_channels"]))
    expert = deepcopy(quick)
    expert["requested_generation_mode"] = "expert"
    smartstore = next(case for case in dataset["cases"] if case["input_mode"] == "owned_product_url")["unified_intake_envelope_expectation"]
    coupang = next(case for case in dataset["cases"] if case["input_mode"] == "photo_only")["unified_intake_envelope_expectation"]

    assert canonical_unified_intake_input_hash(quick) == canonical_unified_intake_input_hash(reverse)
    assert canonical_unified_intake_input_hash(quick) != canonical_unified_intake_input_hash(expert)
    assert canonical_unified_intake_input_hash(smartstore) != canonical_unified_intake_input_hash(coupang)


def test_lg12i_v2_rejects_registered_case_tamper_even_when_rehashed():
    tampered = deepcopy(build_product_intake_golden_dataset_v2())
    tampered["cases"][0]["truth_expectation"]["prohibited_inferences"][0]["fact_id"] = "tampered-inference"
    _rehash_case(tampered["cases"][0])
    _rehash_dataset(tampered)

    with pytest.raises(ProductIntakeGoldenDatasetContractError, match="trusted canonical hash"):
        validate_product_intake_golden_dataset(tampered)


def test_lg12i_v2_rejects_fixture_duplicate_master_and_parent_lineage_tamper():
    fixture_tampered = _unregistered(deepcopy(build_product_intake_golden_dataset_v2()))
    fixture_tampered["cases"][0]["source_expectation"]["fixture_materials"][0]["fixture_bytes_b64"] = "dGFtcGVyZWQ="
    _rehash_case(fixture_tampered["cases"][0])
    _rehash_dataset(fixture_tampered)
    with pytest.raises(ProductIntakeGoldenDatasetContractError, match="fixture bytes"):
        validate_product_intake_golden_dataset(fixture_tampered)

    duplicate = _unregistered(deepcopy(build_product_intake_golden_dataset_v2()))
    duplicate["cases"][1] = deepcopy(duplicate["cases"][0])
    _rehash_dataset(duplicate)
    with pytest.raises(ProductIntakeGoldenDatasetContractError, match="globally unique"):
        validate_product_intake_golden_dataset(duplicate)

    downstream = _unregistered(deepcopy(build_product_intake_golden_dataset_v2()))
    downstream["cases"][0]["commerce_creative_master_expectation"]["downstream_output_refs"] = [{"id": "detail-page"}]
    _rehash_case(downstream["cases"][0])
    _rehash_dataset(downstream)
    with pytest.raises(ProductIntakeGoldenDatasetContractError, match="initial Master"):
        validate_product_intake_golden_dataset(downstream)

    parent_tampered = _unregistered(deepcopy(build_product_intake_golden_dataset_v2()))
    parent_tampered["parent_trusted_hash"] = "a" * 64
    _rehash_dataset(parent_tampered)
    with pytest.raises(ProductIntakeGoldenDatasetContractError, match="trusted v1 parent lineage"):
        validate_product_intake_golden_dataset(parent_tampered)


def test_lg12i_v2_successor_requires_the_actual_trusted_v1_parent():
    successor = _unregistered(deepcopy(build_product_intake_golden_dataset_v2()))
    trusted_parent = load_golden_dataset()
    assert validate_product_intake_dataset_successor(successor, parent_document=trusted_parent)["dataset_version"] == "v2-contract-test"

    tampered_parent = deepcopy(trusted_parent)
    tampered_parent["cases"][0]["input"]["product_name"] = "tampered parent"
    _rehash_dataset(tampered_parent)
    with pytest.raises(ProductIntakeGoldenDatasetContractError, match="trusted v1 contract"):
        validate_product_intake_dataset_successor(successor, parent_document=tampered_parent)


def test_lg12i_v2_is_a_local_fake_fixture_and_never_calls_provider_outbox_or_cost_services():
    dataset = load_product_intake_golden_dataset()

    assert {case["provider_mode"] for case in dataset["cases"]} == {"fake"}
    assert all(case["mode_specific_expectation"].get("actual_url_fetch") is False for case in dataset["cases"] if case["input_mode"] == "owned_product_url")
    assert all(case["mode_specific_expectation"].get("actual_ocr_or_vlm_call") is False for case in dataset["cases"] if case["input_mode"] == "photo_only")
    assert all(case["mode_specific_expectation"].get("actual_manual_normalization") is False for case in dataset["cases"] if case["input_mode"] == "manual")
