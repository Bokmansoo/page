from backend.src.services.generation_mode import GenerationMode, resolve_generation_mode


def test_generation_mode_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("SELLFORM_GENERATION_MODE", raising=False)
    assert resolve_generation_mode() == GenerationMode.MOCK


def test_generation_mode_accepts_real(monkeypatch):
    monkeypatch.setenv("SELLFORM_GENERATION_MODE", "real")
    assert resolve_generation_mode() == GenerationMode.REAL
