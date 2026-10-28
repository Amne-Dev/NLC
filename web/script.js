// Auto-update version from GitHub
fetch('https://api.github.com/repos/Amne-Dev/NLC/releases/latest')
    .then(response => response.json())
    .then(data => {
        if(data.tag_name) {
            // Remove 'v' prefix if present for cleaner display
            const ver = data.tag_name.replace(/^v/, '');
            const versionEl = document.getElementById('version-text');
            if (versionEl) {
                versionEl.innerText = `Version ${ver} • Open Source • Free`;
            }
        }
    })
    .catch(e => console.error("Could not fetch version", e));

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
// Dynamic Vertical Timeline Section Spy & Fluid Beam Progress (Right Rail)
// =============================================================================
(function() {
    const nodes = document.querySelectorAll('.vertical-timeline .timeline-node');
    const progressBar = document.getElementById('timeline-progress-bar');
    if (!nodes.length) return;

    const sections = Array.from(nodes).map(node => {
        const id = node.getAttribute('data-section');
        return document.getElementById(id);
    }).filter(Boolean);

    function updateTimeline() {
        const scrollY = window.scrollY;
        const docHeight = document.documentElement.scrollHeight - window.innerHeight;
        
        // Fluid progress beam fill
        if (progressBar && docHeight > 0) {
            const progress = Math.min(Math.max(scrollY / docHeight, 0), 1);
            progressBar.style.height = `${progress * 100}%`;
        }

        // Active node detection
        const triggerPos = scrollY + window.innerHeight * 0.38;
        let currentSectionId = sections[0]?.id;

        for (const sec of sections) {
            if (triggerPos >= sec.offsetTop) {
                currentSectionId = sec.id;
            }
        }

        nodes.forEach(node => {
            if (node.getAttribute('data-section') === currentSectionId) {
                node.classList.add('active');
            } else {
                node.classList.remove('active');
            }
        });
    }

    window.addEventListener('scroll', updateTimeline, { passive: true });
    window.addEventListener('resize', updateTimeline, { passive: true });
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
