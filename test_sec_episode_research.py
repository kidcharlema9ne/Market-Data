import unittest
from sec_episode_research import build_episodes,prior_disclosure_counts

def row(acc,day,owner="42",issuer="100"):
    return {"accession":acc,"filing_date":day,"issuer_cik":issuer,
            "security_title":"Common Stock","owners":[{"cik":owner}],
            "aggregate_dollars":"1000","review_flags":[]}

class EpisodeTests(unittest.TestCase):
    def test_separate_disclosures_and_gap(self):
        a=[row("a","2026-01-05"),row("b","2026-01-09"),row("c","2026-01-20")]
        episodes=build_episodes(a)
        self.assertEqual([e["disclosure_count"] for e in episodes],[2,1])
        self.assertEqual(episodes[0]["accessions"],["a","b"])
        self.assertFalse(episodes[0]["synthetic_entry"])
    def test_no_cross_insider_grouping(self):
        self.assertEqual(len(build_episodes([row("a","2026-01-05"),row("b","2026-01-06","99")])),2)
    def test_same_day_no_lookahead(self):
        a=[row("a","2026-01-05"),row("b","2026-01-05"),row("c","2026-01-06")]
        c=prior_disclosure_counts(a)
        self.assertEqual(c[("100","42","a")],0)
        self.assertEqual(c[("100","42","b")],0)
        self.assertEqual(c[("100","42","c")],2)

if __name__=="__main__":unittest.main()
