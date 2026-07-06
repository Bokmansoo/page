from pydantic import BaseModel, Field
from typing import List, Optional

class ProductIntakeInput(BaseModel):
    urls: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    asset_ids: List[str] = Field(default_factory=list)
    reference_urls: List[str] = Field(default_factory=list)
    competitor_urls: List[str] = Field(default_factory=list)

def clean_and_deduplicate_urls(urls: List[str]) -> List[str]:
    cleaned = []
    seen = set()
    for url in urls:
        trimmed = url.strip()
        if trimmed and trimmed not in seen:
            cleaned.append(trimmed)
            seen.add(trimmed)
    return cleaned

def clean_ids(ids: List[str]) -> List[str]:
    cleaned = []
    seen = set()
    for i in ids:
        trimmed = i.strip()
        if trimmed and trimmed not in seen:
            cleaned.append(trimmed)
            seen.add(trimmed)
    return cleaned

def normalize_intake_input(input_data: ProductIntakeInput) -> ProductIntakeInput:
    urls = clean_and_deduplicate_urls(input_data.urls)
    reference_urls = clean_and_deduplicate_urls(input_data.reference_urls)
    competitor_urls = clean_and_deduplicate_urls(input_data.competitor_urls)
    asset_ids = clean_ids(input_data.asset_ids)
    
    description = input_data.description
    if description is not None:
        description = description.strip()
        if not description:
            description = None
            
    # Check if normalized data is completely empty
    if not urls and not reference_urls and not competitor_urls and not asset_ids and description is None:
        raise ValueError("Product intake input cannot be completely empty")
        
    return ProductIntakeInput(
        urls=urls,
        description=description,
        asset_ids=asset_ids,
        reference_urls=reference_urls,
        competitor_urls=competitor_urls
    )
