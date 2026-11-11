"""SYNTHETIC regression: feed excerpts can hold evidence absent from retained full/partial text.

No network or live records: packet preservation and refusal before reservation are tested with the existing fake.
"""
import copy
from dataclasses import replace
import json
from unittest import mock
import unittest

from account_fakes import every_file
from second_order import brief_drafting, brief_stages
from second_order.accounts import AccountsRefused
from test_brief_stages import Draft


class SourcePacketTest(unittest.TestCase):
    def text_story(self):
        draft = Draft(self)
        draft.desk = replace(draft.desk, texts=draft.world.root / 'kept-texts')
        story = copy.deepcopy(draft.story())
        report = story['material']['reports'][0]
        story['material']['reports'] = [report]
        report['excerpt'] = 'SYNTHETIC: the investigation began on 18 September; notification was on 22 October.'
        report['text'] = {'state': 'full_text', 'text_sha256': 'a' * 64,
                          'retrieved_at': '2026-10-25T12:00:00+00:00', 'partial_reason': None}
        return draft, story, report

    def test_both_stages_keep_the_feed_evidence_beside_full_or_partial_publication_text(self):
        draft, story, report = self.text_story()
        foundation = brief_drafting.largest(story['material'])
        body = 'SYNTHETIC: parties have 30 days from initiation to submit evidence. No initiation date here.'
        for coverage in ('full_text', 'partial_text'):
            report['text']['state'] = coverage
            with self.subTest(coverage=coverage), mock.patch.object(brief_drafting.news_texts, 'text_of', return_value=body):
                requests = [brief_drafting.stage_1_bytes(story, story['material'], draft.desk.texts),
                            brief_drafting.stage_2_bytes(story, story['material'], draft.desk.texts, None,
                                                        foundation, 'brief-s1-' + '1' * 16)]
                for request in requests:
                    user = json.loads(request)['messages'][0]['content']
                    self.assertIn('Excerpt: ' + report['excerpt'], user)
                    self.assertIn('Publication text', user)
                    self.assertIn(body, user)
                    self.assertLess(user.index('Excerpt:'), user.index('Publication text'))
                    self.assertEqual(user.count(report['excerpt']), 1)
                    self.assertIn(report['entry_id'], user)

    def test_a_cut_publication_does_not_cut_the_excerpt_or_other_report_evidence(self):
        draft, story, report = self.text_story()
        other = copy.deepcopy(report)
        other.update(entry_id='synthetic:other', publisher='SYNTHETIC Other Publisher',
                     excerpt='SYNTHETIC: the other report supplies the product scope.')
        story['material']['reports'].append(other)
        long_text = 'SYNTHETIC body start.\n\n' + 'A' * brief_drafting.DRAFT_TEXT_CHARS + '\n\nSYNTHETIC tail excluded.'
        with mock.patch.object(brief_drafting.news_texts, 'text_of',
                               side_effect=lambda folder, snap: long_text if snap['entry_id'] == report['entry_id']
                               else 'SYNTHETIC second publication.'):
            user = brief_drafting.material_text(story, story['material'], draft.desk.texts)
        first, second = user.split('Report ID: synthetic:other')
        self.assertIn(report['excerpt'], first)
        self.assertNotIn(other['excerpt'], first)
        self.assertIn('not included in this request', first)
        self.assertNotIn('SYNTHETIC tail excluded.', user)
        self.assertIn(other['excerpt'], second)
        self.assertIn('SYNTHETIC second publication.', second)

    def test_excerpt_only_and_missing_text_fallback_still_include_the_excerpt_once(self):
        draft, story, report = self.text_story()
        for has_snapshot in (True, False):
            if not has_snapshot:
                report.pop('text')
            with self.subTest(snapshot=has_snapshot), mock.patch.object(brief_drafting.news_texts, 'text_of', return_value=None):
                user = brief_drafting.material_text(story, story['material'], draft.desk.texts)
                self.assertEqual(user.count('Excerpt: ' + report['excerpt']), 1)
                self.assertNotIn('Publication text', user)

    def test_an_empty_excerpt_does_not_change_a_full_text_packet(self):
        draft, story, report = self.text_story()
        report['excerpt'] = ''
        with mock.patch.object(brief_drafting.news_texts, 'text_of', return_value='SYNTHETIC body.'):
            user = brief_drafting.material_text(story, story['material'], draft.desk.texts)
        self.assertIn('SYNTHETIC body.', user)
        self.assertNotIn('Excerpt:', user)


class SupersededPacketTest(unittest.TestCase):
    def test_stage_one_from_an_older_packet_builder_is_refused_before_reservation(self):
        draft = Draft(self)
        story = draft.story()
        old_body = brief_drafting.stage_1_bytes(story, story['material'], draft.desk.texts) + b'\n'
        with mock.patch.object(brief_drafting, 'stage_1_bytes', return_value=old_body):
            old = draft.preview()
        before = every_file(draft.world.root)
        with self.assertRaises(AccountsRefused) as refused:
            draft.approve(old)
        self.assertEqual(refused.exception.code, 'request_superseded')
        self.assertEqual(every_file(draft.world.root), before)
        self.assertEqual(draft.model.stages(), [])
        current = draft.preview()
        self.assertNotEqual(current['draft_id'], old['draft_id'])
        self.assertEqual(current['attempt']['state'], 'not_attempted')

    def test_stage_two_bound_to_an_older_source_packet_is_refused_without_resending_stage_one(self):
        draft = Draft(self)
        story = draft.story()
        old_body = brief_drafting.stage_1_bytes(story, story['material'], draft.desk.texts) + b'\n'
        with mock.patch.object(brief_drafting, 'stage_1_bytes', return_value=old_body):
            old_second = draft.run_first()
        self.assertEqual(old_second['stage'], 2)
        self.assertEqual(draft.model.stages(), [1])
        before = every_file(draft.world.root)
        with self.assertRaises(AccountsRefused) as refused:
            draft.approve(old_second)
        self.assertEqual(refused.exception.code, 'request_superseded')
        self.assertEqual(every_file(draft.world.root), before)
        self.assertEqual(draft.model.stages(), [1])
        self.assertFalse((draft.folder(old_second['draft_id']) / 'attempt.json').exists())


if __name__ == '__main__':
    unittest.main()
