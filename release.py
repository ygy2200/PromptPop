# -*- coding: utf-8 -*-
"""PromptPop 一条龙发布脚本（第八轮 R16 固化惯例）。

流程：全量回归 → 打包(excludes/no-upx) → 版本校验 → 部署桌面(备份旧件)
      → git commit+push(走代理) → Release+exe 上传。
用法：python release.py 0.7.11   （版本号前缀 v 自动加）
前提：代理 7890 在线；git credential 里有有效 GitHub 凭据。
"""
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
PROXY = "http://127.0.0.1:7890"


def run(cmd, **kw):
    print("$", " ".join(str(c) for c in cmd) if isinstance(cmd, list) else cmd)
    return subprocess.run(cmd, cwd=str(ROOT), shell=isinstance(cmd, str), **kw)


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit("用法: python release.py <版本号>  如 0.7.11")
    ver = sys.argv[1]
    tag = "v" + ver

    # 1) 全量回归（零失败才继续）
    r = run([sys.executable, "tests/run_all.py"], env=None)
    if r.returncode != 0:
        sys.exit("!! 全量回归有失败，中止发布")

    # 2) 打包
    r = run([sys.executable, "-m", "PyInstaller", "PromptPop-onefile.spec",
             "--noconfirm", "--distpath", f"dist_v{ver.replace('.', '')}",
             "--workpath", f"build_v{ver.replace('.', '')}"])
    exe = ROOT / f"dist_v{ver.replace('.', '')}" / "PromptPop.exe"
    if r.returncode != 0 or not exe.exists():
        sys.exit("!! 打包失败")

    # 3) 版本元信息校验
    vi = run(["powershell", "-NoProfile", "-Command",
              f"(Get-Item '{exe}').VersionInfo.FileVersion"], capture_output=True,
             text=True).stdout.strip()
    if not vi.startswith(ver):
        sys.exit(f"!! exe 版本 {vi} != 目标 {ver}（version_info.py 忘改了？）")

    # 4) 部署桌面（备份旧件）
    desk = Path(r"C:\Users\y\Desktop\PromptPop.exe")
    if desk.exists():
        bak = ROOT / f"PromptPop.exe.bak-{ver}-{exe.stat().st_size}"
        shutil.copy2(desk, bak)
        print("旧桌面 exe 已备份:", bak.name)
    shutil.copy2(exe, desk)
    print("桌面已更新:", desk, vi)

    # 5) git commit + push
    run("git add -A")
    run(["git", "commit", "-m", f"PromptPop {tag} 发布（回归全绿→打包→部署）",
         "--allow-empty"])
    r = run(["git", "-c", f"http.proxy={PROXY}", "push", "origin", "main"])
    if r.returncode != 0:
        sys.exit("!! push 失败（检查代理/凭据）")

    # 6) Release + exe 上传（token 走 git credential）
    p = subprocess.run(["git", "credential", "fill"],
                       input="protocol=https\nhost=github.com\n",
                       capture_output=True, text=True)
    token = next((l.split("=", 1)[1].strip() for l in p.stdout.splitlines()
                  if l.startswith("password=")), "")
    if not token:
        sys.exit("!! 未取到 GitHub token")
    op = urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": PROXY, "https": PROXY}))
    op.addheaders = [("User-Agent", "promptpop-release"),
                     ("Authorization", f"Bearer {token}"),
                     ("Accept", "application/vnd.github+json")]

    def api(url, data=None, method=None, timeout=1800):
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method=method)
        with op.open(req, timeout=timeout) as resp:
            b = resp.read()
            return json.loads(b) if b else {}

    rel = api("https://api.github.com/repos/ygy2200/PromptPop/releases",
              {"tag_name": tag, "target_commitish": "main",
               "name": f"PromptPop {tag}", "body": f"PromptPop {tag} · 划词提示词优化器\n\n变更见仓库 ITERATION_OPT_LOG-*.md"},
              method="POST")
    upload = rel["upload_url"].split("{")[0]
    req = urllib.request.Request(f"{upload}?name=PromptPop-{tag}.exe",
                                 data=exe.read_bytes(), method="POST")
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("Content-Length", str(exe.stat().st_size))
    asset = json.loads(op.open(req, timeout=1800).read())
    print(f"Release: {rel.get('html_url')}")
    print(f"exe 附件: {asset.get('state')} {asset.get('browser_download_url')}")
    print("\n发布完成 ✓")


if __name__ == "__main__":
    main()
