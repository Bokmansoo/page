from pydantic import BaseModel


class ImageTextExtractionResult(BaseModel):
    asset_id: str
    filename: str
    extracted_text: str
    confidence: float
    provider: str
    warnings: list[str] = []


class MockImageTextExtractor:
    provider = "mock"

    def extract(self, asset_id: str, filename: str, file_path: str) -> ImageTextExtractionResult:
        lowered = filename.lower()
        facts: list[str] = []

        if "usb" in lowered or "type_c" in lowered or "usb_c" in lowered:
            facts.append("USB-C charging supported")
        if "4000" in lowered or "mah" in lowered:
            facts.append("Battery capacity 4000mAh")
        if "size" in lowered or "spec" in lowered:
            facts.append("Product specification image")
        if "ingredient" in lowered or "composition" in lowered:
            facts.append("Ingredient or composition table")

        if not facts:
            return ImageTextExtractionResult(
                asset_id=asset_id,
                filename=filename,
                extracted_text="",
                confidence=0.0,
                provider=self.provider,
                warnings=["no_text_detected"],
            )

        return ImageTextExtractionResult(
            asset_id=asset_id,
            filename=filename,
            extracted_text=". ".join(facts),
            confidence=0.66,
            provider=self.provider,
            warnings=[],
        )
