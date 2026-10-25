from datetime import timedelta
from itertools import permutations

import numpy as np
from sqlalchemy import update
from test_workflow import conversation, drain

from agent_insights.clustering import CompleteLink, UMAPDiscovery
from agent_insights.domain import utcnow
from agent_insights.storage.sql import facets


def test_clustering_input_order_and_complete_link():
    angles = np.deg2rad([0, 20, 40, 120])
    vectors = np.array([[np.cos(a), np.sin(a)] for a in angles])
    keys = ["a", "b", "c", "d"]
    expected = None
    for order in permutations(range(4)):
        x = vectors[list(order)]
        k = [keys[i] for i in order]
        groups = CompleteLink(0.9).groups(x.tolist(), k)
        actual = sorted(tuple(sorted(k[i] for i in g)) for g in groups)
        expected = actual if expected is None else expected
        assert actual == expected
        assert all(x[i] @ x[j] >= 0.9 for g in groups for i in g for j in g)
    assert UMAPDiscovery().groups([[1.0, 0.0], [1.0, 0.0]], ["a", "b"]) == [[0, 1]]


def test_pending_window_and_batch_bound(repo, service):
    for i in range(3):
        repo.enqueue(conversation(i))
    drain(service)
    assert len(repo.pending("demo", "support", 2, 7, 3)) == 2
    with repo.engine.begin() as conn:
        conn.execute(update(facets).values(created_at=utcnow() - timedelta(days=8)))
    assert repo.pending("demo", "support", 2, 7, 3) == []
    assert repo.status("demo", "support")["facets"] == {"unclassified": 3}
