import os
import subprocess
import uuid

IMAGE = "cses-arcade-sandbox"
TIME_LIMIT = 5


def main():
    # Give this test container a unique name.
    name = f"cses-timeout-{uuid.uuid4().hex[:8]}"

    os.makedirs("logs",exist_ok=True)
    log_path= f"logs/{name}.log"

    # Start a container running a test process.
    start = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", name,
            "--memory=256m",
            "--cpus=1",
            "--pids-limit=64",
            "--network=none",
            IMAGE,
            "python", "-c", "import sys; print('Bot crashed'); sys.exit(1)",
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

        exit_code = int(result.stdout.strip())

        if exit_code == 0:
            print("Outcome: completed")

        else:
            print("Outcome : failed")

        print(f"Exit code : {exit_code}")        

    except subprocess.TimeoutExpired:

        print("Outcome : Timed out")
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
        # Capture container output before removing it.
        logs = subprocess.run(
            ["docker", "logs", name],
            capture_output=True,
            text=True,
        )

        # Save the output to a file.
        with open(log_path, "w") as log_file:
            log_file.write(logs.stdout)
            log_file.write(logs.stderr)

        print(f"Container logs saved to {log_path}")

        # Remove the container even if the test fails.
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            text=True,
        )

        print("Container cleanup complete.")


if __name__ == "__main__":
    main()
