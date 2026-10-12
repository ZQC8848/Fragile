"""Every test runs offline: no developer backend/.env, every LLM role on its mock, every module on its default
path, logs and generated beats in a temporary directory."""

from __future__ import annotations

import os

import pytest

import engine.generate.proposer as proposer_mod
import engine.journal.decisions as journal_mod
import engine.llm.client as client_mod
from engine.llm import reset_clients


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(client_mod, "_env_loaded", True)
    for k in list(os.environ):
        if k.startswith(("LLM_", "PROMPT_VERSION_", "MODEL_")):
            monkeypatch.delenv(k)
    monkeypatch.setattr(journal_mod, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(proposer_mod, "CANDIDATE_POOL_DIR", tmp_path / "candidate_pool")
    reset_clients()
    yield
    reset_clients()
