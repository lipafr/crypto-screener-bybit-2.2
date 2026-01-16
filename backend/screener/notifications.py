"""
Telegram Notifications - WITH TEST METHOD
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Formats and sends Telegram notifications.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from telegram.error import TelegramError


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
    # TEST METHOD (FOR API)
    # ============================================================
    async def send_test_message(self) -> bool:
        """
        Send test notification to verify Telegram configuration.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            message = (
                "✅ <b>Test Notification</b>\n\n"
                "Crypto Screener is working!\n"
                f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
            
            return await self.send_message(message)
            
        except Exception as e:
            self.logger.error(f"❌ Error sending test message: {e}", exc_info=True)
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

            # Market cap
            market_cap = cg_data.get("market_cap")
            market_cap_rank = cg_data.get("market_cap_rank")

            if market_cap and market_cap_rank:
                from .coingecko import format_large_number
                lines.append(
                    f"💎 Market Cap: {format_large_number(market_cap)} (#{market_cap_rank})"
                )

            # Volume 24h
            volume_24h = cg_data.get("total_volume")
            if volume_24h:
                from .coingecko import format_large_number
                lines.append(f"📊 Volume 24h: {format_large_number(volume_24h)}")

            # Price changes
            price_change_24h = cg_data.get("price_change_percentage_24h")
            if price_change_24h is not None:
                emoji = "📈" if price_change_24h > 0 else "📉"
                lines.append(f"{emoji} 24h Change: {price_change_24h:+.2f}%")

            # All-time high
            ath = cg_data.get("ath")
            ath_date = cg_data.get("ath_date")
            bybit_price = cg_data.get("bybit_price")

            if ath and ath_date and bybit_price:
                from .coingecko import format_time_ago
                distance_from_ath = ((bybit_price - ath) / ath) * 100
                lines.append(
                    f"🔴 ATH: ${ath:.4f} ({format_time_ago(ath_date)})\n"
                    f"     Distance: {distance_from_ath:+.2f}%"
                )

            return "\n".join(lines)

        except Exception as e:
            self.logger.error(f"Error formatting CoinGecko data: {e}")
            return ""

    # ============================================================
    # Filter notification formatters
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
        """Format price change notification."""
        market_emoji = "💰" if market == "spot" else "📈"
        market_name = "Spot" if market == "spot" else "Futures"

        price_change = data.get("price_change_percent", 0)
        change_emoji = "🚀" if price_change > 0 else "📉"

        message = f"""
🚨 <b>Filter Triggered!</b>

📋 Filter: {filter_name}
{market_emoji} Market: {market_name}
💱 Pair: {symbol}

{change_emoji} <b>Price Change: {price_change:+.2f}%</b>

💵 Price:
   From: ${data.get('price_from', 0):.4f}
   To: ${data.get('price_to', 0):.4f}

📦 Period Volume: ${data.get('volume_period', 0):,.0f}
📊 24h Volume: ${data.get('volume_24h', 0):,.0f}
        """

        # Add candle range if available
        first_candle = data.get("first_candle_at")
        last_candle = data.get("last_candle_at")

        if first_candle and last_candle:
            from datetime import datetime, timezone
            first_dt = datetime.fromtimestamp(first_candle, tz=timezone.utc)
            last_dt = datetime.fromtimestamp(last_candle, tz=timezone.utc)
            price_from = data.get("price_from", 0)
            price_to = data.get("price_to", 0)

            if price_from and price_to:
                message += (
                    f"\n📊 Calculation Range:"
                    f"\n🕐 Start: {first_dt.strftime('%H:%M')} | ${price_from:.4f}"
                    f"\n🕐 End: {last_dt.strftime('%H:%M')} | ${price_to:.4f}"
                )

        message += f"\n\n🔗 Bybit: {url}"

        if cg_data and data.get('price_to'):
            cg_data["bybit_price"] = data.get('price_to')
            message += self._format_coingecko_data(cg_data)

        return message

    def _format_volume_spike_message(
        self,
        filter_name: str,
        symbol: str,
        market: str,
        data: dict,
        url: str,
        cg_data: Optional[dict] = None,
    ) -> str:
        """Format volume spike notification."""
        market_emoji = "💰" if market == "spot" else "📈"
        market_name = "Spot" if market == "spot" else "Futures"

        spike_percent = data.get("volume_spike_percent", 0)

        message = f"""
🚨 <b>Filter Triggered!</b>

📋 Filter: {filter_name}
{market_emoji} Market: {market_name}
💱 Pair: {symbol}

📊 <b>Volume Spike: {spike_percent:+.2f}%</b>

📦 Period Volume: ${data.get('volume_period', 0):,.0f}
📈 Average Volume: ${data.get('volume_avg', 0):,.0f}
📊 24h Volume: ${data.get('volume_24h', 0):,.0f}

💵 Current Price: ${data.get('price_to', 0):.4f}
        """

        # Add candle range if available
        first_candle = data.get("first_candle_at")
        last_candle = data.get("last_candle_at")

        if first_candle and last_candle:
            from datetime import datetime, timezone
            first_dt = datetime.fromtimestamp(first_candle, tz=timezone.utc)
            last_dt = datetime.fromtimestamp(last_candle, tz=timezone.utc)
            price_from = data.get("price_from", 0)
            price_to = data.get("price_to", 0)

            if price_from and price_to:
                message += (
                    f"\n📊 Calculation Range:"
                    f"\n🕐 Start: {first_dt.strftime('%H:%M')} | ${price_from:.4f}"
                    f"\n🕐 End: {last_dt.strftime('%H:%M')} | ${price_to:.4f}"
                )

        message += f"\n\n🔗 Bybit: {url}"

        if cg_data and data.get('price_to'):
            cg_data["bybit_price"] = data.get('price_to')
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
        """
        Send filter trigger notification.
        
        Args:
            filter_name: Name of the filter
            filter_type: 'price_change' or 'volume_spike'
            symbol: Trading pair
            market: 'spot' or 'futures'
            data: Trigger data dict
            url: Bybit URL
            cg_data: Optional CoinGecko data
        
        Returns:
            True if successful, False otherwise
        """
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
    """Create TelegramNotifier instance."""
    return TelegramNotifier(bot=bot, chat_id=chat_id, logger=logger)