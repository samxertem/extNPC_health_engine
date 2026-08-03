"""
Family trees over the whole population.
=======================================

The population is one big directed acyclic graph: an edge parent -> child for
every reproduction event. Showing all of it at once is noise, so the dashboard
draws the *ego network* of one selected individual -- their ancestors going up
and their descendants coming down -- laid out in generational layers.

networkx holds the graph; layout is a simple layered assignment (y = pedigree
depth, x = spread within a layer) which is readable for the small trees a
150-person world produces.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

import networkx as nx


def build_graph(world) -> nx.DiGraph:
    g = nx.DiGraph()
    for name, npc in world.people.items():
        g.add_node(name)
        if npc.parents:
            mother, father = npc.parents
            if mother in world.people:
                g.add_edge(mother, name)
            if father in world.people:
                g.add_edge(father, name)
    return g


def _ancestors(g: nx.DiGraph, name: str, depth: int) -> Set[str]:
    seen: Set[str] = set()
    frontier = {name}
    for _ in range(depth):
        nxt: Set[str] = set()
        for n in frontier:
            for parent in g.predecessors(n):
                if parent not in seen:
                    seen.add(parent)
                    nxt.add(parent)
        frontier = nxt
    return seen


def _descendants(g: nx.DiGraph, name: str, depth: int) -> Set[str]:
    seen: Set[str] = set()
    frontier = {name}
    for _ in range(depth):
        nxt: Set[str] = set()
        for n in frontier:
            for child in g.successors(n):
                if child not in seen:
                    seen.add(child)
                    nxt.add(child)
        frontier = nxt
    return seen


def ego_tree(world, name: str, up: int = 3, down: int = 3
             ) -> Tuple[List[dict], List[Tuple[str, str]]]:
    """
    Return (nodes, edges) for the ego network of `name`.

    Each node dict carries screen position (x, y), colour, label and whether
    the individual is alive/the ego. y is pedigree generation (higher = older),
    x spreads siblings within a layer.
    """
    if name not in world.people:
        return [], []
    g = build_graph(world)
    keep = {name} | _ancestors(g, name, up) | _descendants(g, name, down)
    sub = g.subgraph(keep)

    # layer each node by its generation attribute for a stable vertical order
    layers: Dict[int, List[str]] = {}
    for n in keep:
        gen = world.people[n].generation
        layers.setdefault(gen, []).append(n)

    nodes: List[dict] = []
    for gen, members in sorted(layers.items()):
        members.sort()
        k = len(members)
        for i, n in enumerate(members):
            npc = world.people[n]
            meta = world.meta[n]
            x = (i - (k - 1) / 2.0)
            nodes.append({
                "name": n,
                "x": x,
                "y": float(gen),
                "color": meta.color,
                "alive": npc.alive,
                "is_ego": n == name,
                "sex": npc.sex,
                "age": npc.age,
                "label": n.split("-")[0],
                "generation": gen,
            })
    edges = [(u, v) for u, v in sub.edges()]
    return nodes, edges
