"""Pure orchestration helpers for the guided campaign workflow.

The Streamlit layer uses these utilities to coordinate the discovery,
theme selection, copy generation, and focus-testing stages.  Keeping the
state machine and iteration logic here lets us test the behaviour without
needing to spin up Streamlit in the test suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple


Stage = str


@dataclass
class TrendPayload:
    """Data returned from the trend discovery step."""

    rising: Sequence[Any]
    news: Sequence[Any]
    themes: List[str]


@dataclass
class FocusTestIteration:
    """Result of a single pass through the persona focus group."""

    round: int
    copy: str
    summary: str
    mean_intent: float
    figure: Any = None
    clusters: Any = None


@dataclass
class FocusTestOutcome:
    """Finalised focus-testing artefacts."""

    iterations: List[FocusTestIteration]
    final_copy: str
    passed: bool


@dataclass
class GuidedFlowState:
    """Simple container tracking the progress through the guided flow."""

    stage: Stage = "start"
    trends: Optional[TrendPayload] = None
    chosen_theme: Optional[str] = None
    variants: List[str] = field(default_factory=list)
    focus_result: Optional[FocusTestOutcome] = None
    focus_source: Optional[str] = None

    def reset(self) -> None:
        """Return the workflow to the initial stage."""

        self.stage = "start"
        self.trends = None
        self.chosen_theme = None
        self.variants.clear()
        self.focus_result = None
        self.focus_source = None


def discover_trends(
    state: GuidedFlowState,
    fetcher: Callable[[], Tuple[Iterable[Any], Iterable[Any]]],
) -> TrendPayload:
    """Fetch the latest trends and prime the state for theme selection."""

    rising, news = fetcher()
    rising_items = list(rising)
    news_items = list(news)
    themes = [
        f"{item.get('query', '(n/a)')} — {item.get('value', '')}"
        for item in rising_items[:10]
    ]

    payload = TrendPayload(rising=rising_items, news=news_items, themes=themes)
    state.reset()
    state.trends = payload
    state.stage = "choose_theme"
    return payload


def choose_theme(state: GuidedFlowState, theme: str) -> None:
    """Store the selected theme and advance to the variant drafting stage."""

    if state.stage not in {"choose_theme", "draft_variants"}:
        raise ValueError("Cannot choose a theme before discovering trends.")

    state.chosen_theme = theme
    state.stage = "draft_variants"
    state.variants.clear()
    state.focus_result = None
    state.focus_source = None


def generate_variants(
    state: GuidedFlowState,
    generator: Callable[[], Sequence[str]],
) -> List[str]:
    """Generate creative variants for the chosen theme."""

    if state.stage != "draft_variants":
        raise ValueError("Variants can only be generated after choosing a theme.")

    variants = list(generator())
    if not variants:
        raise ValueError("Generator must return at least one variant.")

    state.variants = variants
    return variants


def begin_focus_testing(state: GuidedFlowState, base_copy: str) -> None:
    """Prime the state for the focus-testing loop."""

    if state.stage != "draft_variants":
        raise ValueError("Cannot begin focus testing before drafting variants.")

    state.focus_source = base_copy
    state.focus_result = None
    state.stage = "focus_test"


def execute_focus_testing(
    state: GuidedFlowState,
    tester: Callable[[str, int], FocusTestIteration],
    improver: Callable[[str, FocusTestIteration], str],
    *,
    threshold: float,
    max_rounds: int,
) -> FocusTestOutcome:
    """Run iterative focus testing until the copy passes or rounds expire."""

    if max_rounds < 1:
        raise ValueError("max_rounds must be at least 1")
    if state.stage not in {"focus_test", "complete"}:
        raise ValueError("Focus testing can only run after being prepared.")
    if not state.focus_source:
        raise ValueError("No base copy available for focus testing.")

    current = state.focus_source
    iterations: List[FocusTestIteration] = []
    passed = False

    for round_idx in range(1, max_rounds + 1):
        iteration = tester(current, round_idx)
        iterations.append(iteration)

        if iteration.mean_intent >= threshold:
            passed = True
            final_copy = iteration.copy
            break

        if round_idx == max_rounds:
            final_copy = iteration.copy
            break

        current = improver(iteration.copy, iteration)

    else:  # pragma: no cover - loop always breaks via break statements above
        final_copy = current

    outcome = FocusTestOutcome(iterations=iterations, final_copy=final_copy, passed=passed)
    state.focus_result = outcome
    state.stage = "complete"
    state.focus_source = final_copy
    return outcome

