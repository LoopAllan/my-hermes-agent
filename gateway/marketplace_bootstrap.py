"""Initial marketplace clone and root identity installation orchestration."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gateway.marketplace_config import (
    MarketplaceConfig,
    MarketplaceConfigError,
    load_marketplace_config_file,
)
from gateway.marketplace_credentials import GitAuthEnvironment

_MAX_SOUL_BYTES = 20_000
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class MarketplaceBootstrap:
    """Clone one validated marketplace and atomically install its root SOUL."""

    hermes_home: Path
    config: MarketplaceConfig

    def run(self) -> None:
        """Bootstrap through directory file descriptors, never mutable path parents."""
        home_path = Path(os.path.abspath(self.hermes_home))
        repository_path = Path(os.path.abspath(self.config.repo_dir))
        try:
            relative_repository = repository_path.relative_to(home_path)
        except ValueError as exc:
            raise RuntimeError(
                "marketplace repository directory must resolve below HERMES_HOME"
            ) from exc
        if not relative_repository.parts or any(
            component in {"", ".", ".."} for component in relative_repository.parts
        ):
            raise RuntimeError("marketplace repository directory must resolve below HERMES_HOME")

        home_fd = self._open_directory(home_path)
        try:
            parent_fd = self._open_parent(home_fd, relative_repository.parts[:-1])
            try:
                final_name = relative_repository.name
                self._remove_existing_repository(parent_fd, final_name)
                temporary_name = tempfile.mkdtemp(
                    prefix=".marketplace-clone-", dir=self._fd_path(parent_fd)
                )
                try:
                    clone_dir = Path(self._fd_path(parent_fd)) / temporary_name
                    self._clone(clone_dir, parent_fd)
                    self._validate_clone(clone_dir)
                    self._install_soul(
                        clone_dir / "SOUL.md", Path(self._fd_path(home_fd)) / "SOUL.md"
                    )
                    # rename(2) replaces a raced final symlink itself, never its target.
                    os.replace(
                        temporary_name,
                        final_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                    temporary_name = ""
                finally:
                    if temporary_name:
                        shutil.rmtree(temporary_name, dir_fd=parent_fd)
            finally:
                os.close(parent_fd)
        finally:
            os.close(home_fd)

    @staticmethod
    def _fd_path(descriptor: int) -> str:
        """Return a child-process-visible path anchored at an inherited directory fd."""
        return f"/proc/self/fd/{descriptor}"

    @staticmethod
    def _open_directory(path: Path) -> int:
        try:
            return os.open(path, _DIRECTORY_FLAGS)
        except OSError as exc:
            raise RuntimeError("HERMES_HOME must be an existing non-symlink directory") from exc

    @classmethod
    def _open_parent(cls, home_fd: int, components: tuple[str, ...]) -> int:
        descriptor = os.dup(home_fd)
        try:
            for component in components:
                next_descriptor = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
        except OSError as exc:
            os.close(descriptor)
            raise RuntimeError("marketplace repository parent does not exist or is a symlink") from exc
        return descriptor

    @staticmethod
    def _remove_existing_repository(parent_fd: int, final_name: str) -> None:
        try:
            metadata = os.stat(final_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("marketplace repository directory must be a real directory")
        try:
            shutil.rmtree(final_name, dir_fd=parent_fd)
        except OSError as exc:
            raise RuntimeError("cannot safely remove marketplace repository directory") from exc

    def _clone(self, clone_dir: Path, parent_fd: int) -> None:
        # /proc/self/fd is resolved by Git's process, so explicitly inherit the
        # parent descriptor. The path remains tied to the opened directory even
        # if an attacker renames its pathname and substitutes a symlink.
        os.set_inheritable(parent_fd, True)
        try:
            with GitAuthEnvironment.from_vault() as git_env:
                subprocess.run(
                    [
                        "git",
                        "clone",
                        "--depth",
                        "1",
                        "--single-branch",
                        "--no-tags",
                        "--branch",
                        self.config.branch,
                        "--",
                        self.config.repository,
                        str(clone_dir),
                    ],
                    check=True,
                    env=git_env,
                    pass_fds=(parent_fd,),
                )
        finally:
            os.set_inheritable(parent_fd, False)

    def _validate_clone(self, clone_dir: Path) -> None:
        resolved_clone = clone_dir.resolve(strict=True)
        skills_dir = (resolved_clone / self.config.skills_path).resolve(strict=True)
        if resolved_clone not in skills_dir.parents or not skills_dir.is_dir():
            raise RuntimeError("configured skills directory is missing")

    @staticmethod
    def _install_soul(source: Path, target: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(source, flags)
        except OSError as exc:
            raise RuntimeError(
                "root SOUL.md must be a regular non-symlink file"
            ) from exc

        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(
                    "root SOUL.md must be a regular non-symlink file"
                )
            if metadata.st_size < 1 or metadata.st_size > _MAX_SOUL_BYTES:
                raise RuntimeError(
                    "root SOUL.md must be nonempty and at most 20000 bytes"
                )
            with os.fdopen(descriptor, "rb") as source_file:
                descriptor = -1
                content = source_file.read(_MAX_SOUL_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".SOUL.md.", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.fchmod(temporary.fileno(), 0o600)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def main() -> int:
    """Run bootstrap from the runtime environment, failing closed when enabled."""
    home_value = os.environ.get("HERMES_HOME")
    if not home_value:
        print("marketplace bootstrap: missing required configuration: HERMES_HOME", file=sys.stderr)
        return 1
    home = Path(home_value)
    try:
        config = load_marketplace_config_file(home, require_bootstrap=True)
        if config is None:
            return 0
        MarketplaceBootstrap(home, config).run()
    except (
        MarketplaceConfigError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"marketplace bootstrap: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
