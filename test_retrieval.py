"""Source checks follow OKF links and lifecycle before an answer is published."""
import os
import unittest
from unittest.mock import Mock, patch

import web

with patch.dict(os.environ, {'DEMO_NOW': '2026-11-11T12:00:00Z'}):
    import demo
    import okf
    BUNDLE = okf.load_bundle(demo.ROOT / 'bundle')
    NOW = okf.now_utc()
    DOCUMENTS = [web.document(BUNDLE, c, NOW) for c in BUNDLE.concepts.values()]
DOC = {d['concept']: d for d in DOCUMENTS}
INCIDENT, RELAIS = DOC['procedures/incident-p1'], DOC['procedures/astreinte-relais']
OLD, COM = DOC['procedures/escalade-p1-v1'], DOC['procedures/communication-crise']


def page_event(doc, page, call_id):
    return {'type': 'tool_result', 'name': 'get_page_content', 'call_id': call_id,
            'output': {'success': True, 'doc_name': doc['name'], 'content': [{'page': page, 'text': doc['pages'][page]}]}}


def citation(doc, page, index):
    return {'document': doc['name'], 'doc_id': doc['id'], 'page': page,
            'anchor': f'pageindex-citation-{index:02d}', 'index': index}


def evidence(*pairs):
    return {(doc['id'], page): {'doc_name': doc['name'], 'page': page, 'text': doc['pages'][page]} for doc, page in pairs}


def sdk_client():
    by_id = {doc['id']: doc for doc in DOCUMENTS}
    client = Mock()
    client.get_page_content.side_effect = lambda doc_id, spec: [
        {'page_index': int(p), 'markdown': by_id[doc_id]['pages'][int(p)]} for p in spec.split(',')]
    return client


class FollowupTests(unittest.TestCase):
    def test_referral_link_is_followed_but_mention_is_not(self):
        self.assertEqual(web.followups(DOCUMENTS, {(INCIDENT['id'], 2)}), {(INCIDENT['id'], RELAIS['id']): {2}})
        # "Les canaux … sont décrits dans la fiche [communication de crise]" only mentions it.
        self.assertEqual(web.followups(DOCUMENTS, {(INCIDENT['id'], 3)}), {})

    def test_deprecated_concept_hands_over_to_its_replacement(self):
        self.assertEqual(web.followups(DOCUMENTS, {(OLD['id'], 1)}), {(OLD['id'], RELAIS['id']): {2}})

    def test_destination_citation_is_sufficient_when_reference_chain_was_read(self):
        resolved = {'citations': [citation(RELAIS, 2, 1)]}
        self.assertEqual(web.answer_issues(resolved, DOCUMENTS, evidence((INCIDENT, 2), (RELAIS, 2))), [])

    def test_cited_referral_requires_its_target(self):
        resolved = {'citations': [citation(INCIDENT, 2, 1)]}
        issues = web.answer_issues(resolved, DOCUMENTS, evidence((INCIDENT, 2), (RELAIS, 2)))
        self.assertTrue(any('Suivez le renvoi' in issue and RELAIS['name'] in issue for issue in issues))

    def test_deprecated_rule_alone_is_rejected(self):
        issues = web.answer_issues({'citations': [citation(OLD, 1, 1)]}, DOCUMENTS, evidence((OLD, 1), (RELAIS, 2)))
        self.assertTrue(any('obsolète' in issue for issue in issues))
        ok = {'citations': [citation(OLD, 1, 1), citation(RELAIS, 2, 2)]}
        self.assertEqual(web.answer_issues(ok, DOCUMENTS, evidence((OLD, 1), (RELAIS, 2))), [])

    def test_lifecycle_warnings_for_cited_concepts(self):
        warnings = web.okf_warnings({'citations': [citation(COM, 1, 1), citation(OLD, 1, 2), citation(RELAIS, 2, 3)]}, DOCUMENTS)
        self.assertEqual([w['flag'] for w in warnings], ['stale', 'deprecated'])
        self.assertIn('2026-09-30', warnings[0]['message'])

    def test_application_reads_cited_page_and_referral_target(self):
        client = sdk_client()
        found = {}
        events = list(web.retrieve_sources(client, {'citations': [citation(INCIDENT, 2, 1)]}, DOCUMENTS, found, 0))
        self.assertEqual(set(found), {(INCIDENT['id'], 2), (RELAIS['id'], 2)})
        self.assertEqual(client.get_page_content.call_count, 2)
        self.assertTrue(all(event['origin'] == 'source_check' for event in events))
        # Already-read pages do not trigger repeated reads.
        self.assertEqual(list(web.retrieve_sources(client, {'citations': [citation(INCIDENT, 2, 1)]}, DOCUMENTS, found, 1)), [])

    def test_unresolved_or_unread_citation_is_rejected(self):
        for reference in (dict(citation(RELAIS, 2, 1), doc_id=None), citation(RELAIS, 2, 1)):
            with self.subTest(reference=reference):
                self.assertTrue(web.answer_issues({'citations': [reference]}, DOCUMENTS, {}))


class QueryFlowTests(unittest.TestCase):
    def run_query(self, client):
        with patch.object(web, 'configuration', return_value=('index-model', 'chat-model', 'key', 'http://localhost:11434/v1')), \
             patch.object(web, 'endpoint_error', return_value=None), \
             patch.object(web, 'corpus', return_value={'documents': DOCUMENTS}), \
             patch.object(web, 'selected_question', return_value='Qui contacter ?'), \
             patch.object(web, 'pageindex_client', return_value=client):
            return list(web.query_events())

    def test_follows_reference_before_publishing_answer(self):
        streams = [Mock(), Mock()]
        streams[0].events = [page_event(INCIDENT, 2, 'read-1'),
                             {'type': 'answer', 'delta': 'Appliquez le relais d’astreinte.'}]
        streams[1].events = [page_event(RELAIS, 2, 'read-2'),
                             {'type': 'answer', 'delta': 'Contacter le coordinateur de crise.'}]
        client = sdk_client()
        client.chat.side_effect = streams
        client.resolve_citations.side_effect = [
            {'answer': 'Appliquez le relais d’astreinte.', 'citations': [citation(INCIDENT, 2, 1)]},
            {'answer': 'Contacter le coordinateur de crise.', 'citations': [citation(INCIDENT, 2, 1), citation(RELAIS, 2, 2)]},
        ]
        events = self.run_query(client)
        answers = [event for event in events if event['type'] == 'answer']
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]['answer'], 'Contacter le coordinateur de crise.')
        self.assertEqual(client.chat.call_count, 2)
        self.assertIn(RELAIS['name'], str(client.chat.call_args.args[0]))
        for stream in streams:
            stream.close.assert_called_once()

    def test_stale_source_is_published_with_warning(self):
        stream = Mock(events=[page_event(COM, 1, 'read'), {'type': 'answer', 'delta': 'Page de statut.'}])
        client = sdk_client()
        client.chat.return_value = stream
        client.resolve_citations.return_value = {'answer': 'Page de statut.', 'citations': [citation(COM, 1, 1)]}
        events = self.run_query(client)
        self.assertEqual(events[-1]['type'], 'answer')
        self.assertEqual([w['flag'] for w in events[-1]['warnings']], ['stale'])

    def test_continued_incomplete_answer_is_not_published(self):
        client = Mock()
        client.chat.side_effect = [Mock(events=iter([{'type': 'answer', 'delta': 'Consultez un autre document.'}])) for _ in range(2)]
        client.resolve_citations.return_value = {'answer': 'Consultez un autre document.', 'citations': []}
        events = self.run_query(client)
        self.assertFalse(any(event['type'] == 'answer' for event in events))
        self.assertEqual(events[-1]['type'], 'error')
        self.assertEqual(events[-1]['stage'], 'verification')


if __name__ == '__main__':
    unittest.main()
