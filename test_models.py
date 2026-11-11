"""Offline regression checks: configuration, CLI routing and web generation."""
import json
import os
import shutil
import tempfile
import unittest
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
        self.client = Mock()
        self.client.chat.return_value = ['Réponse test']
        self.factory = Mock(return_value=self.client)
        patch.object(demo, 'pageindex_client', self.factory).start()
        patch.object(web, 'pageindex_client', self.factory).start()

    def run_action(self, action, case='renvoi'):
        output = self.root / action
        demo.worker(SimpleNamespace(action=action, case=case, output=str(output)))
        return output

    def doc(self, concept):
        return next(d for d in web.corpus()['documents'] if d['concept'] == concept)

    def test_ask_queries_every_concept_with_generation_model(self):
        output = self.run_action('ask')
        self.assertEqual(self.factory.call_args.args[1], CHAT)
        manifest = json.loads((self.root / 'index_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(self.client.chat.call_args.kwargs['doc_id'], [d['doc_id'] for d in manifest['docs']])
        self.assertEqual(len(manifest['docs']), 11)
        meta = json.loads((output / 'metadata.json').read_text(encoding='utf-8'))
        self.assertEqual((meta['model'], meta['indexer'], meta['okf_version']), (CHAT, 'okf-pageindex/1', '0.2'))

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

    def test_baseline_uses_generation_model_and_whole_bundle(self):
        completion = Mock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='Réponse test'))], usage=None))
        with patch.object(demo, 'llm_completion', completion):
            self.run_action('baseline')
        self.assertEqual(completion.call_args.kwargs['model'], CHAT)
        prompt = completion.call_args.kwargs['messages'][1]['content']
        self.assertIn('SOURCE procedures.astreinte-relais.md', prompt)
        self.assertIn('status: deprecated', prompt)

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
