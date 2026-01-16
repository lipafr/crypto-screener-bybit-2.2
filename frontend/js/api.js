/**
 * API Client for Crypto Screener Backend
 */

const API_BASE_URL = window.location.origin;

class ApiClient {
    constructor() {
        this.baseUrl = API_BASE_URL;
    }

    /**
     * Make HTTP request
     */
    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        };

        try {
            const response = await fetch(url, config);
            
            if (!response.ok) {
                const error = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(error.detail || `HTTP ${response.status}`);
            }

            // Handle 204 No Content
            if (response.status === 204) {
                return null;
            }

            return await response.json();
        } catch (error) {
            console.error('API Request failed:', error);
            throw error;
        }
    }

    // ============================================
    // Health & Status
    // ============================================

    async getHealth() {
        return this.request('/health');
    }

    async getStatus() {
        return this.request('/api/status');
    }

    // ============================================
    // Filters
    // ============================================

    async getFilters(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/api/filters${query ? '?' + query : ''}`);
    }

    async getFilter(id) {
        return this.request(`/api/filters/${id}`);
    }

    async createFilter(data) {
        return this.request('/api/filters', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateFilter(id, data) {
        return this.request(`/api/filters/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async deleteFilter(id) {
        return this.request(`/api/filters/${id}`, {
            method: 'DELETE',
        });
    }

    async toggleFilter(id) {
        return this.request(`/api/filters/${id}/toggle`, {
            method: 'PATCH',
        });
    }

    async cloneFilter(id) {
        return this.request(`/api/filters/${id}/clone`, {
            method: 'POST',
        });
    }

    // ============================================
    // Triggers
    // ============================================

    async getTriggers(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/api/triggers${query ? '?' + query : ''}`);
    }

    async getTriggerStats() {
        return this.request('/api/triggers/stats');
    }

    // ============================================
    // Settings
    // ============================================

    async getSettings() {
        return this.request('/api/settings');
    }

    async updateSettings(data) {
        return this.request('/api/settings', {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async testTelegram() {
        return this.request('/api/settings/test-telegram', {
            method: 'POST',
        });
    }
}

// Create global API instance
const api = new ApiClient();

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { api, ApiClient };
}
