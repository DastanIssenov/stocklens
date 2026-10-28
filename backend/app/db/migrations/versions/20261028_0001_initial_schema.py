"""initial schema: users, tickers, prices (hypertable), news (+pgvector), fundamentals,
predictions, portfolios, positions, trades, trade reviews, fx rates, macro observations

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("locale", sa.String(length=5), server_default="en", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "tickers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("local_symbol", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("exchange", sa.String(length=10), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("sector", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("issuer", sa.String(length=100), nullable=True),
        sa.Column("data_source", sa.String(length=20), nullable=False),
        sa.Column("source_symbol", sa.String(length=30), nullable=False),
        sa.Column("is_liquid", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("currency IN ('USD', 'KZT')", name=op.f("ck_tickers_currency")),
        sa.CheckConstraint(
            "exchange IN ('NASDAQ', 'NYSE', 'KASE', 'AIX', 'LSE')", name=op.f("ck_tickers_exchange")
        ),
        sa.CheckConstraint("market IN ('US', 'KZ')", name=op.f("ck_tickers_market")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickers")),
        sa.UniqueConstraint("symbol", name=op.f("uq_tickers_symbol")),
    )
    op.create_index(op.f("ix_tickers_issuer"), "tickers", ["issuer"], unique=False)
    op.create_index("ix_tickers_market_exchange", "tickers", ["market", "exchange"], unique=False)

    op.create_table(
        "ticker_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=100), nullable=False),
        sa.Column("lang", sa.String(length=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticker_id"], ["tickers.id"], name=op.f("fk_ticker_aliases_ticker_id_tickers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticker_aliases")),
        sa.UniqueConstraint("ticker_id", "alias", name="uq_ticker_aliases_ticker_alias"),
    )

    op.create_table(
        "prices_daily",
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("adj_close", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticker_id"], ["tickers.id"], name=op.f("fk_prices_daily_ticker_id_tickers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("ticker_id", "date", name=op.f("pk_prices_daily")),
    )
    # TimescaleDB hypertable partitioned by date, 1-year chunks.
    op.execute(
        "SELECT create_hypertable('prices_daily', 'date', "
        "chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE)"
    )

    op.create_table(
        "fx_rates",
        sa.Column("pair", sa.String(length=6), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("rate", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.PrimaryKeyConstraint("pair", "date", "source", name=op.f("pk_fx_rates")),
    )

    op.create_table(
        "macro_observations",
        sa.Column("series_id", sa.String(length=40), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("value", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.PrimaryKeyConstraint("series_id", "date", "source", name=op.f("pk_macro_observations")),
    )

    op.create_table(
        "news",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("lang", sa.String(length=2), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("sentiment", sa.Float(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news")),
        sa.UniqueConstraint("url", name=op.f("uq_news_url")),
    )
    op.create_index("ix_news_published_at", "news", ["published_at"], unique=False)

    op.create_table(
        "news_tickers",
        sa.Column("news_id", sa.BigInteger(), nullable=False),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("match_method", sa.String(length=10), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["news_id"], ["news.id"], name=op.f("fk_news_tickers_news_id_news"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["ticker_id"], ["tickers.id"], name=op.f("fk_news_tickers_ticker_id_tickers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("news_id", "ticker_id", name=op.f("pk_news_tickers")),
    )
    op.create_index("ix_news_tickers_ticker_id", "news_tickers", ["ticker_id"], unique=False)

    op.create_table(
        "fundamentals",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Numeric(precision=30, scale=6), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(length=4), nullable=True),
        sa.Column("form", sa.String(length=10), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accession", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticker_id"], ["tickers.id"], name=op.f("fk_fundamentals_ticker_id_tickers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fundamentals")),
        sa.UniqueConstraint("ticker_id", "metric", "period_end", "accession", name="uq_fundamentals_fact"),
    )
    op.create_index(
        "ix_fundamentals_ticker_published", "fundamentals", ["ticker_id", "published_at"], unique=False
    )

    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("horizon", sa.String(length=4), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("predicted_return", sa.Float(), nullable=False),
        sa.Column("prob_up", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("top_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_predictions_confidence_range")
        ),
        sa.CheckConstraint(
            "horizon IN ('1d', '5d', '1m', '3m', '6m', '12m')", name=op.f("ck_predictions_horizon")
        ),
        sa.CheckConstraint("prob_up >= 0 AND prob_up <= 1", name=op.f("ck_predictions_prob_up_range")),
        sa.ForeignKeyConstraint(
            ["ticker_id"], ["tickers.id"], name=op.f("fk_predictions_ticker_id_tickers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_predictions")),
        sa.UniqueConstraint("ticker_id", "model_version", "horizon", "as_of_date", name="uq_predictions_key"),
    )
    op.create_index(
        "ix_predictions_ticker_horizon_asof", "predictions", ["ticker_id", "horizon", "as_of_date"], unique=False
    )

    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cash_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("cash_kzt", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("initial_usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("initial_kzt", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("cash_kzt >= 0", name=op.f("ck_portfolios_cash_kzt_nonneg")),
        sa.CheckConstraint("cash_usd >= 0", name=op.f("ck_portfolios_cash_usd_nonneg")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_portfolios_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolios")),
        sa.UniqueConstraint("user_id", name=op.f("uq_portfolios_user_id")),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("avg_cost", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity >= 0", name=op.f("ck_positions_quantity_nonneg")),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.id"], name=op.f("fk_positions_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ticker_id"], ["tickers.id"], name=op.f("fk_positions_ticker_id_tickers"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_positions")),
        sa.UniqueConstraint("portfolio_id", "ticker_id", name="uq_positions_portfolio_ticker"),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("fee", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("price_source", sa.String(length=30), nullable=False),
        sa.Column("price_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price > 0", name=op.f("ck_trades_price_pos")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_trades_quantity_pos")),
        sa.CheckConstraint("side IN ('buy', 'sell')", name=op.f("ck_trades_side")),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.id"], name=op.f("fk_trades_portfolio_id_portfolios"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["ticker_id"], ["tickers.id"], name=op.f("fk_trades_ticker_id_tickers"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
    )
    op.create_index("ix_trades_portfolio_executed", "trades", ["portfolio_id", "executed_at"], unique=False)

    op.create_table(
        "trade_reviews",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("trade_id", sa.BigInteger(), nullable=False),
        sa.Column("reviewer", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("verdict", sa.String(length=10), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("what_to_watch", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("score BETWEEN 1 AND 10", name=op.f("ck_trade_reviews_score_range")),
        sa.CheckConstraint(
            "verdict IN ('reasonable', 'risky', 'poor')", name=op.f("ck_trade_reviews_verdict")
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"], ["trades.id"], name=op.f("fk_trade_reviews_trade_id_trades"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trade_reviews")),
        sa.UniqueConstraint("trade_id", name=op.f("uq_trade_reviews_trade_id")),
    )


def downgrade() -> None:
    op.drop_table("trade_reviews")
    op.drop_index("ix_trades_portfolio_executed", table_name="trades")
    op.drop_table("trades")
    op.drop_table("positions")
    op.drop_table("portfolios")
    op.drop_index("ix_predictions_ticker_horizon_asof", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("ix_fundamentals_ticker_published", table_name="fundamentals")
    op.drop_table("fundamentals")
    op.drop_index("ix_news_tickers_ticker_id", table_name="news_tickers")
    op.drop_table("news_tickers")
    op.drop_index("ix_news_published_at", table_name="news")
    op.drop_table("news")
    op.drop_table("macro_observations")
    op.drop_table("fx_rates")
    op.drop_table("prices_daily")
    op.drop_table("ticker_aliases")
    op.drop_index("ix_tickers_market_exchange", table_name="tickers")
    op.drop_index(op.f("ix_tickers_issuer"), table_name="tickers")
    op.drop_table("tickers")
    op.drop_table("users")
