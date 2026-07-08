from pathlib import Path


def test_github_pr_workflow_resets_existing_branch_before_pr():
    skill = Path("skills/github/github-pr-workflow/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "git fetch origin \"$DEFAULT_BRANCH\"" in skill
    assert "git checkout -B \"$BRANCH\" \"origin/$DEFAULT_BRANCH\"" in skill
    assert "git reset --hard \"origin/$DEFAULT_BRANCH\"" in skill
