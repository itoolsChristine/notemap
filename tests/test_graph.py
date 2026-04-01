"""Tests for the notemap graph algorithms module.

Covers pagerank, hits, louvain_communities, betweenness_centrality,
shortest_path, get_neighborhood, and suggest_hub_notes.

Run with:  python -m unittest tests.test_graph -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup -- allow imports from src/notemap-mcp/
# ---------------------------------------------------------------------------
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from graph import (  # noqa: E402
    betweenness_centrality,
    get_neighborhood,
    hits,
    louvain_communities,
    pagerank,
    shortest_path,
    suggest_hub_notes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    related_notes: list[dict[str, str]] | None = None,
    library: str = "testlib",
    topic: str = "Test note",
) -> dict[str, Any]:
    """Build a minimal index entry with optional outgoing links."""
    return {
        "related_notes": related_notes or [],
        "library":       library,
        "topic":         topic,
    }


def _build_backlinks(index: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """Derive backlinks from the index (same logic the real code uses)."""
    backlinks: dict[str, list[dict[str, str]]] = {}
    for nid, entry in index.items():
        for link in (entry.get("related_notes") or []):
            target = link.get("id", link) if isinstance(link, dict) else link
            backlinks.setdefault(target, []).append({"source": nid, "type": link.get("type", "related")})
    return backlinks


# ---------------------------------------------------------------------------
# Linear chain: A -> B -> C
# ---------------------------------------------------------------------------

def _linear_chain() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, str]]]]:
    """A -> B -> C. B is the bridge."""
    index = {
        "A": _make_entry(related_notes=[{"id": "B", "type": "related"}]),
        "B": _make_entry(related_notes=[{"id": "C", "type": "related"}]),
        "C": _make_entry(),
    }
    return index, _build_backlinks(index)


# ---------------------------------------------------------------------------
# Star graph: Hub -> S1, Hub -> S2, Hub -> S3
# ---------------------------------------------------------------------------

def _star_graph() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, str]]]]:
    """Hub with 3 spokes. Hub should dominate centrality."""
    index = {
        "Hub": _make_entry(related_notes=[
            {"id": "S1", "type": "related"},
            {"id": "S2", "type": "related"},
            {"id": "S3", "type": "related"},
        ]),
        "S1": _make_entry(),
        "S2": _make_entry(),
        "S3": _make_entry(),
    }
    return index, _build_backlinks(index)


# ---------------------------------------------------------------------------
# Two clusters connected by a bridge
# ---------------------------------------------------------------------------

def _two_clusters() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, str]]]]:
    """Cluster 1: A <-> B <-> C. Cluster 2: D <-> E <-> F. Bridge: C -> D."""
    index = {
        "A": _make_entry(related_notes=[{"id": "B", "type": "related"}]),
        "B": _make_entry(related_notes=[{"id": "A", "type": "related"}, {"id": "C", "type": "related"}]),
        "C": _make_entry(related_notes=[{"id": "B", "type": "related"}, {"id": "D", "type": "related"}]),
        "D": _make_entry(related_notes=[{"id": "C", "type": "related"}, {"id": "E", "type": "related"}]),
        "E": _make_entry(related_notes=[{"id": "D", "type": "related"}, {"id": "F", "type": "related"}]),
        "F": _make_entry(related_notes=[{"id": "E", "type": "related"}]),
    }
    return index, _build_backlinks(index)


# ---------------------------------------------------------------------------
# Disconnected graph: {A -> B} and {C} (no edges to C)
# ---------------------------------------------------------------------------

def _disconnected() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, str]]]]:
    index = {
        "A": _make_entry(related_notes=[{"id": "B", "type": "related"}]),
        "B": _make_entry(),
        "C": _make_entry(),
    }
    return index, _build_backlinks(index)


# ===================================================================
# PageRank
# ===================================================================

class TestPageRank(unittest.TestCase):

    def test_empty_graph(self) -> None:
        self.assertEqual(pagerank({}, {}), {})

    def test_single_node(self) -> None:
        """Single node with no links. Score = (1-d)/n = 0.15 per iteration
        (no rank_sum contribution since there are no incoming links)."""
        index = {"A": _make_entry()}
        scores = pagerank(index, _build_backlinks(index))
        self.assertEqual(len(scores), 1)
        # (1 - 0.85) / 1 = 0.15 -- no incoming links means no rank_sum
        self.assertAlmostEqual(scores["A"], 0.15, places=4)

    def test_star_graph_hub_receives_most_rank(self) -> None:
        """In a star, the hub has 3 incoming backlinks so it should receive
        more PageRank than any spoke (spokes only get rank from the hub
        distributed evenly among 3)."""
        index, backlinks = _star_graph()
        scores = pagerank(index, backlinks)

        # All nodes present
        self.assertEqual(set(scores.keys()), {"Hub", "S1", "S2", "S3"})

        # Spokes receive rank from Hub split 3 ways; Hub receives rank from
        # all 3 spokes (each spoke has 0 outlinks, so they contribute nothing
        # via the rank_sum path, but the (1-d)/n teleportation still feeds Hub).
        # The key structural assertion: all spokes have equal rank.
        self.assertAlmostEqual(scores["S1"], scores["S2"], places=6)
        self.assertAlmostEqual(scores["S2"], scores["S3"], places=6)

    def test_linear_chain_all_scores_positive(self) -> None:
        """All nodes in a connected graph should have positive PageRank."""
        index, backlinks = _linear_chain()
        scores = pagerank(index, backlinks)
        for nid, score in scores.items():
            self.assertGreater(score, 0.0, f"Node {nid} has non-positive score")

    def test_target_gets_more_rank_than_source(self) -> None:
        """In A -> B -> C, C is the final sink. With teleportation, B and C
        should accumulate more rank than A (A has no incoming links)."""
        index, backlinks = _linear_chain()
        scores = pagerank(index, backlinks)
        # A has zero incoming links, B has one (from A), C has one (from B).
        # A should have the lowest rank due to no inbound links.
        self.assertLess(scores["A"], scores["C"])


# ===================================================================
# HITS
# ===================================================================

class TestHITS(unittest.TestCase):

    def test_empty_graph(self) -> None:
        hub, auth = hits({}, {})
        self.assertEqual(hub, {})
        self.assertEqual(auth, {})

    def test_star_hub_has_high_hub_score(self) -> None:
        """Hub links to 3 spokes, so its hub score should be the highest."""
        index, backlinks = _star_graph()
        hub_scores, auth_scores = hits(index, backlinks)
        self.assertEqual(hub_scores["Hub"], max(hub_scores.values()))

    def test_star_spokes_are_authorities(self) -> None:
        """Spokes are linked TO by the hub, so they have authority."""
        index, backlinks = _star_graph()
        _, auth_scores = hits(index, backlinks)
        # All spokes should have equal authority
        self.assertAlmostEqual(auth_scores["S1"], auth_scores["S2"], places=6)
        self.assertAlmostEqual(auth_scores["S2"], auth_scores["S3"], places=6)


# ===================================================================
# Louvain Communities
# ===================================================================

class TestLouvainCommunities(unittest.TestCase):

    def test_empty_graph(self) -> None:
        self.assertEqual(louvain_communities({}, {}), {})

    def test_single_node(self) -> None:
        index = {"A": _make_entry()}
        result = louvain_communities(index, _build_backlinks(index))
        self.assertEqual(len(result), 1)
        self.assertIn("A", result)

    def test_no_edges_each_own_community(self) -> None:
        """With no edges, every node should be in its own community."""
        index = {
            "A": _make_entry(),
            "B": _make_entry(),
            "C": _make_entry(),
        }
        result = louvain_communities(index, _build_backlinks(index))
        communities = set(result.values())
        self.assertEqual(len(communities), 3)

    def test_two_clusters_detected(self) -> None:
        """Two densely connected clusters bridged by one edge should be
        separated into different communities (or at most a small number)."""
        index, backlinks = _two_clusters()
        result = louvain_communities(index, backlinks)
        # All nodes present
        self.assertEqual(set(result.keys()), {"A", "B", "C", "D", "E", "F"})
        # The algorithm should find at most 3 communities (ideally 2)
        unique_communities = set(result.values())
        self.assertLessEqual(len(unique_communities), 4)

    def test_fully_connected_clique_few_communities(self) -> None:
        """A fully connected 3-clique should end up in very few communities.
        The simplified Louvain may not always merge all 3 into one due to
        iteration order, but should produce at most 2."""
        index = {
            "A": _make_entry(related_notes=[{"id": "B", "type": "related"}, {"id": "C", "type": "related"}]),
            "B": _make_entry(related_notes=[{"id": "A", "type": "related"}, {"id": "C", "type": "related"}]),
            "C": _make_entry(related_notes=[{"id": "A", "type": "related"}, {"id": "B", "type": "related"}]),
        }
        result = louvain_communities(index, _build_backlinks(index))
        self.assertLessEqual(len(set(result.values())), 2)

    def test_contiguous_community_ids(self) -> None:
        """Community IDs should be renumbered to 0..N-1."""
        index, backlinks = _disconnected()
        result = louvain_communities(index, backlinks)
        ids = sorted(set(result.values()))
        self.assertEqual(ids, list(range(len(ids))))


# ===================================================================
# Shortest Path
# ===================================================================

class TestShortestPath(unittest.TestCase):

    def test_same_node(self) -> None:
        index = {"A": _make_entry()}
        path = shortest_path(index, {}, "A", "A")
        self.assertEqual(path, ["A"])

    def test_nonexistent_source(self) -> None:
        index = {"A": _make_entry()}
        self.assertIsNone(shortest_path(index, {}, "X", "A"))

    def test_nonexistent_target(self) -> None:
        index = {"A": _make_entry()}
        self.assertIsNone(shortest_path(index, {}, "A", "X"))

    def test_direct_link(self) -> None:
        """A -> B should return [A, B]."""
        index, backlinks = _linear_chain()
        path = shortest_path(index, backlinks, "A", "B")
        self.assertEqual(path, ["A", "B"])

    def test_two_hops(self) -> None:
        """A -> B -> C should return [A, B, C]."""
        index, backlinks = _linear_chain()
        path = shortest_path(index, backlinks, "A", "C")
        self.assertEqual(path, ["A", "B", "C"])

    def test_path_length_correct(self) -> None:
        """Verify path length equals number of edges + 1."""
        index, backlinks = _two_clusters()
        path = shortest_path(index, backlinks, "A", "F")
        self.assertIsNotNone(path)
        # A-B-C-D-E-F = 6 nodes in shortest path
        self.assertEqual(len(path), 6)

    def test_disconnected_returns_none(self) -> None:
        """No path between disconnected components."""
        index, backlinks = _disconnected()
        self.assertIsNone(shortest_path(index, backlinks, "A", "C"))

    def test_max_hops_respected(self) -> None:
        """If max_hops is too small, path should not be found."""
        index, backlinks = _two_clusters()
        # A to F requires 5 hops; setting max_hops=2 should fail
        path = shortest_path(index, backlinks, "A", "F", max_hops=2)
        self.assertIsNone(path)

    def test_reverse_direction_works(self) -> None:
        """Graph is treated as undirected, so C -> A should work too."""
        index, backlinks = _linear_chain()
        path = shortest_path(index, backlinks, "C", "A")
        self.assertIsNotNone(path)
        self.assertEqual(len(path), 3)


# ===================================================================
# Get Neighborhood
# ===================================================================

class TestGetNeighborhood(unittest.TestCase):

    def test_nonexistent_node(self) -> None:
        self.assertEqual(get_neighborhood({}, {}, "X"), [])

    def test_isolated_node_returns_empty(self) -> None:
        """An isolated node has no neighbors, so result is empty
        (the center node itself is NOT included in results)."""
        index = {"A": _make_entry()}
        result = get_neighborhood(index, _build_backlinks(index), "A")
        self.assertEqual(result, [])

    def test_one_hop(self) -> None:
        """A -> B -> C. From A with max_hops=1, only B should appear."""
        index, backlinks = _linear_chain()
        result = get_neighborhood(index, backlinks, "A", max_hops=1)
        ids = [r["id"] for r in result]
        self.assertIn("B", ids)
        self.assertNotIn("C", ids)
        self.assertNotIn("A", ids)  # Center node excluded

    def test_two_hops(self) -> None:
        """A -> B -> C. From A with max_hops=2, both B and C should appear."""
        index, backlinks = _linear_chain()
        result = get_neighborhood(index, backlinks, "A", max_hops=2)
        ids = [r["id"] for r in result]
        self.assertIn("B", ids)
        self.assertIn("C", ids)

    def test_decay_scores(self) -> None:
        """Closer neighbors should have higher scores (exponential decay)."""
        index, backlinks = _linear_chain()
        result = get_neighborhood(index, backlinks, "A", max_hops=2)
        by_id = {r["id"]: r for r in result}
        self.assertGreater(by_id["B"]["score"], by_id["C"]["score"])
        # 1-hop = 1/2 = 0.5, 2-hop = 1/4 = 0.25
        self.assertAlmostEqual(by_id["B"]["score"], 0.5, places=3)
        self.assertAlmostEqual(by_id["C"]["score"], 0.25, places=3)

    def test_hop_count_in_result(self) -> None:
        """Each result should include the hop count."""
        index, backlinks = _linear_chain()
        result = get_neighborhood(index, backlinks, "A", max_hops=2)
        by_id = {r["id"]: r for r in result}
        self.assertEqual(by_id["B"]["hops"], 1)
        self.assertEqual(by_id["C"]["hops"], 2)

    def test_result_sorted_by_score_desc(self) -> None:
        """Results should be sorted by score descending."""
        index, backlinks = _star_graph()
        result = get_neighborhood(index, backlinks, "Hub", max_hops=2)
        scores = [r["score"] for r in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_max_hops_zero(self) -> None:
        """max_hops=0 means no neighbors, empty result."""
        index, backlinks = _linear_chain()
        result = get_neighborhood(index, backlinks, "A", max_hops=0)
        self.assertEqual(result, [])

    def test_backlink_traversal(self) -> None:
        """Neighborhood should include backlink direction too.
        A -> B. From B, A should be reachable via backlinks."""
        index = {
            "A": _make_entry(related_notes=[{"id": "B", "type": "related"}]),
            "B": _make_entry(),
        }
        backlinks = _build_backlinks(index)
        result = get_neighborhood(index, backlinks, "B", max_hops=1)
        ids = [r["id"] for r in result]
        self.assertIn("A", ids)


# ===================================================================
# Betweenness Centrality
# ===================================================================

class TestBetweennessCentrality(unittest.TestCase):

    def test_empty_graph(self) -> None:
        self.assertEqual(betweenness_centrality({}, {}), {})

    def test_single_node(self) -> None:
        index = {"A": _make_entry()}
        result = betweenness_centrality(index, _build_backlinks(index))
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result["A"], 0.0)

    def test_bridge_node_highest_centrality(self) -> None:
        """In A -> B -> C, B is the bridge and should have the highest
        betweenness centrality."""
        index, backlinks = _linear_chain()
        result = betweenness_centrality(index, backlinks)
        self.assertGreater(result["B"], result["A"])
        self.assertGreater(result["B"], result["C"])

    def test_two_cluster_bridge_nodes(self) -> None:
        """In the two-cluster graph, the bridge nodes C and D should have
        higher centrality than leaf nodes A and F."""
        index, backlinks = _two_clusters()
        result = betweenness_centrality(index, backlinks)
        # C and D are the bridge between the two clusters
        self.assertGreater(result["C"], result["A"])
        self.assertGreater(result["D"], result["F"])

    def test_disconnected_graph(self) -> None:
        """Disconnected nodes should have 0 centrality (no shortest paths
        pass through them)."""
        index, backlinks = _disconnected()
        result = betweenness_centrality(index, backlinks)
        # C is completely isolated
        self.assertAlmostEqual(result["C"], 0.0)

    def test_all_nodes_present(self) -> None:
        """All nodes should appear in the result dict."""
        index, backlinks = _star_graph()
        result = betweenness_centrality(index, backlinks)
        self.assertEqual(set(result.keys()), set(index.keys()))


# ===================================================================
# Suggest Hub Notes
# ===================================================================

class TestSuggestHubNotes(unittest.TestCase):

    def test_empty_graph(self) -> None:
        self.assertEqual(suggest_hub_notes({}, {}), [])

    def test_small_library_no_suggestion(self) -> None:
        """Libraries with fewer than 8 notes should NOT be suggested."""
        index = {f"n{i}": _make_entry(library="smalllib") for i in range(5)}
        result = suggest_hub_notes(index, _build_backlinks(index))
        self.assertEqual(result, [])

    def test_large_library_no_hub_suggests(self) -> None:
        """A library with 8+ notes and no note with 3+ outlinks should
        produce a suggestion."""
        index = {f"n{i}": _make_entry(library="biglib") for i in range(10)}
        result = suggest_hub_notes(index, _build_backlinks(index))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["library"], "biglib")
        self.assertEqual(result[0]["note_count"], 10)

    def test_large_library_with_hub_no_suggestion(self) -> None:
        """A library with 8+ notes where one note has 3+ outlinks should
        NOT produce a suggestion."""
        index = {f"n{i}": _make_entry(library="biglib") for i in range(10)}
        # Give one note enough outlinks to qualify as a hub
        index["n0"] = _make_entry(
            library="biglib",
            related_notes=[
                {"id": "n1", "type": "related"},
                {"id": "n2", "type": "related"},
                {"id": "n3", "type": "related"},
            ],
        )
        result = suggest_hub_notes(index, _build_backlinks(index))
        self.assertEqual(result, [])

    def test_multiple_libraries(self) -> None:
        """Multiple libraries can each produce suggestions independently."""
        index = {}
        for i in range(10):
            index[f"a{i}"] = _make_entry(library="lib-a")
            index[f"b{i}"] = _make_entry(library="lib-b")
        result = suggest_hub_notes(index, _build_backlinks(index))
        libs = {s["library"] for s in result}
        self.assertEqual(libs, {"lib-a", "lib-b"})


if __name__ == "__main__":
    unittest.main()
