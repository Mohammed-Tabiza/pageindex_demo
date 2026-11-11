"""Keep incomplete cross-document answers from being presented as success."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import web


def page_event(name, text, call_id):
    return {'type': 'tool_result', 'name': 'get_page_content', 'call_id': call_id,
            'output': {'success': True, 'doc_name': name, 'content': [{'page': 2, 'text': text}]}}


def citation(name, doc_id, index):
    return {'document': name, 'doc_id': doc_id, 'page': 2,
            'anchor': f'pageindex-citation-{index:02d}', 'index': index}


class RetrievalTests(unittest.TestCase):
    def test_incidental_document_word_is_not_a_cross_reference(self):
        documents = [{'id': 'a', 'name': 'astreintes.pdf', 'stored_name': 'astreintes_1.pdf'},
                     {'id': 'i', 'name': 'incidents.pdf', 'stored_name': 'incidents_1.pdf'}]
        evidence = {('a', 3): {'text': 'La passation transmet les incidents ouverts et les actions en attente.'}}
        self.assertEqual(web.referenced_pairs(documents, evidence), set())

    def test_destination_citation_is_sufficient_when_reference_chain_was_read(self):
        documents = [
            {'id': 'i', 'name': 'incidents.pdf', 'stored_name': 'incidents_1.pdf', 'pages': {2: 'Appliquer la procédure astreintes, section Relais.'}},
            {'id': 'a', 'name': 'astreintes.pdf', 'stored_name': 'astreintes_1.pdf', 'pages': {2: 'Contacter le coordinateur de crise.'}},
        ]
        evidence = {(doc['id'], 2): {'text': doc['pages'][2]} for doc in documents}
        self.assertEqual(web.answer_issues({'citations': [citation('astreintes_1.pdf', 'a', 1)]}, documents, evidence), [])

    def test_application_reads_cited_page_and_explicit_section_reference(self):
        documents = [
            {'id': 'guide-id', 'name': 'guide.pdf', 'stored_name': 'guide_2.pdf',
             'pages': {1: 'Appliquer annuaire, section Relais.'}, 'tree': []},
            {'id': 'directory-id', 'name': 'annuaire.pdf', 'stored_name': 'annuaire_2.pdf',
             'pages': {2: 'Contacter le référent.'},
             'tree': [{'title': '2. Relais', 'start_index': 2, 'end_index': 2}]},
        ]
        by_id = {doc['id']: doc for doc in documents}
        client = Mock()
        client.get_page_content.side_effect = lambda doc_id, spec: [
            {'page_index': int(page), 'markdown': by_id[doc_id]['pages'][int(page)]} for page in spec.split(',')]
        resolved = {'citations': [{'doc_id': 'guide-id', 'page': 1}]}
        evidence = {}
        events = list(web.retrieve_sources(client, resolved, documents, evidence, 0))
        self.assertEqual(len(evidence), 2)
        self.assertEqual(client.get_page_content.call_count, 2)
        self.assertTrue(all(event['origin'] == 'source_check' for event in events))
        self.assertEqual(evidence[('directory-id', 2)]['text'], 'Contacter le référent.')
        # Already-read pages do not trigger repeated reads, even across a reference cycle.
        self.assertEqual(list(web.retrieve_sources(client, resolved, documents, evidence, 1)), [])

    def test_follows_reference_before_publishing_answer(self):
        documents = [
            {'id': 'incident-id', 'name': 'incidents.pdf', 'stored_name': 'incidents_1.pdf', 'pages': {2: 'Renvoi vers astreintes, section Relais.'}},
            {'id': 'roster-id', 'name': 'astreintes.pdf', 'stored_name': 'astreintes_1.pdf', 'pages': {2: 'Contacter le coordinateur de crise.'}},
        ]
        streams = [Mock(), Mock()]
        streams[0].events = [
            page_event('incidents_1.pdf', documents[0]['pages'][2], 'read-1'),
            {'type': 'answer', 'delta': 'Consultez la procédure astreintes.'},
        ]
        streams[1].events = [
            page_event('astreintes_1.pdf', documents[1]['pages'][2], 'read-2'),
            {'type': 'answer', 'delta': 'Contacter le coordinateur de crise.'},
        ]
        client = Mock()
        client.chat.side_effect = streams
        client.resolve_citations.side_effect = [
            {'answer': 'Consultez la procédure astreintes.', 'citations': [citation('incidents_1.pdf', 'incident-id', 1)]},
            {'answer': 'Contacter le coordinateur de crise.', 'citations': [
                citation('incidents_1.pdf', 'incident-id', 1), citation('astreintes_1.pdf', 'roster-id', 2)]},
        ]
        manifest = {'docs': [{'doc_id': doc['id']} for doc in documents]}
        with patch.object(web, 'configuration', return_value=('index-model', 'chat-model', 'key', 'http://localhost:11434/v1')), \
             patch.object(web, 'indexed_manifest', return_value=manifest), \
             patch.object(web, 'corpus', return_value={'documents': documents}), \
             patch.object(web, 'selected_question', return_value='Qui contacter ?'), \
             patch.object(web, 'pageindex_client', return_value=client):
            events = list(web.query_events())
        answers = [event for event in events if event['type'] == 'answer']
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]['answer'], 'Contacter le coordinateur de crise.')
        self.assertEqual(client.chat.call_count, 2)
        retry = client.chat.call_args.args[0]
        self.assertIn('astreintes_1.pdf', str(retry))
        for stream in streams:
            stream.close.assert_called_once()

    def test_unresolved_or_unread_citation_is_rejected(self):
        documents = [{'id': 'known-id', 'name': 'doc.pdf', 'stored_name': 'doc_1.pdf', 'pages': {2: 'Source'}}]
        for reference in (citation('invented.pdf', None, 1), citation('doc_1.pdf', 'known-id', 1)):
            with self.subTest(reference=reference):
                issues = web.answer_issues({'citations': [reference]}, documents, {})
                self.assertTrue(issues)

    def test_continued_incomplete_answer_is_not_published(self):
        client = Mock()
        client.chat.side_effect = [SimpleNamespace(events=iter([{'type': 'answer', 'delta': 'Consultez un autre document.'}]), close=Mock()) for _ in range(2)]
        client.resolve_citations.return_value = {'answer': 'Consultez un autre document.', 'citations': []}
        with patch.object(web, 'configuration', return_value=('index', 'chat', 'key', 'http://localhost/v1')), \
             patch.object(web, 'indexed_manifest', return_value={'docs': []}), \
             patch.object(web, 'corpus', return_value={'documents': []}), \
             patch.object(web, 'selected_question', return_value='Question'), \
             patch.object(web, 'pageindex_client', return_value=client):
            events = list(web.query_events())
        self.assertFalse(any(event['type'] == 'answer' for event in events))
        self.assertEqual(events[-1]['type'], 'error')
        self.assertEqual(events[-1]['stage'], 'verification')


if __name__ == '__main__':
    unittest.main()
