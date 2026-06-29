"""command — BYO adapter: run an arbitrary `agent.cmd` from gallery.yaml.

For aider / Codex CLI / a shell script. `agent.cmd` is a template; `{task_file}` is substituted
with the path to the task bundle. The command is responsible for editing + replying.

    agent:
      adapter: command
      cmd: "aider --message-file {task_file} {source}"
"""
from __future__ import annotations

import shlex
import subprocess


def available() -> bool:
    return True


def run(task) -> None:
    tmpl = (task.cfg.get("agent", {}) or {}).get("cmd")
    if not tmpl:
        raise RuntimeError("agent.adapter is 'command' but agent.cmd is unset in gallery.yaml")
    cmd = tmpl.format(task_file=task.task_file, source=task.source or "")
    subprocess.run(shlex.split(cmd), cwd=task.cfg["repo_root"], check=False)
