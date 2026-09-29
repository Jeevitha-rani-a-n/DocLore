(() => {
    const storageKey = "doclore-sounds-muted";
    const sounds = ["#uiClickSound", "#assistantReplySound"]
        .map((selector) => document.querySelector(selector))
        .filter(Boolean);
    let muted = false;

    try { muted = localStorage.getItem(storageKey) === "true"; }
    catch { /* Sound settings still work for this page if storage is unavailable. */ }

    const applyState = () => {
        sounds.forEach((sound) => { sound.muted = muted; });
        document.querySelectorAll(".sound-toggle").forEach((button) => {
            button.classList.toggle("is-muted", muted);
            button.setAttribute("aria-pressed", String(muted));
            button.setAttribute("aria-label", muted ? "Unmute website sounds" : "Mute website sounds");
            button.title = muted ? "Unmute website sounds" : "Mute website sounds";
        });
    };

    applyState();
    document.querySelectorAll(".sound-toggle").forEach((button) => {
        button.addEventListener("click", () => {
            muted = !muted;
            try { localStorage.setItem(storageKey, String(muted)); }
            catch { /* Keep the updated state in memory for this page. */ }
            applyState();
        });
    });
})();
