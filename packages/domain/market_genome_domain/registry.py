from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_genome_domain.models import DataSource, Instrument, Timeframe

STANDARD_TIMEFRAMES = [
    {"code": "M1", "seconds": 60, "label": "1 minute", "is_intraday": True},
    {"code": "M5", "seconds": 300, "label": "5 minutes", "is_intraday": True},
    {"code": "M15", "seconds": 900, "label": "15 minutes", "is_intraday": True},
    {"code": "M30", "seconds": 1800, "label": "30 minutes", "is_intraday": True},
    {"code": "H1", "seconds": 3600, "label": "1 hour", "is_intraday": True},
    {"code": "H4", "seconds": 14400, "label": "4 hours", "is_intraday": True},
    {"code": "D1", "seconds": 86400, "label": "1 day", "is_intraday": False},
    {"code": "W1", "seconds": 604800, "label": "1 week", "is_intraday": False},
    {
        "code": "MN1",
        "seconds": None,
        "label": "1 calendar month",
        "is_intraday": False,
    },
]


@dataclass(frozen=True)
class Page:
    limit: int = 100
    offset: int = 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RegistryService:
    def __init__(self, session: Session):
        self.session = session

    def list_instruments(self, symbol: str | None = None, limit: int = 100, offset: int = 0) -> list[Instrument]:
        query = select(Instrument).order_by(Instrument.symbol, Instrument.exchange).limit(limit).offset(offset)
        if symbol:
            query = query.where(Instrument.symbol == symbol)
        return list(self.session.scalars(query))

    def get_instrument(self, instrument_id: str) -> Instrument | None:
        return self.session.get(Instrument, instrument_id)

    def get_instrument_by_symbol(self, symbol: str, exchange: str | None = None) -> Instrument | None:
        query = select(Instrument).where(Instrument.symbol == symbol)
        query = query.where(Instrument.exchange == exchange)
        return self.session.scalar(query)

    def create_instrument(
        self,
        symbol: str,
        name: str | None = None,
        asset_class: str = "other",
        exchange: str | None = None,
        currency: str | None = None,
        timezone: str = "UTC",
        tick_size: float | None = None,
        price_precision: int | None = None,
        volume_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Instrument:
        existing = self.get_instrument_by_symbol(symbol, exchange)
        if existing:
            return existing
        instrument = Instrument(
            symbol=symbol,
            name=name or symbol,
            asset_class=asset_class,
            exchange=exchange,
            currency=currency,
            timezone=timezone,
            tick_size=tick_size,
            price_precision=price_precision,
            volume_type=volume_type,
            instrument_metadata=metadata or {},
        )
        self.session.add(instrument)
        self.session.flush()
        return instrument

    def update_instrument(self, instrument_id: str, **updates: Any) -> Instrument:
        instrument = self.session.get(Instrument, instrument_id)
        if instrument is None:
            raise KeyError("INSTRUMENT_NOT_FOUND")
        allowed = {
            "name",
            "asset_class",
            "exchange",
            "currency",
            "timezone",
            "tick_size",
            "price_precision",
            "volume_type",
            "is_active",
            "instrument_metadata",
        }
        for key, value in updates.items():
            if key in allowed and value is not None:
                setattr(instrument, key, value)
        instrument.updated_at = _utcnow()
        self.session.flush()
        return instrument

    def list_timeframes(self, limit: int = 100, offset: int = 0) -> list[Timeframe]:
        return list(self.session.scalars(select(Timeframe).order_by(Timeframe.code).limit(limit).offset(offset)))

    def get_timeframe(self, timeframe_id: str) -> Timeframe | None:
        return self.session.get(Timeframe, timeframe_id)

    def get_timeframe_by_code(self, code: str) -> Timeframe | None:
        return self.session.scalar(select(Timeframe).where(Timeframe.code == code))

    def create_timeframe(
        self, code: str, seconds: int | None, label: str | None = None, is_intraday: bool | None = None
    ) -> Timeframe:
        existing = self.get_timeframe_by_code(code)
        if existing:
            return existing
        timeframe = Timeframe(
            code=code,
            seconds=seconds,
            label=label or code,
            is_intraday=(seconds is not None and seconds < 86_400) if is_intraday is None else is_intraday,
        )
        self.session.add(timeframe)
        self.session.flush()
        return timeframe

    def seed_standard_timeframes(self) -> list[Timeframe]:
        seeded = [
            self.create_timeframe(
                code=item["code"],
                seconds=item["seconds"],
                label=item["label"],
                is_intraday=item["is_intraday"],
            )
            for item in STANDARD_TIMEFRAMES
        ]
        self.session.commit()
        return seeded

    def list_sources(self, limit: int = 100, offset: int = 0) -> list[DataSource]:
        return list(self.session.scalars(select(DataSource).order_by(DataSource.name).limit(limit).offset(offset)))

    def get_source(self, source_id: str) -> DataSource | None:
        return self.session.get(DataSource, source_id)

    def get_source_by_name(self, name: str) -> DataSource | None:
        return self.session.scalar(select(DataSource).where(DataSource.name == name))

    def create_source(
        self, name: str, source_type: str = "csv", configuration_metadata: dict[str, Any] | None = None
    ) -> DataSource:
        existing = self.get_source_by_name(name)
        if existing:
            return existing
        source = DataSource(
            name=name,
            source_type=source_type,
            configuration_metadata=configuration_metadata or {},
        )
        self.session.add(source)
        self.session.flush()
        return source

