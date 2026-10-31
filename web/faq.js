/**
 * Ny-Luna Core — Interactive FAQ System
 * Features:
 * - Real-time keyword search across questions and answers
 * - Category chip filtering with active state persistence
 * - Expand / Collapse all toggle
 * - Deep link anchor copying with toast notification
 * - Auto-expand and smooth scroll on page load hash (#anchor)
 */

document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('faq-search');
    const searchClear = document.getElementById('faq-search-clear');
    const chips = document.querySelectorAll('.faq-chip');
    const cards = document.querySelectorAll('.faq-card');
    const counterEl = document.getElementById('faq-counter');
    const toggleAllBtn = document.getElementById('faq-toggle-all');
    const emptyState = document.getElementById('faq-empty-state');
    const toast = document.getElementById('faq-toast');

    let currentCategory = 'all';
    let currentQuery = '';
    let isAllExpanded = false;

    // Show toast notification
    function showToast(message) {
        if (!toast) return;
        toast.innerHTML = `<i class="ri-checkbox-circle-fill" style="color: var(--accent);"></i> ${message}`;
        toast.classList.add('show');
        setTimeout(() => {
            toast.classList.remove('show');
        }, 2200);
    }

    // Filter cards by category and search query
    function applyFilters() {
        let visibleCount = 0;
        const q = currentQuery.toLowerCase().trim();

        cards.forEach(card => {
            const category = card.getAttribute('data-category') || '';
            const title = (card.querySelector('.faq-q-title')?.textContent || '').toLowerCase();
            const body = (card.querySelector('.faq-body')?.textContent || '').toLowerCase();

            const matchesCategory = (currentCategory === 'all' || category === currentCategory);
            const matchesQuery = (!q || title.includes(q) || body.includes(q));

            if (matchesCategory && matchesQuery) {
                card.style.display = 'block';
                visibleCount++;
                // If user is searching, auto-expand matching cards for quick reading
                if (q.length >= 2) {
                    card.open = true;
                }
            } else {
                card.style.display = 'none';
            }
        });

        // Update counter text
        if (counterEl) {
            counterEl.textContent = `${visibleCount} of ${cards.length} questions`;
        }

        // Toggle empty state
        if (emptyState) {
            emptyState.style.display = visibleCount === 0 ? 'block' : 'none';
        }
    }

    // Search input listener
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            currentQuery = e.target.value;
            if (searchClear) {
                searchClear.style.display = currentQuery.length > 0 ? 'flex' : 'none';
            }
            applyFilters();
        });
    }

    // Clear search button
    if (searchClear) {
        searchClear.addEventListener('click', () => {
            if (searchInput) {
                searchInput.value = '';
                searchInput.focus();
            }
            currentQuery = '';
            searchClear.style.display = 'none';
            applyFilters();
        });
    }

    // Category chips listeners
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            chips.forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentCategory = chip.getAttribute('data-filter') || 'all';
            applyFilters();
        });
    });

    // Expand / Collapse All
    if (toggleAllBtn) {
        toggleAllBtn.addEventListener('click', () => {
            isAllExpanded = !isAllExpanded;
            cards.forEach(card => {
                if (card.style.display !== 'none') {
                    card.open = isAllExpanded;
                }
            });
            toggleAllBtn.innerHTML = isAllExpanded
                ? '<i class="ri-contract-up-down-line"></i> Collapse All'
                : '<i class="ri-expand-up-down-line"></i> Expand All';
        });
    }

    // Copy anchor link
    document.querySelectorAll('.faq-copy-anchor').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation(); // prevent toggling details
            const card = btn.closest('.faq-card');
            if (!card || !card.id) return;

            const url = `${window.location.origin}${window.location.pathname}#${card.id}`;
            navigator.clipboard.writeText(url).then(() => {
                showToast('Link copied to clipboard!');
            }).catch(() => {
                // Fallback for older browsers
                const dummy = document.createElement('input');
                document.body.appendChild(dummy);
                dummy.value = url;
                dummy.select();
                document.execCommand('copy');
                document.body.removeChild(dummy);
                showToast('Link copied to clipboard!');
            });
        });
    });

    // Deep link hash auto-expansion
    function checkHash() {
        const hash = window.location.hash;
        if (!hash) return;
        const targetId = hash.substring(1);
        const targetCard = document.getElementById(targetId);
        if (targetCard && targetCard.classList.contains('faq-card')) {
            targetCard.open = true;
            // Switch category chip if needed
            const category = targetCard.getAttribute('data-category');
            if (category && category !== currentCategory) {
                const chip = document.querySelector(`.faq-chip[data-filter="${category}"]`);
                if (chip) chip.click();
            }
            setTimeout(() => {
                targetCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 100);
        }
    }

    window.addEventListener('hashchange', checkHash);
    checkHash();
    applyFilters();
});
