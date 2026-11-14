"""标准库 Tk 启动诊断窗口；关闭窗口不会中断启动或后端。"""
import logging
import queue
import threading
import time


def run_with_progress(operation, initial_elapsed=0.0):
    started = time.monotonic() - initial_elapsed
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title("个人助手 · 启动诊断")
    root.geometry("880x560")
    status = tk.StringVar(value="正在启动…")
    tk.Label(root, textvariable=status, anchor="w", font=("Microsoft YaHei UI", 12)).pack(fill="x", padx=16, pady=12)
    text = ScrolledText(root, wrap="word", font=("Microsoft YaHei UI", 10))
    text.pack(fill="both", expand=True, padx=16, pady=(0, 12))
    text.configure(state="disabled")
    tk.Label(root, text="完成后可关闭此窗口。关闭窗口不会停止服务。诊断日志：launcher/logs/launcher.log", anchor="w").pack(fill="x", padx=16, pady=(0, 12))
    messages = queue.Queue()
    result = []

    class WindowHandler(logging.Handler):
        def emit(self, record):
            messages.put(self.format(record))

    handler = WindowHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    logger = logging.getLogger("__main__")
    logger.addHandler(handler)

    def work():
        try:
            result.append(operation())
        except Exception as exc:
            logger.error("启动失败：%s；详情见 launcher.log / uvicorn.log", type(exc).__name__)
            result.append(1)

    worker = threading.Thread(target=work, daemon=False)
    worker.start()

    def update():
        while True:
            try:
                message = messages.get_nowait()
            except queue.Empty:
                break
            text.configure(state="normal")
            text.insert("end", message + "\n")
            text.see("end")
            text.configure(state="disabled")
        if result and messages.empty():
            status.set(f"{'启动完成' if result[0] == 0 else '启动失败'} · 总耗时 {time.monotonic() - started:.2f} 秒")
            # 完成时间固定，窗口保留供检查。
            return
        status.set(f"正在启动 · 已用 {time.monotonic() - started:.1f} 秒")
        root.after(100, update)

    root.after(100, update)
    root.mainloop()
    logger.removeHandler(handler)
    worker.join()
    return result[0] if result else 1
