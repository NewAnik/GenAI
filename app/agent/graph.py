"""Builds the compiled LangGraph `StateGraph`: every node returns a partial-state dict including
a `_route` key, and the matching `route_after_*` function (co-located with each node, for easy
unit testing) reads it to pick the next edge. One inbound WhatsApp message maps to exactly one
`ainvoke` over this graph.

No checkpointer is attached here — `conversation_sessions.session_state` JSONB is the canonical,
durable store across turns (see `services.session_service`); the compiled graph only needs to
manage state *within* a single turn.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agent.nodes.collect_requirements import collect_requirements_node, route_after_collection
from app.agent.nodes.curate_recommendations import curate_recommendations_node, route_after_curation
from app.agent.nodes.finalize_selection import finalize_selection_node, route_after_finalize
from app.agent.nodes.handle_refinement import handle_refinement_node, route_after_refinement
from app.agent.nodes.present_options import present_options_node, route_after_presentation
from app.agent.nodes.route_intent import route_after_intent, route_intent_node
from app.agent.nodes.search_catalog import route_after_search, search_catalog_node
from app.agent.state import AgentState


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("route_intent", route_intent_node)
    graph.add_node("collect_requirements", collect_requirements_node)
    graph.add_node("search_catalog", search_catalog_node)
    graph.add_node("curate_recommendations", curate_recommendations_node)
    graph.add_node("present_options", present_options_node)
    graph.add_node("handle_refinement", handle_refinement_node)
    graph.add_node("finalize_selection", finalize_selection_node)

    graph.set_entry_point("route_intent")

    graph.add_conditional_edges("route_intent", route_after_intent, {
        "collect_requirements": "collect_requirements",
        "handle_refinement": "handle_refinement",
        "present_options": "present_options",
        "finalize_selection": "finalize_selection",
        "end_turn": END,
    })
    graph.add_conditional_edges("collect_requirements", route_after_collection, {
        "search_catalog": "search_catalog",
        "end_turn": END,
    })
    graph.add_conditional_edges("search_catalog", route_after_search, {
        "curate_recommendations": "curate_recommendations",
    })
    graph.add_conditional_edges("curate_recommendations", route_after_curation, {
        "present_options": "present_options",
        "end_turn": END,
    })
    graph.add_conditional_edges("present_options", route_after_presentation, {
        "end_turn": END,
    })
    graph.add_conditional_edges("handle_refinement", route_after_refinement, {
        "search_catalog": "search_catalog",
    })
    graph.add_conditional_edges("finalize_selection", route_after_finalize, {
        "end_turn": END,
    })

    return graph.compile()
