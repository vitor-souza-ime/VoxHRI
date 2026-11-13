import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import main
from main import Robot, AVATARS
from openrouter_client import OpenRouterClient, Response
from study_protocol import load_questions, transcript_discrepancy
from storage import read_csv


class FakeResponse:
    status_code = 200
    ok = True
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def iter_lines(self, decode_unicode=True):
        yield b'data: {"id":"gen-id","model":"nvidia/nemotron-3-super-120b-a12b","choices":[{"delta":{"content":"Hello"}}]}'
        yield b'data: {"choices":[{"delta":{"content":" there!"},"finish_reason":"stop"}]}'
        yield b'data: {"choices":[],"usage":{"prompt_tokens":45,"completion_tokens":2,"total_tokens":47,"cost":0.0002}}'
        yield b'data: [DONE]'


class ScriptedClient:
    def ask(self, prompt, history=()):
        return Response(success=True, reply="The robot gives a short answer.",
                        model_requested=config.MODEL, model_reported=config.MODEL,
                        llm_s=0.31, ttft_s=0.18,
                        input_tokens=75+len(history)*20,
                        output_tokens=9, total_tokens=84+len(history)*20,
                        cost_usd=0.00003, http_status=200)
    def enrich_metadata(self, response):
        pass


class Tests(unittest.TestCase):
    def test_fixed_model_and_questions(self):
        self.assertEqual(config.MODEL, "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(len(load_questions()), 30)
        self.assertEqual(len({r['id'] for r in load_questions()}), 30)
        self.assertEqual(len(AVATARS), 3)
        self.assertEqual(transcript_discrepancy("What is a sensor?", "what is a sensor"), 0)

    def test_missing_api_key(self):
        response = OpenRouterClient(api_key="").ask("Hello")
        self.assertFalse(response.success)
        self.assertIn("No API key", response.error)

    def test_openrouter_streaming_parses_usage(self):
        session = mock.Mock()
        session.post.return_value = FakeResponse()
        response = OpenRouterClient(api_key="test", session=session).ask("Hello")
        self.assertTrue(response.success)
        self.assertEqual(response.reply, "Hello there!")
        self.assertEqual(response.total_tokens, 47)
        self.assertEqual(response.cost_usd, 0.0002)
        self.assertIsNotNone(response.ttft_s)

    def _robot(self, tmp, demo=False):
        patcher = mock.patch.object(main, "RESULTS", Path(tmp))
        patcher.start(); self.addCleanup(patcher.stop)
        avatar = mock.patch("main.rotate_avatar", return_value="orbit")
        avatar.start();self.addCleanup(avatar.stop)
        robot = Robot(demo=demo, microphone=False, tts=False)
        robot.client=ScriptedClient()
        return robot

    def test_no_collection_before_explicit_start(self):
        with tempfile.TemporaryDirectory() as td:
            robot=self._robot(td)
            self.assertFalse(robot.active)
            self.assertIsNone(robot.process("typed", "Hello"))
            self.assertFalse(list(Path(td).rglob("interactions.csv")))

    def test_start_creates_csv_and_finish_marks_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            robot=self._robot(td)
            self.assertTrue(robot.begin_session())
            self.assertTrue(robot.csv_path.exists())
            self.assertEqual(len(read_csv(robot.csv_path)),0)
            self.assertFalse(robot.begin_session())
            with mock.patch.object(config, "ENABLE_METADATA_LOOKUP", False):
                row=robot.process("typed", "What is artificial intelligence in one sentence?")
            self.assertTrue(row['success'])
            self.assertEqual(len(read_csv(robot.csv_path)),1)
            self.assertTrue(robot.request_finish())
            self.assertTrue(robot.finish_session())
            self.assertFalse(robot.active)
            manifest=json.loads((robot.folder/"session_config.json").read_text())
            self.assertEqual(manifest['status'], 'incomplete')
            self.assertEqual(manifest['successful_questions'],1)
            self.assertEqual(len(read_csv(robot.folder/"human_evaluation.csv")),1)
            self.assertEqual(len(list((robot.folder/"figures").glob("*.png"))),10)

    def test_30_successes_auto_request_finish(self):
        with tempfile.TemporaryDirectory() as td:
            robot=self._robot(td)
            self.assertTrue(robot.begin_session())
            with mock.patch.object(config, "ENABLE_METADATA_LOOKUP", False):
                for row in load_questions():
                    result=robot.process("typed", row['prompt'])
                    self.assertTrue(result['success'])
            self.assertEqual(robot.study_index,30)
            self.assertTrue(robot.finish_requested)
            self.assertEqual(len(read_csv(robot.csv_path)),30)
            self.assertTrue(robot.finish_session())
            summary=json.loads((robot.folder/"session_summary.json").read_text())
            self.assertEqual(summary['status'],'complete')
            self.assertEqual(summary['successful'],30)
            self.assertEqual(len(read_csv(robot.folder/"human_evaluation.csv")),30)
            self.assertEqual(len(list((robot.folder/"figures").glob("*.png"))),10)
            self.assertEqual(len(read_csv(robot.csv_path)),30)
            self.assertEqual(len(set(x['prompt_id'] for x in read_csv(robot.csv_path))),30)

    def test_demo_separate_from_scientific_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            robot=self._robot(td,demo=True)
            robot.begin_session()
            self.assertIn("demos",str(robot.csv_path))
            row=robot.process("typed",load_questions()[0]['prompt'])
            self.assertTrue(row['is_demo'])
            robot.request_finish()
            robot.finish_session()
            self.assertFalse(list(Path(td).glob('sessions/**/*')))
            self.assertFalse((robot.folder/'figures').exists())

if __name__=="__main__":
    unittest.main()
