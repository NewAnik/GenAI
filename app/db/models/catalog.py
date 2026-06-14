"""Catalog tables: categories, products, variants, images, gift boxes, embeddings reference."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin


class Category(CreatedAtMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str | None] = mapped_column(String)
    slug: Mapped[str | None] = mapped_column(String)

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id")


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(String)
    base_price: Mapped[Decimal | None] = mapped_column(Numeric)
    min_order_quantity: Mapped[int | None] = mapped_column(Integer)
    is_customizable: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str | None] = mapped_column(String)

    category: Mapped["Category | None"] = relationship()
    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product")
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product", order_by="ProductImage.display_order"
    )


class ProductVariant(CreatedAtMixin, Base):
    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    sku: Mapped[str | None] = mapped_column(String, unique=True)
    color: Mapped[str | None] = mapped_column(String)
    size: Mapped[str | None] = mapped_column(String)
    price: Mapped[Decimal | None] = mapped_column(Numeric)

    product: Mapped["Product | None"] = relationship(back_populates="variants")


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    image_url: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int | None] = mapped_column(Integer)

    product: Mapped["Product | None"] = relationship(back_populates="images")


class GiftBox(Base):
    __tablename__ = "gift_boxes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric)

    items: Mapped[list["GiftBoxItem"]] = relationship(back_populates="gift_box")


class GiftBoxItem(Base):
    __tablename__ = "gift_box_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    gift_box_id: Mapped[int | None] = mapped_column(ForeignKey("gift_boxes.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int | None] = mapped_column(Integer)

    gift_box: Mapped["GiftBox | None"] = relationship(back_populates="items")
    product: Mapped["Product | None"] = relationship()


class ProductEmbedding(CreatedAtMixin, Base):
    """Maps a product to its vector point in Qdrant (`embedding_id` = Qdrant point UUID)."""

    __tablename__ = "product_embeddings"

    # NOTE: the source schema defines no primary key / unique constraint on this table.
    # SQLAlchemy requires a primary_key for ORM mapping — `product_id` is the natural
    # unique key in practice; a recommended additive migration is noted in the embeddings
    # job (app/jobs/embed_products.py) to add a real UNIQUE constraint for true upserts.
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), primary_key=True)
    embedding_id: Mapped[str | None] = mapped_column(String)
