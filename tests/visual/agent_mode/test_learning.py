from __future__ import annotations

from agent.visual.agent_mode.learning import StrategyAtomStore


def test_strategy_atom_store_updates_ewma_without_forbidden_evidence(tmp_path):
    store = StrategyAtomStore(tmp_path / "strategy_atoms.sqlite3")
    store.initialize()
    forbidden_key = "raw" + "_prompt"
    store.record_outcome(
        bucket="portrait_reference",
        strategy_id="low_angle_leg_emphasis",
        reward=0.8,
        evidence={"artifact_id": "var_1", forbidden_key: "must not persist"},
    )

    rows = store.top_strategies("portrait_reference")

    assert rows[0]["strategy_id"] == "low_angle_leg_emphasis"
    assert rows[0]["score"] == 0.8
    assert forbidden_key not in rows[0]["evidence"]


def test_strategy_atom_store_sorts_by_score_and_updates_count(tmp_path):
    store = StrategyAtomStore(tmp_path / "strategy_atoms.sqlite3")
    store.initialize()
    store.record_outcome(bucket="fashion_editorial", strategy_id="a", reward=0.4, evidence={})
    store.record_outcome(bucket="fashion_editorial", strategy_id="b", reward=0.9, evidence={})
    store.record_outcome(bucket="fashion_editorial", strategy_id="a", reward=0.9, evidence={})

    rows = store.top_strategies("fashion_editorial")

    assert [row["strategy_id"] for row in rows] == ["b", "a"]
    assert rows[1]["score"] == 0.5
    assert rows[1]["count"] == 2


def test_strategy_atom_store_keeps_compact_reward_evidence_only(tmp_path):
    store = StrategyAtomStore(tmp_path / "strategy_atoms.sqlite3")
    store.initialize()
    store.record_outcome(
        bucket="product_showcase",
        strategy_id="clean_window_light",
        reward=0.76,
        evidence={
            "provider_health": 1.0,
            "artifact_quality": 0.8,
            "delivery_health": 1.0,
            "preference_score": 0.5,
            "overall_score": 0.76,
            "confidence": 0.75,
            "prompt": "must not persist",
            "raw_text": "must not persist",
            "reference_image": "/private/ref.png",
            "provider_raw_output": {"secret": True},
        },
    )

    evidence = store.top_strategies("product_showcase")[0]["evidence"]

    assert evidence == {
        "provider_health": 1.0,
        "artifact_quality": 0.8,
        "delivery_health": 1.0,
        "preference_score": 0.5,
        "overall_score": 0.76,
        "confidence": 0.75,
    }
