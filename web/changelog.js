(function () {
    const owner = 'Amne-Dev';
    const repo = 'NLC';
    const api = `https://api.github.com/repos/${owner}/${repo}/releases`;

    const listEl = document.getElementById('list');
    const statusEl = document.getElementById('status');
    const refreshBtn = document.getElementById('refreshBtn');
    const refreshIcon = document.getElementById('refreshIcon');
    const releaseCountEl = document.getElementById('release-count');
    const searchInput = document.getElementById('changelog-search');
    const clearSearchBtn = document.getElementById('changelog-clear-search');
    const filterChips = document.querySelectorAll('.changelog-filter-chip');

    let allReleases = [];
    let activeFilter = 'all'; // 'all' | 'stable' | 'prerelease'
    let searchQuery = '';

    // HTML escape helper
    function esc(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // Format byte sizes into readable string
    function formatBytes(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    // Relative and absolute date formatter
    function formatDate(dateStr) {
        if (!dateStr) return { formatted: 'Unpublished', relative: '' };
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return { formatted: dateStr, relative: '' };

        const options = { year: 'numeric', month: 'short', day: 'numeric' };
        const formatted = date.toLocaleDateString(undefined, options);

        const now = new Date();
        const diffMs = now - date;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

        let relative = '';
        if (diffDays <= 0) {
            relative = 'today';
        } else if (diffDays === 1) {
            relative = 'yesterday';
        } else if (diffDays < 30) {
            relative = `${diffDays} days ago`;
        } else if (diffDays < 365) {
            const months = Math.floor(diffDays / 30);
            relative = `${months} mo. ago`;
        } else {
            const years = Math.floor(diffDays / 365);
            relative = `${years} yr. ago`;
        }

        return { formatted, relative };
    }

    // Determine icon for downloadable assets
    function getAssetIcon(filename) {
        const lower = filename.toLowerCase();
        if (lower.endsWith('.exe') || lower.endsWith('.msi')) {
            return '<i class="ri-windows-fill"></i>';
        }
        if (lower.endsWith('.appimage') || lower.endsWith('.deb') || lower.endsWith('.rpm') || lower.endsWith('.tar.gz') || lower.endsWith('.tar.xz')) {
            return '<i class="ri-linux-fill"></i>';
        }
        if (lower.endsWith('.dmg') || lower.endsWith('.pkg')) {
            return '<i class="ri-apple-fill"></i>';
        }
        if (lower.endsWith('.zip') || lower.endsWith('.7z')) {
            return '<i class="ri-file-zip-line"></i>';
        }
        if (lower.endsWith('.sha256') || lower.endsWith('.sig') || lower.endsWith('.asc')) {
            return '<i class="ri-shield-check-line"></i>';
        }
        return '<i class="ri-file-code-line"></i>';
    }

    // Preprocess GitHub-style markdown alerts: > [!NOTE], > [!TIP], etc.
    function preprocessAlerts(text) {
        if (!text) return '';
        return text.replace(/^>[ \t]*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*\r?\n((?:>[^\r\n]*\r?\n?)*)/gim, (match, type, content) => {
            const cleanContent = content.replace(/^>[ \t]?/gm, '');
            const typeLower = type.toLowerCase();
            let icon = 'ri-information-line';
            if (typeLower === 'tip') icon = 'ri-lightbulb-line';
            else if (typeLower === 'important') icon = 'ri-error-warning-line';
            else if (typeLower === 'warning') icon = 'ri-alert-line';
            else if (typeLower === 'caution') icon = 'ri-alarm-warning-line';

            return `<div class="md-alert md-alert-${typeLower}">
<div class="md-alert-header"><i class="${icon}"></i> <strong>${type.toUpperCase()}</strong></div>
<div class="md-alert-body">

${cleanContent}

</div>
</div>\n\n`;
        });
    }

    // Fallback markdown renderer if marked.js CDN is unavailable
    function fallbackMarkdown(text) {
        if (!text) return '';
        let s = String(text);

        // Preprocess alerts
        s = preprocessAlerts(s);

        // Escape HTML
        s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        // Code blocks
        s = s.replace(/```([a-zA-Z0-9_\-]+)?\r?\n([\s\S]*?)```/g, (m, lang, code) => {
            return `<pre><code class="language-${lang || 'text'}">${code.trim()}</code></pre>`;
        });

        // Headers
        s = s.replace(/^####[ \t](.*)$/gm, '<h4>$1</h4>');
        s = s.replace(/^###[ \t](.*)$/gm, '<h3>$1</h3>');
        s = s.replace(/^##[ \t](.*)$/gm, '<h2>$1</h2>');
        s = s.replace(/^#[ \t](.*)$/gm, '<h1>$1</h1>');

        // Lists
        s = s.replace(/^[-*][ \t](.*)$/gm, '<li>$1</li>');
        s = s.replace(/(<li>[\s\S]*?<\/li>)/g, (m) => `<ul>${m}</ul>`);
        s = s.replace(/<\/ul>\s*<ul>/g, '');

        // Inline formatting
        s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
        s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

        // Auto-links for GitHub issues and usernames
        s = s.replace(/(^|[\s(])#([0-9]+)([\s).,]|$)/g, '$1<a href="https://github.com/Amne-Dev/NLC/issues/$2" target="_blank" rel="noopener">#$2</a>$3');
        s = s.replace(/(^|[\s(])@([a-zA-Z0-9_\-]+)([\s).,]|$)/g, '$1<a href="https://github.com/$2" target="_blank" rel="noopener">@$2</a>$3');

        // Paragraphs / linebreaks
        s = s.replace(/\r?\n\r?\n/g, '</p><p>');
        return `<p>${s}</p>`;
    }

    // Full Markdown parsing with marked + DOMPurify
    function renderMarkdown(raw) {
        if (!raw || !raw.trim()) {
            return '<p style="color: var(--text-muted); font-style: italic;">No detailed release notes provided.</p>';
        }

        try {
            // First preprocess alerts
            const preprocessed = preprocessAlerts(raw);

            let html = '';
            if (window.marked && typeof window.marked.parse === 'function') {
                marked.setOptions({
                    gfm: true,
                    breaks: true
                });
                html = marked.parse(preprocessed);
            } else {
                html = fallbackMarkdown(preprocessed);
            }

            // Postprocess autolinks for GitHub issues and mentions if not already in an anchor tag
            html = html.replace(/(^|[\s(])#([0-9]+)([\s).,]|$)/g, '$1<a href="https://github.com/Amne-Dev/NLC/issues/$2" target="_blank" rel="noopener">#$2</a>$3');
            html = html.replace(/(^|[\s(])@([a-zA-Z0-9_\-]+)([\s).,]|$)/g, '$1<a href="https://github.com/$2" target="_blank" rel="noopener">@$2</a>$3');

            // Sanitize HTML with DOMPurify if available
            if (window.DOMPurify && typeof window.DOMPurify.sanitize === 'function') {
                return DOMPurify.sanitize(html, {
                    ADD_ATTR: ['target', 'rel']
                });
            }

            return html;
        } catch (err) {
            console.error('Markdown parse error:', err);
            return fallbackMarkdown(raw);
        }
    }

    // Render releases to DOM
    function renderList() {
        listEl.innerHTML = '';

        // Filter releases
        const filtered = allReleases.filter(r => {
            // 1. Tag filter
            if (activeFilter === 'stable' && r.prerelease) return false;
            if (activeFilter === 'prerelease' && !r.prerelease) return false;

            // 2. Search query filter
            if (searchQuery) {
                const q = searchQuery.toLowerCase();
                const nameMatch = (r.name || '').toLowerCase().includes(q);
                const tagMatch = (r.tag_name || '').toLowerCase().includes(q);
                const bodyMatch = (r.body || '').toLowerCase().includes(q);
                if (!nameMatch && !tagMatch && !bodyMatch) return false;
            }

            return true;
        });

        // Update count text
        if (releaseCountEl) {
            const total = allReleases.length;
            const shown = filtered.length;
            if (shown === total) {
                releaseCountEl.innerHTML = `<i class="ri-git-commit-line"></i> Showing ${total} official releases`;
            } else {
                releaseCountEl.innerHTML = `<i class="ri-git-commit-line"></i> Showing ${shown} of ${total} releases`;
            }
        }

        // Empty state
        if (filtered.length === 0) {
            listEl.innerHTML = `
                <div class="changelog-state-card">
                    <div class="state-icon"><i class="ri-filter-off-line"></i></div>
                    <h3>No matching releases found</h3>
                    <p>No releases match your current search "${esc(searchQuery)}" and filter selection.</p>
                    <button type="button" class="btn-refresh" id="resetFilterBtn">Reset Filters</button>
                </div>
            `;
            const resetBtn = document.getElementById('resetFilterBtn');
            if (resetBtn) {
                resetBtn.addEventListener('click', () => {
                    activeFilter = 'all';
                    searchQuery = '';
                    if (searchInput) searchInput.value = '';
                    if (clearSearchBtn) clearSearchBtn.hidden = true;
                    filterChips.forEach(chip => chip.classList.toggle('active', chip.dataset.filter === 'all'));
                    renderList();
                });
            }
            return;
        }

        // Find the index of the first stable release to give it a "Latest Release" badge
        let firstStableIndex = -1;
        for (let i = 0; i < allReleases.length; i++) {
            if (!allReleases[i].prerelease && !allReleases[i].draft) {
                firstStableIndex = i;
                break;
            }
        }

        filtered.forEach((r) => {
            const isLatest = allReleases.indexOf(r) === firstStableIndex;
            const isPrerelease = r.prerelease;
            const { formatted, relative } = formatDate(r.published_at);
            const dateDisplay = relative ? `${formatted} (${relative})` : formatted;

            const entry = document.createElement('article');
            entry.className = 'changelog-entry';
            entry.id = `release-${esc(r.tag_name)}`;

            // Timeline indicator icon
            const marker = document.createElement('div');
            marker.className = 'timeline-marker';
            marker.innerHTML = isLatest
                ? '<i class="ri-sparkling-fill" title="Latest Release"></i>'
                : (isPrerelease ? '<i class="ri-test-tube-line" title="Pre-release"></i>' : '<i class="ri-git-commit-line"></i>');

            // Release Card
            const card = document.createElement('div');
            card.className = 'changelog-card';

            // 1. Header
            let badgesHtml = `<span class="release-tag"><i class="ri-price-tag-3-fill"></i> ${esc(r.tag_name || 'v?')}</span>`;
            if (isLatest) {
                badgesHtml += `<span class="badge-latest"><i class="ri-checkbox-circle-fill"></i> Latest Release</span>`;
            }
            if (isPrerelease) {
                badgesHtml += `<span class="badge-prerelease"><i class="ri-flask-fill"></i> Pre-Release</span>`;
            }
            if (r.draft) {
                badgesHtml += `<span class="badge-prerelease">Draft</span>`;
            }

            const authorLogin = r.author ? r.author.login : 'amne-dev';
            const authorAvatar = r.author && r.author.avatar_url ? r.author.avatar_url : 'logo.png';
            const authorUrl = r.author ? r.author.html_url : `https://github.com/${authorLogin}`;
            const releaseTitle = r.name || r.tag_name || 'Release';

            const headerHtml = `
                <div class="changelog-card-header">
                    <div class="release-badges">${badgesHtml}</div>
                    <h2 class="release-title">${esc(releaseTitle)}</h2>
                    <div class="release-meta">
                        <span class="meta-item"><i class="ri-calendar-line"></i> ${esc(dateDisplay)}</span>
                        <a href="${esc(authorUrl)}" target="_blank" rel="noopener" class="meta-item author-tag" title="View contributor profile">
                            <img src="${esc(authorAvatar)}" class="author-avatar" alt="${esc(authorLogin)}">
                            <span>${esc(authorLogin)}</span>
                        </a>
                        <a href="${esc(r.html_url)}" target="_blank" rel="noopener" class="meta-link" title="Open release notes on GitHub">
                            <i class="ri-github-fill"></i> GitHub Release
                        </a>
                    </div>
                </div>
            `;

            // 2. Markdown Body
            const bodyHtml = `
                <div class="changelog-card-body markdown-body">
                    ${renderMarkdown(r.body)}
                </div>
            `;

            // 3. Assets Section
            let assetsHtml = '';
            if (r.assets && r.assets.length > 0) {
                const assetCardsHtml = r.assets.map(asset => {
                    const icon = getAssetIcon(asset.name);
                    const sizeStr = formatBytes(asset.size);
                    const downloadsStr = (asset.download_count || 0).toLocaleString();
                    return `
                        <a href="${esc(asset.browser_download_url)}" class="asset-card" download title="Download ${esc(asset.name)}">
                            <div class="asset-icon">${icon}</div>
                            <div class="asset-info">
                                <span class="asset-name">${esc(asset.name)}</span>
                                <span class="asset-details">${sizeStr} · ${downloadsStr} downloads</span>
                            </div>
                            <i class="ri-download-line asset-arrow"></i>
                        </a>
                    `;
                }).join('');

                assetsHtml = `
                    <div class="changelog-assets">
                        <div class="assets-header">
                            <span class="assets-title"><i class="ri-download-2-line"></i> Downloadable Assets (${r.assets.length})</span>
                        </div>
                        <div class="assets-grid">
                            ${assetCardsHtml}
                        </div>
                    </div>
                `;
            }

            card.innerHTML = headerHtml + bodyHtml + assetsHtml;
            entry.appendChild(marker);
            entry.appendChild(card);
            listEl.appendChild(entry);
        });
    }

    // Fetch releases from GitHub API
    async function fetchReleases() {
        if (statusEl) {
            statusEl.innerHTML = `
                <div class="changelog-state-card">
                    <div class="state-icon"><i class="ri-loader-4-line ri-spin"></i></div>
                    <h3>Fetching releases from GitHub...</h3>
                    <p>Retrieving changelog history and binary assets for Ny-Luna Core.</p>
                </div>
            `;
        }
        if (refreshIcon) refreshIcon.classList.add('spinning');
        if (refreshBtn) refreshBtn.disabled = true;

        try {
            const res = await fetch(api + '?per_page=50');
            if (!res.ok) {
                if (res.status === 403) {
                    throw new Error('GitHub API rate limit reached. Please try again shortly or view releases directly on GitHub.');
                }
                throw new Error(`GitHub API returned status ${res.status}: ${res.statusText}`);
            }
            const data = await res.json();
            if (statusEl) statusEl.innerHTML = '';

            if (!Array.isArray(data) || data.length === 0) {
                allReleases = [];
                listEl.innerHTML = `
                    <div class="changelog-state-card">
                        <div class="state-icon"><i class="ri-inbox-line"></i></div>
                        <h3>No releases found</h3>
                        <p>No published releases were returned by the GitHub repository.</p>
                    </div>
                `;
                return;
            }

            allReleases = data;
            renderList();
        } catch (err) {
            console.error('Failed to fetch releases:', err);
            if (statusEl) {
                statusEl.innerHTML = `
                    <div class="changelog-state-card">
                        <div class="state-icon" style="color: #FF5252;"><i class="ri-error-warning-line"></i></div>
                        <h3>Unable to load releases</h3>
                        <p>${esc(err && err.message)}</p>
                        <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
                            <button type="button" class="btn-refresh" id="retryFetchBtn"><i class="ri-refresh-line"></i> Retry</button>
                            <a href="https://github.com/${owner}/${repo}/releases" target="_blank" rel="noopener" class="btn-refresh"><i class="ri-github-fill"></i> View on GitHub</a>
                        </div>
                    </div>
                `;
                const retryBtn = document.getElementById('retryFetchBtn');
                if (retryBtn) retryBtn.addEventListener('click', fetchReleases);
            }
        } finally {
            if (refreshIcon) refreshIcon.classList.remove('spinning');
            if (refreshBtn) refreshBtn.disabled = false;
        }
    }

    // Search and filter listeners
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            searchQuery = e.target.value.trim();
            if (clearSearchBtn) {
                clearSearchBtn.hidden = searchQuery.length === 0;
            }
            renderList();
        });
    }

    if (clearSearchBtn) {
        clearSearchBtn.addEventListener('click', () => {
            searchQuery = '';
            if (searchInput) {
                searchInput.value = '';
                searchInput.focus();
            }
            clearSearchBtn.hidden = true;
            renderList();
        });
    }

    filterChips.forEach(chip => {
        chip.addEventListener('click', () => {
            filterChips.forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            activeFilter = chip.dataset.filter || 'all';
            renderList();
        });
    });

    if (refreshBtn) {
        refreshBtn.addEventListener('click', fetchReleases);
    }

    // Auto-load on page load
    fetchReleases();
})();
