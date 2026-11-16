"""Offline regression checks: configuration, CLI routing and web generation."""
import json
import os
import shutil
import socket
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import demo
import web

INDEX = 'openai/gemma4:e4b'
CHAT = 'openai/gemma4:31b-cloud'
URL = 'http://localhost:11434/v1'


class ConfigurationTests(unittest.TestCase):
    def config(self, **values):
        env = {'OPENAI_API_KEY': 'test-key', 'OPENAI_BASE_URL': URL, **values}
        with patch.dict(os.environ, env, clear=True), patch('dotenv.load_dotenv'):
            return demo.configuration()

    def test_separate_models_override_legacy_default(self):
        self.assertEqual(self.config(DEMO_MODEL='old', DEMO_INDEX_MODEL=INDEX,
                                     DEMO_CHAT_MODEL=CHAT), (INDEX, CHAT, 'test-key', URL))

    def test_index_model_is_optional_because_okf_indexing_is_deterministic(self):
        self.assertEqual(self.config(DEMO_CHAT_MODEL=CHAT)[:2], (CHAT, CHAT))
        self.assertEqual(self.config(DEMO_MODEL=INDEX)[:2], (INDEX, INDEX))

    def test_missing_or_placeholder_model_is_rejected(self):
        for values in ({'DEMO_INDEX_MODEL': INDEX},
                       {'DEMO_INDEX_MODEL': INDEX, 'DEMO_CHAT_MODEL': 'cloud'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.config(**values)

    def test_length_diagnostic_explains_input_and_output_budget(self):
        error = RuntimeError("unfinished (finish_reason 'length') confidential-token")
        error.usage = {'request_usage_entries': [{'prompt_tokens': 4013, 'completion_tokens': 82, 'total_tokens': 4095}]}
        event = web.error_event(error, 'generation')
        self.assertIn('4013', event['message'])
        self.assertIn('82', event['message'])
        self.assertIn('contexte', event['message'])
        self.assertNotIn('confidential-token', json.dumps(event))


class EndpointTests(unittest.TestCase):
    def test_unreachable_server_is_reported_quickly_without_credentials(self):
        with socket.socket() as probe:     # a free port nobody listens on
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        message = demo.endpoint_error(f'http://user:secret@127.0.0.1:{port}/v1', 'test-key', timeout=2)
        self.assertIn('injoignable', message)
        self.assertIn(f'127.0.0.1:{port}', message)
        self.assertNotIn('secret', message)

    def test_any_http_answer_counts_as_reachable(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)   # answers 501
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertIsNone(demo.endpoint_error(f'http://127.0.0.1:{server.server_port}/v1', 'k', timeout=2))
        finally:
            server.shutdown()
            server.server_close()

    def test_web_stops_before_generation_when_server_is_unreachable(self):
        with patch.object(web, 'configuration', return_value=(INDEX, CHAT, 'k', URL)), \
             patch.object(web, 'endpoint_error', return_value='Serveur du modèle injoignable'), \
             patch.object(web, 'pageindex_client') as factory:
            events = list(web.query_events())
        self.assertEqual([(e['type'], e['stage']) for e in events], [('error', 'connection')])
        factory.assert_not_called()


class ModelRoutingTests(unittest.TestCase):
    """A temporary copy of the demo bundle, with the SDK client replaced by a double."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copytree(demo.ROOT / 'bundle', self.root / 'bundle')
        shutil.copyfile(demo.ROOT / 'questions.json', self.root / 'questions.json')
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'DEMO_NOW': '2026-11-11T12:00:00Z'}).start()
        for name in ('DEMO_BUNDLE', 'DEMO_QUESTIONS'):
            os.environ.pop(name, None)
        patch.object(demo, 'ROOT', self.root).start()
        patch.object(web, 'ROOT', self.root).start()
        patch.object(demo, 'configuration', return_value=(INDEX, CHAT, 'test-key', URL)).start()
        patch.object(web, 'configuration', return_value=(INDEX, CHAT, 'test-key', URL)).start()
        patch.object(web, 'endpoint_error', return_value=None).start()
        self.client = Mock()
        self.client.chat.return_value = ['Réponse test']
        self.factory = Mock(return_value=self.client)
        patch.object(demo, 'pageindex_client', self.factory).start()
        patch.object(web, 'pageindex_client', self.factory).start()

    def run_action(self, action, case='renvoi', status=0):
        output = self.root / action
        self.assertEqual(demo.worker(SimpleNamespace(action=action, case=case, output=str(output))), status)
        return output

    def doc(self, concept):
        return next(d for d in web.corpus()['documents'] if d['concept'] == concept)

    def test_ask_queries_every_concept_with_generation_model(self):
        relais = self.doc('procedures/astreinte-relais')
        self.client.chat.return_value = Mock(events=[
            {'type': 'tool_call', 'name': 'get_page_content', 'call_id': 'read',
             'arguments': {'doc_name': relais['name'], 'pages': '2'}},
            {'type': 'tool_result', 'name': 'get_page_content', 'call_id': 'read',
             'output': {'success': True, 'doc_name': relais['name'],
                        'content': [{'page': 2, 'text': relais['pages'][2]}]}},
            {'type': 'answer', 'delta': 'Le coordinateur de crise.'},
        ])
        self.client.resolve_citations.return_value = {'answer': 'Le coordinateur de crise.', 'citations': [
            {'document': relais['name'], 'doc_id': relais['id'], 'page': 2, 'anchor': 'c1', 'index': 1}]}
        output = self.run_action('ask', case='exception')
        self.assertEqual(self.factory.call_args.args[1], CHAT)
        manifest = json.loads((self.root / 'index_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(self.client.chat.call_args.kwargs['doc_id'], [d['doc_id'] for d in manifest['docs']])
        self.assertEqual(len(manifest['docs']), 11)
        # The CLI shares the web prompt and source checks.
        self.assertEqual(self.client.chat.call_args.kwargs['instructions'], web.QUERY_INSTRUCTIONS)
        meta = json.loads((output / 'metadata.json').read_text(encoding='utf-8'))
        self.assertEqual((meta['model'], meta['indexer'], meta['okf_version']), (CHAT, 'okf-pageindex/1', '0.2'))
        self.assertEqual(meta['final_event'], 'answer')
        self.assertIn('[citation 1] procedures.astreinte-relais.md page 2', (output / 'trace.txt').read_text(encoding='utf-8'))
        # The web archive replays the recorded events, without relabelling the run as live.
        (output / 'execution.json').write_text('{"returncode": 0}', encoding='utf-8')
        replay = list(web.archived_events(output))
        self.assertEqual([e['type'] for e in replay], ['tool_call', 'tool_result', 'answer'])
        self.assertEqual(replay[-1]['citations'][0]['page'], 2)

    def test_ask_without_verified_answer_fails(self):
        self.client.chat.return_value = Mock(events=[])
        output = self.run_action('ask', status=1)
        self.assertEqual(json.loads((output / 'metadata.json').read_text(encoding='utf-8'))['final_event'], 'error')

    def test_index_makes_no_llm_call_and_is_incremental(self):
        demo.index(self.root / 'run1')
        self.factory.assert_not_called()
        self.assertTrue((self.root / 'run1' / 'procedures.incident-p1_tree.json').is_file())
        _, manifest = demo.ensure_index()
        self.assertEqual(manifest['changed'], [])
        path = self.root / 'bundle' / 'procedures' / 'incident-p1.md'
        path.write_text(path.read_text(encoding='utf-8').replace('30 minutes', '20 minutes'), encoding='utf-8')
        _, manifest = demo.ensure_index()
        self.assertEqual(manifest['changed'], ['procedures/incident-p1'])

    def run_baseline(self, action):
        relais = self.doc('procedures/astreinte-relais')
        answer = f'Le coordinateur de crise. <cite doc="{relais["name"]}" page="2"/>'
        completion = Mock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=answer))], usage=None))
        self.client.resolve_citations.return_value = {'answer': 'Le coordinateur de crise. [[1]]', 'citations': [
            {'document': relais['name'], 'doc_id': relais['id'], 'page': 2, 'anchor': 'c1', 'index': 1}]}
        with patch.object(demo, 'llm_completion', completion):
            output = self.run_action(action)
        meta = json.loads((output / 'metadata.json').read_text(encoding='utf-8'))
        messages = completion.call_args.kwargs['messages']
        return completion, messages, meta

    def test_baseline_uses_generation_model_and_whole_bundle(self):
        completion, messages, meta = self.run_baseline('baseline')
        self.assertEqual(completion.call_args.kwargs['model'], CHAT)
        prompt = messages[1]['content']
        self.assertIn('DOCUMENT procedures.astreinte-relais.md', prompt)
        self.assertIn('status: deprecated', prompt)     # raw frontmatter, nothing computed
        self.assertIn('PAGE 2\n# Relais', prompt)
        self.assertNotIn('PÉRIMÉ', prompt)
        self.assertEqual(meta['citations'], [{'document': 'procedures.astreinte-relais.md', 'page': 2}])
        self.assertEqual(meta['issues'], [])

    def test_okf_baseline_reads_the_pages_of_the_agent_with_shared_instructions(self):
        _, messages, _ = self.run_baseline('baseline-okf')
        prompt = messages[1]['content']
        self.assertIn('PÉRIMÉ depuis le 2026-09-30', prompt)
        self.assertIn('{→ procedures.astreinte-relais.md, page 2}', prompt)
        self.assertNotIn('status: deprecated', prompt)
        system = messages[0]['content']
        for scope, text in demo.QUERY_PARTS:
            self.assertEqual(text in system, scope == 'all', text)
        self.assertIn('<cite doc=', system)

    def test_ask_once_keeps_a_refused_answer_with_its_issues(self):
        self.client.chat.return_value = Mock(events=[{'type': 'answer', 'delta': 'Relais.'}])
        self.client.resolve_citations.return_value = {'answer': 'Relais.', 'citations': []}
        output = self.run_action('ask-once')
        self.assertEqual(self.client.chat.call_count, 1)
        meta = json.loads((output / 'metadata.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['final_event'], 'answer')
        self.assertTrue(meta['issues'])
        self.assertIn('[refus des contrôles, réponse conservée]', (output / 'trace.txt').read_text(encoding='utf-8'))

    def test_web_uses_generation_model_without_local_reasoning_override(self):
        relais = self.doc('procedures/astreinte-relais')
        stream = Mock()
        stream.events = [
            {'type': 'answer', 'delta': 'Je vais analyser les documents. '},
            {'type': 'tool_call', 'name': 'get_page_content', 'call_id': 'read',
             'arguments': {'doc_name': relais['name'], 'pages': '2'}},
            {'type': 'tool_result', 'name': 'get_page_content', 'call_id': 'read',
             'output': {'success': True, 'doc_name': relais['name'],
                        'content': [{'page': 2, 'text': relais['pages'][2]}]}},
            {'type': 'answer', 'delta': 'Réponse test'},
        ]
        self.client.chat.return_value = stream
        self.client.resolve_citations.return_value = {'answer': 'Réponse test', 'citations': [
            {'document': relais['name'], 'doc_id': relais['id'], 'page': 2,
             'anchor': 'pageindex-citation-01', 'index': 1},
        ]}
        events = list(web.query_events())
        self.assertEqual([event['type'] for event in events], ['start', 'tool_call', 'tool_result', 'answer'])
        self.assertEqual(events[-1]['warnings'], [])
        self.assertEqual(self.client.resolve_citations.call_args.args[0], 'Réponse test')
        self.assertFalse(events[0]['reasoning_disabled'])
        self.assertNotIn('reasoning_effort', self.client.chat.call_args.kwargs)
        self.assertEqual(self.factory.call_args.args[:2], (INDEX, CHAT))
        stream.close.assert_called_once()

    def test_several_bundles_in_cli_corpus_and_question_sources(self):
        shutil.copytree(self.root / 'bundle', self.root / 'rh')
        with patch.dict(os.environ, {'DEMO_BUNDLE': os.pathsep.join(['bundle', 'rh'])}):
            bundles = demo.load_bundles()
            self.assertEqual([b.name for b in bundles], ['bundle', 'rh'])
            concept, section = demo.resolve_source(bundles, 'rh:procedures/astreinte-relais#relais')
            self.assertEqual((concept.root, section.page), (str(self.root / 'rh'), 2))
            with self.assertRaisesRegex(ValueError, 'plusieurs bundles'):
                demo.resolve_source(bundles, 'procedures/astreinte-relais#relais')
            data = web.corpus()
            self.assertEqual(len(data['documents']), 22)
            self.assertEqual(data['bundle']['names'], ['bundle', 'rh'])
            self.assertEqual(data['bundle']['folders']['rh/procedures'], 'rh · Procédures')
            doc = next(d for d in data['documents'] if d['concept'] == 'rh:procedures/incident-p1')
            self.assertEqual((doc['name'], doc['folder'], doc['bundle']), ('rh.procedures.incident-p1.md', 'rh/procedures', 'rh'))
            relais = next(link for link in doc['links'] if link['href'] == '/procedures/astreinte-relais.md#relais')
            self.assertEqual(relais['target_doc'], next(d['id'] for d in data['documents']
                                                        if d['concept'] == 'rh:procedures/astreinte-relais'))
        # Back to the single default bundle: unprefixed names, the other bundle stays stored.
        documents = web.corpus()['documents']
        self.assertEqual({d['name'] for d in documents if d['concept'] == 'procedures/incident-p1'},
                         {'procedures.incident-p1.md'})

    def test_corpus_exposes_okf_signals(self):
        documents = {d['concept']: d for d in web.corpus()['documents']}
        deprecated = documents['procedures/escalade-p1-v1']
        self.assertEqual(deprecated['name'], 'procedures.escalade-p1-v1.md')
        self.assertEqual(deprecated['superseded_by'], documents['procedures/astreinte-relais']['id'])
        self.assertEqual(documents['procedures/communication-crise']['flags'], ['stale'])
        self.assertEqual(documents['procedures/changement-urgent']['flags'], ['draft', 'unverified'])
        self.assertEqual(documents['roles/coordinateur-crise']['trust_tier'], 'human-reviewed')

    def test_web_explains_payment_refusal_without_exposing_provider_details(self):
        error = RuntimeError('Provider response with confidential-token')
        error.status_code = 402

        def rejected_events():
            yield from ()
            raise error

        stream = Mock()
        stream.events = rejected_events()
        self.client.chat.return_value = stream
        events = list(web.query_events())
        self.assertEqual([event['type'] for event in events], ['start', 'error'])
        event = events[-1]
        self.assertEqual(event['stage'], 'generation')
        self.assertEqual(event['diagnostic']['http_status'], 402)
        self.assertIn('402', event['message'])
        self.assertIn('crédits', event['message'])
        self.assertNotIn('confidential-token', json.dumps(events))
        stream.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
