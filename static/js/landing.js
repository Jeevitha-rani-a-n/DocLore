(() => {
    const nav = document.querySelector(".landing-nav");
    const menuButton = document.querySelector(".mobile-menu");
    const themeButton = document.querySelector(".theme-toggle");
    const signupForm = document.querySelector("#signupForm");
    const loginForm = document.querySelector("#loginForm");
    const authTitle = document.querySelector("#authTitle");
    const authSubtitle = document.querySelector("#authSubtitle");
    const switchText = document.querySelector("#authSwitchText");
    const switchButton = document.querySelector("#authSwitch");

    function setAuthMode(mode, scroll = false) {
        const login = mode === "login";
        signupForm.classList.toggle("hidden", login);
        loginForm.classList.toggle("hidden", !login);
        authTitle.textContent = login ? "Welcome back" : "Create your account";
        authSubtitle.textContent = login ? "Log in to continue to your documents." : "Start asking your documents in minutes.";
        switchText.textContent = login ? "New to DocLore?" : "Already have an account?";
        switchButton.textContent = login ? "Sign up" : "Log in";
        switchButton.dataset.authMode = login ? "signup" : "login";
        if (scroll) document.querySelector("#signup").scrollIntoView({ behavior: "smooth" });
    }

    document.querySelectorAll("[data-auth-mode]").forEach((button) => {
        button.addEventListener("click", () => setAuthMode(button.dataset.authMode, true));
    });
    document.querySelectorAll('a[href="#signup"]').forEach((link) => link.addEventListener("click", () => setAuthMode("signup")));
    setAuthMode(new URLSearchParams(window.location.search).get("mode"));

    const savedTheme = localStorage.getItem("doclore-theme");
    if (savedTheme === "light") document.body.classList.add("light-landing");
    themeButton?.addEventListener("click", () => {
        document.body.classList.toggle("light-landing");
        localStorage.setItem("doclore-theme", document.body.classList.contains("light-landing") ? "light" : "dark");
    });

    menuButton?.addEventListener("click", () => {
        const open = nav.classList.toggle("menu-open");
        menuButton.setAttribute("aria-expanded", String(open));
        menuButton.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    });
    document.querySelectorAll(".landing-links a").forEach((link) => link.addEventListener("click", () => {
        nav.classList.remove("menu-open");
        menuButton?.setAttribute("aria-expanded", "false");
    }));

    const revealItems = document.querySelectorAll(".reveal");
    if ("IntersectionObserver" in window) {
        const observer = new IntersectionObserver((entries, currentObserver) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-visible");
                    currentObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12 });
        revealItems.forEach((item) => observer.observe(item));
    } else {
        revealItems.forEach((item) => item.classList.add("is-visible"));
    }

    const heroVisual = document.querySelector(".hero-visual");
    let scrollFrame = 0;
    window.addEventListener("scroll", () => {
        if (!heroVisual || window.matchMedia("(prefers-reduced-motion: reduce)").matches || scrollFrame) return;
        scrollFrame = window.requestAnimationFrame(() => {
            const offset = Math.min(window.scrollY * 0.08, 35);
            heroVisual.style.translate = `0 ${offset}px`;
            scrollFrame = 0;
        });
    }, { passive: true });

    const useCases = {
        university: {
            label: "01 / UNIVERSITY",
            heading: "Help students find the rule, not just the PDF.",
            description: "Ask about appeals, attendance, course requirements, or campus policies and check the cited handbook page.",
            question: "“What is the deadline to appeal an academic decision?”",
            source: "Answer linked to page 18"
        },
        compliance: {
            label: "02 / COMPLIANCE",
            heading: "Make policy answers easier to verify.",
            description: "Find the relevant requirement in a policy manual and follow each answer back to its source passage.",
            question: "“How soon must an incident be reported?”",
            source: "Example source: Reporting Policy · page 7"
        },
        grants: {
            label: "03 / GRANTS",
            heading: "Spend less time hunting through guidelines.",
            description: "Ask about eligibility, deadlines, and application requirements across grant documents.",
            question: "“Which costs are eligible for reimbursement?”",
            source: "Example source: Grant Guide · page 12"
        }
    };
    const panel = document.querySelector("#usecasePanel");
    document.querySelectorAll(".usecase-tabs [role='tab']").forEach((tab) => tab.addEventListener("click", () => {
        const key = tab.id.replace("tab-", "");
        const data = useCases[key];
        if (!data) return;
        document.querySelectorAll(".usecase-tabs [role='tab']").forEach((item) => item.setAttribute("aria-selected", String(item === tab)));
        panel.setAttribute("aria-labelledby", tab.id);
        panel.querySelector(".usecase-mark").textContent = data.label;
        panel.querySelector("h3").textContent = data.heading;
        panel.querySelector(".usecase-panel-copy").textContent = data.description;
        panel.querySelector("#usecaseQuestion").textContent = data.question;
        panel.querySelector(".quote-source").textContent = data.source;
    }));

    const demoExamples = [
        { match: /attendance|absen/i, answer: "The sample handbook requires students to attend at least 80% of scheduled classes. Check the attendance policy in your own handbook for its exact rule.", source: "Attendance Policy · Page 9" },
        { match: /appeal|decision/i, answer: "The sample says an appeal is due within 10 working days after the decision. The real deadline depends on the document you upload.", source: "Academic Appeals · Page 18" },
        { match: /grant|eligible|reimburse|cost/i, answer: "The sample guidelines say approved travel and project materials may qualify. Eligibility depends on the specific grant rules.", source: "Sample Grant Guide · Page 12" },
        { match: /deadline|due date/i, answer: "The sample handbook lists a 10 working day review period. Upload your document in the workspace to get its actual deadline and citation.", source: "Sample Handbook · Page 18" },
    ];
    const demoForm = document.querySelector("#demoForm");
    const demoInput = document.querySelector("#demoInput");
    const demoThread = document.querySelector("#demoThread");
    demoForm?.addEventListener("submit", (event) => {
        event.preventDefault();
        const question = demoInput.value.trim();
        if (!question) return;
        const example = demoExamples.find((item) => item.match.test(question)) || {
            answer: "This preview can only show sample handbook information. Upload your own PDF in the workspace to get an answer grounded in its text.",
            source: "Sample preview · not from an uploaded document"
        };

        const userMessage = document.createElement("div");
        userMessage.className = "demo-message demo-user";
        const userAvatar = document.createElement("span");
        userAvatar.className = "demo-avatar";
        userAvatar.textContent = "Y";
        const userContent = document.createElement("div");
        const userLabel = document.createElement("small");
        userLabel.textContent = "You";
        const userText = document.createElement("p");
        userText.textContent = question;
        userContent.append(userLabel, userText);
        userMessage.append(userAvatar, userContent);

        const assistantMessage = document.createElement("div");
        assistantMessage.className = "demo-message demo-assistant";
        const assistantAvatar = document.createElement("span");
        assistantAvatar.className = "demo-avatar";
        assistantAvatar.textContent = "✳";
        const assistantContent = document.createElement("div");
        const assistantLabel = document.createElement("small");
        assistantLabel.textContent = "DocLore · sample answer";
        const assistantText = document.createElement("p");
        assistantText.textContent = example.answer;
        const source = document.createElement("span");
        source.className = "demo-source demo-source-label";
        source.textContent = `↗ ${example.source}`;
        assistantContent.append(assistantLabel, assistantText, source);
        assistantMessage.append(assistantAvatar, assistantContent);
        demoThread.append(userMessage, assistantMessage);
        demoThread.scrollTop = demoThread.scrollHeight;
        demoInput.value = "";
        demoInput.focus();
    });
})();
