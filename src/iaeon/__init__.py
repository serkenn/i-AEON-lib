"""iaeon - iAEON authentication, digital receipt, and food inventory toolkit"""

__version__ = "0.1.0"

from iaeon.auth import IAEONAuth, IAEONAuthError
from iaeon.inventory.db import FoodInventoryDB
from iaeon.receipt.client import IAEONReceiptClient

__all__ = [
    "IAEONAuth",
    "IAEONAuthError",
    "IAEONReceiptClient",
    "FoodInventoryDB",
]
