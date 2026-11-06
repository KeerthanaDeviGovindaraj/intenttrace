import { useEffect, useState } from "react";

type Theme = "light" | "dark";
const KEY = "intenttrace-theme";

function current(): Theme {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

function saved(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(current);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Follow the system preference until the user makes an explicit choice.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => {
      if (saved() === null) setTheme(e.matches ? "dark" : "light");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const next: Theme = theme === "dark" ? "light" : "dark";
  const toggle = () => {
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* storage unavailable: the choice applies for this session only */
    }
    setTheme(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${next} theme`}
      className="ml-auto rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-0.5 text-xs focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
    >
      <span aria-hidden="true">{theme === "dark" ? "☀ " : "☾ "}</span>
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
