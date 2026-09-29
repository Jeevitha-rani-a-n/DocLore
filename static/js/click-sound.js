(() => {
    const clickSound = document.querySelector("#uiClickSound");
    if (!clickSound) return;
    try { clickSound.muted = localStorage.getItem("doclore-sounds-muted") === "true"; }
    catch { /* Sound controls can initialize the local state later. */ }

    document.addEventListener("click", (event) => {
        if (event.target.closest(".sound-toggle")) return;
        const control = event.target.closest("button, a, input, select, textarea, summary, [role='button']");
        if (!control || control.disabled || control.getAttribute("aria-disabled") === "true" || clickSound.muted) return;

        clickSound.pause();
        clickSound.currentTime = 0;
        clickSound.play().catch(() => {});
    }, true);
})();
