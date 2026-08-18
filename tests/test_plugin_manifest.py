"""Tests for the Claude Code plugin packaging manifests.

These tests verify that `.claude-plugin/plugin.json`, `.mcp.json`, and the
`skills/` directory are well-formed and internally consistent with
`pyproject.toml` — not runtime tool behavior (there is none here yet).
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_SKILL_NAMES = (
    'brancher-spinup',
    'brancher-preview',
    'brancher-cleanup',
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open('rb') as handle:
        return json.loads(handle.read())


def _load_pyproject() -> dict[str, Any]:
    with (REPO_ROOT / 'pyproject.toml').open('rb') as handle:
        return tomllib.load(handle)


def test_it_declares_the_mcp_server_entrypoint_correctly_in_the_plugin_manifest() -> None:
    mcp_manifest = _load_json(REPO_ROOT / '.mcp.json')
    pyproject = _load_pyproject()

    scripts: dict[str, str] = pyproject['project']['scripts']
    assert 'pb-hypernode-mcp' in scripts
    assert scripts['pb-hypernode-mcp'] == 'pb_hypernode_mcp.server:main'

    servers: dict[str, Any] = mcp_manifest['mcpServers']
    assert 'pb-hypernode-mcp' in servers

    server_entry = servers['pb-hypernode-mcp']
    assert server_entry['command'] == 'uv'
    assert '${CLAUDE_PLUGIN_ROOT}' in server_entry['args']
    assert 'run' in server_entry['args']
    assert 'pb-hypernode-mcp' in server_entry['args']


def test_it_declares_all_three_skills_in_the_plugin_manifest() -> None:
    skills_dir = REPO_ROOT / 'skills'
    declared = {entry.name for entry in skills_dir.iterdir() if entry.is_dir()}

    assert declared == set(EXPECTED_SKILL_NAMES)

    for skill_name in EXPECTED_SKILL_NAMES:
        skill_md = skills_dir / skill_name / 'SKILL.md'
        assert skill_md.is_file(), f'{skill_md} is missing'

        content = skill_md.read_text()
        frontmatter_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
        assert frontmatter_match, f'{skill_md} has no YAML frontmatter block'

        frontmatter = frontmatter_match.group(1)
        name_match = re.search(r'^name:\s*(\S+)\s*$', frontmatter, re.MULTILINE)
        assert name_match, f'{skill_md} frontmatter has no name field'
        assert name_match.group(1) == skill_name

        assert re.search(r'^description:\s*\S', frontmatter, re.MULTILINE), (
            f'{skill_md} frontmatter has no description field'
        )


def test_it_documents_required_environment_variables_in_the_manifest_or_install_docs() -> None:
    plugin_manifest = _load_json(REPO_ROOT / '.claude-plugin' / 'plugin.json')
    readme = (REPO_ROOT / 'README.md').read_text()

    user_config: dict[str, Any] = plugin_manifest['userConfig']
    assert 'HYPERNODE_API_TOKEN' in user_config['hypernode_api_token_env']['default']

    assert 'HYPERNODE_API_TOKEN' in readme
    assert 'HYPERNODE_APP_ALLOWLIST' in readme
