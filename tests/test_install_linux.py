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
    zsh = _run(home, work, "zsh", alias="wfs-studio")
    assert zsh.returncode == 0, zsh.stderr
    assert "WSLg" not in zsh.stdout
    rc = (home / ".zshrc").read_text(encoding="utf-8")
    assert "alias wfs-studio=" in rc
    assert "PULSE_SERVER" not in rc
    assert "QT_AUDIO_BACKEND" not in rc
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


def _wsl(tmp_path: Path, *, distro: str, version: str, kernel: str, machine: str = "x86_64", wslg: bool = True, libs: bool | None = None):
    probe = tmp_path / "probe"
    probe.mkdir(parents=True)
    (probe / "version").write_text(kernel + "\n", encoding="utf-8")
    (probe / "os-release").write_text(
        f'ID={distro}\nVERSION_ID="{version}"\n',
        encoding="utf-8",
    )
    wslg_dir = probe / "wslg"
    if wslg:
        wslg_dir.mkdir()
    lib_dir = probe / "libs"
    if libs is not None:
        lib_dir.mkdir()
        if libs:
            for name in (
                "libxcb-cursor.so.0",
                "libxkbcommon.so.0",
                "libxkbcommon-x11.so.0",
                "libEGL.so.1",
                "libGL.so.1",
                "libfontconfig.so.1",
                "libpulse.so.0",
            ):
                (lib_dir / name).write_bytes(b"")
    return probe, wslg_dir, lib_dir


def _run_wsl(home: Path, work: Path, probe: Path, wslg_dir: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["WFS_INSTALL_ALLOW_NON_LINUX"] = "1"
    env["WFS_INSTALL_SKIP_PIP"] = "1"
    env["WFS_INSTALL_DIR"] = str(work)
    env["WFS_INSTALL_ALIAS"] = "wfs-studio"
    env["WFS_INSTALL_SHELL"] = "bash"
    env["WSL_DISTRO_NAME"] = "Ubuntu"
    env["WFS_INSTALL_PROC_VERSION"] = str(probe / "version")
    env["WFS_INSTALL_OS_RELEASE"] = str(probe / "os-release")
    env["WFS_INSTALL_WSLG_DIR"] = str(wslg_dir)
    env["WFS_INSTALL_MACHINE"] = extra.pop("machine", "x86_64")
    env.update(extra)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_wsl2_ubuntu_and_debian_use_the_linux_installer(tmp_path: Path):
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    _checkout(work)
    kernel = "Linux version 6.6.87.2-microsoft-standard-WSL2"
    ubuntu = _wsl(tmp_path / "ubuntu", distro="ubuntu", version="24.04", kernel=kernel)
    result = _run_wsl(home, work, *ubuntu[:2], **{"WFS_INSTALL_SKIP_PACKAGES": "1"})
    assert result.returncode == 0, result.stderr
    assert "Distro: ubuntu 24.04" in result.stdout
    assert "WSL2 Ubuntu" in result.stdout
    assert "Menu music is not supported on WSL." in result.stdout
    alias = (home / ".bashrc").read_text(encoding="utf-8")
    assert "alias wfs-studio=" in alias
    assert "PULSE_SERVER" not in alias
    assert "QT_QPA_PLATFORM=xcb" in alias
    assert "QT_AUDIO_BACKEND=PulseAudio" in alias

    debian_home = tmp_path / "debian-home"
    debian_home.mkdir()
    debian = _wsl(tmp_path / "debian", distro="debian", version="12", kernel=kernel)
    debian_result = _run_wsl(debian_home, work, *debian[:2], **{"WFS_INSTALL_SKIP_PACKAGES": "1"})
    assert debian_result.returncode == 0, debian_result.stderr
    assert "Distro: debian 12" in debian_result.stdout
    assert "WSL2 Debian" in debian_result.stdout
    assert "Menu music is not supported on WSL." in debian_result.stdout
    debian_alias = (debian_home / ".bashrc").read_text(encoding="utf-8")
    assert "PULSE_SERVER" not in debian_alias
    assert "QT_QPA_PLATFORM=xcb" in debian_alias
    assert "QT_AUDIO_BACKEND=PulseAudio" in debian_alias


@pytest.mark.parametrize(
    ("distro", "version", "kernel", "machine", "wslg", "text"),
    [
        ("ubuntu", "24.04", "Linux version 4.4.0-19041-Microsoft", "x86_64", True, "WSL1"),
        ("ubuntu", "20.04", "Linux version 6.6.87.2-microsoft-standard-WSL2", "x86_64", True, "22.04"),
        ("debian", "11", "Linux version 6.6.87.2-microsoft-standard-WSL2", "x86_64", True, "Debian 12"),
        ("fedora", "40", "Linux version 6.6.87.2-microsoft-standard-WSL2", "x86_64", True, "Ubuntu 22.04"),
        ("ubuntu", "24.04", "Linux version 6.6.87.2-microsoft-standard-WSL2", "aarch64", True, "x86_64"),
        ("ubuntu", "24.04", "Linux version 6.6.87.2-microsoft-standard-WSL2", "x86_64", False, "WSLg"),
    ],
)
def test_wsl_outside_the_support_contract_is_refused(tmp_path: Path, distro, version, kernel, machine, wslg, text):
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    _checkout(work)
    probe, wslg_dir, _libs = _wsl(
        tmp_path / "probe",
        distro=distro,
        version=version,
        kernel=kernel,
        machine=machine,
        wslg=wslg,
    )
    result = _run_wsl(
        home,
        work,
        probe,
        wslg_dir,
        machine=machine,
        WFS_INSTALL_SKIP_PACKAGES="1",
    )
    assert result.returncode == 1
    assert text in result.stderr
    assert not (home / ".bashrc").exists()


def test_wsl_installs_without_a_windows_audio_socket(tmp_path: Path):
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    _checkout(work)
    kernel = "Linux version 6.6.87.2-microsoft-standard-WSL2"
    probe, wslg_dir, _libs = _wsl(
        tmp_path / "probe",
        distro="ubuntu",
        version="24.04",
        kernel=kernel,
    )
    result = _run_wsl(home, work, probe, wslg_dir, WFS_INSTALL_SKIP_PACKAGES="1")
    assert result.returncode == 0, result.stderr
    assert "Menu music is not supported on WSL." in result.stdout
    alias = (home / ".bashrc").read_text(encoding="utf-8")
    assert "PULSE_SERVER" not in alias
    assert "QT_AUDIO_BACKEND=PulseAudio" in alias


def test_wsl_refuses_a_windows_drive(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    kernel = "Linux version 6.6.87.2-microsoft-standard-WSL2"
    probe, wslg_dir, _libs = _wsl(tmp_path / "probe", distro="ubuntu", version="22.04", kernel=kernel)
    env_work = "/mnt/c/Users/me/wfs-studio"
    result = _run_wsl(home, Path(env_work), probe, wslg_dir, WFS_INSTALL_SKIP_PACKAGES="1")
    assert result.returncode == 1
    assert "/mnt" in result.stderr
    assert not Path(env_work).exists()
    assert not (home / ".bashrc").exists()


def test_wsl_prints_the_apt_line_when_a_library_is_missing(tmp_path: Path):
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    _checkout(work)
    kernel = "Linux version 6.6.87.2-microsoft-standard-WSL2"
    probe, wslg_dir, lib_dir = _wsl(
        tmp_path / "probe",
        distro="ubuntu",
        version="24.04",
        kernel=kernel,
        libs=True,
    )
    (lib_dir / "libxcb-cursor.so.0").unlink()
    result = _run_wsl(
        home,
        work,
        probe,
        wslg_dir,
        WFS_INSTALL_LIB_DIR=str(lib_dir),
    )
    assert result.returncode == 1
    assert "missing libraries" in result.stderr
    assert "sudo apt install libxcb-cursor0" in result.stderr
    assert "libxkbcommon0" not in result.stderr
    assert not (home / ".bashrc").exists()


def test_wsl_accepts_the_runtime_libraries(tmp_path: Path):
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    _checkout(work)
    kernel = "Linux version 6.6.87.2-microsoft-standard-WSL2"
    probe, wslg_dir, lib_dir = _wsl(
        tmp_path / "probe",
        distro="debian",
        version="13",
        kernel=kernel,
        libs=True,
    )
    result = _run_wsl(
        home,
        work,
        probe,
        wslg_dir,
        WFS_INSTALL_LIB_DIR=str(lib_dir),
    )
    assert result.returncode == 0, result.stderr
    assert "WSL2 Debian" in result.stdout
