"""Batch discovery only; registered topic assignment stays in original embedding space."""

import numpy as np


def normalized(vectors):
    values = np.asarray(vectors, dtype=float)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("Expected finite, equally sized embedding vectors")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("Zero embedding")
    return values / norms


class CompleteLink:
    """Deterministic small-batch reference strategy, bounded by pending_batch_size."""

    def __init__(self, threshold=0.8):
        self.threshold = threshold

    def groups(self, vectors, keys):
        if not vectors:
            return []
        x = normalized(vectors)
        scores = x @ x.T
        groups = [(i,) for i in sorted(range(len(keys)), key=lambda i: keys[i])]
        while True:
            best = None
            for a in range(len(groups)):
                for b in range(a + 1, len(groups)):
                    similarity = min(float(scores[i, j]) for i in groups[a] for j in groups[b])
                    if similarity < self.threshold:
                        continue
                    merged = tuple(sorted(groups[a] + groups[b], key=lambda i: keys[i]))
                    candidate = (
                        -round(similarity, 12),
                        tuple(keys[i] for i in merged),
                        a,
                        b,
                        merged,
                    )
                    if best is None or candidate < best:
                        best = candidate
            if best is None:
                break
            _, _, a, b, merged = best
            groups = [g for i, g in enumerate(groups) if i not in (a, b)] + [merged]
            groups.sort(key=lambda g: tuple(keys[i] for i in g))
        return [list(g) for g in groups]


class UMAPDiscovery:
    """Optional batch-local UMAP + HDBSCAN. Reduced coordinates are never persisted."""

    def __init__(self, dimensions=10, min_cluster_size=3, fallback_threshold=0.8):
        self.dimensions, self.min_cluster_size = dimensions, min_cluster_size
        self.fallback = CompleteLink(fallback_threshold)

    def groups(self, vectors, keys):
        if len(vectors) <= self.dimensions + 2:
            return self.fallback.groups(vectors, keys)
        try:
            from hdbscan import HDBSCAN
            from umap import UMAP
        except ImportError:
            raise RuntimeError("Install agent-insights[umap] for this clusterer") from None
        order = sorted(range(len(keys)), key=lambda i: keys[i])
        x = normalized(vectors)[order]
        reduced = UMAP(
            n_components=self.dimensions,
            n_neighbors=min(15, len(x) - 1),
            metric="cosine",
            random_state=42,
        ).fit_transform(x)
        labels = HDBSCAN(min_cluster_size=self.min_cluster_size).fit_predict(reduced)
        groups = [
            [order[i] for i, label in enumerate(labels) if label == k]
            for k in sorted(set(labels))
            if k >= 0
        ]
        groups.extend([[order[i]] for i, label in enumerate(labels) if label == -1])
        return groups
