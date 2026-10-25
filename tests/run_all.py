"""一键跑全部测试：每个文件独立进程 + 硬超时 + 逐行汇总。

为什么不是 `pytest tests/`：这些测试文件各自在模块级创建 QApplication，
同进程收集会互相冲突；而用 shell 循环跑时，一旦某个文件挂住，
外层 subshell/管道可能一起卡死（本项目已踩过两次，排查成本很高）。
本脚本给每个文件 180s 硬超时，挂住的直接标 TIMEOUT 继续往下跑，
最后打印汇总表并以非零码退出（便于 CI/脚本判断）。

用法： QT_QPA_PLATFORM=offscreen python tests/run_all.py
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILES = [
    "smoke_test.py",
    "test_rounds.py",
    "test_hotkey.py",
    "test_threads.py",
    "test_local_actions.py",
    "test_capture_sel.py",
    "test_overlay_models.py",
    "test_settings_backup.py",
    "test_actions_clipboard.py",
    "test_history_clear.py",
    "test_engine_errors.py",
    "test_engine_cancel.py",
    "test_meta_ctx.py",
    "test_config_import_guard.py",
    "test_library_tag.py",
    "test_template_vars.py",
    "test_round5_ui.py",
    "test_round6_ui.py",
    "test_round7_ui.py",
    "test_stream_buffer.py",
    "adv_config.py",
    "adv_history.py",
    "adv_util.py",
    "adv_text.py",
    "adv_engine.py",
    "adv_threads.py",
    "adv_dataflow.py",
    "test_input_count.py",
    "test_ui_smoke.py",
    "test_cycle2.py",
    "test_cycle3.py",
    "test_cycle4.py",
    "test_cycle5.py",
    "test_cycle6.py",
]
TIMEOUT = 180


def main():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    results = []
    for name in FILES:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            results.append((name, "MISSING", 0.0, ""))
            continue
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, path], capture_output=True, text=True,
                               timeout=TIMEOUT, env=env, cwd=ROOT)
            dt = time.time() - t0
            out = (r.stdout or "").strip().splitlines()
            tail = next((l for l in reversed(out) if l.strip()), "")
            status = "OK" if r.returncode == 0 else "FAIL(%d)" % r.returncode
            results.append((name, status, dt, tail))
            if r.returncode != 0:
                print("--- %s 失败输出（尾部） ---" % name)
                print("\n".join(out[-40:]))
                print((r.stderr or "")[-2000:])
        except subprocess.TimeoutExpired:
            results.append((name, "TIMEOUT", time.time() - t0, ">%ds" % TIMEOUT))

    print("\n================ 汇总 ================")
    bad = 0
    for name, status, dt, tail in results:
        flag = "  " if status == "OK" else "!!"
        if status != "OK":
            bad += 1
        print("%s %-24s %-10s %6.1fs  %s" % (flag, name, status, dt, tail))
    print("=====================================")
    print("共 %d 个文件，失败/超时 %d 个" % (len(results), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
