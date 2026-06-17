#!/usr/bin/env python3
"""Generate a concise AI change report from the current git worktree."""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import subprocess
import sys
import traceback


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / ".openharness" / "last_ai_change.md"


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.rstrip("\n")


def classify_impact(path: str) -> list[str]:
    tags: list[str] = []
    if path.startswith("web_config/static/"):
        tags.append("前端界面/静态资源")
    if path.startswith("web_config/") and not path.startswith("web_config/static/"):
        tags.append("Web 服务端")
    if path.startswith("src/openharness/tools/"):
        tags.append("Agent 工具")
    elif path.startswith("src/openharness/"):
        tags.append("OpenHarness 核心")
    if path.startswith("tests/") or path.startswith("scripts/test_"):
        tags.append("测试")
    if path.startswith("scripts/") and "测试" not in tags:
        tags.append("开发脚本")
    if path.endswith((".md", ".markdown", ".rst")):
        tags.append("文档/规则")
    if path.endswith((".js", ".ts", ".tsx", ".css", ".html")):
        tags.append("浏览器行为/样式")
    if path.endswith(".py"):
        tags.append("Python 运行逻辑")
    return tags or ["影响待确认"]


def parse_status() -> tuple[list[str], list[str]]:
    status = run_git(["status", "--short"])
    tracked: list[str] = []
    untracked: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if line.startswith("?? "):
            untracked.append(path)
        else:
            tracked.append(path)
    return tracked, untracked


def parse_numstat() -> dict[str, tuple[str, str]]:
    output = run_git(["diff", "HEAD", "--numstat"])
    stats: dict[str, tuple[str, str]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            stats[parts[2]] = (parts[0], parts[1])
    return stats


def make_file_summary(path: str, numstat: dict[str, tuple[str, str]]) -> str:
    tags = "、".join(classify_impact(path))
    if path in numstat:
        added, deleted = numstat[path]
        size = f"+{added}/-{deleted}"
    else:
        size = "未纳入 diff"
    return f"- `{path}`：{tags}；变更规模 {size}"


def build_report() -> str:
    tracked, untracked = parse_status()
    changed_paths = tracked + untracked
    now = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    branch = run_git(["branch", "--show-current"]) or "(detached)"
    stat = run_git(["diff", "HEAD", "--stat"]) or "无 tracked diff"
    numstat = parse_numstat()

    lines = [
        "# AI Change Report",
        "",
        f"- 生成时间: {now}",
        f"- 分支: `{branch}`",
        f"- 变更文件数: {len(changed_paths)}",
        "",
        "## 文件清单",
    ]
    if tracked:
        lines.append("")
        lines.append("### 已跟踪文件")
        lines.extend(make_file_summary(path, numstat) for path in tracked)
    if untracked:
        lines.append("")
        lines.append("### 未跟踪文件")
        lines.extend(make_file_summary(path, numstat) for path in untracked)
    if not changed_paths:
        lines.append("")
        lines.append("- 当前工作区没有未提交改动。")

    lines.extend([
        "",
        "## 影响范围",
    ])
    impact_map: dict[str, list[str]] = {}
    for path in changed_paths:
        for tag in classify_impact(path):
            impact_map.setdefault(tag, []).append(path)
    if impact_map:
        for tag, paths in sorted(impact_map.items()):
            preview = ", ".join(f"`{path}`" for path in paths[:5])
            suffix = f" 等 {len(paths)} 个文件" if len(paths) > 5 else ""
            lines.append(f"- {tag}: {preview}{suffix}")
    else:
        lines.append("- 无")

    lines.extend([
        "",
        "## Git Diff Stat",
        "",
        "```text",
        stat,
        "```",
        "",
        "## 给 AI 最终回复的核对清单",
        "",
        "- 说明修改了哪些文件，以及每个文件改了什么。",
        "- 说明可能影响的页面、接口、数据格式、配置或部署流程。",
        "- 说明已运行的验证命令；未验证的地方要明确说。",
        "- 说明是否已同步到服务端部署目录。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Report output path. Defaults to .openharness/last_ai_change.md.",
    )
    args = parser.parse_args()

    output = pathlib.Path(args.output)
    if not output.is_absolute():
        output = REPO_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_report()
    output.write_text(report, encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
