"""Keep fork CI on hosted runners and limited to lanes under five minutes (PR #40)."""
from pathlib import Path
import hermes_yaml as yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())


_LANES_OVER_FIVE_MINUTES = {'tests', 'tests-os', 'js-tests', 'e2e-desktop-core', 'e2e-desktop-update'}
_WORKFLOWS_OVER_FIVE_MINUTES = (
    'pm-bundle.yml', 'windows-bundle-sdk.yml', 'install-e2e.yml', 'nix.yml', 'docker.yml',
)


def _triggers(name):
    # YAML 1.1 parses the bare ``on`` key as boolean True.
    data = workflow(name)
    return set(data.get('on', data.get(True)) or {})


def test_fork_ci_runs_only_fast_lanes_automatically():
    """Fork policy: nothing over five minutes runs on PRs, pushes or schedules; it stays dispatchable."""
    jobs = workflow('ci.yaml')['jobs']
    assert _LANES_OVER_FIVE_MINUTES.isdisjoint(jobs)
    assert _LANES_OVER_FIVE_MINUTES.isdisjoint(jobs['all-checks-pass']['needs'])
    assert {'lint', 'rust-tests', 'review-labels', 'supply-chain'} <= jobs.keys()
    for name in _WORKFLOWS_OVER_FIVE_MINUTES:
        triggers = _triggers(name)
        assert triggers.isdisjoint({'pull_request', 'push', 'schedule'}), name
        assert triggers & {'workflow_dispatch', 'workflow_call'}, name


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

    windows_install = workflow('windows-install-update-e2e.yml')['jobs']['install-update']
    run_step = next(
        step for step in windows_install['steps']
        if step.get('name') == 'Run Windows install + update E2E'
    )
    assert int(run_step['env']['HERMES_TEST_WORKERS']) <= 2
    assert windows_install['timeout-minutes'] >= 60


def test_fork_image_publishes_main_tags_only_from_main():
    """A manual dispatch from a feature branch must not overwrite the production ``:main`` image."""
    for name, job in workflow('fork-ghcr.yml')['jobs'].items():
        assert job.get('if') == "github.ref == 'refs/heads/main'", name
