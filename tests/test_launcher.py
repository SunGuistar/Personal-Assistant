"""启动器使用临时配置与假进程验证，不启动或停止真实服务。"""

import subprocess
import sys
import pytest

from launcher import launch


def test_port_config_and_command_share_one_value(tmp_path, monkeypatch):
    config = tmp_path / "launcher.ini"
    config.write_text("[server]\nport = 18620\n", encoding="ascii")
    monkeypatch.setattr(launch, "PORT", launch.read_port(config))
    interpreter = tmp_path / "python.exe"
    interpreter.touch()
    monkeypatch.setenv("PH_HUB_PYTHON", str(interpreter))
    command = launch.resolve_python_cmd()
    assert command[command.index("--port") + 1] == "18620"
    assert command[command.index("--app-dir") + 1] == str(launch.ROOT_DIR)


@pytest.mark.parametrize("value", ["0", "65536", "wrong"])
def test_invalid_port_rejected(tmp_path, value):
    config = tmp_path / "launcher.ini"
    config.write_text(f"[server]\nport = {value}\n", encoding="ascii")
    with pytest.raises(RuntimeError):
        launch.read_port(config)


@pytest.mark.parametrize("action, expected", [
    ("start", ["start"]), ("stop", ["stop"]), ("restart", ["stop", "start"]),
])
def test_actions(action, expected, monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["launch.py", "--action", action, "--no-browser"])
    monkeypatch.setattr(launch, "stop_service", lambda: calls.append("stop"))
    monkeypatch.setattr(launch, "ensure_service", lambda: calls.append("start"))
    assert launch.main() == 0
    assert calls == expected


def test_restart_aborts_if_stop_fails(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["launch.py", "--action", "restart"])
    def refuse():
        raise RuntimeError("unverified process")
    monkeypatch.setattr(launch, "stop_service", refuse)
    monkeypatch.setattr(launch, "ensure_service", lambda: pytest.fail("must not start"))
    with pytest.raises(RuntimeError, match="unverified"):
        launch.main()


def test_restart_uses_config_port_for_stop_health_and_start(tmp_path, monkeypatch):
    config = tmp_path / "launcher.ini"
    config.write_text("[server]\nport = 18620\n", encoding="ascii")
    monkeypatch.setattr(launch, "CONFIG_PATH", config)
    monkeypatch.setattr(sys, "argv", ["launch.py", "--action", "restart", "--no-browser"])
    commands = []
    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    interpreter = tmp_path / "python.exe"
    interpreter.touch()
    monkeypatch.setenv("PH_HUB_PYTHON", str(interpreter))
    def fake_start():
        assert launch.HEALTH_URL == "http://127.0.0.1:18620/api/health"
        assert launch.HOME_URL == "http://127.0.0.1:18620/"
        command = launch.resolve_python_cmd()
        assert command[command.index("--port") + 1] == "18620"
    monkeypatch.setattr(launch, "ensure_service", fake_start)
    launch.main()
    assert commands[0][commands[0].index("-Port") + 1] == "18620"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
@pytest.mark.parametrize("owner", ["own", "other", "legacy", "absent"])
def test_stop_script_with_fake_processes(tmp_path, owner):
    root = str(tmp_path).replace("'", "''")
    command = '-m uvicorn --factory app.main:create_app --port 18621'
    if owner != "legacy":
        command += f' --app-dir "{root if owner == "own" else root + "-other"}"'
    present = "$false" if owner == "absent" else "$true"
    harness = tmp_path / "fake_stop.ps1"
    harness.write_text(f"""
$global:launcher_test_present = {present}
function Get-NetTCPConnection {{
    if ($global:launcher_test_present) {{ [pscustomobject]@{{ LocalPort=18621; OwningProcess=12345 }} }}
}}
function Get-CimInstance {{
    [pscustomobject]@{{ Name='python.exe'; ProcessId=12345; CreationDate='fixed'; CommandLine='{command}' }}
}}
function Stop-Process {{
    param($Id, $ErrorAction)
    Write-Output "STOP:$Id"
    $global:launcher_test_present = $false
}}
& '{str(launch.ROOT_DIR / 'launcher' / 'stop_service.ps1').replace(chr(39), chr(39) * 2)}' -Port 18621 -AppDir '{root}'
exit $LASTEXITCODE
""", encoding="ascii")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                             "-File", str(harness)], capture_output=True, text=True, timeout=20)
    if owner in ("own", "absent"):
        assert result.returncode == 0, result.stderr
        assert ("STOP:12345" in result.stdout) == (owner == "own")
    else:
        assert result.returncode == 1
        assert "STOP:" not in result.stdout
        assert "Refusing to stop" in result.stderr


def test_windows_entry_files_are_ascii():
    for path in (launch.ROOT_DIR / "launcher").iterdir():
        if path.suffix in (".bat", ".vbs", ".ini", ".ps1"):
            path.read_bytes().decode("ascii")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_vbs_builds_action_without_launching(action):
    result = subprocess.run(["cscript.exe", "//nologo",
        str(launch.ROOT_DIR / "launcher" / "start_hub.vbs"), action, "/check"],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert f"--action {action}" in result.stdout
    assert str(launch.ROOT_DIR / "launcher" / "launch.py") in result.stdout
