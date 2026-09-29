(() => {
    const form = document.querySelector("#profileForm");
    const avatarInput = document.querySelector("#selectedAvatar");
    const avatarPreview = document.querySelector("#identityAvatar");
    const nameInput = document.querySelector("#displayName");
    const namePreview = document.querySelector("#identityName");
    const roleInput = document.querySelector("#profileRole");
    const rolePreview = document.querySelector(".profile-identity-copy > span");
    const darkMode = document.querySelector("#darkMode");
    const saveNote = document.querySelector("#profileSaveNote");

    document.querySelectorAll(".avatar-choice").forEach((button) => {
        button.addEventListener("click", () => {
            document.querySelectorAll(".avatar-choice").forEach((choice) => {
                const selected = choice === button;
                choice.classList.toggle("selected", selected);
                choice.setAttribute("aria-pressed", String(selected));
            });
            avatarInput.value = button.dataset.avatar;
            avatarPreview.textContent = button.dataset.avatar;
            avatarPreview.classList.remove("avatar-pop");
            requestAnimationFrame(() => avatarPreview.classList.add("avatar-pop"));
            window.setTimeout(() => avatarPreview.classList.remove("avatar-pop"), 220);
            saveNote.textContent = "Unsaved changes";
        });
    });

    nameInput.addEventListener("input", () => {
        namePreview.textContent = nameInput.value.trim() || "Your name";
        saveNote.textContent = "Unsaved changes";
    });
    roleInput.addEventListener("change", () => {
        rolePreview.textContent = roleInput.value;
        saveNote.textContent = "Unsaved changes";
    });
    document.querySelectorAll(".profile-form input, .profile-form select").forEach((field) => {
        field.addEventListener("change", () => { saveNote.textContent = "Unsaved changes"; });
    });
    darkMode.addEventListener("change", () => {
        document.body.classList.toggle("light-theme", !darkMode.checked);
    });

    form.addEventListener("submit", () => {
        saveNote.textContent = "Saving your profile…";
        const userId = form.dataset.userId;
        const stateKey = `rag-workspace-v1:${userId}`;
        const theme = darkMode.checked ? "dark" : "light";
        try {
            const state = JSON.parse(localStorage.getItem(stateKey) || "{}");
            state.theme = theme;
            localStorage.setItem(stateKey, JSON.stringify(state));
        } catch { /* The server still saves the profile when browser storage is unavailable. */ }
    });
})();
