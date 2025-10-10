from __future__ import annotations

import shutil
import subprocess


class ShellError(RuntimeError):
    pass


def run(cmd: list[str], timeout: int = 15) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout)
        return out.decode()
    except subprocess.CalledProcessError as e:
        raise ShellError(f"cmd failed: {' '.join(cmd)}\n{e.output.decode()}")


def has_cmd(name: str) -> bool:
    return shutil.which(name) is not None
