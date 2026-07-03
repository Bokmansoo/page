import os
from enum import Enum


class GenerationMode(str, Enum):
    MOCK = "mock"
    REAL = "real"


def resolve_generation_mode() -> GenerationMode:
    mode_str = os.getenv("SELLFORM_GENERATION_MODE", "mock").lower()
    if mode_str == "real":
        return GenerationMode.REAL
    return GenerationMode.MOCK
