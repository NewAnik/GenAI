"""Serverless storefront API (auth/cart/orders/payments) — Lambda + API Gateway + Cognito.

Deliberately independent of `app/` (the FastAPI + LangGraph agent backend): no FastAPI,
no Pydantic, no SQLAlchemy, no LangChain/LangGraph/OpenAI/Qdrant/Tavily dependency anywhere
in this package. It reuses only the Postgres schema those tables already live in (see
alembic/), not any code from `app/`. See the migration plan for the full rationale.
"""
