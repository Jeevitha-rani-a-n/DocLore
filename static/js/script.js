const $ = (selector) => document.querySelector(selector);
const chatBox = $("#chatBox");
const questionInput = $("#question");
const askBtn = $("#askBtn");
const pdfInput = $("#pdf");
const composerUploadBtn = $("#composerUploadBtn");
const pdfFrame = $("#pdfFrame");
const toastRegion = $("#toastRegion");
const workspaceGrid = $(".workspace-grid");

let documentInfo = null;
let documents = [];
let conversations = [];
let selectedConversationId = null;
let busy = false;
let allHandbooksSelected = true;
let zoom = 100;
let sidebarVisible = true;
let documentVisible = true;

function readPaneWidth(key) {
    try { return parseInt(localStorage.getItem(key), 10); }
    catch { return NaN; }
}

function savePaneWidth(key, value) {
    try { localStorage.setItem(key, value); }
    catch { /* Resizing still works when browser storage is unavailable. */ }
}

function setPanelVisibility(panel, visible) {
    const isSidebar = panel === "sidebar";
    const className = isSidebar ? "hide-sidebar" : "hide-document";
    const button = isSidebar ? $("#toggleSidebarBtn") : $("#toggleDocumentBtn");
    const label = isSidebar ? "conversation history" : "PDF viewer";
    workspaceGrid.classList.toggle(className, !visible);
    button.setAttribute("aria-pressed", String(visible));
    button.setAttribute("aria-label", `${visible ? "Hide" : "Show"} ${label}`);
    button.title = `${visible ? "Hide" : "Show"} ${label}`;
    button.querySelector(".edge-toggle-icon").textContent = isSidebar
        ? (visible ? "‹" : "›")
        : (visible ? "›" : "‹");
    if (isSidebar) sidebarVisible = visible;
    else documentVisible = visible;
}

function setPaneWidth(side, width) {
    const isLeft = side === "left";
    const minimum = isLeft ? 230 : 300;
    const otherProperty = isLeft ? "--document-width" : "--sidebar-width";
    const otherVisible = isLeft ? documentVisible : sidebarVisible;
    const otherWidth = otherVisible ? (parseInt(getComputedStyle(workspaceGrid).getPropertyValue(otherProperty), 10) || (isLeft ? 380 : 300)) : 0;
    const available = workspaceGrid.clientWidth - 32 - otherWidth - 360 - (otherVisible ? 14 : 0);
    const maximum = Math.max(minimum, Math.min(isLeft ? 460 : 560, available));
    const bounded = Math.round(Math.max(minimum, Math.min(maximum, width)));
    workspaceGrid.style.setProperty(isLeft ? "--sidebar-width" : "--document-width", `${bounded}px`);
    const handle = isLeft ? $("#leftResizer") : $("#rightResizer");
    handle.setAttribute("aria-valuemin", String(minimum));
    handle.setAttribute("aria-valuemax", String(maximum));
    handle.setAttribute("aria-valuenow", String(bounded));
    return bounded;
}

function setupResizer(handleId, side) {
    const handle = $(handleId);
    let dragging = false;
    const resizeAt = (clientX) => {
        const rect = workspaceGrid.getBoundingClientRect();
        const width = side === "left" ? clientX - rect.left - 16 : rect.right - clientX - 16;
        setPaneWidth(side, width);
    };
    handle.addEventListener("pointerdown", (event) => {
        if (window.innerWidth <= 1120) return;
        dragging = true;
        handle.classList.add("dragging");
        handle.setPointerCapture(event.pointerId);
        resizeAt(event.clientX);
    });
    handle.addEventListener("pointermove", (event) => {
        if (dragging) resizeAt(event.clientX);
    });
    const finish = () => {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove("dragging");
        const property = side === "left" ? "--sidebar-width" : "--document-width";
        savePaneWidth(`rag-${side}-panel-width`, workspaceGrid.style.getPropertyValue(property));
    };
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
    handle.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        const current = parseInt(getComputedStyle(workspaceGrid).getPropertyValue(side === "left" ? "--sidebar-width" : "--document-width"), 10);
        const direction = event.key === "ArrowRight" ? 1 : -1;
        const adjusted = setPaneWidth(side, current + direction * 20);
        const property = side === "left" ? "--sidebar-width" : "--document-width";
        savePaneWidth(`rag-${side}-panel-width`, `${adjusted}px`);
    });
}

function setupPanelControls() {
    const leftWidth = readPaneWidth("rag-left-panel-width");
    const rightWidth = readPaneWidth("rag-right-panel-width");
    if (leftWidth) setPaneWidth("left", leftWidth);
    else setPaneWidth("left", 300);
    if (rightWidth) setPaneWidth("right", rightWidth);
    else setPaneWidth("right", 380);
    $("#toggleSidebarBtn").addEventListener("click", () => setPanelVisibility("sidebar", !sidebarVisible));
    $("#toggleDocumentBtn").addEventListener("click", () => setPanelVisibility("document", !documentVisible));
    setupResizer("#leftResizer", "left");
    setupResizer("#rightResizer", "right");
}

const STORE_KEY = `rag-workspace-v1:${document.body.dataset.userId || "guest"}`;

function saveState() {
    try {
        const keep = conversations.filter((item) => item.messages.length || item.id === selectedConversationId);
        localStorage.setItem(STORE_KEY, JSON.stringify({
            conversations: keep,
            selectedConversationId,
            theme: document.body.classList.contains("light-theme") ? "light" : "dark"
        }));
    } catch { /* storage unavailable: keep working in memory */ }
}

function loadState() {
    try {
        const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
        if (!saved) return;
        conversations = Array.isArray(saved.conversations) ? saved.conversations : [];
        selectedConversationId = saved.selectedConversationId || null;
        const theme = document.body.dataset.profileTheme || saved.theme || "dark";
        document.body.classList.toggle("light-theme", theme === "light");
    } catch { conversations = []; }
}

function toggleTheme() {
    document.body.classList.toggle("light-theme");
    saveState();
    const theme = document.body.classList.contains("light-theme") ? "light" : "dark";
    fetch("/profile/theme", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ theme, csrf_token: document.body.dataset.csrfToken || "" })
    }).then((response) => {
        if (!response.ok) throw new Error("Theme preference could not be saved.");
        document.body.dataset.profileTheme = theme;
    }).catch((error) => toast(error.message || "Theme preference could not be saved.", true));
}

function toast(message, isError = false) {
    const item = document.createElement("div");
    item.className = `toast${isError ? " error" : ""}`;
    item.textContent = message;
    toastRegion.append(item);
    window.setTimeout(() => item.remove(), 3200);
}

function currentConversation() {
    return conversations.find((item) => item.id === selectedConversationId) || null;
}

function timestamp(date = new Date()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function escapeFragment(value) {
    return encodeURIComponent(value).replaceAll("%20", "+");
}

function refreshPdfView(forceReload = false, pageJumpOnly = false) {
    if (!documentInfo) return;
    const page = Number($("#pageNumber").value) || 1;
    const targetPage = Math.max(1, Math.floor(page));
    const term = pageJumpOnly ? "" : $("#pdfSearch").value.trim();
    const hash = `#page=${targetPage}&zoom=${zoom}${term ? `&search=${escapeFragment(term)}` : ""}`;
    const pdfUrl = new URL(documentInfo.url, window.location.href);
    // Citation navigation opens the original PDF directly; do not request a
    // server-generated highlighted copy.
    pdfUrl.searchParams.delete("highlight");
    if (forceReload) pdfUrl.searchParams.set("citation", String(Date.now()));
    pdfFrame.src = `${pdfUrl.href}${hash}`;
}

function navigateToCitation(source, citedDocumentId = null) {
    const sourceDocumentId = source.match(/\[Document ID:\s*([^\]]+)\]/i)?.[1]?.trim();
    const targetDocumentId = sourceDocumentId || citedDocumentId;
    if (targetDocumentId && documentInfo?.id !== targetDocumentId) {
        const citedDocument = documents.find((item) => item.id === targetDocumentId);
        if (!citedDocument) {
            toast("The PDF for this citation is no longer available.", true);
            return;
        }
        selectDocument(targetDocumentId);
    }
    if (!documentInfo) {
        toast("The cited PDF is not available. Upload it again to view this citation.", true);
        return;
    }
    const pageMatch = source.match(/\[Page\s+(\d+)\]/i);
    const requestedPage = pageMatch ? Number(pageMatch[1]) : 1;
    const page = Math.max(1, requestedPage);
    $("#pageNumber").value = String(page);
    $("#pdfSearch").value = "";
    setPanelVisibility("document", true);
    refreshPdfView(true, true);
}

function renderConversations() {
    const activeRoot = $("#activeConversations");
    const search = $("#historySearch").value.trim().toLowerCase();
    const handbook = $("#handbookFilter").value;
    activeRoot.replaceChildren();
    const visible = conversations.filter((item) => {
        const messageText = item.messages.map((message) => message.text).join(" ");
        const label = `${item.title} ${item.documentName || ""} ${messageText}`.toLowerCase();
        return label.includes(search) && (handbook === "all" || item.documentId === handbook);
    });

    const appendGroup = (root, items, emptyText) => {
        if (!items.length) {
            const empty = document.createElement("p");
            empty.className = "conversation-empty";
            empty.textContent = emptyText;
            root.append(empty);
            return;
        }
        items.forEach((conversation) => {
            const entry = document.createElement("div");
            entry.className = "conversation-entry";
            const button = document.createElement("button");
            button.type = "button";
            button.className = `conversation-item${conversation.id === selectedConversationId ? " active" : ""}`;
            const icon = document.createElement("span");
            icon.className = "conversation-icon";
            icon.textContent = "▤";
            const copy = document.createElement("span");
            copy.className = "conversation-copy";
            const title = document.createElement("span");
            title.className = "conversation-title";
            title.textContent = conversation.title;
            const when = document.createElement("span");
            when.className = "conversation-time";
            when.textContent = timestamp(new Date(conversation.updatedAt));
            copy.append(title);
            button.append(icon, copy, when);
            button.addEventListener("click", () => {
                selectedConversationId = conversation.id;
                allHandbooksSelected = Boolean(conversation.allDocuments);
                $("#handbookFilter").value = conversation.allDocuments ? "all" : (conversation.documentId || "all");
                if (documents.some((doc) => doc.id === conversation.documentId)) selectDocument(conversation.documentId);
                else renderAll();
            });
            entry.append(button);
            if (conversation.id !== selectedConversationId) {
                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "conversation-delete-button delete-conversation-button";
                remove.textContent = "×";
                remove.title = "Delete conversation";
                remove.setAttribute("aria-label", remove.title);
                remove.addEventListener("click", () => deleteConversation(conversation.id));
                entry.append(remove);
            }
            if (conversation.id === selectedConversationId) {
                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "conversation-delete-button";
                remove.textContent = "✕";
                remove.title = "Delete conversation";
                remove.setAttribute("aria-label", remove.title);
                remove.addEventListener("click", () => deleteConversation(conversation.id));
                entry.append(remove);
            }
            root.append(entry);
        });
    };

    const active = visible.sort((a, b) => b.updatedAt - a.updatedAt);
    appendGroup(activeRoot, active, conversations.length ? "No matching conversations." : "Your conversations will appear here.");
    $("#conversationCount").textContent = String(active.length);

    const filter = $("#handbookFilter");
    const previous = filter.value;
    const knownDocuments = [...new Map([
        ...documents.map((item) => [item.id, item.filename]),
        ...conversations.filter((item) => item.documentId).map((item) => [item.documentId, item.documentName])
    ]).entries()];
    filter.replaceChildren(new Option("All handbooks", "all"));
    knownDocuments.forEach(([id, name]) => filter.add(new Option(name, id)));
    if (knownDocuments.some(([id]) => id === previous)) filter.value = previous;

    const quick = $("#quickHandbooks");
    quick.replaceChildren();
    if (!documents.length) {
        const empty = document.createElement("p");
        empty.className = "sidebar-empty";
        empty.textContent = "Upload a PDF to add it here.";
        quick.append(empty);
    } else {
        documents.forEach((doc) => {
            const row = document.createElement("div");
            row.className = "handbook-entry";
            const link = document.createElement("button");
            link.type = "button";
            link.className = "handbook-link";
            const icon = document.createElement("span");
            icon.textContent = "▧";
            const name = document.createElement("span");
            name.textContent = doc.filename;
            link.append(icon, name);
            link.addEventListener("click", () => openDocument(doc.id));
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "handbook-delete-button";
            remove.textContent = "x";
            remove.title = `Delete ${doc.filename} permanently`;
            remove.setAttribute("aria-label", `Delete ${doc.filename} permanently`);
            remove.addEventListener("click", () => deleteDocument(doc.id));
            row.append(link, remove);
            quick.append(row);
        });
    }
}

async function deleteDocument(documentId) {
    const target = documents.find((doc) => doc.id === documentId);
    if (!target || !window.confirm(`Permanently delete "${target.filename}" and its uploaded PDF? This cannot be undone.`)) return;
    try {
        const response = await fetch(`/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "Could not delete the document.");

        documents = documents.filter((doc) => doc.id !== documentId);
        conversations = conversations.filter((item) => item.documentId !== documentId);
        if (documentInfo?.id === documentId) {
            resetViewer();
            selectedConversationId = null;
            if (documents.length) {
                selectDocument(documents[0].id);
                ensureConversationFor(documents[0].id);
            }
        }
        renderAll();
        toast("Handbook and uploaded PDF permanently deleted.");
    } catch (error) {
        toast(error.message || "Could not delete the document.", true);
    }
}

function createCopyButton(text, label, successMessage) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-btn";
    button.setAttribute("aria-label", label);
    button.title = label;
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("aria-hidden", "true");
    const front = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    front.setAttribute("x", "8"); front.setAttribute("y", "8");
    front.setAttribute("width", "12"); front.setAttribute("height", "12");
    front.setAttribute("rx", "2");
    const back = document.createElementNS("http://www.w3.org/2000/svg", "path");
    back.setAttribute("d", "M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3");
    icon.append(front, back);
    button.append(icon);
    button.addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(text);
            toast(successMessage);
        } catch {
            toast("Clipboard access is unavailable in this browser.", true);
        }
    });
    return button;
}

function createMessage(role, text, sources = [], isThinking = false, createdAt = Date.now(), timings = null, answerInfo = null, citedDocumentId = null) {
    const row = document.createElement("article");
    row.className = `message-row ${role === "user" ? "user-row" : "assistant-row"}${isThinking ? " thinking-row" : ""}`;
    const avatar = document.createElement("div");
    avatar.className = `avatar ${role === "user" ? "user-avatar" : "assistant-avatar"}`;
    avatar.setAttribute("aria-hidden", "true");
    const content = document.createElement("div");
    content.className = "message-content";
    const meta = document.createElement("p");
    meta.className = "message-meta";
    const who = document.createElement("span");
    who.textContent = role === "user" ? "You" : "AI Assistant";
    const time = document.createElement("time");
    time.textContent = ` · ${timestamp(new Date(createdAt))}`;
    meta.append(who, time);
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    if (isThinking) {
        bubble.setAttribute("aria-label", "Generating answer");
        const dots = document.createElement("span");
        dots.className = "thinking-dots";
        dots.innerHTML = "<i></i><i></i><i></i>";
        bubble.append(dots);
    } else if (role === "assistant" && window.marked && window.DOMPurify) {
        bubble.classList.add("markdown");
        bubble.innerHTML = window.DOMPurify.sanitize(window.marked.parse(text || "", { breaks: true }));
    } else {
        bubble.textContent = text;
    }
    content.append(meta, bubble);

    if ((role === "assistant" || role === "user") && !isThinking) {
        const tools = document.createElement("div");
        tools.className = role === "assistant" ? "assistant-tools" : "user-tools";
        tools.append(createCopyButton(text, role === "assistant" ? "Copy answer" : "Copy question", role === "assistant" ? "Answer copied." : "Question copied."));
        content.append(tools);
    }
    let answerMetrics = null;
    if (role === "assistant" && !isThinking) {
        answerMetrics = document.createElement("div");
        answerMetrics.className = "answer-info-metrics";
        const metricRows = [
            ["Retrieval time", timings ? formatDuration(timings.retrieval_ms) : "Unavailable"],
            ["Generation time", timings ? formatDuration(timings.generation_ms) : "Unavailable"],
            ["Confidence", formatPercent(answerInfo?.confidence_score)],
            ["Grounding score", formatPercent(answerInfo?.grounding_score)]
        ];
        metricRows.forEach(([label, value]) => {
            const row = document.createElement("div");
            row.className = "answer-info-metric";
            const name = document.createElement("span");
            name.textContent = label;
            const reading = document.createElement("strong");
            reading.textContent = value;
            row.append(name, reading);
            answerMetrics.append(row);
        });
    }
    if (role === "assistant" && !isThinking && sources.length) {
        const citationDetails = document.createElement("details");
        citationDetails.className = "answer-citations";
        const citationSummary = document.createElement("summary");
        citationSummary.textContent = `Citations (${sources.length})`;
        citationDetails.append(citationSummary);
        const citationContent = document.createElement("div");
        citationContent.className = "answer-citation-content";
        const citationRow = document.createElement("div");
        citationRow.className = "answer-citation-links";
        sources.forEach((source, index) => {
            const pageMatch = source.match(/\[Page (\d+)\]/i);
            const sourceDocument = source.match(/\[Document:\s*([^\]]+)\]/i)?.[1];
            const citation = document.createElement("button");
            citation.type = "button";
            citation.className = "citation-link";
            citation.textContent = `${sourceDocument ? `${sourceDocument} · ` : ""}[${index + 1}]${pageMatch ? ` p. ${pageMatch[1]}` : ""}`;
            citation.title = `${sourceDocument ? `Open ${sourceDocument} · ` : ""}${pageMatch ? `open page ${pageMatch[1]} in the PDF viewer` : "open the cited PDF in the viewer"}`;
            citation.setAttribute("aria-label", citation.title);
            citation.addEventListener("click", () => navigateToCitation(source, citedDocumentId));
            citationRow.append(citation);
        });
        citationContent.append(citationRow);

        const sourceGroup = document.createElement("details");
        sourceGroup.className = "answer-sources";
        const sourceHeading = document.createElement("summary");
        sourceHeading.textContent = `Retrieved sources · ${sources.length} passage${sources.length === 1 ? "" : "s"}`;
        sourceGroup.append(sourceHeading);

        sources.forEach((source, index) => {
            const details = document.createElement("details");
            details.className = "source-card";
            const summary = document.createElement("summary");
            summary.textContent = `Passage ${index + 1}`;
            const excerpt = document.createElement("p");
            excerpt.textContent = source;
            const find = document.createElement("button");
            find.type = "button";
            find.className = "find-source-button";
            find.textContent = "Find in PDF";
            find.addEventListener("click", () => navigateToCitation(source, citedDocumentId));
            details.append(summary, excerpt, find);
            sourceGroup.append(details);
        });
        citationContent.append(sourceGroup);
        citationDetails.append(citationContent);
        content.append(citationDetails);
    }
    if (answerMetrics) content.append(answerMetrics);
    row.append(avatar, content);
    return row;
}

function renderMessages() {
    const conversation = currentConversation();
    chatBox.replaceChildren();
    if (!conversation || !conversation.messages.length) {
        const welcome = document.createElement("div");
        welcome.className = "welcome-state";
        welcome.innerHTML = `<div class="welcome-icon" aria-hidden="true"></div><p class="eyebrow">Document-grounded answers</p><h2>Ask your handbook anything</h2><p>Upload a PDF, then ask a question. Answers include the passages used so you can verify them against the document.</p><div class="example-prompts"><button class="prompt-chip" type="button">Summarize this document</button><button class="prompt-chip" type="button">What are the key points?</button><button class="prompt-chip" type="button">Who is the author?</button></div>`;
        chatBox.append(welcome);
        return;
    }
    conversation.messages.forEach((message) => chatBox.append(createMessage(message.role, message.text, message.sources || [], false, message.time, message.timings || null, message.answerInfo || null, message.documentId || conversation.documentId)));
    chatBox.scrollTop = chatBox.scrollHeight;
}

function formatDuration(milliseconds) {
    const value = Number(milliseconds);
    if (!Number.isFinite(value)) return "—";
    return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(2)} s`;
}

function formatPercent(value) {
    const score = Number(value);
    return Number.isFinite(score) ? `${Math.round(score)}%` : "Unavailable";
}

function playChatPopSound() {
    const sound = $("#assistantReplySound");
    if (!sound) return;
    sound.currentTime = 0;
    sound.play().catch(() => {});
}

function syncComposer() {
    const conversation = currentConversation();
    const matchesCurrentDoc = Boolean(conversation && documentInfo && conversation.documentId === documentInfo.id);
    const searchesAllDocuments = allHandbooksSelected || Boolean(conversation?.allDocuments);
    const composer = $(".prompt-composer");
    $("#composerDocument").classList.toggle("hidden", !documentInfo);
    composer.classList.toggle("has-document", Boolean(documentInfo));
    if (documentInfo) {
        $("#composerDocumentName").textContent = documentInfo.filename;
        $("#composerDocumentStatus").textContent = "Ready for questions";
    }
    questionInput.disabled = busy;
    askBtn.disabled = busy;
    composerUploadBtn.disabled = busy;
    if (searchesAllDocuments) $("#chatStatus").textContent = documents.length
        ? `Searching all ${documents.length} handbook${documents.length === 1 ? "" : "s"}`
        : "Upload a handbook PDF to start asking questions.";
    else if (!conversation) $("#chatStatus").textContent = documentInfo ? "Ask a question about this PDF." : "Upload a handbook PDF to start asking questions.";
    else if (!documentInfo) $("#chatStatus").textContent = "Upload a PDF to continue this conversation.";
    else if (!matchesCurrentDoc) $("#chatStatus").textContent = `This thread was for ${conversation.documentName}. Sending a message starts a new chat about ${documentInfo.filename}.`;
    else $("#chatStatus").textContent = `Asking about ${documentInfo.filename}`;
}

function renderAll() {
    renderConversations();
    renderMessages();
    syncComposer();
    saveState();
}

function resetViewer() {
    documentInfo = null;
    $("#documentTitle").textContent = "No handbook uploaded";
    $("#pdfEmpty").classList.remove("hidden");
    pdfFrame.classList.add("hidden");
    pdfFrame.src = "about:blank";
    $("#documentReadyBadge").textContent = "No document";
    $("#documentReadyBadge").classList.remove("ready");
    $("#pageNumber").disabled = true;
    $("#pageNumber").value = "1";
    $("#pageCount").textContent = "—";
    $("#documentDetails").classList.add("hidden");
}

function selectDocument(documentId) {
    const selected = documents.find((item) => item.id === documentId);
    if (!selected) return;
    documentInfo = selected;
    $("#documentTitle").textContent = selected.filename;
    $("#pdfEmpty").classList.add("hidden");
    pdfFrame.classList.remove("hidden");
    $("#documentReadyBadge").textContent = "Indexed";
    $("#documentReadyBadge").classList.add("ready");
    $("#pageNumber").disabled = false;
    $("#pageNumber").max = String(selected.pages || 1);
    $("#pageNumber").value = "1";
    $("#pageCount").textContent = String(selected.pages || "—");
    $("#docSize").textContent = `${selected.file_size} KB`;
    $("#docPages").textContent = String(selected.pages || "—");
    $("#docCharacters").textContent = Number(selected.characters).toLocaleString();
    $("#docChunks").textContent = String(selected.chunks);
    $("#docUploadTime").textContent = selected.uploaded_at;
    $("#documentDetails").classList.remove("hidden");
    refreshPdfView();
    renderAll();
}

function openDocument(documentId) {
    selectDocument(documentId);
    const existing = conversations
        .filter((conversation) => conversation.documentId === documentId)
        .sort((a, b) => b.updatedAt - a.updatedAt)[0];
    if (existing) {
        selectedConversationId = existing.id;
        renderAll();
    } else {
        newConversation();
    }
}

function ensureConversationFor(documentId) {
    const existing = conversations
        .filter((item) => item.documentId === documentId)
        .sort((a, b) => b.updatedAt - a.updatedAt)[0];
    if (existing) {
        selectedConversationId = existing.id;
        renderAll();
    } else {
        newConversation();
    }
}

function ensureConversationForAllDocuments() {
    const existing = conversations
        .filter((item) => item.allDocuments)
        .sort((a, b) => b.updatedAt - a.updatedAt)[0];
    if (existing) {
        selectedConversationId = existing.id;
        renderAll();
    } else {
        newConversation();
    }
}

function handleHandbookFilterChange() {
    const documentId = $("#handbookFilter").value;
    if (documentId === "all") {
        allHandbooksSelected = true;
        if (!documents.length) {
            renderConversations();
            toast("Upload at least one handbook to search all documents.", true);
            return;
        }
        ensureConversationForAllDocuments();
        questionInput.focus();
        return;
    }

    allHandbooksSelected = false;
    if (!documents.some((item) => item.id === documentId)) {
        renderConversations();
        toast("This handbook is not loaded in the workspace. Upload it again to chat with it.", true);
        return;
    }

    selectDocument(documentId);
    ensureConversationFor(documentId);
    questionInput.focus();
}

function deleteConversation(id) {
    conversations = conversations.filter((item) => item.id !== id);
    if (selectedConversationId === id) {
        const next = conversations
            .filter((item) => !documentInfo || item.documentId === documentInfo.id)
            .sort((a, b) => b.updatedAt - a.updatedAt)[0];
        selectedConversationId = next?.id || null;
    }
    renderAll();
    toast("Conversation deleted.");
}

function newConversation() {
    const allDocuments = allHandbooksSelected;
    const targetDocumentId = allDocuments ? null : (documentInfo?.id || null);
    const emptyChat = conversations.find((item) => !item.messages.length
        && Boolean(item.allDocuments) === allDocuments
        && item.documentId === targetDocumentId);
    if (emptyChat) {
        selectedConversationId = emptyChat.id;
        renderAll();
        questionInput.focus();
        return;
    }
    const conversation = {
        id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
        title: "New conversation",
        documentId: targetDocumentId,
        documentName: allDocuments ? "All handbooks" : (documentInfo?.filename || ""),
        updatedAt: Date.now(),
        messages: [],
        allDocuments
    };
    conversations.push(conversation);
    selectedConversationId = conversation.id;
    renderAll();
    questionInput.focus();
}

function clearCurrentConversation() {
    const conversation = currentConversation();
    if (!conversation || busy) return;
    conversation.messages = [];
    conversation.title = "New conversation";
    conversation.updatedAt = Date.now();
    renderAll();
    questionInput.focus();
}

async function uploadSelectedPdf() {
    const file = pdfInput.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf") || (file.type && file.type !== "application/pdf")) {
        toast("Please select a PDF file.", true);
        pdfInput.value = "";
        return;
    }
    $("#documentReadyBadge").textContent = "Indexing…";
    $("#chatStatus").textContent = "Uploading and indexing your PDF…";
    busy = true;
    syncComposer();
    $("#composerDocument").classList.remove("hidden");
    $(".prompt-composer").classList.add("has-document");
    $("#composerDocumentName").textContent = file.name;
    $("#composerDocumentStatus").textContent = "Uploading and indexing your PDF...";
    const body = new FormData();
    body.append("pdf", file);
    try {
        const response = await fetch("/upload", { method: "POST", body });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Upload failed.");
        const uploadedDocument = { ...data, url: data.document_url };
        documents.unshift(uploadedDocument);
        allHandbooksSelected = false;
        $("#handbookFilter").value = data.id;
        // chats saved before a server restart point to a document id that no longer exists;
        // re-attach them when the same file is uploaded again
        conversations.forEach((item) => {
            if (item.documentName === data.filename && !documents.some((doc) => doc.id === item.documentId)) item.documentId = data.id;
        });
        selectDocument(data.id);
        newConversation();
        toast("PDF uploaded and indexed.");
    } catch (error) {
        $("#documentReadyBadge").textContent = documentInfo ? "Previous document" : "Upload failed";
        toast(error.message || "Upload failed.", true);
    } finally {
        pdfInput.value = "";
        busy = false;
        syncComposer();
    }
}

function openPdfPicker() {
    if (busy) return;
    pdfInput.value = "";
    pdfInput.click();
}

async function submitQuestion(event) {
    event.preventDefault();
    const question = questionInput.value.trim();
    let conversation = currentConversation();
    if (!question || busy) return;
    const searchAllDocuments = allHandbooksSelected || Boolean(conversation?.allDocuments);
    if (searchAllDocuments) {
        if (!documents.length) {
            toast("Upload at least one handbook before asking a question.", true);
            return;
        }
        allHandbooksSelected = true;
        if (!conversation?.allDocuments) {
            ensureConversationForAllDocuments();
            conversation = currentConversation();
        }
    } else if (!documentInfo) {
        toast("Upload a PDF first. Your question is still in the prompt.", true);
        return;
    } else if (!conversation || conversation.documentId !== documentInfo.id) {
        ensureConversationFor(documentInfo.id);
        conversation = currentConversation();
    }
    if (!conversation) return;
    busy = true;
    conversation.messages.push({ role: "user", text: question, sources: [], time: Date.now() });
    if (conversation.title === "New conversation") conversation.title = question.length > 34 ? `${question.slice(0, 34)}…` : question;
    conversation.updatedAt = Date.now();
    questionInput.value = "";
    renderAll();
    playChatPopSound();
    chatBox.append(createMessage("assistant", "", [], true));
    chatBox.scrollTop = chatBox.scrollHeight;
    syncComposer();
    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, document_id: conversation.documentId, all_documents: Boolean(conversation.allDocuments) })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "The question could not be answered.");
        conversation.messages.push({
            role: "assistant",
            text: data.answer,
            sources: data.sources || [],
            timings: data.timings || null,
            answerInfo: data.answer_info || null,
            documentId: data.document_id || conversation.documentId,
            time: Date.now()
        });
        conversation.updatedAt = Date.now();
        renderAll();
        playChatPopSound();
    } catch (error) {
        conversation.messages.push({ role: "assistant", text: error.message || "Something went wrong.", sources: [], time: Date.now() });
        renderAll();
        toast(error.message || "Something went wrong.", true);
    } finally {
        busy = false;
        syncComposer();
        questionInput.focus();
    }
}

$("#uploadForm").addEventListener("submit", (event) => event.preventDefault());
setupPanelControls();
pdfInput.addEventListener("change", uploadSelectedPdf);
composerUploadBtn.addEventListener("click", openPdfPicker);
[$(".chat-panel"), $(".document-panel")].forEach((target) => {
    target.addEventListener("dragover", (event) => {
        event.preventDefault();
        target.classList.add("dragover-panel");
    });
    target.addEventListener("dragleave", (event) => {
        if (!target.contains(event.relatedTarget)) target.classList.remove("dragover-panel");
    });
    target.addEventListener("drop", (event) => {
        event.preventDefault();
        target.classList.remove("dragover-panel");
        if (event.dataTransfer.files.length) {
            pdfInput.files = event.dataTransfer.files;
            pdfInput.dispatchEvent(new Event("change", { bubbles: true }));
        }
    });
});
$("#emptyUploadBtn").addEventListener("click", () => pdfInput.click());
$("#uploadManagerBtn").addEventListener("click", (event) => {
    event.preventDefault();
    openPdfPicker();
});
$("#questionForm").addEventListener("submit", submitQuestion);
$("#newChatBottomBtn").addEventListener("click", newConversation);
$("#clearConversationBtn").addEventListener("click", clearCurrentConversation);
$("#historySearch").addEventListener("input", renderConversations);
$("#handbookFilter").addEventListener("change", handleHandbookFilterChange);
$("#documentDetailsBtn").addEventListener("click", () => {
    if (!documentInfo) return toast("Upload a PDF to view its details.", true);
    $("#documentDetails").classList.toggle("hidden");
});
$("#indexStatusBtn").addEventListener("click", () => toast(documents.length ? `${documents.length} handbook${documents.length === 1 ? "" : "s"} indexed and ready.` : "No document has been indexed yet.", !documents.length));
$("#themeBtn").addEventListener("click", toggleTheme);
const settingsDialog = $("#settingsDialog");
$("#settingsBtn").addEventListener("click", () => {
    if (typeof settingsDialog.showModal === "function") settingsDialog.showModal();
    else settingsDialog.setAttribute("open", "");
});
$("#settingsClose").addEventListener("click", () => settingsDialog.close());
$("#settingsTheme").addEventListener("click", toggleTheme);
$("#settingsClearAll").addEventListener("click", () => {
    if (!conversations.length || !window.confirm("Delete all conversations? This cannot be undone.")) return;
    conversations = [];
    selectedConversationId = null;
    renderAll();
    settingsDialog.close();
    toast("All conversations deleted.");
});
$("#settingsRemoveDoc").addEventListener("click", async () => {
    if (!documentInfo) return toast("No document is selected.", true);
    const documentId = documentInfo.id;
    settingsDialog.close();
    await deleteDocument(documentId);
});
questionInput.addEventListener("input", () => {
    questionInput.style.height = "auto";
    questionInput.style.height = `${Math.min(questionInput.scrollHeight, 110)}px`;
});
const profileButton = $("#profileBtn");
const profileDropdown = $("#profileDropdown");
function closeProfileDropdown() {
    profileDropdown.hidden = true;
    profileButton.setAttribute("aria-expanded", "false");
}
profileButton.addEventListener("click", (event) => {
    event.stopPropagation();
    profileDropdown.hidden = !profileDropdown.hidden;
    profileButton.setAttribute("aria-expanded", String(!profileDropdown.hidden));
});
document.addEventListener("click", (event) => {
    if (!event.target.closest(".profile-menu")) closeProfileDropdown();
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeProfileDropdown();
});
$("#pageNumber").addEventListener("change", refreshPdfView);
$("#zoomInBtn").addEventListener("click", () => { zoom = Math.min(200, zoom + 10); $("#zoomValue").textContent = `${zoom}%`; refreshPdfView(); });
$("#zoomOutBtn").addEventListener("click", () => { zoom = Math.max(50, zoom - 10); $("#zoomValue").textContent = `${zoom}%`; refreshPdfView(); });
$("#pdfSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") refreshPdfView(); });
$("#pdfSearch").addEventListener("search", refreshPdfView);
$("#shareBtn").addEventListener("click", async () => {
    try {
        if (navigator.share) await navigator.share({ title: "DocLore", url: location.href });
        else { await navigator.clipboard.writeText(location.href); toast("Workspace link copied."); }
    } catch (error) {
        if (error.name !== "AbortError") toast("Could not share this workspace link.", true);
    }
});
$("#question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("#questionForm").requestSubmit(); }
});
document.addEventListener("click", (event) => {
    const chip = event.target.closest(".prompt-chip");
    if (!chip || askBtn.disabled) return;
    questionInput.value = chip.textContent.trim();
    $("#questionForm").requestSubmit();
});

loadState();
fetch("/documents")
    .then((response) => response.json())
    .then((data) => {
        documents = (data.documents || []).map((doc) => ({ ...doc, url: doc.document_url }));
        if (documents.length) {
            const saved = currentConversation();
            const preferred = saved && !saved.allDocuments && documents.some((doc) => doc.id === saved.documentId)
                ? saved.documentId
                : documents[0].id;
            selectDocument(preferred);
            if (saved?.allDocuments) {
                allHandbooksSelected = true;
                $("#handbookFilter").value = "all";
                renderAll();
            } else if (saved && saved.documentId === preferred) {
                allHandbooksSelected = false;
                $("#handbookFilter").value = preferred;
                renderAll();
            } else if (saved) {
                allHandbooksSelected = false;
                $("#handbookFilter").value = preferred;
                ensureConversationFor(preferred);
            } else {
                allHandbooksSelected = true;
                $("#handbookFilter").value = "all";
                renderAll();
            }
        } else {
            renderAll();
        }
    })
    .catch(() => renderAll());
