"""Shared environment policy for model-driven child processes."""

# Operator-provisioned credentials that intentionally belong to the agent's
# execution environment rather than to Hermes' own provider/runtime internals.
# Keep this exact-name allowlist narrow: these values reach model-driven local
# execution surfaces, including terminal and execute_code.
AGENT_OWNED_ENV_VARS = frozenset({"GITHUB_TOKEN"})
