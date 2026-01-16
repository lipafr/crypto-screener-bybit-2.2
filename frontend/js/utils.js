/**
 * Utility functions
 */

// ============================================
// Toast Notifications
// ============================================

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ============================================
// Date/Time Formatting
// ============================================

function formatTimestamp(timestamp) {
    if (!timestamp) return 'N/A';
    
    const date = new Date(timestamp * 1000);
    
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    
    return `${day}.${month}.${year} ${hours}:${minutes}:${seconds}`;
}

function formatRelativeTime(timestamp) {
    if (!timestamp) return 'Never';
    
    const now = Math.floor(Date.now() / 1000);
    const diff = now - timestamp;
    
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
    if (diff < 2592000) return `${Math.floor(diff / 86400)} days ago`;
    
    return formatTimestamp(timestamp);
}

function formatUptime(seconds) {
    if (!seconds) return 'N/A';
    
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

// ============================================
// Number Formatting
// ============================================

function formatNumber(num, decimals = 2) {
    if (num === null || num === undefined) return 'N/A';
    return Number(num).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

function formatCurrency(amount, decimals = 2) {
    if (amount === null || amount === undefined) return 'N/A';
    return '$' + formatNumber(amount, decimals);
}

function formatPercent(value, decimals = 2) {
    if (value === null || value === undefined) return 'N/A';
    const sign = value > 0 ? '+' : '';
    return `${sign}${formatNumber(value, decimals)}%`;
}

function formatVolume(volume) {
    if (!volume) return '$0';
    
    if (volume >= 1_000_000_000) {
        return `$${(volume / 1_000_000_000).toFixed(2)}B`;
    }
    if (volume >= 1_000_000) {
        return `$${(volume / 1_000_000).toFixed(2)}M`;
    }
    if (volume >= 1_000) {
        return `$${(volume / 1_000).toFixed(2)}K`;
    }
    return `$${volume.toFixed(0)}`;
}

// ============================================
// DOM Helpers
// ============================================

function createElement(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content) element.textContent = content;
    return element;
}

function clearElement(element) {
    while (element.firstChild) {
        element.removeChild(element.firstChild);
    }
}

// ============================================
// Loading State
// ============================================

function showLoading(container) {
    clearElement(container);
    const spinner = createElement('div', 'spinner');
    const wrapper = createElement('div', 'flex justify-center items-center py-12');
    wrapper.appendChild(spinner);
    container.appendChild(wrapper);
}

function showError(container, message) {
    clearElement(container);
    const error = createElement('div', 'text-red-400 text-center py-8', `❌ Error: ${message}`);
    container.appendChild(error);
}

function showEmpty(container, message = 'No data available') {
    clearElement(container);
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = `
        <div class="empty-state-icon">📭</div>
        <p>${message}</p>
    `;
    container.appendChild(empty);
}

// ============================================
// Modal
// ============================================

function showModal(content) {
    const overlay = createElement('div', 'modal-overlay');
    const modal = createElement('div', 'modal');
    
    if (typeof content === 'string') {
        modal.innerHTML = content;
    } else {
        modal.appendChild(content);
    }
    
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    
    // Close on overlay click
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            closeModal(overlay);
        }
    });
    
    // Close on Escape
    const escapeHandler = (e) => {
        if (e.key === 'Escape') {
            closeModal(overlay);
            document.removeEventListener('keydown', escapeHandler);
        }
    };
    document.addEventListener('keydown', escapeHandler);
    
    return overlay;
}

function closeModal(overlay) {
    overlay.style.animation = 'fadeOut 0.2s ease';
    setTimeout(() => overlay.remove(), 200);
}

// ============================================
// Confirmation Dialog
// ============================================

function confirm(message, onConfirm) {
    const content = document.createElement('div');
    content.innerHTML = `
        <h3 class="text-xl font-bold mb-4">Confirm Action</h3>
        <p class="mb-6">${message}</p>
        <div class="flex gap-3 justify-end">
            <button class="btn btn-secondary" id="cancel-btn">Cancel</button>
            <button class="btn btn-danger" id="confirm-btn">Confirm</button>
        </div>
    `;
    
    const modal = showModal(content);
    
    content.querySelector('#cancel-btn').onclick = () => closeModal(modal);
    content.querySelector('#confirm-btn').onclick = () => {
        onConfirm();
        closeModal(modal);
    };
}

// ============================================
// Filter Type Labels
// ============================================

function getFilterTypeLabel(type) {
    const labels = {
        'price_change': 'Price Change',
        'volume_spike': 'Volume Spike',
    };
    return labels[type] || type;
}

function getFilterTypeIcon(type) {
    const icons = {
        'price_change': '📈',
        'volume_spike': '🔥',
    };
    return icons[type] || '🔍';
}

// ============================================
// Market Labels
// ============================================

function getMarketLabel(market) {
    const labels = {
        'spot': 'Spot',
        'futures': 'Futures',
    };
    return labels[market] || market;
}

function getMarketBadge(market) {
    const classes = {
        'spot': 'badge-info',
        'futures': 'badge-warning',
    };
    return `<span class="badge ${classes[market] || 'badge-info'}">${getMarketLabel(market)}</span>`;
}

// ============================================
// Direction Labels
// ============================================

function getDirectionLabel(direction) {
    const labels = {
        'up': '📈 Up',
        'down': '📉 Down',
        'any': '↕️ Any',
        'all': '↕️ All',
    };
    return labels[direction] || direction;
}

// ============================================
// Export functions
// ============================================

if (typeof window !== 'undefined') {
    window.utils = {
        showToast,
        formatTimestamp,
        formatRelativeTime,
        formatUptime,
        formatNumber,
        formatCurrency,
        formatPercent,
        formatVolume,
        createElement,
        clearElement,
        showLoading,
        showError,
        showEmpty,
        showModal,
        closeModal,
        confirm,
        getFilterTypeLabel,
        getFilterTypeIcon,
        getMarketLabel,
        getMarketBadge,
        getDirectionLabel,
    };
}
