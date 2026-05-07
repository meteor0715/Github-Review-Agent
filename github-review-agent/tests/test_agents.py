"""
Unit tests for all agents (orchestrator, code_analysis_agent, formatter_agent).
LLM calls are mocked so tests run without Ollama running.
"""
import pytest


class TestCodeAnalysisAgent:
    def test_analyze_bugs_returns_list(self):
        # TODO: A2.5 — mock ChatOllama and assert findings are returned as list
        pass

    def test_analyze_security_flags_hardcoded_secret(self):
        # TODO: A2.5 — inject snippet with hardcoded password, assert finding returned
        pass

    def test_analyze_quality_detects_code_smell(self):
        # TODO: A2.5 — inject long function, assert complexity finding returned
        pass


class TestFormatterAgent:
    def test_format_outputs_github_comment_shape(self):
        # TODO: A2.5 — assert output has path, line, side, body keys
        pass


class TestOrchestrator:
    def test_orchestrator_calls_sub_agents(self):
        # TODO: A2.5 — mock sub-agents and assert they are called
        pass
