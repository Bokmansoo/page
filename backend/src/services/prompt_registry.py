import os


class PromptRegistry:
    def __init__(self, base_path: str = "backend/prompts"):
        self.base_path = os.path.abspath(base_path)

    def load(self, name: str) -> str:
        # Path traversal guard
        if ".." in name or name.startswith("/") or name.startswith("\\"):
            raise ValueError(f"Invalid prompt name: {name}")

        target_path = os.path.abspath(os.path.join(self.base_path, f"{name}.md"))
        
        # Ensure the resolved path remains inside base_path
        if not target_path.startswith(self.base_path):
            raise ValueError(f"Invalid prompt name: {name}")

        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Prompt file not found at: {target_path}")

        with open(target_path, "r", encoding="utf-8") as f:
            return f.read()
