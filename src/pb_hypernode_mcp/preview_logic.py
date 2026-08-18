"""Pure/async helpers backing the `brancher-preview` skill.

The skill itself (`skills/brancher-preview/SKILL.md`) is markdown instructions
telling Claude how to run the spin-up -> apply-changes -> build -> screenshot
-> cleanup-reminder loop, reusing the already-tested `brancher-spinup` flow
(task 011) and the `brancher_put`/`brancher_exec` tools (tasks 007/008). The
two pieces of real decision logic in that loop — which Magento build commands
are needed after a change, and the end-of-loop cost reminder text — are
extracted here as plain, unit-testable functions rather than left as prose
for Claude to interpret at runtime.

The screenshot step itself has no Python surface: it is the client's own
browser MCP tool (e.g. `claude-in-chrome`/`chrome-devtools`), invoked directly
by Claude against the node's `access_url` — this plugin does not wrap or
mock a screenshot tool.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# Default Magento build sequence for v1. Kept simple and safe-by-default
# rather than an exhaustive dependency-graph analysis of the changed files:
# always flush cache; add the heavier steps only when plausibly needed.
CACHE_FLUSH_COMMAND = 'bin/magento cache:flush'
SETUP_UPGRADE_COMMAND = 'bin/magento setup:upgrade'
DI_COMPILE_COMMAND = 'bin/magento setup:di:compile'
STATIC_CONTENT_DEPLOY_COMMAND = 'bin/magento setup:static-content:deploy -f'

# Path fragments that indicate each heavier build step is needed.
_SCHEMA_MARKERS = ('db_schema.xml', 'module.xml')
_DI_MARKERS = ('di.xml',)
_FRONTEND_MARKERS = ('.phtml', '.css', '.js', '/web/', 'view/frontend', 'view/adminhtml')

ExecCommand = Callable[[str, str], Awaitable[dict[str, Any]]]
PutFiles = Callable[[str, str, str], Awaitable[dict[str, Any]]]


def decide_build_commands(changed_paths: list[str]) -> list[str]:
    """Decide which Magento build commands to run, given the changed file paths.

    Always includes a cache flush. Adds `setup:upgrade` when a module/schema
    file changed, `setup:di:compile` when a `di.xml` changed, and a static
    content deploy when a frontend template/asset changed. A reasonable v1
    default — not an exhaustive dependency-graph analysis.
    """
    commands = [CACHE_FLUSH_COMMAND]

    if any(marker in path for path in changed_paths for marker in _SCHEMA_MARKERS):
        commands.append(SETUP_UPGRADE_COMMAND)

    if any(marker in path for path in changed_paths for marker in _DI_MARKERS):
        commands.append(DI_COMPILE_COMMAND)

    if any(marker in path for path in changed_paths for marker in _FRONTEND_MARKERS):
        commands.append(STATIC_CONTENT_DEPLOY_COMMAND)

    return commands


async def apply_local_change(
    node_name: str,
    local_path: str,
    remote_path: str,
    *,
    put_files: PutFiles,
) -> dict[str, Any]:
    """Push a local file/directory onto `node_name` via `brancher_put`'s `put_files`.

    Thin wrapper — kept as its own function so the preview loop's "apply
    local changes" step has a single, unit-testable call site, and so the
    caller can inject a fake `put_files` in tests instead of shelling out.
    """
    return await put_files(node_name, local_path, remote_path)


async def run_build_sequence(
    node_name: str,
    changed_paths: list[str],
    *,
    exec_command: ExecCommand,
) -> dict[str, Any]:
    """Decide + run the Magento build sequence on `node_name` after changes are applied."""
    commands = decide_build_commands(changed_paths)
    results = []

    for command in commands:
        result = await exec_command(node_name, command)
        results.append({'command': command, **result})

    return {'commands': commands, 'results': results}


def cleanup_reminder(node_name: str, access_url: str) -> str:
    """Build the end-of-loop reminder that the node is still running and billing minutes."""
    return (
        f"Node '{node_name}' ({access_url}) is still running and consuming Brancher "
        "minutes. Delete it with brancher_delete when you're done previewing, or run "
        'the brancher-cleanup skill later.'
    )
