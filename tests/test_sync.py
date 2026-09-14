import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / "docker/sync-entrypoint.sh"
BUILD_HOOK = ROOT / "docker/build-site.sh"


class SyncSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tempdir)
        self.count_file = self.tempdir / "sync-count"
        self.sleep_log = self.tempdir / "sleep-log"
        self.error_file = self.tempdir / "sync-error.json"
        self.success_file = self.tempdir / "sync-success"

        self.fake_sync = self.tempdir / "fake-git-sync"
        self.fake_sync.write_text(
            """#!/bin/sh
count=0
if [ -f "$FAKE_COUNT_FILE" ]; then
    count=$(cat "$FAKE_COUNT_FILE")
fi
count=$((count + 1))
printf '%s\\n' "$count" > "$FAKE_COUNT_FILE"

if [ "${FAKE_MODE:-transient}" = permanent ]; then
    printf '%s\\n' '{"err":"fatal: repository not found"}' > "$GITSYNC_ERROR_FILE"
    exit 1
fi

if [ "${FAKE_MODE:-transient}" = sustained ] || [ "$count" -le "${FAKE_TRANSIENT_FAILURES:-0}" ]; then
    printf '%s\\n' '{"err":"fatal: Could not resolve host: github.com"}' > "$GITSYNC_ERROR_FILE"
    exit 1
fi
exit 0
"""
        )
        self.fake_sync.chmod(0o755)

        self.fake_sleep = self.tempdir / "fake-sleep"
        self.fake_sleep.write_text(
            """#!/bin/sh
printf '%s\\n' "$1" >> "$FAKE_SLEEP_LOG"
sleep 0.02
"""
        )
        self.fake_sleep.chmod(0o755)

        self.env = os.environ.copy()
        self.env.update(
            {
                "GIT_SYNC_BIN": str(self.fake_sync),
                "GITSYNC_ERROR_FILE": str(self.error_file),
                "SYNC_SUCCESS_FILE": str(self.success_file),
                "SYNC_RETRY_BASE_SECONDS": "2",
                "SYNC_RETRY_MAX_SECONDS": "8",
                "SYNC_RETRY_JITTER_PERCENT": "0",
                "SYNC_RETRY_SLEEP_BIN": str(self.fake_sleep),
                "FAKE_COUNT_FILE": str(self.count_file),
                "FAKE_SLEEP_LOG": str(self.sleep_log),
            }
        )

    def run_supervisor(self, **env):
        child_env = self.env | {key: str(value) for key, value in env.items()}
        return subprocess.run(
            ["sh", str(SUPERVISOR)],
            env=child_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def start_supervisor(self, **env):
        child_env = self.env | {key: str(value) for key, value in env.items()}
        process = subprocess.Popen(
            ["sh", str(SUPERVISOR)],
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self.stop_process, process)
        return process

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

    def wait_for_attempts(self, expected):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.count_file.exists() and int(self.count_file.read_text()) >= expected:
                return
            time.sleep(0.01)
        self.fail(f"sync process did not reach {expected} attempts")

    def retry_delays(self):
        if not self.sleep_log.exists():
            return []
        return [int(value) for value in self.sleep_log.read_text().splitlines()]

    def test_one_transient_dns_failure_then_success(self):
        result = self.run_supervisor(FAKE_TRANSIENT_FAILURES=1)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("2", self.count_file.read_text().strip())
        self.assertEqual([2], self.retry_delays())

    def test_consecutive_transient_failures_then_success(self):
        result = self.run_supervisor(FAKE_TRANSIENT_FAILURES=4)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("5", self.count_file.read_text().strip())
        self.assertEqual([2, 4, 8, 8], self.retry_delays())

    def test_sustained_failure_keeps_supervisor_alive_with_bounded_backoff(self):
        process = self.start_supervisor(FAKE_MODE="sustained")
        self.wait_for_attempts(5)

        self.assertIsNone(process.poll())
        self.assertEqual([2, 4, 8, 8], self.retry_delays()[:4])

    def test_permanent_failure_opens_circuit_without_retrying(self):
        process = self.start_supervisor(FAKE_MODE="permanent")
        self.wait_for_attempts(1)
        time.sleep(0.1)

        self.assertIsNone(process.poll())
        self.assertEqual("1", self.count_file.read_text().strip())
        self.assertEqual([], self.retry_delays())
        process.terminate()
        _, stderr = process.communicate(timeout=2)
        self.assertIn("automatic retries disabled", stderr)


class SyncDeploymentTests(unittest.TestCase):
    def test_sync_policy_and_healthchecks_are_valid(self):
        if not shutil.which("docker"):
            self.skipTest("docker compose is not installed")
        result = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        config = json.loads(result.stdout)
        sync = config["services"]["sync"]
        site = config["services"]["site"]

        self.assertIn("--period=10s", sync["command"])
        self.assertIn("--max-failures=6", sync["command"])
        self.assertIn("--init-max-failures=6", sync["command"])
        self.assertIn("--exechook-command=/usr/local/bin/build-site", sync["command"])
        self.assertNotIn("depends_on", site)
        self.assertIn("healthcheck", site)

    def test_successful_build_hook_publishes_site_and_records_recovery(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            checkout = temp / "checkout"
            checkout.mkdir()
            shutil.copy2(ROOT / "config.toml", checkout)
            for directory in ("content", "static", "templates"):
                shutil.copytree(ROOT / directory, checkout / directory)

            site_link = temp / "deployed-site"
            success_file = temp / "sync-success"
            env = os.environ | {
                "SITE_LINK": str(site_link),
                "SYNC_SUCCESS_FILE": str(success_file),
            }
            subprocess.run(
                ["sh", str(BUILD_HOOK)],
                cwd=checkout,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertTrue(site_link.is_symlink())
            self.assertTrue((site_link / "index.html").is_file())
            self.assertTrue(success_file.is_file())


if __name__ == "__main__":
    unittest.main()
