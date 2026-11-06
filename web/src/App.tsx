import { Link, Route, Routes } from "react-router-dom";
import CaseDetailPage from "./pages/CaseDetailPage";
import CaseListPage from "./pages/CaseListPage";
import BenchmarkPage from "./pages/BenchmarkPage";
import ThemeToggle from "./components/ThemeToggle";


export default function App() {
  return (
    <div className="mx-auto max-w-5xl p-4">
      <nav className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-[var(--border)] pb-2 text-sm">
        <Link to="/" className="font-semibold text-[var(--accent)]">
          IntentTrace
        </Link>
        <Link to="/benchmark">Benchmark</Link>
        <ThemeToggle />
      </nav>
      <Routes>
        <Route path="/" element={<CaseListPage />} />
        <Route path="/cases/:id" element={<CaseDetailPage />} />
        <Route path="/benchmark" element={<BenchmarkPage />} />
      </Routes>
    </div>
  );
}
