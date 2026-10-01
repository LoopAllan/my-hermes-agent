"""Keep PR automation on hosted runners and exclude long-running lanes."""
from pathlib import Path
import hermes_yaml as yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())


def test_pr_ci_excludes_long_running_lanes():
    jobs = workflow('tests.yml')['jobs']
    assert {'test', 'e2e', 'e2e-upgrade'} <= jobs.keys()

    pr_jobs = workflow('ci.yaml')['jobs']
    removed = {
        'tests', 'tests-os', 'lint', 'js-tests', 'rust-tests', 'bootstrap-installer',
        'e2e-desktop', 'e2e-desktop-core', 'e2e-desktop-update', 'docs-site',
        'history-check', 'uv-lockfile', 'icons-freshness-check',
    }
    assert removed.isdisjoint(pr_jobs)
    assert 'pull_request' not in workflow('nix.yml')[True]
    assert set(workflow('windows-install-update-e2e.yml')[True]) == {'workflow_call'}


def test_native_windows_both_architectures_and_current_selector():
    job = workflow('tests-os.yml')['jobs']['os-tests']
    matrix = job['strategy']['matrix']['include']
    assert {'windows-latest', 'windows-11-arm', 'macos-latest'} <= {row['runner'] for row in matrix}
    command = next(s['run'] for s in job['steps'] if 'scripts/ci/list_os_marked_tests.py' in s.get('run', ''))
    assert 'scripts/run_tests.sh --files' in command
    assert '-m "platforms and not integration"' in command
    assert 'windows_only' not in command
    assert '[ ! -s "$LIST" ]' in command


def _runner_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {'runs-on', 'runner'}:
                yield child
            yield from _runner_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _runner_values(child)


def test_all_workflows_use_only_github_hosted_runners():
    workflow_root = ROOT / '.github' / 'workflows'
    for path in workflow_root.rglob('*'):
        if path.suffix not in {'.yml', '.yaml'}:
            continue
        for runner in _runner_values(yaml.safe_load(path.read_text())):
            runner_text = str(runner).lower()
            assert 'self-hosted' not in runner_text, path
            assert '-core' not in runner_text, path
    assert not (ROOT / '.github' / 'actionlint.yaml').exists()
