
import subprocess
import uuid

IMAGE = "cses-arcade-sandbox"
TIME_LIMIT = 5


def main():
    # Give this test container a unique name.
    name = f"cses-timeout-{uuid.uuid4().hex[:8]}"

    # Start a container running an infinite loop.
    start = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", name,
            "--memory=256m",
            "--cpus=1",
            "--pids-limit=64",
            "--network=none",
            IMAGE,
            "python", "-c", "while True: pass",
        ],
        capture_output=True,
        text=True,
    )

    if start.returncode != 0:
        print("Failed to start container:")
        print(start.stderr)
        return

    print(f"Started container: {name}")

    try:
        # Wait for the container, but enforce a deadline.
        result = subprocess.run(
            ["docker", "wait", name],
            capture_output=True,
            text=True,
            timeout=TIME_LIMIT,
            check=True,
        )

        print(f"Container exited naturally: {result.stdout.strip()}")

    except subprocess.TimeoutExpired:
        print("Time limit exceeded. Stopping container...")

        stop = subprocess.run(
            ["docker", "stop", "--time", "1", name],
            capture_output=True,
            text=True,
        )

        if stop.returncode == 0:
            print("Container stopped successfully.")
        else:
            print("Stop failed:", stop.stderr)

    finally:
        # Remove the container even if the test fails.
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            text=True,
        )
        print("Container cleanup complete.")


if __name__ == "__main__":
    main()
