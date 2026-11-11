"""个人助手 Windows 启动器（ARCH §3.5）。

流程：读取 launcher.ini → 健康检查 → 已运行则直接开浏览器；
未运行则拉起 uvicorn → 轮询就绪（默认 30s 超时）→ 打开默认浏览器首页。

解释器解析顺序（统一使用 Conda `agent` 环境，不依赖项目 .venv）：
1. 环境变量 PH_HUB_PYTHON 显式指定的解释器；
2. Conda `agent` 环境（经 conda 命令解析，兼容 conda 未加入 PATH 的情况；
   conda.exe 按 PATH → 常见安装位置 的顺序探测）；
找不到时抛出明确错误并给出处理建议，绝不自动创建环境。

用法：
    python launcher/launch.py              # 检查并启动服务后打开浏览器
    python launcher/launch.py --no-browser  # 只确保服务运行（调试用）
    python launcher/launch.py --action stop     # 停止本工作区服务
    python launcher/launch.py --action restart  # 停止后重新启动
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "launcher" / "launcher.ini"


def read_port(config_path: Path = CONFIG_PATH) -> int:
    """三个 BAT 共用的唯一端口配置，不使用环境变量隐式覆盖。"""
    config = configparser.ConfigParser()
    if not config.read(config_path, encoding="ascii"):
        raise RuntimeError(f"启动配置不存在: {config_path}")
    try:
        port = config.getint("server", "port")
    except (configparser.Error, ValueError) as exc:
        raise RuntimeError("launcher.ini 的 server.port 必须是整数") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("launcher.ini 的 server.port 必须在 1 到 65535 之间")
    return port


PORT = 0
HOME_URL = ""
HEALTH_URL = ""
logger = logging.getLogger(__name__)
READY_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL = 0.5
AGENT_ENV_NAME = "agent"

# conda 常见安装位置（PATH 探测失败时兜底；也可用 PH_CONDA_BAT 环境变量直接指定）
CONDA_BAT_CANDIDATES = [
    Path(os.environ.get("PH_CONDA_BAT", "")),  # 环境变量优先（空路径自动跳过）
    Path(os.environ.get("USERPROFILE", "")) / "miniconda3" / "condabin" / "conda.bat",
    Path(os.environ.get("USERPROFILE", "")) / "anaconda3" / "condabin" / "conda.bat",
    Path("D:/miniconda/condabin/conda.bat"),
    Path("D:/anaconda3/condabin/conda.bat"),
    Path("C:/ProgramData/miniconda3/condabin/conda.bat"),
    Path("C:/ProgramData/anaconda3/condabin/conda.bat"),
]


class InterpreterNotFound(RuntimeError):
    pass


def service_ready(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def find_conda_bat() -> Path | None:
    on_path = shutil.which("conda.bat")
    if on_path:
        return Path(on_path)
    for candidate in CONDA_BAT_CANDIDATES:
        if str(candidate) in ("", "."):  # Path("") 会退化为当前目录
            continue
        if candidate.exists():
            return candidate
    return None


def resolve_python_cmd() -> list[str] | str:
    """返回完整 uvicorn 启动命令（argv 列表）。

    Conda 经 condabin\\conda.bat + cmd /c 调用（规避 conda.exe 直跑的权限问题）；
    cmd 的首个参数是被引用的路径时，整条命令需再包一层引号。
    """

    uvicorn_args = [
        "-m", "uvicorn", "--factory", "app.main:create_app",
        "--host", "127.0.0.1", "--port", str(PORT), "--app-dir", str(ROOT_DIR),
    ]

    override = os.environ.get("PH_HUB_PYTHON", "").strip()
    if override:
        if Path(override).exists():
            return [override, *uvicorn_args]
        raise InterpreterNotFound(f"PH_HUB_PYTHON 指向的解释器不存在: {override}")

    conda_bat = find_conda_bat()
    if conda_bat is None:
        raise InterpreterNotFound(
            "未找到 Conda。请安装 Miniconda/Anaconda，通过环境变量 "
            "PH_CONDA_BAT 指定 conda.bat，或 PH_HUB_PYTHON 指定解释器。"
        )

    # shell=True 字符串形态：cmd 收到原样命令行，经引用的首 token 合法
    inner = f'"{conda_bat}" run -n {AGENT_ENV_NAME} --no-capture-output python'
    check = subprocess.run(
        f'{inner} -c "import sys; print(sys.executable)"',
        shell=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if check.returncode != 0:
        raise InterpreterNotFound(
            f"Conda 环境 {AGENT_ENV_NAME!r} 不可用（conda.bat 位于 {conda_bat}）。"
            f"请确认该环境存在，或经 PH_HUB_PYTHON 指定解释器。详情: "
            f"{(check.stderr or check.stdout).strip()[:300]}"
        )
    return f"{inner} {subprocess.list2cmdline(uvicorn_args)}"


def start_service(log_dir: Path, command) -> subprocess.Popen:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "uvicorn.log", "a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(ROOT_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        shell=isinstance(command, str),  # conda 形态为完整命令字符串
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return process


def ensure_service() -> None:
    if service_ready(HEALTH_URL):
        print("服务已在运行。")
        return

    print("服务未运行，正在启动…")
    python_cmd = resolve_python_cmd()
    process = start_service(ROOT_DIR / "data" / "logs", python_cmd)
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"服务进程提前退出（code={process.returncode}），请查看 data/logs/uvicorn.log"
            )
        if service_ready(HEALTH_URL):
            print("服务已就绪。")
            return
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"服务 {READY_TIMEOUT_SECONDS:.0f}s 内未就绪，请查看 data/logs/uvicorn.log")


def stop_service() -> None:
    """仅停止带有本工作区 --app-dir 标识的监听进程，拒绝按端口盲杀。"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(ROOT_DIR / "launcher" / "stop_service.ps1"),
         "-Port", str(PORT), "-AppDir", str(ROOT_DIR)],
        capture_output=True, text=True, timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError(f"停止失败: {(result.stderr or result.stdout).strip()[:1500]}")
    logger.info("停止服务完成: port=%s", PORT)


def main() -> int:
    global PORT, HOME_URL, HEALTH_URL
    parser = argparse.ArgumentParser(description="个人助手启动器")
    parser.add_argument("--no-browser", action="store_true", help="只启动服务，不打开浏览器")
    parser.add_argument("--action", choices=("start", "stop", "restart"), default="start")
    args = parser.parse_args()
    PORT = read_port(CONFIG_PATH)
    HOME_URL = f"http://127.0.0.1:{PORT}/"
    HEALTH_URL = f"{HOME_URL}api/health"

    if args.action in ("stop", "restart"):
        stop_service()
    if args.action == "stop":
        return 0
    ensure_service()
    if not args.no_browser:
        webbrowser.open(HOME_URL)
        print(f"已在默认浏览器打开 {HOME_URL}")
    return 0


if __name__ == "__main__":
    log_dir = ROOT_DIR / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / "launcher.log", encoding="utf-8", level=logging.INFO)
    with open(log_dir / "launcher.log", "a", encoding="utf-8") as output:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                raise SystemExit(main())
            except (RuntimeError, TimeoutError, OSError, subprocess.SubprocessError) as exc:
                logger.error("启动器操作失败: %s", exc)
                raise SystemExit(1)
