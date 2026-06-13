from .amazon_sa import AmazonSAScraper
from .noon import NoonScraper
from .jarir import JarirScraper
from .extra import ExtraScraper
from .sharaf_dg import SharafDGScraper

ALL_SCRAPERS = [
    AmazonSAScraper,
    NoonScraper,
    JarirScraper,
    ExtraScraper,
    SharafDGScraper,
]
