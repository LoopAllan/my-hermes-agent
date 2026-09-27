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


def test_other_coverage_is_not_deleted_to_avoid_custom_runners():
    for name in ('js-tests.yml', 'rust-tests.yml', 'e2e-desktop.yml'):
        jobs = workflow(name)['jobs']
        assert any(job.get('runs-on') == 'ubuntu-latest' for job in jobs.values())
        assert all('core' not in str(job.get('runs-on', '')) for job in jobs.values())
