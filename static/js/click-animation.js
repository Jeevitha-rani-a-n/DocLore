(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    document.addEventListener("click", (event) => {
        if (reduceMotion.matches) return;

        let x = event.clientX;
        let y = event.clientY;
        if (event.detail === 0 && event.target instanceof Element) {
            const bounds = event.target.getBoundingClientRect();
            x = bounds.left + bounds.width / 2;
            y = bounds.top + bounds.height / 2;
        }

        const burst = document.createElement("span");
        burst.className = "click-burst";
        burst.setAttribute("aria-hidden", "true");
        burst.style.left = `${x}px`;
        burst.style.top = `${y}px`;
        for (let index = 0; index < 8; index += 1) {
            const spark = document.createElement("i");
            spark.style.setProperty("--spark-angle", `${index * 45}deg`);
            burst.append(spark);
        }
        document.body.append(burst);
        window.setTimeout(() => burst.remove(), 500);
    }, true);
})();
