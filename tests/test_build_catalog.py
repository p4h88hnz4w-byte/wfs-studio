import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-catalog.sh"


def _compiler(path: Path, name: str, major: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    binary = path / name
    binary.write_text(
        "#!/bin/bash\n"
        "if [ \"$1\" = \"-dumpversion\" ]; then\n"
        f"  echo {major}\n"
        "  exit 0\n"
        "fi\n"
        "echo unsupported >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)


def _check(path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = str(path) + os.pathsep + "/bin" + os.pathsep + "/usr/bin"
    env["WFS_CATALOG_CHECK_ONLY"] = "1"
    env["WFS_CATALOG_UNAME"] = "Linux"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_linux_build_uses_gpp_14_when_that_command_exists(tmp_path: Path):
    _compiler(tmp_path, "g++", "13")
    _compiler(tmp_path, "g++-14", "14")
    _compiler(tmp_path, "gcc-14", "14")
    result = _check(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "g++-14"


def test_linux_build_accepts_plain_gpp_at_gcc_14(tmp_path: Path):
    _compiler(tmp_path, "g++", "14.2.0")
    result = _check(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "g++"


def test_linux_build_refuses_gcc_13(tmp_path: Path):
    _compiler(tmp_path, "g++", "13")
    result = _check(tmp_path)
    assert result.returncode == 1
    assert result.stderr.strip() == "GCC 14 is required."


def test_mac_build_does_not_require_gpp_14():
    env = os.environ.copy()
    env["WFS_CATALOG_CHECK_ONLY"] = "1"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "default"
