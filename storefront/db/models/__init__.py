"""Re-exports every in-scope model and an `ALL_MODELS` list (used by test fixtures to
create/drop tables against a throwaway Postgres). Import order matters: each module imports
only the models it directly depends on, so listing them here in dependency order is enough
— no whole-package-import forward-ref trick needed (unlike SQLAlchemy's declarative
registry), since none of the in-scope models are mutually/self-referential."""
from db.models.audit import AuditLog
from db.models.catalog import GiftBox, GiftBoxImage, GiftBoxItem, Product, ProductVariant
from db.models.commerce import Invoice, Order, OrderItem, Payment, Shipment
from db.models.inventory import Inventory
from db.models.storefront import Address, Cart, CartItem
from db.models.users import User

ALL_MODELS = [
    Product,
    ProductVariant,
    GiftBox,
    GiftBoxItem,
    GiftBoxImage,
    User,
    Address,
    Cart,
    CartItem,
    Inventory,
    Order,
    OrderItem,
    Payment,
    Invoice,
    Shipment,
    AuditLog,
]

__all__ = [
    "ALL_MODELS",
    "Product",
    "ProductVariant",
    "GiftBox",
    "GiftBoxItem",
    "GiftBoxImage",
    "User",
    "Address",
    "Cart",
    "CartItem",
    "Inventory",
    "Order",
    "OrderItem",
    "Payment",
    "Invoice",
    "Shipment",
    "AuditLog",
]
