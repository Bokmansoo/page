from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from src.agents.state import AgentRunState

RealTextGenerator = Callable[[str, str, dict[str, Any], type], dict[str, Any]]


class AgentNode(ABC):
    name: str

    @abstractmethod
    def run(self, state: AgentRunState) -> AgentRunState:
        raise NotImplementedError

    def run_real_text(
        self,
        state: AgentRunState,
        generate_output: RealTextGenerator,
    ) -> AgentRunState:
        return self.run(state)
