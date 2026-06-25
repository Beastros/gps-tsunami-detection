from pathlib import Path
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pipeline-push.yml"


class PipelineWorkflowTests(unittest.TestCase):
    def test_scheduled_pipeline_does_not_preconsume_usgs_events(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertNotIn("python usgs_listener.py --once", workflow)
        self.assertIn("python pipeline.py --once", workflow)


if __name__ == "__main__":
    unittest.main()
