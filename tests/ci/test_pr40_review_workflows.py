"""Keep PR #40's restored test lanes wired to standard hosted runners."""
from pathlib import Path
import hermes_yaml as yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())


def test_full_python_suite_and_e2e_are_preserved():
    jobs = workflow('tests.yml')['jobs']
    suite = jobs['test']
    assert suite['runs-on'] == 'ubuntu-latest'
    steps = [step for step in suite['steps'] if step.get('name') == 'Run tests']
    assert len(steps) == 1
    assert steps[0]['run'].strip() == 'scripts/run_tests.sh'
    assert 1 <= int(steps[0]['env']['HERMES_TEST_WORKERS']) <= 4
    assert suite['timeout-minutes'] >= 120
    assert 'e2e' in jobs and 'e2e-upgrade' in jobs
    upgrade = jobs['e2e-upgrade']
    baseline_step = next(
        step for step in upgrade['steps']
        if step.get('name') == 'Fetch and verify release baseline'
    )
    assert 'https://github.com/NousResearch/hermes-agent.git' in baseline_step['run']
    assert "'refs/tags/v20*:refs/tags/v20*'" in baseline_step['run']
    assert "git describe --tags --abbrev=0 --match 'v20[0-9][0-9].*' HEAD~1" in baseline_step['run']
    assert workflow('ci.yaml')['jobs']['tests']['uses'] == './.github/workflows/tests.yml'


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
