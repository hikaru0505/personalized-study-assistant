document.addEventListener("DOMContentLoaded", () => {

  // ------------------------------------------------------------------
  // Dark mode toggle (persisted in localStorage - this is a real
  // deployed website, not a sandboxed artifact, so localStorage is the
  // right tool here for a lightweight, no-backend-needed preference).
  // ------------------------------------------------------------------
  const darkModeToggle = document.getElementById("darkModeToggle");
  const root = document.documentElement;

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    if (darkModeToggle) darkModeToggle.textContent = theme === "dark" ? "☀️" : "🌙";
  }

  const savedTheme = localStorage.getItem("theme") || "light";
  applyTheme(savedTheme);

  if (darkModeToggle) {
    darkModeToggle.addEventListener("click", () => {
      const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      localStorage.setItem("theme", next);
      applyTheme(next);
    });
  }

  // ------------------------------------------------------------------
  // Custom file-picker label
  // ------------------------------------------------------------------
  const fileInput = document.getElementById("pdf");
  const filePickerLabel = document.getElementById("filePickerLabel");
  if (fileInput && filePickerLabel) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files.length > 0) {
        filePickerLabel.textContent = `📄 ${fileInput.files[0].name}`;
        filePickerLabel.classList.add("file-picker-label-filled");
      } else {
        filePickerLabel.textContent = "📄 Upload a PDF or DOCX to begin learning.";
        filePickerLabel.classList.remove("file-picker-label-filled");
      }
    });
  }

  // ------------------------------------------------------------------
  // Rotating loading overlay for slow (multi-LLM-call) form submissions
  // ------------------------------------------------------------------
  const loadingOverlay = document.getElementById("loadingOverlay");
  const loadingText = document.getElementById("loadingText");

  function attachLoadingOverlay(form, stages) {
    if (!form || !loadingOverlay || !loadingText) return;
    form.addEventListener("submit", () => {
      loadingOverlay.classList.add("visible");
      let i = 0;
      loadingText.textContent = stages[0];
      setInterval(() => {
        i = Math.min(i + 1, stages.length - 1);
        loadingText.textContent = stages[i];
      }, 4000);
    });
  }

  attachLoadingOverlay(document.getElementById("uploadForm"), [
    "Uploading your document...",
    "Extracting text...",
    "Building the knowledge base...",
    "Generating your summary...",
    "Almost done...",
  ]);

  document.querySelectorAll(".inline-form").forEach((form) => {
    attachLoadingOverlay(form, ["Generating...", "Talking to the model...", "Almost done..."]);
  });

  // ------------------------------------------------------------------
  // Quiz submission: build hidden JSON values for "match" questions,
  // then show a grading overlay
  // ------------------------------------------------------------------
  const quizForm = document.getElementById("quizForm");
  if (quizForm) {
    quizForm.addEventListener("submit", () => {
      document.querySelectorAll(".match-hidden-input").forEach((hiddenInput) => {
        const qidx = hiddenInput.dataset.qidx;
        const selects = document.querySelectorAll(`.match-select[data-qidx="${qidx}"]`);
        const answerMap = {};
        selects.forEach((select) => {
          answerMap[select.dataset.pairidx] = select.value;
        });
        hiddenInput.value = JSON.stringify(answerMap);
      });

      const button = quizForm.querySelector("button[type='submit']");
      if (button) {
        button.disabled = true;
        button.textContent = "Grading your quiz...";
      }
      if (loadingOverlay && loadingText) {
        loadingOverlay.classList.add("visible");
        loadingText.textContent = "Grading your answers...";
      }
    });
  }

  // ------------------------------------------------------------------
  // Voice input (ask a question by speaking) - Web Speech API
  // ------------------------------------------------------------------
  const voiceInputBtn = document.getElementById("voiceInputBtn");
  if (voiceInputBtn) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      voiceInputBtn.title = "Voice input isn't supported in this browser";
      voiceInputBtn.disabled = true;
    } else {
      voiceInputBtn.addEventListener("click", () => {
        const recognition = new SpeechRecognition();
        recognition.lang = "en-US";
        recognition.interimResults = false;
        voiceInputBtn.textContent = "🎙️...";
        recognition.start();

        recognition.onresult = (event) => {
          const transcript = event.results[0][0].transcript;
          const questionInput = document.querySelector('.ask-form input[name="question"]');
          if (questionInput) questionInput.value = transcript;
          voiceInputBtn.textContent = "🎤";
        };
        recognition.onerror = () => { voiceInputBtn.textContent = "🎤"; };
        recognition.onend = () => { voiceInputBtn.textContent = "🎤"; };
      });
    }
  }

  // ------------------------------------------------------------------
  // Read answer aloud - Web Speech API speech synthesis
  // ------------------------------------------------------------------
  const readAloudBtn = document.getElementById("readAloudBtn");
  if (readAloudBtn && window.speechSynthesis) {
    readAloudBtn.addEventListener("click", () => {
      const text = readAloudBtn.dataset.text;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      window.speechSynthesis.speak(utterance);
    });
  }

  // ------------------------------------------------------------------
  // AI explanation styles (AJAX, no page reload)
  // ------------------------------------------------------------------
  document.querySelectorAll(".explain-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const wrapper = btn.closest(".explain-styles");
      const outputBox = document.getElementById("explainOutput");
      if (!wrapper || !outputBox) return;

      const question = wrapper.dataset.question;
      const answer = wrapper.dataset.answer;
      const style = btn.dataset.style;

      outputBox.style.display = "block";
      outputBox.textContent = "Rewriting the answer...";

      try {
        const res = await fetch("/explain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, answer, style }),
        });
        const data = await res.json();
        outputBox.textContent = data.text || "Something went wrong.";
      } catch (err) {
        outputBox.textContent = "Something went wrong generating that explanation.";
      }
    });
  });

  // ------------------------------------------------------------------
  // Search inside the document (AJAX) + jump to page
  // ------------------------------------------------------------------
  const searchButton = document.getElementById("searchButton");
  const searchBox = document.getElementById("searchBox");
  const searchResults = document.getElementById("searchResults");
  const pdfFrame = document.getElementById("pdfFrame");

  function jumpToPage(pageNum) {
    if (pdfFrame) {
      const baseSrc = pdfFrame.src.split("#")[0];
      pdfFrame.src = `${baseSrc}#page=${pageNum}`;
    }
  }

  if (searchButton && searchBox && searchResults) {
    searchButton.addEventListener("click", async () => {
      const query = searchBox.value.trim();
      if (!query || !window.STUDY_ASSISTANT_DOC_ID) return;

      searchResults.innerHTML = "Searching...";
      try {
        const res = await fetch(`/document/${window.STUDY_ASSISTANT_DOC_ID}/search?q=${encodeURIComponent(query)}`);
        const data = await res.json();
        if (!data.results || data.results.length === 0) {
          searchResults.innerHTML = "<p class='hint'>No matches found.</p>";
          return;
        }
        searchResults.innerHTML = "";
        data.results.forEach((r) => {
          const div = document.createElement("div");
          div.className = "search-result-item";
          div.textContent = `Page ${r.page}: ${r.snippet}`;
          div.addEventListener("click", () => jumpToPage(r.page));
          searchResults.appendChild(div);
        });
      } catch (err) {
        searchResults.innerHTML = "<p class='hint'>Search failed.</p>";
      }
    });
  }

  document.querySelectorAll(".jump-to-page").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      jumpToPage(link.dataset.page);
    });
  });

  // ------------------------------------------------------------------
  // Study plan day checkboxes - persisted per-document in localStorage
  // (client-side only; not synced across devices, called out in README)
  // ------------------------------------------------------------------
  const planContainer = document.querySelector(".study-plan-days");
  if (planContainer) {
    const docId = planContainer.dataset.docId;
    const storageKey = `study-plan-progress-${docId}`;
    const checkboxes = planContainer.querySelectorAll(".plan-day-checkbox");
    const progressFill = document.getElementById("planProgressFill");
    const progressLabel = document.getElementById("planProgressLabel");

    function loadCompletedDays() {
      try {
        return JSON.parse(localStorage.getItem(storageKey)) || [];
      } catch {
        return [];
      }
    }

    function updateProgressUI() {
      const completed = loadCompletedDays();
      const pct = checkboxes.length ? Math.round((completed.length / checkboxes.length) * 100) : 0;
      if (progressFill) progressFill.style.width = `${pct}%`;
      if (progressLabel) progressLabel.textContent = `${completed.length}/${checkboxes.length} Days Completed`;
    }

    const completedDays = loadCompletedDays();
    checkboxes.forEach((cb) => {
      if (completedDays.includes(cb.dataset.day)) cb.checked = true;
      cb.addEventListener("change", () => {
        let completed = loadCompletedDays();
        if (cb.checked) {
          if (!completed.includes(cb.dataset.day)) completed.push(cb.dataset.day);
        } else {
          completed = completed.filter((d) => d !== cb.dataset.day);
        }
        localStorage.setItem(storageKey, JSON.stringify(completed));
        updateProgressUI();
      });
    });
    updateProgressUI();
  }

  // ------------------------------------------------------------------
  // Flashcard flip
  // ------------------------------------------------------------------
  document.querySelectorAll(".flip-button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = document.getElementById(btn.dataset.target);
      if (!card) return;
      const front = card.querySelector(".flashcard-front");
      const back = card.querySelector(".flashcard-back");
      front.style.display = "none";
      back.style.display = "flex";
      btn.style.display = "none";
      const ratingForm = btn.parentElement.querySelector(".rating-form");
      if (ratingForm) ratingForm.style.display = "flex";
    });
  });

});
