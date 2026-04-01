"""Graph algorithms for the notemap knowledge graph.

Pure Python implementations. No external dependencies.
All algorithms produce neutral/uniform output when the graph is sparse.
"""
from __future__ import annotations

from typing import Any


def pagerank(
    index: dict[str, dict[str, Any]],
    backlinks: dict[str, list[dict[str, str]]],
    damping: float = 0.85,
    iterations: int = 20,
) -> dict[str, float]:
    """Compute PageRank for all notes. Returns {note_id: score}."""
    n = len(index)
    if n == 0:
        return {}
    uniform = 1.0 / n
    scores: dict[str, float] = {nid: uniform for nid in index}

    for _ in range(iterations):
        new_scores: dict[str, float] = {}
        for nid in index:
            incoming = backlinks.get(nid, [])
            rank_sum = 0.0
            for link in incoming:
                src = link.get("source", "")
                if src in index:
                    src_outlinks = len(index[src].get("related_notes") or [])
                    if src_outlinks > 0:
                        rank_sum += scores.get(src, 0) / src_outlinks
            new_scores[nid] = (1 - damping) / n + damping * rank_sum
        scores = new_scores

    return scores


def hits(
    index: dict[str, dict[str, Any]],
    backlinks: dict[str, list[dict[str, str]]],
    iterations: int = 20,
) -> tuple[dict[str, float], dict[str, float]]:
    """Compute HITS hub and authority scores. Returns (hub_scores, authority_scores)."""
    n = len(index)
    if n == 0:
        return {}, {}

    hub: dict[str, float] = {nid: 1.0 for nid in index}
    auth: dict[str, float] = {nid: 1.0 for nid in index}

    for _ in range(iterations):
        # Authority = sum of hub scores of pages linking TO this page
        new_auth: dict[str, float] = {}
        for nid in index:
            incoming = backlinks.get(nid, [])
            new_auth[nid] = sum(hub.get(link.get("source", ""), 0) for link in incoming)

        # Hub = sum of authority scores of pages this page links TO
        new_hub: dict[str, float] = {}
        for nid in index:
            related = index[nid].get("related_notes") or []
            total = 0.0
            for link in related:
                target = link.get("id", link) if isinstance(link, dict) else link
                total += new_auth.get(target, 0)
            new_hub[nid] = total

        # Normalize
        max_auth = max(new_auth.values()) if new_auth else 1
        max_hub = max(new_hub.values()) if new_hub else 1
        auth = {k: v / max_auth if max_auth > 0 else 0 for k, v in new_auth.items()}
        hub = {k: v / max_hub if max_hub > 0 else 0 for k, v in new_hub.items()}

    return hub, auth


def louvain_communities(
    index: dict[str, dict[str, Any]],
    backlinks: dict[str, list[dict[str, str]]],
) -> dict[str, int]:
    """Simple community detection. Returns {note_id: community_id}.

    Uses a greedy modularity optimization (simplified Louvain).
    On sparse graphs, returns each note in its own community.
    """
    n = len(index)
    if n == 0:
        return {}

    # Build adjacency: undirected edges from related_notes + backlinks
    neighbors: dict[str, set[str]] = {nid: set() for nid in index}
    for nid, entry in index.items():
        for link in (entry.get("related_notes") or []):
            target = link.get("id", link) if isinstance(link, dict) else link
            if target in index:
                neighbors[nid].add(target)
                neighbors[target].add(nid)

    # Initialize: each node in its own community
    community: dict[str, int] = {nid: i for i, nid in enumerate(index)}

    # Total edges
    m = sum(len(nbrs) for nbrs in neighbors.values()) / 2
    if m == 0:
        return community  # No edges, each node is its own community

    # Greedy: move each node to the community that maximizes modularity gain
    improved = True
    max_iterations = 10
    iteration = 0
    while improved and iteration < max_iterations:
        improved = False
        iteration += 1
        for nid in index:
            best_comm = community[nid]
            best_gain = 0.0

            # Count edges to each neighboring community
            comm_edges: dict[int, int] = {}
            for nbr in neighbors[nid]:
                c = community[nbr]
                comm_edges[c] = comm_edges.get(c, 0) + 1

            ki = len(neighbors[nid])
            for c, edges_to_c in comm_edges.items():
                if c == community[nid]:
                    continue
                # Simplified modularity gain
                gain = edges_to_c / m - (ki * ki) / (4 * m * m)
                if gain > best_gain:
                    best_gain = gain
                    best_comm = c

            if best_comm != community[nid]:
                community[nid] = best_comm
                improved = True

    # Renumber communities to be contiguous
    unique = sorted(set(community.values()))
    remap = {old: new for new, old in enumerate(unique)}
    return {nid: remap[c] for nid, c in community.items()}


def shortest_path(
    index: dict[str, dict[str, Any]],
    backlinks: dict[str, list[dict[str, str]]],
    from_id: str,
    to_id: str,
    max_hops: int = 5,
) -> list[str] | None:
    """Find shortest path between two notes via BFS. Returns list of note IDs or None."""
    if from_id not in index or to_id not in index:
        return None
    if from_id == to_id:
        return [from_id]

    # Build undirected adjacency
    neighbors: dict[str, set[str]] = {nid: set() for nid in index}
    for nid, entry in index.items():
        for link in (entry.get("related_notes") or []):
            target = link.get("id", link) if isinstance(link, dict) else link
            if target in index:
                neighbors[nid].add(target)
                neighbors[target].add(nid)

    # BFS
    visited: set[str] = {from_id}
    queue: list[tuple[str, list[str]]] = [(from_id, [from_id])]
    while queue:
        current, path = queue.pop(0)
        if len(path) > max_hops:
            break
        for nbr in neighbors.get(current, set()):
            if nbr == to_id:
                return path + [nbr]
            if nbr not in visited:
                visited.add(nbr)
                queue.append((nbr, path + [nbr]))

    return None


def get_neighborhood(
    index: dict[str, dict[str, Any]],
    backlinks: dict[str, list[dict[str, str]]],
    note_id: str,
    max_hops: int = 2,
) -> list[dict[str, Any]]:
    """Get all notes within max_hops of note_id with decay scores."""
    if note_id not in index:
        return []

    result: list[dict[str, Any]] = []
    visited: set[str] = {note_id}
    queue: list[tuple[str, int]] = [(note_id, 0)]

    while queue:
        current, depth = queue.pop(0)
        if depth > max_hops:
            break
        if depth > 0:
            score = 1.0 / (2 ** depth)  # Exponential decay
            entry = index.get(current, {})
            result.append({
                "id": current,
                "topic": entry.get("topic", ""),
                "library": entry.get("library", ""),
                "hops": depth,
                "score": round(score, 3),
            })

        # Expand: outgoing + incoming
        entry = index.get(current, {})
        for link in (entry.get("related_notes") or []):
            target = link.get("id", link) if isinstance(link, dict) else link
            if target not in visited and target in index:
                visited.add(target)
                queue.append((target, depth + 1))
        for bl in backlinks.get(current, []):
            src = bl.get("source", "")
            if src not in visited and src in index:
                visited.add(src)
                queue.append((src, depth + 1))

    result.sort(key=lambda x: (-x["score"], x["id"]))
    return result


def betweenness_centrality(
    index: dict[str, dict[str, Any]],
    backlinks: dict[str, list[dict[str, str]]],
) -> dict[str, float]:
    """Compute approximate betweenness centrality for each note.

    Uses BFS from each node (capped at 50 sources for performance).
    Returns {note_id: centrality_score}.
    """
    n = len(index)
    if n == 0:
        return {}

    # Build undirected adjacency
    neighbors: dict[str, set[str]] = {nid: set() for nid in index}
    for nid, entry in index.items():
        for link in (entry.get("related_notes") or []):
            target = link.get("id", link) if isinstance(link, dict) else link
            if target in index:
                neighbors[nid].add(target)
                neighbors[target].add(nid)

    centrality: dict[str, float] = {nid: 0.0 for nid in index}

    # Sample-based: cap at 50 source nodes for performance (random to avoid bias)
    import random
    sample_size = min(n, 50)
    all_ids = list(index.keys())
    sources = random.sample(all_ids, sample_size) if len(all_ids) > sample_size else all_ids

    for source in sources:
        # BFS from source
        visited: dict[str, int] = {source: 0}
        queue = [source]
        predecessors: dict[str, list[str]] = {source: []}
        sigma: dict[str, int] = {source: 1}  # number of shortest paths

        while queue:
            current = queue.pop(0)
            for nbr in neighbors.get(current, set()):
                if nbr not in visited:
                    visited[nbr] = visited[current] + 1
                    queue.append(nbr)
                    predecessors[nbr] = [current]
                    sigma[nbr] = sigma[current]
                elif visited[nbr] == visited[current] + 1:
                    predecessors[nbr].append(current)
                    sigma[nbr] += sigma[current]

        # Accumulate centrality (back-propagation)
        delta: dict[str, float] = {nid: 0.0 for nid in visited}
        nodes_by_dist = sorted(visited.keys(), key=lambda x: -visited[x])
        for w in nodes_by_dist:
            for v in predecessors.get(w, []):
                delta[v] += (sigma[v] / max(sigma[w], 1)) * (1 + delta[w])
            if w != source:
                centrality[w] += delta[w]

    # Normalize
    if n > 2:
        norm = 1.0 / ((n - 1) * (n - 2))
        centrality = {k: v * norm for k, v in centrality.items()}

    return centrality


def suggest_hub_notes(
    index: dict[str, dict[str, Any]],
    backlinks: dict[str, list[dict[str, str]]],
) -> list[dict[str, Any]]:
    """Find topic clusters that could benefit from a hub/structure note."""
    # Group notes by library
    by_lib: dict[str, list[str]] = {}
    for nid, entry in index.items():
        lib = entry.get("library", "")
        by_lib.setdefault(lib, []).append(nid)

    suggestions: list[dict[str, Any]] = []
    for lib, note_ids in by_lib.items():
        if len(note_ids) < 8:
            continue

        # Check if library already has a hub-like note (one with many outgoing links)
        max_outlinks = 0
        for nid in note_ids:
            outlinks = len(index[nid].get("related_notes") or [])
            max_outlinks = max(max_outlinks, outlinks)

        if max_outlinks < 3:
            suggestions.append({
                "library": lib,
                "note_count": len(note_ids),
                "reason": f"Library '{lib}' has {len(note_ids)} notes but no hub note (max outlinks: {max_outlinks})",
            })

    return suggestions
