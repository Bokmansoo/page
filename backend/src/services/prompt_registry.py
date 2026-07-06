import os


class PromptRegistry:
    def __init__(self, base_path: str = "backend/prompts"):
        candidate_path = os.path.abspath(base_path)
        normalized_base_path = os.path.normpath(base_path)
        backend_prefix = f"backend{os.sep}"

        if not os.path.exists(candidate_path) and normalized_base_path.startswith(backend_prefix):
            local_path = os.path.abspath(normalized_base_path[len(backend_prefix):])
            if os.path.exists(local_path):
                candidate_path = local_path

        self.base_path = candidate_path

    def load(self, name: str) -> str:
        # Path traversal guard
        if ".." in name or name.startswith("/") or name.startswith("\\"):
            raise ValueError(f"Invalid prompt name: {name}")

        target_path = os.path.abspath(os.path.join(self.base_path, f"{name}.md"))
        
        # Ensure the resolved path remains inside base_path
        if os.path.commonpath([self.base_path, target_path]) != self.base_path:
            raise ValueError(f"Invalid prompt name: {name}")

        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Prompt file not found at: {target_path}")

        with open(target_path, "r", encoding="utf-8") as f:
            return f.read()

    def load_agent_prompt(self, agent_name: str) -> str:
        normalized_name = agent_name.removeprefix("agents/")
        if (
            not normalized_name
            or ".." in normalized_name
            or "/" in normalized_name
            or "\\" in normalized_name
        ):
            raise ValueError(f"Invalid agent prompt name: {agent_name}")

        return self.load(os.path.join(normalized_name, "prompt"))
