"""Deal data model."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Deal:
    site_name: str          # "Amazon.sa", "Noon", "Jarir", "Extra", "SharafDG"
    title: str
    url: str
    sale_price: float       # SAR
    original_price: float   # SAR  (0 if unknown)
    discount_percent: float # 0–100
    category: str
    image_url: str = ""
    deal_id: str = ""       # unique key for deduplication
    found_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        # Auto-derive discount if missing
        if self.discount_percent == 0 and self.original_price > 0 and self.sale_price < self.original_price:
            self.discount_percent = round(
                (1 - self.sale_price / self.original_price) * 100, 1
            )

        # Auto-derive deal_id from URL if not provided
        if not self.deal_id:
            self.deal_id = self.url.split("?")[0].rstrip("/")
