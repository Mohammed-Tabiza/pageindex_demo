"""Offline regression checks for separate indexing and generation models."""
import hashlib
import json
import os
import shutil
import sys
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

    def test_legacy_model_remains_a_fallback_for_each_role(self):
        self.assertEqual(self.config(DEMO_MODEL=INDEX)[:2], (INDEX, INDEX))
        self.assertEqual(self.config(DEMO_MODEL=INDEX, DEMO_CHAT_MODEL=CHAT)[:2], (INDEX, CHAT))

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
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'data').mkdir()
        shutil.copyfile(demo.ROOT / 'data' / 'astreintes.pdf', self.root / 'data' / 'astreintes.pdf')
        self.manifest = {'model': 'gemma4:e4b', 'docs': [{
            'file': 'astreintes.pdf', 'doc_id': 'existing-doc',
            'sha256': hashlib.sha256((self.root / 'data' / 'astreintes.pdf').read_bytes()).hexdigest(),
        }]}
        demo.write(self.root / 'index_manifest.json', self.manifest)
        demo.write(self.root / 'questions.json', [{
            'id': 'renvoi', 'question': 'Question test', 'expected': 'Réponse test', 'sources': [],
        }])
        directory = self.root / '.pageindex' / 'docs' / 'existing-doc'
        directory.mkdir(parents=True)
        demo.write(directory / 'doc.json', {'name': 'astreintes_1.pdf'})
        demo.write(directory / 'tree.json', [])
        demo.write(directory / 'pages.json', [{'page_index': 2, 'markdown': 'Texte source.'}])
        self.addCleanup(patch.stopall)
        patch.object(demo, 'ROOT', self.root).start()
        patch.object(web, 'ROOT', self.root).start()
        patch.object(demo, 'configuration', return_value=(INDEX, CHAT, 'test-key', URL)).start()
        patch.object(web, 'configuration', return_value=(INDEX, CHAT, 'test-key', URL)).start()
        self.client = Mock()
        self.client.submit_document.return_value = {'doc_id': 'new-doc'}
        self.client.get_tree.return_value = []
        self.client.chat.return_value = ['Réponse test']
        self.factory = Mock(return_value=self.client)
        patch.dict(sys.modules, {'pageindex': SimpleNamespace(PageIndexClient=self.factory)}).start()

    def run_action(self, action):
        output = self.root / action
        demo.worker(SimpleNamespace(action=action, case='renvoi', output=str(output)))
        config = self.factory.call_args.kwargs
        self.assertEqual(config['index']['model'], INDEX)
        self.assertEqual(config['chat']['model'], CHAT)
        return output

    def test_existing_index_can_be_queried_with_cloud_model(self):
        output = self.run_action('ask')
        self.client.submit_document.assert_not_called()
        self.assertEqual(self.client.chat.call_args.kwargs['doc_id'], ['existing-doc'])
        meta = json.loads((output / 'metadata.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['model'], CHAT)
        self.assertEqual(meta['index_model'], 'gemma4:e4b')

    def test_new_manifest_records_indexing_model(self):
        self.run_action('index')
        manifest = demo.indexed_manifest(INDEX)
        self.assertEqual(manifest['index_model'], INDEX)
        self.assertEqual(manifest['model'], INDEX)
        self.client.chat.assert_not_called()

    def test_changed_indexing_model_or_corpus_still_requires_reindexing(self):
        with self.assertRaisesRegex(ValueError, 'indexation modifié'):
            demo.indexed_manifest(CHAT)
        (self.root / 'data' / 'astreintes.pdf').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Corpus modifié'):
            demo.indexed_manifest(INDEX)

    def test_baseline_uses_generation_model(self):
        completion = Mock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='Réponse test'))], usage=None))
        with patch.dict(sys.modules, {'litellm': SimpleNamespace(completion=completion)}):
            self.run_action('baseline')
        self.assertEqual(completion.call_args.kwargs['model'], CHAT)

    def test_web_uses_generation_model_without_local_reasoning_override(self):
        stream = Mock()
        stream.events = [
            {'type': 'answer', 'delta': 'Je vais analyser les documents. '},
            {'type': 'tool_call', 'name': 'get_page_content', 'call_id': 'read',
             'arguments': {'doc_name': 'astreintes_1.pdf', 'pages': '2'}},
            {'type': 'tool_result', 'name': 'get_page_content', 'call_id': 'read',
             'output': {'success': True, 'doc_name': 'astreintes_1.pdf',
                        'content': [{'page': 2, 'text': 'Texte source.'}]}},
            {'type': 'answer', 'delta': 'Réponse test'},
        ]
        self.client.chat.return_value = stream
        self.client.resolve_citations.return_value = {'answer': 'Réponse test', 'citations': [
            {'document': 'astreintes_1.pdf', 'doc_id': 'existing-doc', 'page': 2,
             'anchor': 'pageindex-citation-01', 'index': 1},
        ]}
        events = list(web.query_events())
        self.assertEqual([event['type'] for event in events], ['start', 'tool_call', 'tool_result', 'answer'])
        self.assertEqual(self.client.resolve_citations.call_args.args[0], 'Réponse test')
        self.assertFalse(events[0]['reasoning_disabled'])
        self.assertNotIn('reasoning_effort', self.client.chat.call_args.kwargs)
        config = self.factory.call_args.kwargs
        self.assertEqual((config['index']['model'], config['chat']['model']), (INDEX, CHAT))
        stream.close.assert_called_once()

    def test_corpus_exposes_stored_name_for_tool_results(self):
        document = web.corpus()['documents'][0]
        self.assertEqual(document['name'], 'astreintes.pdf')
        self.assertEqual(document['stored_name'], 'astreintes_1.pdf')

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
