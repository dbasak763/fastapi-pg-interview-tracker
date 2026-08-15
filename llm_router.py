"""Deterministic LangGraph routing for dashboard LLM requests.

The graph classifies request shape and selects an available provider. It does
not ask another model to route, keeping the decision fast, inexpensive, and
fully testable. Provider nodes are intentionally separate so future routes can
gain their own policies without turning the FastAPI endpoint into a condition
tree.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


RequestIntent = Literal["lookup", "analysis", "visualization"]

VISUALIZATION_WORDS = {
    "chart",
    "dashboard",
    "graph",
    "histogram",
    "plot",
    "sparkline",
    "visualise",
    "visualize",
    "visualisation",
    "visualization",
}
ANALYSIS_WORDS = {
    "average",
    "best",
    "change",
    "coach",
    "compare",
    "comparison",
    "focus",
    "improve",
    "progress",
    "recommend",
    "strongest",
    "trend",
    "weakest",
    "why",
}


class RouteState(TypedDict, total=False):
    message: str
    intent: RequestIntent
    available_providers: tuple[str, ...]
    preferences: Dict[str, str]
    provider: str
    reason: str


@dataclass(frozen=True)
class RouteDecision:
    intent: RequestIntent
    provider: str
    reason: str


def classify_request(message: str) -> RequestIntent:
    """Classify a request using stable product-language signals."""

    words = {
        token.strip(".,!?;:()[]{}\"'").lower()
        for token in message.split()
    }
    if words.intersection(VISUALIZATION_WORDS):
        return "visualization"
    if words.intersection(ANALYSIS_WORDS):
        return "analysis"
    return "lookup"


def _classify_node(state: RouteState) -> RouteState:
    return {"intent": classify_request(state["message"])}


def _intent_edge(state: RouteState) -> RequestIntent:
    return state["intent"]


def _select_provider(state: RouteState, intent: RequestIntent) -> RouteState:
    available = state["available_providers"]
    preferred = state["preferences"].get(intent, "groq")
    if preferred in available:
        selected = preferred
        reason = f"{intent} requests prefer {preferred}"
    elif available:
        selected = available[0]
        reason = f"{preferred} unavailable; using {selected}"
    else:
        selected = "fallback"
        reason = "no LLM provider is configured"
    return {"provider": selected, "reason": reason}


def _lookup_node(state: RouteState) -> RouteState:
    return _select_provider(state, "lookup")


def _analysis_node(state: RouteState) -> RouteState:
    return _select_provider(state, "analysis")


def _visualization_node(state: RouteState) -> RouteState:
    return _select_provider(state, "visualization")


def build_router_graph():
    """Compile the small conditional routing graph once at import time."""

    builder = StateGraph(RouteState)
    builder.add_node("classify", _classify_node)
    builder.add_node("lookup", _lookup_node)
    builder.add_node("analysis", _analysis_node)
    builder.add_node("visualization", _visualization_node)
    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        _intent_edge,
        {
            "lookup": "lookup",
            "analysis": "analysis",
            "visualization": "visualization",
        },
    )
    builder.add_edge("lookup", END)
    builder.add_edge("analysis", END)
    builder.add_edge("visualization", END)
    return builder.compile()


ROUTER_GRAPH = build_router_graph()


def route_llm_request(
    message: str,
    *,
    available_providers: Iterable[str],
    preferences: Dict[str, str] | None = None,
) -> RouteDecision:
    """Run the LangGraph router and return its public decision contract."""

    state = ROUTER_GRAPH.invoke(
        {
            "message": message,
            "available_providers": tuple(available_providers),
            "preferences": preferences
            or {
                "lookup": "groq",
                "analysis": "groq",
                "visualization": "groq",
            },
        }
    )
    return RouteDecision(
        intent=state["intent"],
        provider=state["provider"],
        reason=state["reason"],
    )
