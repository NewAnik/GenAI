from db.models.audit import AuditLog
from db.models.campaigns import Campaign, CampaignRecipient
from db.models.catalog import Category, Product, ProductVariant
from db.models.commerce import Order, OrderItem, Org, Quote, QuoteItem
from db.models.inventory import Inventory, Warehouse
from db.models.offers import Offer, OfferCategory, OfferProduct
from db.models.users import User

ALL_MODELS = [
    Org,
    User,
    Category,
    Product,
    ProductVariant,
    Warehouse,
    Inventory,
    Quote,
    QuoteItem,
    Order,
    OrderItem,
    Offer,
    OfferProduct,
    OfferCategory,
    Campaign,
    CampaignRecipient,
    AuditLog,
]

__all__ = [
    "ALL_MODELS",
    "Org",
    "User",
    "Category",
    "Product",
    "ProductVariant",
    "Warehouse",
    "Inventory",
    "Quote",
    "QuoteItem",
    "Order",
    "OrderItem",
    "Offer",
    "OfferProduct",
    "OfferCategory",
    "Campaign",
    "CampaignRecipient",
    "AuditLog",
]
