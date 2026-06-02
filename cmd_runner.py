#!/usr/bin/env python3
import json
import subprocess
import time
import os

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PENDING_FILE = os.path.join(REPO_DIR, "cmds", "pending.json")
RESULT_FILE = os.path.join(REPO_DIR, "cmds", "result.json")
POLL_INTERVAL = 5
TIMEOUT = 120
MAX_OUTPUT = 3000

last_executed_id = None


def read_json(path):
    with open(path, "r") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def git_commit_and_push(message):
    subprocess.run(["git", "add", "cmds/result.json"], cwd=REPO_DIR, check=False)
    subprocess.run(["git", "commit", "-m", message], cwd=REPO_DIR, check=False)
    subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=REPO_DIR, check=False)
    subprocess.run(["git", "push"], cwd=REPO_DIR, check=False)


def run_command(cmd):
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        output = proc.stdout + proc.stderr
        return {
            "returncode": proc.returncode,
            "output": output[-MAX_OUTPUT:] if len(output) > MAX_OUTPUT else output,
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "output": "", "error": "timeout"}
    except Exception as e:
        return {"returncode": -1, "output": "", "error": str(e)}


def main():
    global last_executed_id
    print("cmd_runner started, polling every 5s...")
    while True:
        try:
            pending = read_json(PENDING_FILE)
            cmd_id = pending.get("id")
            cmd = pending.get("cmd")

            if cmd_id and cmd and cmd_id != last_executed_id:
                print(f"Executing [{cmd_id}]: {cmd}")
                result = run_command(cmd)
                payload = {"id": cmd_id, "cmd": cmd, **result}
                write_json(RESULT_FILE, payload)
                git_commit_and_push(f"result: {cmd_id}")
                last_executed_id = cmd_id
                print(f"Done [{cmd_id}], rc={result['returncode']}")
        except Exception as e:
            print(f"Error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
