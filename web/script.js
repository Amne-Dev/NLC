// Auto-update version from GitHub
fetch('https://api.github.com/repos/Amne-Dev/NLC/releases/latest')
    .then(response => response.json())
    .then(data => {
        if(data.tag_name) {
            // Remove 'v' prefix if present for cleaner display
            const ver = data.tag_name.replace(/^v/, '');
            const versionEl = document.getElementById('version-text');
            if (versionEl) {
                versionEl.innerText = `Version ${ver}`;
            }
        }
    })
    .catch(e => console.error("Could not fetch version", e));

fetch('https://api.github.com/repos/Amne-Dev/NLC/releases')
    .then(res => res.json())
    .then(releases => {
        let totalDownloads = 0;

        // Loop through all releases and accumulate asset download counts
        releases.forEach(release => {
            if (release.assets) {
                release.assets.forEach(asset => {
                    totalDownloads += asset.download_count;
                });
            }
        });

        // Update the DOM exactly once with the finalized total
        const downloadsEl = document.querySelector('.stats .stat:first-child');
        if (downloadsEl) {
            downloadsEl.innerText = `${totalDownloads.toLocaleString()} Downloads`;
        }
    })
    .catch(err => console.error("Error fetching release data:", err));

// Switch between Modpacks and Mods views in Modrinth showcase
function switchModrinthTab(tab) {
    const imgModpacks = document.getElementById('img-modpacks');
    const imgMods = document.getElementById('img-mods');
    const btnModpacks = document.getElementById('tab-btn-modpacks');
    const btnMods = document.getElementById('tab-btn-mods');

    if (!imgModpacks || !imgMods) return;

    if (tab === 'mods') {
        imgModpacks.style.display = 'none';
        imgMods.style.display = 'block';
        btnModpacks?.classList.remove('active');
        btnMods?.classList.add('active');
    } else {
        imgModpacks.style.display = 'block';
        imgMods.style.display = 'none';
        btnModpacks?.classList.add('active');
        btnMods?.classList.remove('active');
    }
}


// =============================================================================
// Ny-Luna Intro Reveal Animation with Navbar FLIP Transition
// =============================================================================
(function() {
    const G = {
        N: [0, "X...X", "XX..X", "XX..X", "X.X.X", "X..XX", "X..XX", "X...X"],
        y: [2, "X...X", "X...X", "X...X", "X...X", ".XXXX", "....X", "XXXX."],
        "-": [3, "XXXXX"],
        L: [0, "X....", "X....", "X....", "X....", "X....", "X....", "XXXXX"],
        u: [2, "X...X", "X...X", "X...X", "X...X", ".XXXX"],
        n: [2, "XXXX.", "X...X", "X...X", "X...X", "X...X"],
        a: [2, ".XXX.", "....X", ".XXXX", "X...X", ".XXXX"]
    };

    function renderPixelWord() {
        const wordEl = document.getElementById("intro-word");
        const navWord = document.getElementById("nav-logo-word");
        const word = "Ny-Luna";
        let fg = "", sh = "", x = 0;
        for (const ch of word) {
            const entry = G[ch];
            if (!entry) { x += 6; continue; }
            const [top, ...rows] = entry;
            rows.forEach((r, j) => {
                [...r].forEach((c, i) => {
                    if (c === "X") {
                        const px = x + i, py = top + j;
                        sh += `<rect x="${px + 1}" y="${py + 1}" width="1" height="1"/>`;
                        fg += `<rect x="${px}" y="${py}" width="1" height="1"/>`;
                    }
                });
            });
            x += 6;
        }
        const svgContent = `<g fill="#6b2650">${sh}</g><g fill="#ffffff">${fg}</g>`;
        if (wordEl) wordEl.innerHTML = svgContent;
        if (navWord) navWord.innerHTML = svgContent;
        document.querySelectorAll(".logo-wordmark-svg").forEach(el => {
            el.innerHTML = svgContent;
        });
    }

    function initSparkles() {
        const pxBox = document.getElementById("intro-px");
        if (!pxBox || pxBox.children.length > 0) return;
        for (let i = 0; i < 24; i++) {
            const d = document.createElement("div");
            d.className = "intro-px";
            d.style.left = (8 + Math.random() * 84) + "%";
            d.style.top = (40 + Math.random() * 50) + "%";
            d.style.setProperty("--d", (3.5 + Math.random() * 3.5) + "s");
            d.style.setProperty("--dl", (Math.random() * 4) + "s");
            d.style.opacity = 0;
            pxBox.appendChild(d);
        }
    }

    const overlay = document.getElementById("intro-overlay");
    const lockup = document.getElementById("intro-lockup");
    const skipBtn = document.getElementById("intro-skip");
    const replayBtn = document.getElementById("btn-replay-intro");
    let introTimers = [];

    function clearIntroTimers() {
        introTimers.forEach(clearTimeout);
        introTimers = [];
    }

    function transitionToNavbar() {
        clearIntroTimers();
        if (!overlay || !lockup) return;

        const navBrand = document.getElementById("nav-brand");
        if (navBrand) {
            const navRect = navBrand.getBoundingClientRect();
            const lockupRect = lockup.getBoundingClientRect();

            const dx = navRect.left + (navRect.width / 2) - (lockupRect.left + (lockupRect.width / 2));
            const dy = navRect.top + (navRect.height / 2) - (lockupRect.top + (lockupRect.height / 2));
            const scale = Math.max(0.28, Math.min(0.45, navRect.height / (lockupRect.height || 1)));

            // 1. Begin moving lockup to navbar position
            lockup.style.transform = `translate(${dx}px, ${dy}px) scale(${scale})`;
            lockup.style.opacity = "1";
        }

        // 2. SIMULTANEOUSLY fade out the dark background into the webpage content
        overlay.classList.add("transitioning");

        // 3. When movement arrives (1.25s): seamlessly switch to nav-brand and dismiss overlay
        setTimeout(() => {
            document.body.classList.add("intro-arrived");
            overlay.classList.add("dismissed");
            setTimeout(() => {
                overlay.style.display = "none";
                overlay.classList.remove("transitioning", "go", "slide", "dismissed");
                lockup.style.transform = "";
                lockup.style.opacity = "";
                document.body.classList.remove("intro-active", "intro-arrived");
            }, 300);
        }, 1250);

        localStorage.setItem("nyluna_intro_played", "1");
    }

    window.playNyLunaIntro = function(force = false) {
        if (!overlay) return;
        const played = localStorage.getItem("nyluna_intro_played");
        if (played && !force) {
            overlay.style.display = "none";
            overlay.classList.add("dismissed");
            document.body.classList.remove("intro-active", "intro-arrived");
            return;
        }

        document.body.classList.add("intro-active");
        renderPixelWord();
        initSparkles();

        clearIntroTimers();
        overlay.style.display = "flex";
        overlay.classList.remove("dismissed", "go", "slide", "transitioning");
        lockup.style.transform = "";
        lockup.style.opacity = "";
        void overlay.offsetWidth;

        introTimers.push(setTimeout(() => overlay.classList.add("go"), 400));
        introTimers.push(setTimeout(() => overlay.classList.add("slide"), 2400));
        introTimers.push(setTimeout(() => transitionToNavbar(), 4600));
    };

    if (skipBtn) {
        skipBtn.addEventListener("click", () => transitionToNavbar());
    }

    if (replayBtn) {
        replayBtn.addEventListener("click", () => {
            window.scrollTo({ top: 0, behavior: "smooth" });
            setTimeout(() => window.playNyLunaIntro(true), 250);
        });
    }

    // Auto-run on first visit
    window.playNyLunaIntro(false);
})();

// =============================================================================
// Download Version Picker Modal
// =============================================================================
(function() {
    const modal = document.getElementById("download-modal");
    const closeBtn = document.getElementById("modal-close");
    const triggers = document.querySelectorAll(".btn-trigger-download");

    function openModal() {
        if (!modal) return;
        modal.hidden = false;
        void modal.offsetWidth;
        modal.classList.add("active");
        document.body.style.overflow = "hidden";
    }

    function closeModal() {
        if (!modal) return;
        modal.classList.remove("active");
        document.body.style.overflow = "";
        setTimeout(() => {
            if (!modal.classList.contains("active")) {
                modal.hidden = true;
            }
        }, 250);
    }

    triggers.forEach(btn => {
        btn.addEventListener("click", e => {
            e.preventDefault();
            openModal();
        });
    });

    if (window.location.hash === "#download") {
        setTimeout(openModal, 150);
    }
    window.addEventListener("hashchange", () => {
        if (window.location.hash === "#download") {
            openModal();
        }
    });

    if (closeBtn) {
        closeBtn.addEventListener("click", closeModal);
    }

    if (modal) {
        modal.addEventListener("click", e => {
            if (e.target === modal) {
                closeModal();
            }
        });
    }

    document.addEventListener("keydown", e => {
        if (e.key === "Escape" && modal && modal.classList.contains("active")) {
            closeModal();
        }
    });
})();

// =============================================================================
// Mobile Navigation Drawer Toggle
// =============================================================================
(function() {
    const navToggle = document.getElementById("nav-toggle");
    const navLinks = document.getElementById("nav-links");
    if (!navToggle || !navLinks) return;

    function toggleMenu() {
        const isOpen = navLinks.classList.toggle("open");
        navToggle.classList.toggle("open", isOpen);
        navToggle.setAttribute("aria-expanded", String(isOpen));
        if (isOpen) {
            document.body.classList.add("nav-open");
        } else {
            document.body.classList.remove("nav-open");
        }
    }

    function closeMenu() {
        navLinks.classList.remove("open");
        navToggle.classList.remove("open");
        navToggle.setAttribute("aria-expanded", "false");
        document.body.classList.remove("nav-open");
    }

    navToggle.addEventListener("click", toggleMenu);

    // Close on navigation link click
    navLinks.querySelectorAll("a").forEach(link => {
        link.addEventListener("click", closeMenu);
    });

    // Close on Escape key
    document.addEventListener("keydown", e => {
        if (e.key === "Escape" && navLinks.classList.contains("open")) {
            closeMenu();
        }
    });

    // Auto-close if resized to desktop viewport
    window.addEventListener("resize", () => {
        if (window.innerWidth > 768 && navLinks.classList.contains("open")) {
            closeMenu();
        }
    }, { passive: true });
})();


// =============================================================================
// Dynamic Vertical Timeline Section Spy & Fluid Beam Progress (Glassmorphism Capsule 2.0)
// =============================================================================
(function() {
    const timeline = document.querySelector('.vertical-timeline');
    const nodes = document.querySelectorAll('.vertical-timeline .timeline-node');
    const progressBar = document.getElementById('timeline-progress-bar');
    const trackBg = document.querySelector('.timeline-track-bg');
    if (!timeline || !nodes.length) return;

    const sections = Array.from(nodes).map(node => {
        const id = node.getAttribute('data-section');
        return document.getElementById(id);
    }).filter(Boolean);

    function alignTrack() {
        if (trackBg && nodes.length > 1) {
            const firstDot = nodes[0].querySelector('.timeline-dot');
            const lastDot = nodes[nodes.length - 1].querySelector('.timeline-dot');
            if (firstDot && lastDot) {
                const timelineRect = timeline.getBoundingClientRect();
                const firstRect = firstDot.getBoundingClientRect();
                const lastRect = lastDot.getBoundingClientRect();
                const topOffset = (firstRect.top + firstRect.height / 2) - timelineRect.top;
                const totalHeight = (lastRect.top + lastRect.height / 2) - (firstRect.top + firstRect.height / 2);
                trackBg.style.top = topOffset + 'px';
                trackBg.style.height = totalHeight + 'px';
                trackBg.style.bottom = 'auto';
            }
        }
    }

    function updateTimeline() {
        const scrollY = window.scrollY;
        const triggerPos = scrollY + window.innerHeight * 0.38;
        let activeIdx = 0;

        sections.forEach((sec, idx) => {
            if (triggerPos >= sec.offsetTop) {
                activeIdx = idx;
            }
        });

        // If scrolled to bottom, highlight the final section
        if (window.innerHeight + scrollY >= document.documentElement.scrollHeight - 60) {
            activeIdx = sections.length - 1;
        }

        nodes.forEach((node, idx) => {
            if (idx === activeIdx) {
                node.classList.add('active');
            } else {
                node.classList.remove('active');
            }
        });

        // Precisely connect progress beam from first dot to active dot center
        if (progressBar && nodes.length > 1) {
            const firstDot = nodes[0].querySelector('.timeline-dot');
            const activeDot = nodes[activeIdx]?.querySelector('.timeline-dot');
            
            if (firstDot && activeDot) {
                const timelineRect = timeline.getBoundingClientRect();
                const firstRect = firstDot.getBoundingClientRect();
                const activeRect = activeDot.getBoundingClientRect();
                
                const topOffset = (firstRect.top + firstRect.height / 2) - timelineRect.top;
                const activeCenter = (activeRect.top + activeRect.height / 2) - timelineRect.top;
                const fillHeight = Math.max(0, activeCenter - topOffset);
                
                progressBar.style.top = topOffset + 'px';
                progressBar.style.height = fillHeight + 'px';
            }
        }
    }

    window.addEventListener('scroll', updateTimeline, { passive: true });
    window.addEventListener('resize', () => {
        alignTrack();
        updateTimeline();
    }, { passive: true });

    // Initial setup
    alignTrack();
    updateTimeline();

    // Smooth navigation click
    nodes.forEach(node => {
        node.addEventListener('click', e => {
            const id = node.getAttribute('data-section');
            const target = document.getElementById(id);
            if (target) {
                e.preventDefault();
                target.scrollIntoView({ behavior: 'smooth' });
            }
        });
    });
})();

// Interactive Copy Code Snippet Controller
(function() {
    function initCodeSnippets() {
        // Find any <div class="code-snippet"> or plain <pre> elements not yet wrapped
        const preElements = document.querySelectorAll('pre');
        const copyIconSvg = '<svg viewBox="0 0 24 24"><path d="M16 1H4C2.9 1 2 1.9 2 3V17H4V3H16V1ZM19 5H8C6.9 5 6 5.9 6 7V21C6 22.1 6.9 23 8 23H19C20.1 23 21 22.1 21 21V7C21 5.9 20.1 5 19 5ZM19 21H8V7H19V21Z"/></svg>';
        const checkIconSvg = '<svg viewBox="0 0 24 24"><path d="M9 16.2L4.8 12L3.4 13.4L9 19L21 7L19.6 5.6L9 16.2Z"/></svg>';

        preElements.forEach(pre => {
            let wrapper = pre.parentElement;
            if (!wrapper || !wrapper.classList.contains('code-snippet')) {
                wrapper = document.createElement('div');
                wrapper.className = 'code-snippet';
                pre.parentNode.insertBefore(wrapper, pre);
                wrapper.appendChild(pre);
            }

            // Ensure only one copy button per snippet container
            if (wrapper.querySelector('.btn-copy-code')) return;

            const btn = document.createElement('button');
            btn.className = 'btn-copy-code';
            btn.setAttribute('type', 'button');
            btn.setAttribute('aria-label', 'Copy code to clipboard');
            btn.innerHTML = `${copyIconSvg}<span>Copy</span>`;

            btn.addEventListener('click', async () => {
                const codeEl = pre.querySelector('code') || pre;
                const textToCopy = codeEl.innerText.trim();

                try {
                    if (navigator.clipboard && window.isSecureContext) {
                        await navigator.clipboard.writeText(textToCopy);
                    } else {
                        // Fallback for non-https/local file viewing
                        const textarea = document.createElement('textarea');
                        textarea.value = textToCopy;
                        textarea.style.position = 'fixed';
                        textarea.style.opacity = '0';
                        document.body.appendChild(textarea);
                        textarea.focus();
                        textarea.select();
                        document.execCommand('copy');
                        document.body.removeChild(textarea);
                    }

                    btn.classList.add('copied');
                    btn.innerHTML = `${checkIconSvg}<span>Copied!</span>`;

                    setTimeout(() => {
                        btn.classList.remove('copied');
                        btn.innerHTML = `${copyIconSvg}<span>Copy</span>`;
                    }, 2000);
                } catch (err) {
                    console.error('Failed to copy code snippet: ', err);
                }
            });

            wrapper.appendChild(btn);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCodeSnippets);
    } else {
        initCodeSnippets();
    }
})();

