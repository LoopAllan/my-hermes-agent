"""Shared environment policy for model-driven child processes."""

# Operator-provisioned credentials that intentionally belong to the agent's
# execution environment rather than to Hermes' own provider/runtime internals.
# Keep this exact-name allowlist narrow: these values reach model-driven local
# execution surfaces, including terminal and execute_code.
AGENT_OWNED_ENV_VARS = frozenset({"GITHUB_TOKEN"})


def resolve_agent_owned_env_value(name: str, fallback: str | None = None) -> str | None:
    """Resolve an agent-owned credential through the active profile scope.

    In multiplex mode a profile scope is authoritative: an absent value must
    not borrow the process environment, which may belong to another profile.
    An unscoped multiplex read also fails closed. Single-profile callers keep
    their existing process-environment fallback through ``get_secret``.
    """
    if name not in AGENT_OWNED_ENV_VARS:
        return fallback
    try:
        from agent.secret_scope import get_secret, is_multiplex_active
    except Exception:
        return None
    try:
        return get_secret(name, None if is_multiplex_active() else fallback)
    except Exception:
        # A missing scope resolver must not turn a child-process credential
        # boundary into a process-environment fallback.
        return None
