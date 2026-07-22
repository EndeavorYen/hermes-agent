from dataclasses import replace

from agent.visual.production_kernel.contract import VisualIntentContract
from agent.visual.production_kernel.contract import compile_visual_intent_contract
from agent.visual.production_kernel.contract import visual_contract_hash


def test_contract_hash_is_stable_for_equivalent_context_order():
    first = compile_visual_intent_contract(
        "Create a cinematic image of a red bicycle in rain",
        {
            "primary_subject": "red bicycle",
            "required_details": ["visible rain", "wet street"],
            "aspect_ratio": "16:9",
        },
    )
    second = compile_visual_intent_contract(
        "Create a cinematic image of a red bicycle in rain",
        {
            "aspect_ratio": "16:9",
            "required_details": ["visible rain", "wet street"],
            "primary_subject": "red bicycle",
        },
    )

    assert visual_contract_hash(first) == visual_contract_hash(second)


def test_contract_hash_changes_when_acceptance_criteria_change():
    contract = compile_visual_intent_contract(
        "Create a cinematic image of a red bicycle in rain",
        {"primary_subject": "red bicycle"},
    )
    changed = replace(
        contract,
        acceptance_criteria=(*contract.acceptance_criteria, "rain streaks remain visible"),
    )

    assert visual_contract_hash(contract) != visual_contract_hash(changed)


def test_contract_hash_changes_when_reference_role_changes():
    identity = compile_visual_intent_contract(
        "Create a portrait from the reference",
        {"reference_roles": {"ref-1.png": "identity"}},
    )
    inspiration = compile_visual_intent_contract(
        "Create a portrait from the reference",
        {"reference_roles": {"ref-1.png": "style_inspiration"}},
    )

    assert visual_contract_hash(identity) != visual_contract_hash(inspiration)


def test_provider_prompt_is_not_part_of_contract_identity():
    first = compile_visual_intent_contract(
        "Create a portrait from the reference",
        {
            "primary_subject": "the referenced person",
            "provider_prompt": "OpenAI-specific verbose prompt",
            "provider": "openai-codex",
        },
    )
    second = compile_visual_intent_contract(
        "Create a portrait from the reference",
        {
            "primary_subject": "the referenced person",
            "provider_prompt": "Compact xAI prompt",
            "provider": "xai",
        },
    )

    assert visual_contract_hash(first) == visual_contract_hash(second)
    assert "provider" not in first.to_canonical_dict()


def test_contract_serialization_is_json_safe_and_explicit():
    contract = VisualIntentContract(
        original_request="Create a product close-up",
        primary_subject="mechanical watch movement",
        observable_action="gears turning",
        focal_point="escapement",
        acceptance_criteria=("escapement is sharp",),
        reference_roles=(("watch.png", "identity"),),
        aspect_ratio="4:5",
    )

    assert contract.to_canonical_dict() == {
        "schema": "visual_intent_contract_v1",
        "original_request": "Create a product close-up",
        "primary_subject": "mechanical watch movement",
        "observable_action": "gears turning",
        "decisive_moment": "",
        "focal_point": "escapement",
        "composition": "",
        "style": "",
        "audience_effect": "",
        "reference_roles": [["watch.png", "identity"]],
        "required_details": [],
        "forbidden_details": [],
        "acceptance_criteria": ["escapement is sharp"],
        "aspect_ratio": "4:5",
        "truth_mode": "",
    }
