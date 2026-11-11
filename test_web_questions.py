"""Question selection reaches the worker without exposing reference answers."""
import http.client
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import demo
import web


class QuestionTests(unittest.TestCase):
    def test_public_questions_contain_only_reader_fields(self):
        questions = web.questions()
        self.assertEqual({q['id'] for q in questions}, {'nominal', 'renvoi', 'exception', 'absent', 'validation',
                                                        'obsolete', 'perime', 'brouillon'})
        self.assertTrue(all(set(q) == {'id', 'label', 'question'} for q in questions))
        for invalid in ('unknown', '../renvoi', None, ['renvoi']):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                web.selected_question(invalid)

    def test_each_selected_question_reaches_the_model(self):
        for question in web.questions():
            with self.subTest(case=question['id']):
                stream = Mock(events=iter([]))
                client = Mock()
                client.chat.return_value = stream
                with patch.object(web, 'configuration', return_value=('index', 'chat', 'key', 'http://localhost/v1')), \
                     patch.object(web, 'corpus', return_value={'documents': []}), \
                     patch.object(web, 'pageindex_client', return_value=client):
                    events = list(web.query_events(question['id']))
                self.assertEqual(events[0]['case'], question['id'])
                self.assertEqual(client.chat.call_args.args[0], [{'role': 'user', 'content': question['question']}])

    def test_worker_receives_selected_case(self):
        handler = web.Handler.__new__(web.Handler)
        handler.send_headers = Mock()
        handler.wfile = io.BytesIO()
        process = MagicMock()
        worker = process.__enter__.return_value
        worker.stdout = io.BytesIO(b'PAGEINDEX_EVENT {"type":"answer","answer":"test","citations":[]}\n')
        worker.poll.return_value = 0
        with patch.object(web.subprocess, 'Popen', return_value=process) as popen:
            handler.stream_query('validation')
        self.assertEqual(popen.call_args.args[0][-2:], ['--case', 'validation'])

    def test_archives_are_scoped_to_the_selected_question(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'ROOT', Path(directory)), \
             patch.object(demo, 'ROOT', Path(directory)), patch.dict('os.environ', {'DEMO_QUESTIONS': ''}):
            (Path(directory) / 'questions.json').write_text(json.dumps([
                {'id': 'renvoi', 'question': 'Renvoi ?'}, {'id': 'exception', 'question': 'Exercice ?'}]), encoding='utf-8')
            for case in ('renvoi', 'exception'):
                run = Path(directory) / 'runs' / f'20261111-ask-{case}'
                run.mkdir(parents=True)
                (run / 'trace.txt').write_text('trace', encoding='utf-8')
                (run / 'execution.json').write_text('{}', encoding='utf-8')
            self.assertEqual(web.archived_run('exception').name, '20261111-ask-exception')
            self.assertEqual(web.archived_run().name, '20261111-ask-renvoi')


class QuestionHTTPTests(unittest.TestCase):
    def setUp(self):
        class QuietHandler(web.Handler):
            def log_message(self, *args):
                pass

            def stream_query(self, case):
                self.send_json(200, {'received_case': case})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, body=None, content_type='application/json'):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request('POST', '/api/query', body, {'Content-Type': content_type})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_selected_case_and_legacy_default(self):
        status, data = self.post(json.dumps({'case': 'exception'}))
        self.assertEqual((status, data['received_case']), (200, 'exception'))
        status, data = self.post()
        self.assertEqual((status, data['received_case']), (200, 'renvoi'))

    def test_invalid_requests_are_rejected_before_generation(self):
        for body in ('{', '[]', '{"case":"unknown"}', '{"case":["renvoi"]}'):
            with self.subTest(body=body):
                self.assertEqual(self.post(body)[0], 400)
        self.assertEqual(self.post('{"case":"renvoi"}', 'text/plain')[0], 415)
        self.assertEqual(self.post('x' * 1025)[0], 413)


if __name__ == '__main__':
    unittest.main()
