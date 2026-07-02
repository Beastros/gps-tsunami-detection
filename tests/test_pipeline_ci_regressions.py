import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_IMPORTS = (
    "usgs_listener",
    "rinex_downloader",
    "detector_runner",
    "scorer",
    "notify",
    "notify_discord",
    "dyfi_poller",
)


@contextmanager
def stub_pipeline_imports():
    previous = {name: sys.modules.get(name) for name in PIPELINE_IMPORTS}
    try:
        for name in PIPELINE_IMPORTS:
            module = types.ModuleType(name)
            if name == "notify_discord":
                module.send_pipeline_error = lambda *args, **kwargs: None
            sys.modules[name] = module
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@contextmanager
def temporary_cwd(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@contextmanager
def ci_environment():
    previous = {
        "CI": os.environ.get("CI"),
        "GITHUB_ACTIONS": os.environ.get("GITHUB_ACTIONS"),
    }
    os.environ["CI"] = "true"
    os.environ["GITHUB_ACTIONS"] = "true"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def load_pipeline(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


class PipelineCIRegressionTests(unittest.TestCase):
    def test_ci_once_exits_even_when_fast_poll_is_active(self):
        for relative_path in ("pipeline.py", "scripts/pipeline.py"):
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory() as tmp:
                    with temporary_cwd(tmp), stub_pipeline_imports(), ci_environment():
                        fast_poll = {
                            "active": True,
                            "trigger_mag": 6.2,
                            "trigger_place": "test quake",
                            "expires_utc": (
                                datetime.now(timezone.utc) + timedelta(hours=1)
                            ).isoformat(),
                            "poll_interval_sec": 120,
                        }
                        Path("fast_poll.json").write_text(
                            json.dumps(fast_poll), encoding="utf-8"
                        )
                        module = load_pipeline(
                            REPO_ROOT / relative_path,
                            f"test_pipeline_{relative_path.replace('/', '_')}",
                        )

                        calls = []
                        module.run_pipeline = lambda: calls.append("run")

                        def fail_sleep(seconds):
                            raise AssertionError(
                                f"CI --once should not sleep for fast poll ({seconds}s)"
                            )

                        module.time.sleep = fail_sleep
                        module.main(once=True)

                        self.assertEqual(calls, ["run"])

    def test_scheduled_workflow_lets_pipeline_own_usgs_polling(self):
        workflow = (REPO_ROOT / ".github/workflows/pipeline-push.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("cancel-in-progress: true", workflow)
        self.assertNotIn("python usgs_listener.py --once", workflow)
        self.assertNotIn("python dyfi_poller.py", workflow)
        self.assertIn("python pipeline.py --once", workflow)


if __name__ == "__main__":
    unittest.main()
