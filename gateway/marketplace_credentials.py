"""Vault token parsing and scoped Git authentication for the marketplace."""
from __future__ import annotations

import shlex
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

_TOKEN_NAME = "MARKETPLACE_GIT_AUTH_TOKEN"
_TOKEN_PREFIX = f"{_TOKEN_NAME}="
_ASKPASS = """#!/bin/sh
case "$1" in
  *Username*) printf '%s' x-access-token ;;
  *) printf '%s' "$MARKETPLACE_GIT_AUTH_TOKEN" ;;
esac
"""


def _contains_shell_evaluation(value: str) -> bool:
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "`" or (char == "$" and value[index : index + 2] in {"$(", "${"}):
            return True
    return False


def _decode_go_quoted(value: str) -> str:
    """Decode one Go double-quoted string without evaluating shell syntax."""
    if len(value) < 2 or not value.startswith('"') or not value.endswith('"'):
        raise ValueError("not one quoted Go string")
    decoded: list[str] = []
    index = 1
    limit = len(value) - 1
    escapes = {
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        '"': '"',
    }
    while index < limit:
        char = value[index]
        if char != "\\":
            if ord(char) < 0x20:
                raise ValueError("unescaped control character")
            decoded.append(char)
            index += 1
            continue
        index += 1
        if index >= limit:
            raise ValueError("truncated escape")
        escape = value[index]
        if escape in escapes:
            decoded.append(escapes[escape])
            index += 1
            continue
        widths = {"x": 2, "u": 4, "U": 8}
        if escape in widths:
            width = widths[escape]
            digits = value[index + 1 : index + 1 + width]
            if len(digits) != width or any(digit not in "0123456789abcdefABCDEF" for digit in digits):
                raise ValueError("invalid hexadecimal escape")
            codepoint = int(digits, 16)
            if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                raise ValueError("invalid Unicode code point")
            decoded.append(chr(codepoint))
            index += width + 1
            continue
        if escape in "0123":
            digits = value[index : index + 3]
            if len(digits) != 3 or any(digit not in "01234567" for digit in digits):
                raise ValueError("invalid octal escape")
            decoded.append(chr(int(digits, 8)))
            index += 3
            continue
        raise ValueError("unsupported Go escape")
    return "".join(decoded)


def read_marketplace_token(path: Path) -> str:
    """Parse one safe shell-escaped (``%q``) token from a Vault env file."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise RuntimeError("MARKETPLACE_VAULT_ENV_FILE is unreadable") from exc

    for line in lines:
        if not line.startswith(_TOKEN_PREFIX):
            continue
        rendered = line[len(_TOKEN_PREFIX) :]
        if not rendered or rendered.startswith("'") or _contains_shell_evaluation(rendered):
            break
        try:
            token = (
                _decode_go_quoted(rendered)
                if rendered.startswith('"')
                else _decode_shell_word(rendered)
            )
        except ValueError:
            break
        if token and not any(char in token for char in "\r\n\x00"):
            return token
        break
    raise RuntimeError(f"{_TOKEN_NAME} is unavailable")


def marketplace_git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for every marketplace Git child: credential-scrubbed, never prompting.

    The process environment is the launch profile's, while the marketplace may belong to any served
    profile, so provider, bot and GitHub secrets are removed before Git sees them; only ``extra``
    (the askpass helper and marketplace token) is added back.
    """
    from hermes_cli._subprocess_compat import noninteractive_git_env
    from tools.environments.local import hermes_subprocess_env

    env = noninteractive_git_env(hermes_subprocess_env())
    # GitHub tokens deliberately pass through to agent children; marketplace Git authenticates
    # with its own askpass token, so the launch profile's must not ride along.
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        env.pop(name, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra or {})
    return env


def _decode_shell_word(rendered: str) -> str:
    """Retain support for legacy unquoted shell words without executing them."""
    words = shlex.split(rendered, posix=True)
    if len(words) != 1:
        raise ValueError("not one shell word")
    return words[0]


@dataclass
class GitAuthEnvironment:
    """Context manager exposing a Vault token only to a Git child process."""

    vault_file: Path
    _temporary_directory: tempfile.TemporaryDirectory[str] | None = field(
        default=None, init=False, repr=False
    )

    @classmethod
    def from_vault(cls) -> GitAuthEnvironment:
        """Use the ACTIVE profile's Vault file: under multiplex each served profile has its own."""
        from agent.secret_scope import get_secret

        env_file = get_secret("MARKETPLACE_VAULT_ENV_FILE")
        if not env_file:
            raise RuntimeError("MARKETPLACE_VAULT_ENV_FILE is unavailable")
        return cls(Path(env_file))

    def __enter__(self) -> dict[str, str]:
        token = read_marketplace_token(self.vault_file)
        temporary_directory = tempfile.TemporaryDirectory(prefix="hermes-marketplace-")
        self._temporary_directory = temporary_directory
        askpass = Path(temporary_directory.name) / "askpass"
        try:
            askpass.write_text(_ASKPASS, encoding="utf-8")
            askpass.chmod(0o700)
        except OSError:
            temporary_directory.cleanup()
            self._temporary_directory = None
            raise
        return marketplace_git_env({"GIT_ASKPASS": str(askpass), _TOKEN_NAME: token})

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None
