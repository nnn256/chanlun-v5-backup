import unittest

from chanmodel.signal_chart import candidate_counts,is_active_candidate


class CandidateCountTests(unittest.TestCase):
    def test_disputed_expired_and_unknown_states_are_not_active_candidates(self):
        signals=[{'class':'first_buy','state':s} for s in ['structure_complete','candidate',
            'needs_review','withdrawn','invalidated','session_expired','unrecognized']]
        result=candidate_counts(signals)
        self.assertEqual(result['total'],7)
        self.assertEqual(result['active'],2)
        self.assertEqual(result['review'],1)
        self.assertEqual(result['classes']['first_buy'],7)
        self.assertFalse(is_active_candidate({'state':'needs_review'}))

    def test_three_complete_one_review_does_not_claim_four_usable_points(self):
        signals=[{'class':'third_buy','state':'structure_complete'} for _ in range(3)]
        signals.append({'class':'first_sell','state':'needs_review'})
        self.assertEqual(candidate_counts(signals)['active'],3)
        self.assertEqual(candidate_counts(signals)['review'],1)


if __name__=='__main__':unittest.main()
