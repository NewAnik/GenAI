"""Import every model module so all mapped classes register on `Base.registry`
(needed for string-based forward refs in relationships to resolve correctly)."""
from app.db.base import Base

from app.db.models.org import Org
from app.db.models.users import User
from app.db.models.catalog import (
    Category,
    GiftBox,
    GiftBoxItem,
    Product,
    ProductEmbedding,
    ProductImage,
    ProductVariant,
)
from app.db.models.inventory import Inventory, Supplier, SupplierProduct, Warehouse
from app.db.models.campaigns import Campaign, CampaignRecipient
from app.db.models.commerce import (
    Invoice,
    Order,
    OrderItem,
    Payment,
    Quote,
    QuoteItem,
    Shipment,
)
from app.db.models.branding import BrandingRequest, LogoAsset
from app.db.models.crm import AuditLog, Lead, LeadActivity
from app.db.models.conversation import ConversationSession, RecommendationLog
from app.db.models.storefront import Address, Cart, CartItem

__all__ = [
    "Base",
    "Org",
    "User",
    "Category",
    "Product",
    "ProductVariant",
    "ProductImage",
    "GiftBox",
    "GiftBoxItem",
    "ProductEmbedding",
    "Warehouse",
    "Inventory",
    "Supplier",
    "SupplierProduct",
    "Campaign",
    "CampaignRecipient",
    "Quote",
    "QuoteItem",
    "Order",
    "OrderItem",
    "Payment",
    "Invoice",
    "Shipment",
    "LogoAsset",
    "BrandingRequest",
    "Lead",
    "LeadActivity",
    "AuditLog",
    "ConversationSession",
    "RecommendationLog",
    "Address",
    "Cart",
    "CartItem",
]
