from __future__ import annotations

from types import SimpleNamespace


def test_generate_previews_loads_model_once_and_writes_each_speaker(tmp_path) -> None:
    from scripts.preview_qwen_custom_voices import generate_previews

    class FakeArrayModule:
        float32 = object()

        @staticmethod
        def asarray(values, *, dtype):
            assert dtype is FakeArrayModule.float32
            return list(values)

        @staticmethod
        def concatenate(chunks):
            return [value for chunk in chunks for value in chunk]

    class FakeModel:
        def __init__(self):
            self.calls = []

        def get_supported_speakers(self):
            return ["vivian", "serena"]

        def generate_custom_voice(self, **kwargs):
            self.calls.append(kwargs)
            yield SimpleNamespace(
                audio=[0.1, -0.1],
                sample_rate=24000,
            )

    model = FakeModel()
    load_calls = []
    write_calls = []

    result = generate_previews(
        model_path="/models/custom",
        output_dir=tmp_path,
        text="這是一段試聽。",
        speakers=["Vivian", "Serena"],
        language="chinese",
        model_loader=lambda path: load_calls.append(path) or model,
        array_module=FakeArrayModule,
        audio_writer=lambda path, audio, sample_rate: write_calls.append(
            (path, audio, sample_rate)
        ),
    )

    assert load_calls == ["/models/custom"]
    assert [call["speaker"] for call in model.calls] == ["Vivian", "Serena"]
    assert all(call["language"] == "chinese" for call in model.calls)
    assert [path.name for path in result] == ["Vivian.wav", "Serena.wav"]
    assert [call[0].name for call in write_calls] == ["Vivian.wav", "Serena.wav"]
    assert all(call[2] == 24000 for call in write_calls)
