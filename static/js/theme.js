// ---------------- GLOBAL THEME MANAGER ----------------

// Apply theme on load securely
(function () {
    const savedTheme = localStorage.getItem('travel_app_theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
})();

document.addEventListener('DOMContentLoaded', () => {
    updateThemeToggleButton();
});

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';

    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('travel_app_theme', newTheme);

    updateThemeToggleButton();

    // Dispatch a custom event so charts can re-render if needed
    window.dispatchEvent(new Event('themeChanged'));
}

function updateThemeToggleButton() {
    const toggles = document.querySelectorAll('.theme-toggle-btn');
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

    toggles.forEach(btn => {
        btn.innerHTML = isDark ? '☀ Light Mode' : '🌙 Dark Mode';
        if (isDark) {
            btn.classList.remove('btn-dark');
            btn.classList.add('btn-light');
        } else {
            btn.classList.remove('btn-light');
            btn.classList.add('btn-dark');
        }
    });
}

// ---------------- CHART THEME UTILITIES ----------------

window.getChartColors = function () {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

    return {
        textColor: isDark ? '#cbd5e1' : '#4a5568',
        gridColor: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)',
        tooltipBg: isDark ? 'rgba(30, 41, 59, 0.9)' : 'rgba(255, 255, 255, 0.9)',
        tooltipText: isDark ? '#f8fafc' : '#1e293b',
        primaryGradientStart: isDark ? 'rgba(59, 130, 246, 0.8)' : 'rgba(31, 60, 136, 0.8)',
        primaryGradientEnd: isDark ? 'rgba(59, 130, 246, 0.2)' : 'rgba(31, 60, 136, 0.2)'
    };
};
