from abc import ABC, abstractmethod
from backend.src.agents.state import AgentRunState


class BaseNode(ABC):
    @abstractmethod
    def run(self, state: AgentRunState) -> AgentRunState:
        pass
