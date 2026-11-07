"""Pruebas del cargador mínimo de .env (app/config.py)."""
import os

from app.config import load_env


def test_load_env_carga_sin_pisar_variables_existentes(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comentario ignorado\n"
        "\n"
        "LLM_PROVIDER=ollama\n"
        'SECRET_KEY="valor con espacios"\n'
        "linea_sin_igual\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("SECRET_KEY", "ya-existe")

    assert load_env(env_file) == 1  # solo LLM_PROVIDER es nueva
    assert os.environ["LLM_PROVIDER"] == "ollama"
    assert os.environ["SECRET_KEY"] == "ya-existe"  # nunca pisa lo ya definido


def test_load_env_sin_archivo_devuelve_cero(tmp_path):
    assert load_env(tmp_path / "no-existe.env") == 0
