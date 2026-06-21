def test_strategy_atom_signature_is_versioned_and_private_safe():
    from agent.visual.strategy_atoms import StrategyAtom

    atom = StrategyAtom(
        atom_id="composition.full_body_product",
        version="v1",
        kind="composition",
        public_summary="full subject visible with clean background",
        prompt_delta="full subject visible, clean background",
        negative_delta="cropped subject",
    )

    assert atom.signature == "composition.full_body_product@v1"
    assert "private" not in atom.to_record()


def test_builtin_strategy_atoms_are_versioned_and_unique():
    from agent.visual.strategy_atoms import builtin_strategy_atoms

    atoms = builtin_strategy_atoms()
    signatures = [atom.signature for atom in atoms]

    assert "composition.full_subject_visible@v1" in signatures
    assert "motion.camera_push_in@v1" in signatures
    assert len(signatures) == len(set(signatures))
