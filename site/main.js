// Copy buttons, and the window that follows the story.
// Without JavaScript (and on phones) each chapter shows its own picture.

for (const box of document.querySelectorAll("[data-copy]")) {
  const button = box.querySelector(".copy");
  let timer;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(box.dataset.copy);
      button.textContent = "Copied";
    } catch {
      const range = document.createRange();
      range.selectNodeContents(box.querySelector("code"));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      button.textContent = "Ctrl+C";
    }
    clearTimeout(timer);
    timer = setTimeout(() => { button.textContent = "Copy"; }, 2000);
  });
}

const show = document.querySelector(".show");
if (show) {
  const chapters = [...show.querySelectorAll(".chapter")];
  const framesBox = show.querySelector(".frames");
  const bar = show.querySelector(".dock-bar");
  const countLabel = show.querySelector(".dock-count");
  const titleLabel = show.querySelector(".dock-title");
  const [prevButton, nextButton] = show.querySelectorAll(".dock-nav button");
  const pad = (n) => String(n).padStart(2, "0");

  // One frame per chapter: a copy of its picture, kept in the window on the right.
  const frames = chapters.map((chapter) => {
    const frame = document.createElement("div");
    frame.className = "frame";
    const shot = chapter.querySelector(".shot").cloneNode(true);
    for (const img of shot.querySelectorAll("img")) img.loading = "eager";
    frame.appendChild(shot);
    framesBox.appendChild(frame);
    return frame;
  });

  // The progress bar: one segment per chapter, a gap between acts.
  const segments = chapters.map((chapter, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-label", chapter.dataset.title);
    button.appendChild(document.createElement("span"));
    if (i > 0 && chapters[i - 1].dataset.act !== chapter.dataset.act) button.classList.add("act-start");
    button.addEventListener("click", () => go(i));
    bar.appendChild(button);
    return button;
  });

  let current = -1;
  const activate = (n) => {
    if (n === current) return;
    current = n;
    chapters.forEach((c, i) => c.classList.toggle("active", i === n));
    frames.forEach((frame, i) => { frame.dataset.state = i === n ? "active" : i < n ? "prev" : "next"; });
    segments.forEach((segment, i) => {
      segment.classList.toggle("on", i === n);
      segment.classList.toggle("done", i < n);
      segment.setAttribute("aria-current", i === n ? "step" : "false");
    });
    countLabel.textContent = "";
    const bold = document.createElement("b");
    bold.textContent = pad(n + 1);
    countLabel.append(bold, ` / ${pad(chapters.length)}`);
    titleLabel.textContent = chapters[n].dataset.title;
    prevButton.disabled = n === 0;
    nextButton.disabled = n === chapters.length - 1;
  };

  const go = (n) => {
    const target = chapters[Math.max(0, Math.min(chapters.length - 1, n))];
    target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
  };
  prevButton.addEventListener("click", () => go(current - 1));
  nextButton.addEventListener("click", () => go(current + 1));

  // A chapter becomes the current one when it crosses the middle of the screen.
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) activate(chapters.indexOf(entry.target));
    }
  }, { rootMargin: "-48% 0px -48% 0px" });
  chapters.forEach((chapter) => observer.observe(chapter));

  show.classList.add("staged");
  activate(0);
}
