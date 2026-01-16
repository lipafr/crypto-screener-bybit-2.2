from datetime import datetime, timezone
from typing import Optional

from telegram.error import TelegramError

from backend.screener.coingecko import (
    format_large_number,
    format_time_ago,
)


class TelegramNotifier:
    def __init__(self, bot, chat_id: str, logger):
        self.bot = bot
        self.chat_id = chat_id
        self.logger = logger

    # ============================================================
    # Generic send
    # ============================================================
    async def send_message(
        self,
        message: str,
        parse_mode: str = "HTML",
    ) -> bool:
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )

            self.logger.info("✅ Telegram message sent")
            return True

        except TelegramError as e:
            self.logger.error(f"❌ Telegram error: {e}", exc_info=True)
            return False

        except Exception as e:
            self.logger.error(f"❌ Unexpected error: {e}", exc_info=True)
            return False

    # ============================================================
    # CoinGecko formatter
    # ============================================================
    def _format_coingecko_data(self, cg_data: dict) -> str:
        if not cg_data:
            return ""

        try:
            lines = ["\n──────────────────────────────"]
            lines.append("📊 <b>CoinGecko Data:</b>")

            market_cap = cg_data.get("market_cap")
            market_cap_rank = cg_data.get("market_cap_rank")

            if market_cap and market_cap_rank:
                lines.append(
                    f"💎 Market Cap: {format_large_number(market_cap)} (#{market_cap_rank})"
                )

            mc_change = cg_data.get("market_cap_change_percentage_24h")
            if mc_change is not None:
                emoji = "📈" if mc_change > 0 else "📉"
                lines.append(f"{emoji} 24h: {mc_change:+.2f}%")

            ath = cg_data.get("ath")
            ath_change = cg_data.get("ath_change_percentage")
            ath_date = cg_data.get("ath_date")

            if ath and ath_change is not None:
                lines.append(f"🏔️ ATH: ${ath:.4f} ({ath_change:+.1f}%)")
                if ath_date:
                    ath_dt = datetime.fromtimestamp(ath_date, tz=timezone.utc)
                    lines.append(f"📅 {ath_dt.strftime('%Y-%m-%d')}")

            circulating = cg_data.get("circulating_supply")
            max_supply = cg_data.get("max_supply")

            if circulating:
                supply = f"🪙 Supply: {format_large_number(circulating)}"
                if max_supply:
                    percent = (circulating / max_supply) * 100
                    supply += f" / {format_large_number(max_supply)} ({percent:.1f}%)"
                lines.append(supply)

            volume = cg_data.get("total_volume_24h")
            if volume and market_cap:
                ratio = (volume / market_cap) * 100
                emoji = "🔥" if ratio > 10 else "📊"
                lines.append(f"{emoji} Volume/MCap: {ratio:.1f}%")

            cg_price = cg_data.get("current_price")
            bybit_price = cg_data.get("bybit_price")

            if cg_price and bybit_price:
                diff = ((bybit_price - cg_price) / cg_price) * 100
                if abs(diff) > 0.5:
                    lines.append(
                        f"ℹ️ Price diff: {diff:+.1f}% (CG: ${cg_price:.4f})"
                    )

            cached_at = cg_data.get("cached_at")
            if cached_at:
                age = int(datetime.now(timezone.utc).timestamp()) - cached_at
                lines.append(f"🕐 Data: {format_time_ago(age)}")

            coingecko_id = cg_data.get("coingecko_id")
            if coingecko_id:
                lines.append(
                    f"🔗 <a href='https://www.coingecko.com/en/coins/{coingecko_id}'>CoinGecko</a>"
                )

            return "\n".join(lines)

        except Exception as e:
            self.logger.error(
                f"❌ Error formatting CoinGecko data: {e}", exc_info=True
            )
            return ""

    # ============================================================
    # Price change message
    # ============================================================
    def _format_price_change_message(
        self,
        filter_name: str,
        symbol: str,
        market: str,
        data: dict,
        url: str,
        cg_data: Optional[dict] = None,
    ) -> str:
        price_change = data["price_change_percent"]
        price_from = data["price_from"]
        price_to = data["price_to"]
        volume_period = data["volume_period"]
        volume_24h = data["volume_24h"]

        first_ts = data.get("first_candle_timestamp")
        last_ts = data.get("last_candle_timestamp")

        emoji = "🚀" if price_change > 0 else "📉"
        market_name = "Spot" if market == "spot" else "Futures"
        event_time = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")

        message = f"""{emoji} Сработал фильтр: "{filter_name}"
⏰ Время: {event_time}

💰 Пара: {symbol}
📊 Рынок: {market_name}

📈 Изменение: {price_change:+.2f}%
💵 Цена: ${price_from:.4f} → ${price_to:.4f}
📦 Объём: ${volume_period:,.0f}
📊 Объём 24ч: ${volume_24h:,.0f}"""

        if first_ts and last_ts:
            first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
            last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)
            message += (
                f"\n\n📊 Диапазон расчёта:"
                f"\n🕐 Начало: {first_dt.strftime('%H:%M')} | ${price_from:.4f}"
                f"\n🕐 Конец: {last_dt.strftime('%H:%M')} | ${price_to:.4f}"
            )

        message += f"\n\n🔗 Bybit: {url}"

        if cg_data:
            cg_data["bybit_price"] = price_to
            message += self._format_coingecko_data(cg_data)

        return message

    # ============================================================
    # Volume spike message
    # ============================================================
    def _format_volume_spike_message(
        self,
        filter_name: str,
        symbol: str,
        market: str,
        data: dict,
        url: str,
        cg_data: Optional[dict] = None,
    ) -> str:
        spike = data["spike_coefficient"]
        current = data["current_volume"]
        avg = data["average_volume"]
        volume_24h = data["volume_24h"]

        price_change = data.get("price_change_percent")
        price_from = data.get("price_from")
        price_to = data.get("price_to")

        first_ts = data.get("first_candle_timestamp")
        last_ts = data.get("last_candle_timestamp")

        market_name = "Spot" if market == "spot" else "Futures"
        event_time = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")

        message = f"""🔥 Сработал фильтр: "{filter_name}"
⏰ Время: {event_time}

💰 Пара: {symbol}
📊 Рынок: {market_name}

📈 Всплеск объёма: {spike:.1f}x
📦 Текущий объём: ${current:,.0f}
📊 Средний объём: ${avg:,.0f}
📊 Объём 24ч: ${volume_24h:,.0f}"""

        if price_change is not None and price_from and price_to:
            message += f"\n\n💵 Цена: ${price_from:.4f} → ${price_to:.4f} ({price_change:+.2f}%)"

            if first_ts and last_ts:
                first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
                last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)
                message += (
                    f"\n📊 Диапазон расчёта:"
                    f"\n🕐 Начало: {first_dt.strftime('%H:%M')} | ${price_from:.4f}"
                    f"\n🕐 Конец: {last_dt.strftime('%H:%M')} | ${price_to:.4f}"
                )

        message += f"\n\n🔗 Bybit: {url}"

        if cg_data and price_to:
            cg_data["bybit_price"] = price_to
            message += self._format_coingecko_data(cg_data)

        return message

    # ============================================================
    # Public API
    # ============================================================
    async def send_trigger_notification(
        self,
        filter_name: str,
        filter_type: str,
        symbol: str,
        market: str,
        data: dict,
        url: str,
        cg_data: Optional[dict] = None,
    ) -> bool:
        try:
            if filter_type == "price_change":
                message = self._format_price_change_message(
                    filter_name, symbol, market, data, url, cg_data
                )
            elif filter_type == "volume_spike":
                message = self._format_volume_spike_message(
                    filter_name, symbol, market, data, url, cg_data
                )
            else:
                self.logger.error(f"Unknown filter type: {filter_type}")
                return False

            return await self.send_message(message)

        except Exception as e:
            self.logger.error(
                f"❌ Error sending trigger notification: {e}", exc_info=True
            )
            return False


# ============================================================
# Factory
# ============================================================
def create_notifier(bot, chat_id: str, logger) -> TelegramNotifier:
    return TelegramNotifier(bot=bot, chat_id=chat_id, logger=logger)
