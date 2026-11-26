"""Create a fresh workspace for one benchmark task (public files only).

    python -m benchmarks.coding_agent.prepare --task T1 --workspace /tmp/ws_t1
"""
import argparse
import os
import shutil

from .common import build_workspace, task_name


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True, help="T1, T2 or T3")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--force", action="store_true", help="replace an existing workspace")
    args = ap.parse_args()
    if os.path.exists(args.workspace) and os.listdir(args.workspace):
        if not args.force:
            ap.error(f"{args.workspace} is not empty (use --force to replace it)")
        shutil.rmtree(args.workspace)
    build_workspace(args.task, args.workspace)
    print(f"prepared {task_name(args.task)} in {args.workspace}")


if __name__ == "__main__":
    main()
