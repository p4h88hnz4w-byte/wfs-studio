import os
import platform
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "install-linux.sh"


def _run(home: Path, work: Path, shell: str, alias: str = "wfsu") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["WFS_INSTALL_ALLOW_NON_LINUX"] = "1"
    env["WFS_INSTALL_SKIP_PIP"] = "1"
    env["WFS_INSTALL_DIR"] = str(work)
    env["WFS_INSTALL_ALIAS"] = alias
    env["WFS_INSTALL_SHELL"] = shell
    return subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _checkout(work: Path) -> None:
    work.mkdir(parents=True)
    (work / "pyproject.toml").write_text("[project]\nname = 'wfs-studio'\n", encoding="utf-8")


@pytest.mark.skipif(platform.system() == "Linux", reason="The installer is meant to run on Linux.")
def test_installer_refuses_a_non_linux_system():
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env={"HOME": "/tmp", "PATH": os.environ.get("PATH", "")},
    )
    assert result.returncode == 1
    assert "Linux" in result.stderr


def test_installer_writes_the_alias_into_the_chosen_shell(tmp_path: Path):
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    _checkout(work)
    zsh = _run(home, work, "zsh")
    assert zsh.returncode == 0, zsh.stderr
    rc = (home / ".zshrc").read_text(encoding="utf-8")
    assert "alias wfsu=" in rc
    assert str(work) in rc
    assert ".venv/bin/python" in rc
    assert "-m wfs_studio" in rc
    assert not (home / ".bashrc").exists()
    again = _run(home, work, "zsh")
    assert again.returncode == 0, again.stderr
    rewritten = (home / ".zshrc").read_text(encoding="utf-8")
    assert rewritten.count("# >>> wfs-studio >>>") == 1

    bash_home = tmp_path / "bash-home"
    bash_home.mkdir()
    bash = _run(bash_home, work, "BASH", alias="studio")
    assert bash.returncode == 0, bash.stderr
    bashrc = (bash_home / ".bashrc").read_text(encoding="utf-8")
    assert "alias studio=" in bashrc
    assert not (bash_home / ".zshrc").exists()


def test_installer_rejects_a_bad_alias_and_a_full_folder(tmp_path: Path):
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    _checkout(work)
    bad = _run(home, work, "bash", alias="wfs studio")
    assert bad.returncode == 1
    assert "alias" in bad.stderr.lower()
    assert not (home / ".bashrc").exists()

    messy = tmp_path / "messy"
    messy.mkdir()
    (messy / "notes.txt").write_text("keep", encoding="utf-8")
    refused = _run(home, messy, "bash")
    assert refused.returncode == 1
    assert "not empty" in refused.stderr
    assert (messy / "notes.txt").read_text(encoding="utf-8") == "keep"
