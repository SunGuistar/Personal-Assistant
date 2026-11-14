"""个人助手 Windows 启动器（ARCH §3.5）。

流程：读取 launcher.ini → 打开浏览器启动页 → 健康检查；
未运行则拉起 uvicorn → 轮询首页就绪（默认 120s 超时）→ 启动页自动进入首页。
非首页模块由后端继续初始化，前端按模块状态显示加载中。

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
from datetime import datetime
import logging
from logging.handlers import TimedRotatingFileHandler
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
import uuid
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
# Windows 登录后磁盘与 CPU 繁忙，冷启动可能超过 30 秒。
READY_TIMEOUT_SECONDS = 120.0
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


def bootstrap_seconds() -> float:
    """VBS 进入 Python 前的耗时（墙钟、秒精度）；其余阶段用单调时钟。"""
    value = os.environ.get("PH_LAUNCH_BOOTSTRAP_AT", "")
    try:
        return max(0.0, (datetime.now() - datetime.fromisoformat(value)).total_seconds())
    except (ValueError, TypeError):
        return 0.0


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
    try:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            shell=isinstance(command, str),  # conda 形态为完整命令字符串
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        log_file.close()
    return process


def read_startup_events(trace: Path, offset: int) -> int:
    """逐行读取当前启动专用文件；未写完的行留待下次读取。"""
    if not trace.exists():
        return offset
    with trace.open("rb") as source:
        source.seek(offset)
        while line := source.readline():
            if not line.endswith(b"\n"):
                break
            offset = source.tell()
            try:
                event = json.loads(line)
                state = {"running": "进行中", "success": "完成", "failed": "失败"}[event["status"]]
                logger.info("后端 · %s · %s · 阶段 %.2fs", event["stage"], state, event["duration_s"])
            except (ValueError, KeyError, TypeError):
                logger.warning("启动诊断记录格式错误")
    return offset


def ensure_service() -> None:
    started = time.monotonic()
    logger.info("开始启动检查 · 健康检查进行中")
    if service_ready(HEALTH_URL):
        logger.info("服务已在运行 · 启动总耗时 %.2fs（复用现有服务）", time.monotonic() - started)
        return

    logger.info("健康检查完成 · 阶段 %.2fs", time.monotonic() - started)
    phase = time.monotonic()
    logger.info("解释器检测 · 进行中（Conda 检测最多等待 180s）")
    python_cmd = resolve_python_cmd()
    logger.info("解释器检测 · 完成 · 阶段 %.2fs", time.monotonic() - phase)
    log_dir = ROOT_DIR / "launcher" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    trace = log_dir / f"startup-{uuid.uuid4().hex}.jsonl"
    previous = os.environ.get("PH_STARTUP_TRACE")
    os.environ["PH_STARTUP_TRACE"] = str(trace)
    phase = time.monotonic()
    try:
        logger.info("启动后端进程 · 进行中")
        process = start_service(log_dir, python_cmd)
    finally:
        if previous is None:
            os.environ.pop("PH_STARTUP_TRACE", None)
        else:
            os.environ["PH_STARTUP_TRACE"] = previous
    logger.info("启动后端进程 · 完成 · 阶段 %.2fs", time.monotonic() - phase)
    waiting = time.monotonic()
    deadline = waiting + READY_TIMEOUT_SECONDS
    next_update = waiting
    offset = 0
    while time.monotonic() < deadline:
        offset = read_startup_events(trace, offset)
        if process.poll() is not None:
            raise RuntimeError(
                f"服务进程提前退出（code={process.returncode}），请查看 launcher/logs/uvicorn.log"
            )
        if service_ready(HEALTH_URL):
            read_startup_events(trace, offset)
            logger.info("服务已就绪 · 等待后端 %.2fs · 启动总耗时 %.2fs", time.monotonic() - waiting, time.monotonic() - started)
            return
        if time.monotonic() >= next_update:
            logger.info("等待后端就绪 · 已等待 %.1fs · 累计 %.1fs", time.monotonic() - waiting, time.monotonic() - started)
            next_update = time.monotonic() + 5
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"服务 {READY_TIMEOUT_SECONDS:.0f}s 内未就绪，请查看 launcher/logs/uvicorn.log")


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
    parser.add_argument("--progress", action="store_true", help="显示启动进度与耗时窗口")
    parser.add_argument("--action", choices=("start", "stop", "restart"), default="start")
    args = parser.parse_args()
    phase = time.monotonic()
    bootstrap = bootstrap_seconds()
    started = phase - bootstrap
    if bootstrap:
        logger.info("启动脚本 / Conda 引导 · 完成 · 阶段约 %.2fs（进入 Python 前，秒精度）", bootstrap)
    PORT = read_port(CONFIG_PATH)
    logger.info("读取启动配置 · 完成 · 阶段 %.2fs", time.monotonic() - phase)
    HOME_URL = f"http://127.0.0.1:{PORT}/"
    HEALTH_URL = f"{HOME_URL}api/health"

    if args.action == "stop":
        stop_service()
        return 0
    page = None
    if not args.no_browser:
        if __package__:
            from .startup_page import StartupPage
        else:
            from startup_page import StartupPage
        page = StartupPage(logger, HOME_URL, initial_elapsed=bootstrap_seconds())
        try:
            webbrowser.open(page.url)
        except Exception:
            page.close()
            raise
        logger.info("浏览器启动页已打开，首页就绪后自动进入")
    try:
        if args.action == "restart":
            phase = time.monotonic()
            logger.info("停止当前工作区服务 · 进行中")
            stop_service()
            logger.info("停止当前工作区服务 · 完成 · 阶段 %.2fs", time.monotonic() - phase)
        ensure_service()
    except Exception as exc:
        if page:
            page.finish(error=f"启动失败（{type(exc).__name__}），请查看 launcher/logs/launcher.log 后重试。")
        raise
    logger.info("首页启动完成 · 总耗时 %.2fs · 其他模块继续后台初始化", time.monotonic() - started)
    if page:
        page.finish()
    return 0


if __name__ == "__main__":
    log_dir = ROOT_DIR / "launcher" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(log_dir / "launcher.log", when="midnight", backupCount=7, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(handlers=[handler, logging.StreamHandler()], level=logging.INFO)

    def run():
        started = time.monotonic() - bootstrap_seconds()
        try:
            return main()
        except (RuntimeError, TimeoutError, OSError, subprocess.SubprocessError) as exc:
            logger.error("启动器操作失败 · 总耗时 %.2fs · %s", time.monotonic() - started, exc)
            return 1

    if "--progress" in sys.argv:
        from progress_window import run_with_progress
        raise SystemExit(run_with_progress(run, initial_elapsed=bootstrap_seconds()))
    raise SystemExit(run())
