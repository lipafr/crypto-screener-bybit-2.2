/**
 * Charts.js - Модуль для работы с графиками
 * 
 * Использует Lightweight Charts для отображения свечных графиков
 * и WebSocket для real-time обновлений.
 */

const API_BASE = 'http://localhost:8000/api';
const WS_BASE = 'ws://localhost:8000';

class ChartManager {
    constructor() {
        this.chart = null;
        this.candlestickSeries = null;
        this.volumeSeries = null;
        this.currentSymbol = null;
        this.currentMarket = null;
        this.currentTimeframe = '1m';
        this.websocket = null;
        this.symbols = [];
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.triggerMarkers = [];
        
        this.init();
    }
    
    async init() {
        console.log('📊 Initializing Chart Manager...');
        
        // Инициализация UI
        this.setupEventListeners();
        
        // Загрузка списка символов
        await this.loadSymbols();
        
        // Подключение к WebSocket
        this.connectWebSocket();
        
        // Показываем сообщение "выберите инструмент"
        document.getElementById('noDataMessage').classList.remove('hidden');
        
        console.log('✅ Chart Manager initialized');
    }
    
    setupEventListeners() {
        // Поиск символов
        const searchInput = document.getElementById('symbolSearch');
        const dropdown = document.getElementById('symbolDropdown');
        
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            this.filterSymbols(query);
        });
        
        searchInput.addEventListener('focus', () => {
            dropdown.classList.remove('hidden');
        });
        
        // Закрытие dropdown при клике вне
        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        });
        
        // Переключение таймфреймов
        document.querySelectorAll('.timeframe-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const timeframe = btn.dataset.tf;
                this.changeTimeframe(timeframe);
            });
        });
    }
    
    async loadSymbols() {
        try {
            const response = await fetch(`${API_BASE}/symbols`);
            if (!response.ok) throw new Error('Failed to load symbols');
            
            this.symbols = await response.json();
            console.log(`📋 Loaded ${this.symbols.length} symbols`);
            
            // Инициализация dropdown
            this.filterSymbols('');
        } catch (error) {
            console.error('❌ Error loading symbols:', error);
            this.updateStatus('offline');
        }
    }
    
    filterSymbols(query) {
        const dropdown = document.getElementById('symbolDropdown');
        
        if (!this.symbols.length) {
            dropdown.innerHTML = '<div class="px-4 py-2 text-gray-400">Загрузка...</div>';
            return;
        }
        
        const filtered = this.symbols.filter(s => 
            s.symbol.toLowerCase().includes(query)
        );
        
        if (!filtered.length) {
            dropdown.innerHTML = '<div class="px-4 py-2 text-gray-400">Ничего не найдено</div>';
            return;
        }
        
        // Группировка по рынкам
        const spotSymbols = filtered.filter(s => s.market === 'spot');
        const futuresSymbols = filtered.filter(s => s.market === 'futures');
        
        let html = '';
        
        if (spotSymbols.length) {
            html += '<div class="px-4 py-2 text-xs font-semibold text-gray-400 uppercase">Spot</div>';
            spotSymbols.forEach(s => {
                html += `
                    <div class="symbol-item px-4 py-2 hover:bg-slate-600 cursor-pointer flex justify-between items-center" 
                         data-symbol="${s.symbol}" data-market="${s.market}">
                        <span>${s.symbol}</span>
                        <span class="text-xs text-green-400">SPOT</span>
                    </div>
                `;
            });
        }
        
        if (futuresSymbols.length) {
            html += '<div class="px-4 py-2 text-xs font-semibold text-gray-400 uppercase border-t border-slate-600">Futures</div>';
            futuresSymbols.forEach(s => {
                html += `
                    <div class="symbol-item px-4 py-2 hover:bg-slate-600 cursor-pointer flex justify-between items-center" 
                         data-symbol="${s.symbol}" data-market="${s.market}">
                        <span>${s.symbol}</span>
                        <span class="text-xs text-blue-400">FUTURES</span>
                    </div>
                `;
            });
        }
        
        dropdown.innerHTML = html;
        
        // Обработчики кликов на символы
        dropdown.querySelectorAll('.symbol-item').forEach(item => {
            item.addEventListener('click', () => {
                const symbol = item.dataset.symbol;
                const market = item.dataset.market;
                this.selectSymbol(symbol, market);
                dropdown.classList.add('hidden');
            });
        });
    }
    
    async selectSymbol(symbol, market) {
        console.log(`📊 Selected: ${symbol} (${market})`);
        
        this.currentSymbol = symbol;
        this.currentMarket = market;
        
        // Обновление UI
        document.getElementById('symbolSearch').value = symbol;
        const marketBadge = document.getElementById('marketBadge');
        if (market === 'spot') {
            marketBadge.innerHTML = '<span class="text-green-400 font-medium">SPOT</span>';
        } else {
            marketBadge.innerHTML = '<span class="text-blue-400 font-medium">FUTURES</span>';
        }
        
        // Загрузка данных
        await this.loadChartData();
        
        // Подписка на WebSocket обновления
        this.subscribeToSymbol(symbol, market);
    }
    
    async loadChartData() {
        try {
            const response = await fetch(
                `${API_BASE}/candles?symbol=${encodeURIComponent(this.currentSymbol)}&market=${this.currentMarket}&timeframe=${this.currentTimeframe}`
            );
            
            if (!response.ok) {
                if (response.status === 404) {
                    alert('⚠️ Нет данных для этого инструмента. Скринер ещё не начал мониторинг или данные устарели.');
                    return;
                }
                throw new Error('Failed to load chart data');
            }
            
            const data = await response.json();
            console.log(`✅ Loaded ${data.candles.length} candles`);
            
            // Скрываем сообщение "выберите инструмент"
            document.getElementById('noDataMessage').classList.add('hidden');
            
            // Инициализация графика (если ещё не создан)
            if (!this.chart) {
                this.initChart();
            }
            
            // Загрузка данных в график
            this.candlestickSeries.setData(data.candles);
            
            // Преобразуем volume для histogram (нужен только time и value)
            const volumeData = data.candles.map(c => ({
                time: c.time,
                value: c.volume,
                color: c.close >= c.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)'
            }));
            this.volumeSeries.setData(volumeData);
            
            // Отображение меток фильтров
            this.renderTriggerMarks(data.triggers);
            
            // Обновление счётчика
            document.getElementById('candleCount').textContent = data.candles.length;
            this.updateLastUpdateTime();
            
        } catch (error) {
            console.error('❌ Error loading chart data:', error);
            alert('Ошибка загрузки данных графика');
        }
    }
    
    initChart() {
        const container = document.getElementById('chartContainer');
        
        // Очистка контейнера
        container.innerHTML = '';
        
        // Создание графика
        this.chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 600,
            layout: {
                background: { color: '#1e293b' },
                textColor: '#d1d5db',
            },
            grid: {
                vertLines: { color: '#334155' },
                horzLines: { color: '#334155' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: '#334155',
            },
            timeScale: {
                borderColor: '#334155',
                timeVisible: true,
                secondsVisible: false,
            },
        });
        
        // Свечная серия
        this.candlestickSeries = this.chart.addCandlestickSeries({
            upColor: '#22c55e',
            downColor: '#ef4444',
            borderVisible: false,
            wickUpColor: '#22c55e',
            wickDownColor: '#ef4444',
        });
        
        // Серия объёмов (внизу)
        this.volumeSeries = this.chart.addHistogramSeries({
            color: '#26a69a',
            priceFormat: {
                type: 'volume',
            },
            priceScaleId: 'volume',
            scaleMargins: {
                top: 0.8,
                bottom: 0,
            },
        });
        
        // Адаптивность при изменении размера окна
        window.addEventListener('resize', () => {
            if (this.chart) {
                this.chart.applyOptions({ 
                    width: container.clientWidth 
                });
            }
        });
        
        console.log('✅ Chart initialized');
    }
    
    renderTriggerMarks(triggers) {
        // Очистка старых меток
        this.triggerMarkers.forEach(marker => marker.remove());
        this.triggerMarkers = [];
        
        if (!triggers || !triggers.length) return;
        
        const container = document.getElementById('chartContainer');
        
        triggers.forEach(trigger => {
            // Создаём вертикальную линию-метку
            const marker = document.createElement('div');
            marker.className = 'trigger-marker';
            marker.style.height = '100%';
            marker.style.top = '0';
            
            // Позиционируем по времени (примерно, т.к. точное позиционирование требует доступа к TimeScale API)
            // Это упрощённая версия, можно улучшить
            
            // Tooltip
            const tooltip = document.createElement('div');
            tooltip.className = 'trigger-tooltip hidden';
            tooltip.innerHTML = `
                <div><strong>${trigger.filter_name}</strong></div>
                <div class="text-xs text-gray-400">${trigger.filter_type}</div>
                <div class="text-xs">${new Date(trigger.time * 1000).toLocaleString()}</div>
            `;
            
            marker.addEventListener('mouseenter', () => {
                tooltip.classList.remove('hidden');
            });
            
            marker.addEventListener('mouseleave', () => {
                tooltip.classList.add('hidden');
            });
            
            marker.appendChild(tooltip);
            container.appendChild(marker);
            this.triggerMarkers.push(marker);
        });
        
        console.log(`📌 Rendered ${triggers.length} trigger marks`);
    }
    
    changeTimeframe(timeframe) {
        console.log(`⏱️ Changing timeframe to ${timeframe}`);
        
        // Обновление кнопок
        document.querySelectorAll('.timeframe-btn').forEach(btn => {
            if (btn.dataset.tf === timeframe) {
                btn.classList.remove('bg-slate-700', 'text-gray-300');
                btn.classList.add('bg-blue-600', 'text-white');
            } else {
                btn.classList.remove('bg-blue-600', 'text-white');
                btn.classList.add('bg-slate-700', 'text-gray-300');
            }
        });
        
        this.currentTimeframe = timeframe;
        
        // Перезагрузка данных
        if (this.currentSymbol && this.currentMarket) {
            this.loadChartData();
        }
    }
    
    connectWebSocket() {
        if (this.websocket) {
            this.websocket.close();
        }
        
        console.log('🔌 Connecting to WebSocket...');
        this.updateStatus('connecting');
        
        this.websocket = new WebSocket(`${WS_BASE}/ws/charts`);
        
        this.websocket.onopen = () => {
            console.log('✅ WebSocket connected');
            this.updateStatus('live');
            this.reconnectAttempts = 0;
        };
        
        this.websocket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                this.handleWebSocketMessage(message);
            } catch (error) {
                console.error('❌ Error parsing WebSocket message:', error);
            }
        };
        
        this.websocket.onerror = (error) => {
            console.error('❌ WebSocket error:', error);
            this.updateStatus('error');
        };
        
        this.websocket.onclose = () => {
            console.log('🔌 WebSocket disconnected');
            this.updateStatus('offline');
            this.scheduleReconnect();
        };
    }
    
    handleWebSocketMessage(message) {
        switch (message.type) {
            case 'candle_update':
                if (message.symbol === this.currentSymbol && message.market === this.currentMarket) {
                    this.updateCandle(message.candle);
                }
                break;
            
            case 'trigger_mark':
                if (message.symbol === this.currentSymbol && message.market === this.currentMarket) {
                    this.addTriggerMark(message.trigger);
                }
                break;
            
            case 'status':
                this.updateStatus(message.status);
                break;
            
            case 'subscribed':
                console.log(`✅ Subscribed to ${message.symbol} (${message.market})`);
                break;
            
            case 'unsubscribed':
                console.log(`✅ Unsubscribed from ${message.symbol} (${message.market})`);
                break;
            
            default:
                console.warn('⚠️ Unknown message type:', message.type);
        }
    }
    
    updateCandle(candle) {
        if (!this.candlestickSeries || !this.volumeSeries) return;
        
        // Обновление свечи
        this.candlestickSeries.update(candle);
        
        // Обновление объёма
        const volumeData = {
            time: candle.time,
            value: candle.volume,
            color: candle.close >= candle.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)'
        };
        this.volumeSeries.update(volumeData);
        
        this.updateLastUpdateTime();
        
        console.log(`📊 Candle updated: ${candle.time}`);
    }
    
    addTriggerMark(trigger) {
        console.log(`📌 New trigger mark:`, trigger);
        this.renderTriggerMarks([trigger]);
    }
    
    subscribeToSymbol(symbol, market) {
        if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
            console.warn('⚠️ WebSocket not ready, cannot subscribe');
            return;
        }
        
        const message = {
            action: 'subscribe',
            symbol: symbol,
            market: market
        };
        
        this.websocket.send(JSON.stringify(message));
        console.log(`📡 Subscribing to ${symbol} (${market})`);
    }
    
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('❌ Max reconnect attempts reached');
            this.updateStatus('offline');
            return;
        }
        
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
        this.reconnectAttempts++;
        
        console.log(`🔄 Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        this.updateStatus('reconnecting');
        
        setTimeout(() => this.connectWebSocket(), delay);
    }
    
    updateStatus(status) {
        const badge = document.getElementById('statusBadge');
        badge.className = 'status-badge px-3 py-1 rounded-full text-sm font-medium';
        
        switch (status) {
            case 'live':
                badge.classList.add('bg-green-600', 'text-white');
                badge.textContent = '🟢 LIVE';
                break;
            case 'connecting':
                badge.classList.add('bg-yellow-600', 'text-white');
                badge.textContent = '🟡 Подключение...';
                break;
            case 'reconnecting':
                badge.classList.add('bg-yellow-600', 'text-white');
                badge.textContent = '🟡 Переподключение...';
                break;
            case 'offline':
                badge.classList.add('bg-red-600', 'text-white');
                badge.textContent = '🔴 Offline';
                break;
            case 'stale':
                badge.classList.add('bg-orange-600', 'text-white');
                badge.textContent = '⚠️ Данные устарели';
                break;
            default:
                badge.classList.add('bg-gray-700', 'text-gray-300');
                badge.textContent = status;
        }
    }
    
    updateLastUpdateTime() {
        const now = new Date();
        document.getElementById('lastUpdate').textContent = now.toLocaleTimeString();
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    window.chartManager = new ChartManager();
});