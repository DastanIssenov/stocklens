"""Mock ML implementations used until the real models exist (GPU phase).

* `MockPredictionProvider` — deterministic demo numbers: a hash of (symbol, date, horizon) nudged by
  the real recent momentum. Every result has `is_demo=True` so the UI shows a "Demo" badge.
* `MockTradeReviewer` — transparent rule-based review: concentration, volatility, recent price move,
  liquidity, cash usage, agreement with the (demo) prediction.
"""

from __future__ import annotations

import hashlib
import math

from app.ml_interface.base import (
    HORIZON_DAYS,
    FeatureContribution,
    PredictionContext,
    PredictionProvider,
    PredictionResult,
    TradeContext,
    TradeReviewer,
    TradeReviewOutput,
)
from app.services import analytics

MOCK_MODEL_VERSION = "mock-0.1"


def _unit_hash(*parts: object) -> float:
    """Deterministic pseudo-random number in [0, 1)."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class MockPredictionProvider(PredictionProvider):
    name = "mock"
    is_demo = True

    async def predict(self, ctx: PredictionContext) -> list[PredictionResult]:
        closes = ctx.closes
        daily_vol = analytics.volatility(closes, 60, annualize=False) or (
            0.02 if ctx.market == "US" else 0.025
        )
        mom20 = analytics.simple_return(closes, 20) or 0.0
        ret5 = analytics.simple_return(closes, 5) or 0.0
        rsi14 = analytics.rsi(closes, 14)
        vol20 = analytics.volatility(closes, 20)
        out: list[PredictionResult] = []
        for h in ctx.horizons:
            days = HORIZON_DAYS[h]
            scale = daily_vol * math.sqrt(days)
            u = _unit_hash(ctx.symbol, ctx.as_of_date.isoformat(), h)
            # demo signal: half noise, half (bounded) momentum — looks plausible, means nothing
            momentum_part = 0.5 * math.tanh(mom20 * 5)
            noise_part = u - 0.5
            drift = 0.07 * days / 252  # small positive equity drift
            pred = drift + scale * 0.6 * (momentum_part + noise_part)
            prob_up = _clip(_sigmoid(1.6 * pred / max(scale, 1e-6)), 0.05, 0.95)
            conf = 0.25 + 0.6 * abs(prob_up - 0.5) + 0.1 * _unit_hash("conf", ctx.symbol, h)
            if not ctx.is_liquid:
                conf *= 0.7
            conf = _clip(conf, 0.05, 0.75)  # demo predictions never claim high confidence
            feats = [
                FeatureContribution(
                    name="momentum_20d",
                    value=round(mom20, 4),
                    contribution=round(0.6 * momentum_part * scale, 5),
                ),
                FeatureContribution(
                    name="noise_demo", value=None, contribution=round(0.6 * noise_part * scale, 5)
                ),
                FeatureContribution(name="return_5d", value=round(ret5, 4), contribution=0.0),
                FeatureContribution(
                    name="volatility_20d", value=None if vol20 is None else round(vol20, 4), contribution=0.0
                ),
                FeatureContribution(
                    name="rsi_14", value=None if rsi14 is None else round(rsi14, 2), contribution=0.0
                ),
            ]
            feats.sort(key=lambda f: abs(f.contribution), reverse=True)
            out.append(
                PredictionResult(
                    symbol=ctx.symbol,
                    horizon=h,
                    horizon_days=days,
                    as_of_date=ctx.as_of_date,
                    predicted_return=round(pred, 6),
                    prob_up=round(prob_up, 4),
                    confidence=round(conf, 4),
                    top_features=feats,
                    model_version=MOCK_MODEL_VERSION,
                    is_demo=True,
                )
            )
        return out


# ---------------------------------------------------------------- trade reviewer
_T: dict[str, dict[str, str]] = {
    "weight": {
        "en": "After this trade {symbol} is {w:.0%} of your portfolio.",
        "ru": "После сделки {symbol} составляет {w:.0%} портфеля.",
    },
    "concentrated": {
        "en": "High concentration: more than {lim:.0%} of the portfolio in one stock.",
        "ru": "Высокая концентрация: более {lim:.0%} портфеля в одной бумаге.",
    },
    "very_concentrated": {
        "en": "Very high concentration: a single stock dominates the portfolio.",
        "ru": "Очень высокая концентрация: одна бумага доминирует в портфеле.",
    },
    "diversified": {
        "en": "Position size is moderate relative to the portfolio.",
        "ru": "Размер позиции умеренный относительно портфеля.",
    },
    "vol": {
        "en": "20-day annualised volatility is {v:.0%}.",
        "ru": "Годовая волатильность за 20 дней — {v:.0%}.",
    },
    "high_vol": {
        "en": "Volatility is high, so the price can swing strongly in days.",
        "ru": "Волатильность высокая: цена может сильно меняться за несколько дней.",
    },
    "move5": {
        "en": "The price moved {r:+.1%} over the last 5 trading days.",
        "ru": "За последние 5 торговых дней цена изменилась на {r:+.1%}.",
    },
    "chasing": {
        "en": "Buying after a sharp rally: risk of chasing momentum near a short-term top.",
        "ru": "Покупка после резкого роста: риск войти на краткосрочном пике.",
    },
    "falling_knife": {
        "en": 'Buying after a sharp fall: the decline may continue ("catching a falling knife").',
        "ru": "Покупка после резкого падения: снижение может продолжиться.",
    },
    "panic_sell": {
        "en": "Selling after a sharp drop can lock in a loss right before a rebound.",
        "ru": "Продажа после резкого падения может зафиксировать убыток перед отскоком.",
    },
    "take_profit": {
        "en": "Selling after a strong rise locks in gains.",
        "ru": "Продажа после сильного роста фиксирует прибыль.",
    },
    "illiquid": {
        "en": "The stock trades thinly; real orders could move the price and be hard to exit.",
        "ru": "Бумага малоликвидна: реальная заявка может сдвинуть цену, выйти будет сложно.",
    },
    "big_vs_volume": {
        "en": "Order size is large compared with the average daily volume.",
        "ru": "Объём заявки велик по сравнению со средним дневным объёмом торгов.",
    },
    "cash_drain": {
        "en": "This trade uses almost all remaining cash in {cur}.",
        "ru": "Сделка использует почти весь оставшийся кэш в {cur}.",
    },
    "pred_agree": {
        "en": "The demo 5-day model leans the same way (P(up) = {p:.0%}); demo models are not reliable.",
        "ru": "Демо-модель на 5 дней указывает в ту же сторону (P(рост) = {p:.0%}); демо-модели ненадёжны.",
    },
    "pred_disagree": {
        "en": "The demo 5-day model leans the other way (P(up) = {p:.0%}); demo models are not reliable.",
        "ru": "Демо-модель на 5 дней указывает в обратную сторону (P(рост) = {p:.0%}); "
        "демо-модели ненадёжны.",
    },
    "realized": {
        "en": "Realised P&L on this sale: {pnl:,.2f} {cur}.",
        "ru": "Зафиксированный результат по продаже: {pnl:,.2f} {cur}.",
    },
    "fee": {
        "en": "Commission paid: {fee:,.2f} {cur}.",
        "ru": "Уплаченная комиссия: {fee:,.2f} {cur}.",
    },
    "executed": {
        "en": "Paper {side} of {qty:g} {symbol} at {price:,.2f} {cur}.",
        "ru": "Учебная сделка ({side}): {qty:g} {symbol} по {price:,.2f} {cur}.",
    },
    "fx": {
        "en": "{cur} asset: returns in USD also depend on the USD/KZT rate.",
        "ru": "Актив в {cur}: доходность в долларах зависит и от курса USD/KZT.",
    },
    "market_risk": {
        "en": "General market risk: prices can fall regardless of company news.",
        "ru": "Общий рыночный риск: цены могут упасть независимо от новостей компании.",
    },
    "watch_news": {
        "en": "Company news and upcoming earnings / reporting dates for {symbol}.",
        "ru": "Новости компании и ближайшие даты отчётности {symbol}.",
    },
    "watch_weight": {
        "en": "Keep any single position below {lim:.0%} of the portfolio.",
        "ru": "Держите долю одной позиции ниже {lim:.0%} портфеля.",
    },
    "watch_stop": {
        "en": "Decide in advance at what loss you would exit (e.g. {stop:.0%} below entry).",
        "ru": "Заранее решите, при каком убытке выйдете из позиции (например, {stop:.0%} ниже входа).",
    },
    "watch_fx": {"en": "The USD/KZT exchange rate.", "ru": "Курс доллара к тенге."},
    "watch_oil": {
        "en": "Oil prices (Brent) — important for the Kazakh market.",
        "ru": "Цены на нефть (Brent) — важны для рынка Казахстана.",
    },
    "sum_reasonable": {
        "en": "The trade looks reasonable for a paper portfolio; main risks are listed below.",
        "ru": "Сделка выглядит разумной для учебного портфеля; основные риски ниже.",
    },
    "sum_risky": {
        "en": "The trade is risky: several warning signs were found.",
        "ru": "Сделка рискованная: найдено несколько тревожных признаков.",
    },
    "sum_poor": {
        "en": "The trade looks poor from a risk-management point of view.",
        "ru": "С точки зрения управления рисками сделка выглядит неудачной.",
    },
}


def _t(key: str, lang: str, **kw: object) -> str:
    entry = _T[key]
    template = entry.get(lang) or entry.get("ru" if lang == "kk" else "en") or entry["en"]
    return template.format(**kw)


class MockTradeReviewer(TradeReviewer):
    """Rule-based reviewer. Deterministic and explainable; no LLM needed."""

    name = "mock"
    model = "rules-0.1"

    CONCENTRATION = 0.25
    HIGH_CONCENTRATION = 0.40
    HIGH_VOL = 0.45
    SHARP_MOVE = 0.08

    async def review(self, ctx: TradeContext, lang: str = "en") -> TradeReviewOutput:
        score = 8.0
        reasons: list[str] = []
        risks: list[str] = []
        watch: list[str] = []
        sym = ctx.symbol

        # 1. concentration (only meaningful for buys; sells reduce it)
        reasons.append(_t("weight", lang, symbol=sym, w=ctx.position_weight_after))
        if ctx.side == "buy":
            if ctx.position_weight_after > self.HIGH_CONCENTRATION:
                score -= 3
                risks.append(_t("very_concentrated", lang))
            elif ctx.position_weight_after > self.CONCENTRATION:
                score -= 1.5
                risks.append(_t("concentrated", lang, lim=self.CONCENTRATION))
            else:
                reasons.append(_t("diversified", lang))
            if ctx.cash_left_ratio < 0.05:
                score -= 1
                risks.append(_t("cash_drain", lang, cur=ctx.currency))

        # 2. volatility
        if ctx.volatility_20d is not None:
            reasons.append(_t("vol", lang, v=ctx.volatility_20d))
            if ctx.volatility_20d > self.HIGH_VOL:
                score -= 1.5 if ctx.side == "buy" else 0.5
                risks.append(_t("high_vol", lang))

        # 3. recent price move
        if ctx.return_5d is not None:
            reasons.append(_t("move5", lang, r=ctx.return_5d))
            if ctx.side == "buy" and ctx.return_5d > self.SHARP_MOVE:
                score -= 1
                risks.append(_t("chasing", lang))
            elif ctx.side == "buy" and ctx.return_5d < -self.SHARP_MOVE:
                score -= 1
                risks.append(_t("falling_knife", lang))
            elif ctx.side == "sell" and ctx.return_5d < -self.SHARP_MOVE:
                score -= 1
                risks.append(_t("panic_sell", lang))
            elif ctx.side == "sell" and ctx.return_5d > self.SHARP_MOVE:
                reasons.append(_t("take_profit", lang))

        # 4. liquidity
        if not ctx.is_liquid:
            score -= 1
            risks.append(_t("illiquid", lang))
        if ctx.avg_volume_20d and ctx.quantity > 0.1 * ctx.avg_volume_20d:
            score -= 1
            risks.append(_t("big_vs_volume", lang))

        # 5. agreement with the (demo) model — small weight on purpose
        if ctx.prediction_5d_prob_up is not None:
            p = ctx.prediction_5d_prob_up
            agrees = (ctx.side == "buy" and p >= 0.5) or (ctx.side == "sell" and p < 0.5)
            reasons.append(_t("pred_agree" if agrees else "pred_disagree", lang, p=p))
            score += 0.25 if agrees else -0.25

        if ctx.side == "sell" and ctx.realized_pnl is not None:
            reasons.append(_t("realized", lang, pnl=ctx.realized_pnl, cur=ctx.currency))
        fillers = [
            _t("fee", lang, fee=ctx.fee, cur=ctx.currency),
            _t(
                "executed",
                lang,
                side=ctx.side,
                qty=ctx.quantity,
                symbol=sym,
                price=ctx.price,
                cur=ctx.currency,
            ),
        ]
        while len(reasons) < 3 and fillers:
            reasons.append(fillers.pop(0))
        if ctx.currency == "KZT" and len(risks) < 5:
            risks.append(_t("fx", lang, cur=ctx.currency))
        if not risks:
            risks.append(_t("market_risk", lang))

        watch.append(_t("watch_news", lang, symbol=sym))
        if ctx.side == "buy":
            if ctx.position_weight_after > self.CONCENTRATION:
                watch.append(_t("watch_weight", lang, lim=self.CONCENTRATION))
            vol = ctx.volatility_20d or 0.3
            watch.append(_t("watch_stop", lang, stop=min(0.25, max(0.05, round(vol / 4, 2)))))
        if ctx.market == "KZ":
            watch.append(_t("watch_fx", lang))
            watch.append(_t("watch_oil", lang))

        final = round(_clip(score, 1, 10))
        verdict = "reasonable" if final >= 7 else "risky" if final >= 4 else "poor"
        return TradeReviewOutput(
            verdict=verdict,
            score=final,
            summary=_t(f"sum_{verdict}", lang),
            reasons=reasons[:5],
            risks=risks[:5],
            what_to_watch=watch[:5],
        )
