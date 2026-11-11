"""SYNTHETIC insufficient-evidence workflows and questions about unknown causes; no provider calls."""
import copy
import hashlib
import json
import unittest

from second_order import brief_drafting, brief_stages, story_briefs
from second_order.accounts import AccountsRefused
from test_brief_stages import Draft
from test_news_stories import GOOD
from news_desk_fakes import insufficient_economics


class UnknownQuestionTest(unittest.TestCase):
    def findings(self, field, text):
        raw = copy.deepcopy(GOOD)
        raw[field] = [text] if field in ('missing', 'uncertainties') else text
        return story_briefs.guard(raw)['findings']

    def test_simple_questions_in_unknowns_fields_are_not_causal_assertions(self):
        for field in ('missing', 'uncertainties'):
            for text in ('Which retail categories drove the September change', 'What caused the change?',
                         'Who triggered the review?', 'Which costs resulted in the change?'):
                with self.subTest(field=field, text=text):
                    self.assertNotIn('causal_claim', [r['rule'] for r in self.findings(field, text)])

    def test_statements_and_questions_outside_unknowns_are_still_flagged(self):
        for field, text in (('missing', 'Tax cuts caused growth.'),
                            ('uncertainties', 'The price increase drove inflation.'),
                            ('summary', 'Which retail categories drove the change?'),
                            ('headline', 'What caused growth?')):
            with self.subTest(field=field, text=text):
                self.assertIn('causal_claim', [r['rule'] for r in self.findings(field, text)])

    def test_a_question_does_not_hide_a_later_or_compound_claim(self):
        for text in ('Which categories drove the change? The tax cut caused growth.',
                     'What caused the change; the tax cut drove growth.',
                     'Which categories drove the gain, because of the tax cut.',
                     'Which categories drove the gain and forced prices up.'):
            with self.subTest(text=text):
                self.assertIn('causal_claim', [r['rule'] for r in self.findings('missing', text)])

    def test_advice_and_implication_guards_are_unchanged(self):
        self.assertIn('advice', [r['rule'] for r in self.findings('missing', 'Which policy drove growth; investors should buy shares?')])
        raw = copy.deepcopy(GOOD)
        raw['implications'] = [{'text': 'Which policy caused growth?'}]
        rules = [r['rule'] for r in story_briefs.guard(raw)['findings']]
        self.assertIn('causal_claim', rules)
        self.assertIn('unhedged', rules)


class BriefOnlyFlowTest(unittest.TestCase):
    def thin(self):
        draft = Draft(self)
        draft.model.economics = insufficient_economics
        return draft

    def test_preview_uses_a_closed_four_field_contract_and_reuses_stage_one(self):
        draft = self.thin()
        view = draft.run_first()
        body = json.loads((draft.folder(view['draft_id']) / 'request.json').read_bytes())
        schema = body['output_config']['format']['schema']
        self.assertEqual(set(schema['properties']), {'headline', 'summary', 'implications', 'uncertainties'})
        self.assertEqual(set(schema['required']), set(schema['properties']))
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(view['stages'][1]['stage_version'], brief_stages.BRIEF_ONLY_VERSION)
        self.assertIn(brief_stages.BRIEF_ONLY_RULES, body['system'])
        self.assertNotIn('Framework notes', body['messages'][0]['content'])
        self.assertEqual(draft.preview()['draft_id'], view['draft_id'])
        self.assertEqual(draft.model.stages(), [1])

    def test_valid_reply_preserves_the_exact_first_stage_decision_and_saves_an_unpublished_version(self):
        draft = self.thin()
        view = draft.run_first()
        first = draft.folder(view['stages'][0]['draft_id']) / 'foundations.json'
        kept = first.read_bytes()
        reason = json.loads(kept)['reason']
        done, sent = draft.approve(view)
        self.assertEqual((sent, done['attempt']['state']), (True, 'recorded'))
        row = draft.versions()[-1]
        economics = row['content']['economics']
        self.assertEqual((economics['status'], economics['insufficient_reason']), ('insufficient_evidence', reason))
        self.assertEqual(economics['channels'], [])
        self.assertEqual(first.read_bytes(), kept)
        self.assertEqual(row['preparation']['model']['stages'][1]['stage_version'], brief_stages.BRIEF_ONLY_VERSION)
        self.assertIsNone(draft.story()['publication'])
        self.assertFalse(draft.approve(view)[1])
        self.assertEqual(draft.model.stages(), [1, 2])

    def test_an_extra_explanation_reason_is_refused_not_dropped_or_repaired(self):
        draft = self.thin()
        view = draft.run_first()
        draft.model.fit_format = False
        draft.model.stage_reply[2] = lambda reply: {**reply, 'insufficient_explanation': 'SYNTHETIC: not enough evidence.'}
        done, sent = draft.approve(view)
        self.assertEqual((sent, done['attempt']['state']), (True, 'invalid'))
        self.assertEqual(draft.versions(), [])
        self.assertTrue((draft.folder(view['draft_id']) / 'response.json').exists())
        self.assertFalse(draft.approve(view)[1])
        self.assertEqual(draft.model.stages(), [1, 2])

    def test_missing_or_null_fields_are_refused_without_defaults(self):
        for change in (lambda reply: {k: v for k, v in reply.items() if k != 'summary'},
                       lambda reply: {**reply, 'summary': None}):
            with self.subTest(change=change):
                draft = self.thin()
                view = draft.run_first()
                draft.model.fit_format = False
                draft.model.stage_reply[2] = change
                self.assertEqual(draft.approve(view)[0]['attempt']['state'], 'invalid')
                self.assertEqual(draft.versions(), [])

    def test_brief_only_cannot_be_used_for_explained_evidence_or_to_repair_a_legacy_reply(self):
        reply = {'headline': 'SYNTHETIC', 'summary': 'SYNTHETIC', 'implications': [], 'uncertainties': []}
        with self.assertRaises(AccountsRefused):
            brief_stages.assemble_brief_only({'status': 'explained'}, reply)
        legacy = {**reply, 'insufficient_explanation': 'SYNTHETIC: thin.', 'significance': '',
                  'main_uncertainty': '', **{k: [] for k in brief_stages.EXPLANATION_LISTS}}
        with self.assertRaisesRegex(AccountsRefused, 'first stage found'):
            brief_stages.assemble({'status': 'insufficient_evidence', 'reason': 'SYNTHETIC: original.'}, legacy)

    def test_an_unattempted_legacy_contract_is_refused_before_reservation(self):
        draft = self.thin()
        current = draft.run_first()
        body = brief_drafting._body(2, 'SYNTHETIC legacy full-contract material.')
        story = draft.story()
        older = brief_drafting._save(draft.desk, 2, body, story, None, current['stages'][1]['bound_to'])
        form = {'draft_id': older, 'request_sha256': hashlib.sha256(body).hexdigest(),
                'estimate': brief_drafting.planning_estimate(body, brief_stages.MAX_TOKENS[2])}
        with self.assertRaises(AccountsRefused) as refused:
            draft.approve(form)
        self.assertEqual(refused.exception.code, 'request_superseded')
        self.assertFalse((draft.folder(older) / 'attempt.json').exists())
        self.assertEqual(draft.model.stages(), [1])


if __name__ == '__main__':
    unittest.main()
