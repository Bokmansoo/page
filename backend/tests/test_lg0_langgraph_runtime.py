from langgraph.checkpoint.memory import InMemorySaver

from src.agents.langgraph_runtime import (
    LANGGRAPH_GRAPH_RUNTIME,
    LEGACY_GRAPH_RUNTIME,
    build_lg0_compiled_graph,
    build_lg0_graph_input,
    checkpoint_safe_input_snapshot,
    configured_graph_runtime,
    langgraph_runtime_enabled,
)
from src.config import Settings, settings


def test_lg0_compiles_and_executes_a_real_langgraph_state_graph():
    graph = build_lg0_compiled_graph()

    result = graph.invoke(
        build_lg0_graph_input(
            run_id="lg0-run",
            project_id="lg0-project",
            input_snapshot={"product_name": "경추 마사지 베개"},
        )
    )

    assert result["run_id"] == "lg0-run"
    assert result["events"] == ["bootstrap_run", "finalize_run"]


def test_lg0_checkpoint_state_uses_an_allowlist_and_never_persists_provider_secrets():
    checkpointer = InMemorySaver()
    graph = build_lg0_compiled_graph(checkpointer=checkpointer)
    graph_input = build_lg0_graph_input(
        run_id="lg0-safe-run",
        project_id="lg0-project",
        input_snapshot={
            "product_name": "경추 마사지 베개",
            "asset_ids": ["asset-1"],
            "OPENAI_API_KEY": "sk-must-not-be-persisted",
            "authorization": "Bearer must-not-be-persisted",
            "unexpected_runtime_object": {"secret": "must-not-be-persisted"},
        },
    )

    graph.invoke(graph_input, {"configurable": {"thread_id": "lg0-safe-run"}})
    snapshot = graph.get_state({"configurable": {"thread_id": "lg0-safe-run"}})

    assert snapshot.values["input_snapshot"] == {
        "product_name": "경추 마사지 베개",
        "asset_ids": ["asset-1"],
    }
    assert "sk-must-not-be-persisted" not in repr(snapshot.values)
    assert "authorization" not in snapshot.values["input_snapshot"]


def test_lg0_graph_enforces_secret_filtering_when_a_caller_bypasses_input_helper():
    checkpointer = InMemorySaver()
    graph = build_lg0_compiled_graph(checkpointer=checkpointer)

    graph.invoke(
        {
            "run_id": "lg0-direct-input-run",
            "project_id": "lg0-project",
            "input_snapshot": {
                "product_name": "경추 마사지 베개",
                "OPENAI_API_KEY": "sk-direct-input-must-not-be-persisted",
                "authorization": "Bearer direct-input-must-not-be-persisted",
            },
            "events": [],
        },
        {"configurable": {"thread_id": "lg0-direct-input-run"}},
    )
    snapshot = graph.get_state(
        {"configurable": {"thread_id": "lg0-direct-input-run"}}
    )

    assert snapshot.values["input_snapshot"] == {"product_name": "경추 마사지 베개"}
    assert "direct-input-must-not-be-persisted" not in repr(snapshot.values)


def test_lg0_checkpoint_input_copy_is_not_mutated_by_callers():
    raw_input = {"product_name": "원본", "asset_ids": ["asset-1"]}

    safe_input = checkpoint_safe_input_snapshot(raw_input)
    raw_input["asset_ids"].append("asset-2")

    assert safe_input == {"product_name": "원본", "asset_ids": ["asset-1"]}


def test_lg0_feature_flag_defaults_to_legacy_and_can_be_opted_in(monkeypatch):
    assert Settings(_env_file=None).SELLFORM_GRAPH_RUNTIME == LEGACY_GRAPH_RUNTIME

    monkeypatch.setattr(settings, "SELLFORM_GRAPH_RUNTIME", LEGACY_GRAPH_RUNTIME)
    assert configured_graph_runtime() == LEGACY_GRAPH_RUNTIME
    assert langgraph_runtime_enabled() is False

    monkeypatch.setattr(settings, "SELLFORM_GRAPH_RUNTIME", LANGGRAPH_GRAPH_RUNTIME)
    assert configured_graph_runtime() == LANGGRAPH_GRAPH_RUNTIME
    assert langgraph_runtime_enabled() is True
