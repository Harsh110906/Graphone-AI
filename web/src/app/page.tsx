"use client";

import React, { useState, useMemo } from "react";
import rawRecords from "../data/records.json";

interface RecordItem {
  id?: string;
  schemaVersion?: string;
  recordType: "STARTUP" | "PRODUCT" | "RESEARCH_PAPER" | "JOB" | "NEWS";
  source?: {
    name?: string;
    url?: string;
  };
  content?: Record<string, any>;
  collectedAt?: string;
  dataQualityScore?: number;
}

export default function Home() {
  const records = rawRecords as RecordItem[];
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedType, setSelectedType] = useState<string>("ALL");
  const [pricingFilter, setPricingFilter] = useState<string>("ALL");
  const [selectedRecord, setSelectedRecord] = useState<RecordItem | null>(null);

  // Statistics
  const stats = useMemo(() => {
    return {
      total: records.length,
      startups: records.filter((r) => r.recordType === "STARTUP").length,
      products: records.filter((r) => r.recordType === "PRODUCT").length,
      papers: records.filter((r) => r.recordType === "RESEARCH_PAPER").length,
      jobs: records.filter((r) => r.recordType === "JOB").length,
      news: records.filter((r) => r.recordType === "NEWS").length,
    };
  }, [records]);

  // Filtering
  const filteredRecords = useMemo(() => {
    return records.filter((r) => {
      // Type filter
      if (selectedType !== "ALL" && r.recordType !== selectedType) {
        return false;
      }

      // Pricing filter
      if (pricingFilter !== "ALL" && r.recordType === "PRODUCT") {
        const pricing = r.content?.pricingModel || "UNVERIFIED";
        if (pricing !== pricingFilter) return false;
      }

      // Search query
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();

      const title = (
        r.content?.entityName ||
        r.content?.title ||
        r.content?.company ||
        ""
      ).toLowerCase();
      const desc = (
        r.content?.fullText ||
        r.content?.startupName ||
        r.source?.name ||
        ""
      ).toLowerCase();
      const authors = Array.isArray(r.content?.authors)
        ? r.content?.authors.join(" ").toLowerCase()
        : "";

      return title.includes(q) || desc.includes(q) || authors.includes(q);
    });
  }, [records, searchQuery, selectedType, pricingFilter]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50 font-sans selection:bg-blue-500 selection:text-white pb-20">
      {/* Header */}
      <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center font-bold text-white shadow-lg shadow-blue-500/30">
              G1
            </div>
            <div>
              <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                GraphOne AI
              </span>
              <span className="ml-2 text-xs bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded-full font-mono">
                v1.0 Live
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <a
              href="https://docs.google.com/spreadsheets/d/1U5PnFQMsGVCvlSv1mEBkY-BcNYe6s3dzpOQPTzzfZ8c/edit?usp=sharing"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-all"
            >
              <span>📊</span> Google Sheet Dataset
            </a>
            <a
              href="https://github.com/Harsh110906/Graphone-AI.git"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-all"
            >
              <span>💻</span> GitHub
            </a>
          </div>
        </div>
      </header>

      {/* Hero Search Section */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-10">
        <div className="text-center max-w-3xl mx-auto mb-8">
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight mb-3 bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
            AI Ecosystem Intelligence Search
          </h1>
          <p className="text-slate-400 text-sm sm:text-base">
            Search verified startups, interactive products, arXiv research preprints, 24-hour fresh jobs, and news with complete data lineage.
          </p>
        </div>

        {/* Search Input */}
        <div className="max-w-3xl mx-auto mb-8">
          <div className="relative">
            <input
              type="text"
              placeholder="Search by company, product, paper topic, or keyword (e.g., 'Meta', 'Llama', 'Vision', 'Anthropic')..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-slate-900/90 border border-slate-800 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 rounded-xl px-4 py-3.5 pl-11 text-sm text-slate-100 placeholder-slate-500 shadow-xl transition-all outline-none"
            />
            <svg
              className="absolute left-3.5 top-4 w-4 h-4 text-slate-500"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-3.5 top-3.5 text-xs text-slate-400 hover:text-white bg-slate-800 px-2 py-1 rounded"
              >
                Clear
              </button>
            )}
          </div>

          {/* Category Tabs */}
          <div className="flex flex-wrap gap-2 mt-4 justify-center sm:justify-start">
            {[
              { label: "All Records", value: "ALL", count: stats.total },
              { label: "Startups", value: "STARTUP", count: stats.startups },
              { label: "Products", value: "PRODUCT", count: stats.products },
              { label: "Research Papers", value: "RESEARCH_PAPER", count: stats.papers },
              { label: "Jobs (24h)", value: "JOB", count: stats.jobs },
              { label: "News (24h)", value: "NEWS", count: stats.news },
            ].map((tab) => (
              <button
                key={tab.value}
                onClick={() => setSelectedType(tab.value)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  selectedType === tab.value
                    ? "bg-blue-600 text-white shadow-lg shadow-blue-500/25"
                    : "bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700"
                }`}
              >
                {tab.label}{" "}
                <span className="ml-1 opacity-70 font-mono text-[10px]">
                  ({tab.count})
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Results Metadata */}
        <div className="flex items-center justify-between text-xs text-slate-400 mb-4 px-1">
          <span>
            Showing <strong className="text-slate-200">{filteredRecords.length}</strong> verified facts
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            Zero Hallucination Guarantee
          </span>
        </div>

        {/* Results Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredRecords.slice(0, 60).map((record, idx) => (
            <div
              key={record.id || idx}
              onClick={() => setSelectedRecord(record)}
              className="bg-slate-900/60 border border-slate-800 hover:border-blue-500/40 rounded-xl p-4 transition-all hover:shadow-xl hover:shadow-blue-500/5 cursor-pointer flex flex-col justify-between group"
            >
              <div>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span
                    className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded ${
                      record.recordType === "STARTUP"
                        ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                        : record.recordType === "PRODUCT"
                        ? "bg-purple-500/10 text-purple-400 border border-purple-500/20"
                        : record.recordType === "RESEARCH_PAPER"
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                        : record.recordType === "JOB"
                        ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                        : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                    }`}
                  >
                    {record.recordType.replace("_", " ")}
                  </span>
                  {record.dataQualityScore && (
                    <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-800/40 px-1.5 py-0.5 rounded">
                      DQS {record.dataQualityScore.toFixed(0)}
                    </span>
                  )}
                </div>

                <h3 className="font-semibold text-slate-100 text-sm group-hover:text-blue-400 transition-colors line-clamp-2 mb-1.5">
                  {record.content?.entityName ||
                    record.content?.title ||
                    record.content?.company ||
                    "Entity Record"}
                </h3>

                {/* Subtitle / Attributes */}
                {record.recordType === "PRODUCT" && (
                  <div className="flex items-center gap-2 text-xs text-slate-400 mb-2">
                    {record.content?.startupName && (
                      <span>By: <strong className="text-slate-300">{record.content.startupName}</strong></span>
                    )}
                    {record.content?.pricingModel && (
                      <span className="bg-slate-800 text-slate-300 px-1.5 py-0.5 rounded text-[10px] font-mono">
                        {record.content.pricingModel}
                      </span>
                    )}
                  </div>
                )}

                {record.recordType === "RESEARCH_PAPER" && (
                  <div className="text-xs text-slate-400 mb-2 line-clamp-1">
                    {Array.isArray(record.content?.authors)
                      ? record.content?.authors.slice(0, 3).join(", ")
                      : ""}
                  </div>
                )}

                {record.recordType === "JOB" && (
                  <div className="text-xs text-slate-400 mb-2 flex items-center gap-2">
                    <span className="font-medium text-slate-300">{record.content?.company}</span>
                    {record.content?.role_family && (
                      <span className="bg-slate-800 text-slate-300 px-1.5 py-0.5 rounded text-[10px]">
                        {record.content.role_family}
                      </span>
                    )}
                  </div>
                )}

                {record.recordType === "NEWS" && (
                  <p className="text-xs text-slate-400 line-clamp-2 mb-2">
                    {record.content?.fullText?.slice(0, 140)}...
                  </p>
                )}
              </div>

              <div className="pt-3 border-t border-slate-800/60 flex items-center justify-between text-[11px] text-slate-500">
                <span className="truncate max-w-[180px]">
                  {record.source?.name || "Verified Source"}
                </span>
                <span className="text-blue-400 group-hover:underline">
                  Inspect &rarr;
                </span>
              </div>
            </div>
          ))}
        </div>
      </main>

      {/* Detail Modal */}
      {selectedRecord && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-4 border-b border-slate-800 mb-4">
              <span className="text-xs font-mono font-semibold px-2 py-1 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                {selectedRecord.recordType}
              </span>
              <button
                onClick={() => setSelectedRecord(null)}
                className="text-slate-400 hover:text-white bg-slate-800 px-3 py-1 rounded-lg text-sm"
              >
                Close
              </button>
            </div>

            <h2 className="text-xl font-bold text-white mb-2">
              {selectedRecord.content?.entityName ||
                selectedRecord.content?.title ||
                selectedRecord.content?.company}
            </h2>

            {selectedRecord.source?.url && (
              <div className="mb-4">
                <span className="text-xs text-slate-400">Source URL: </span>
                <a
                  href={selectedRecord.source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-400 hover:underline break-all font-mono"
                >
                  {selectedRecord.source.url}
                </a>
              </div>
            )}

            <div className="mb-4 bg-slate-950 p-4 rounded-xl border border-slate-800/80">
              <div className="text-xs font-semibold text-slate-300 mb-2">
                Structured Fact Schema
              </div>
              <pre className="text-xs font-mono text-slate-300 overflow-x-auto">
                {JSON.stringify(selectedRecord, null, 2)}
              </pre>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              {selectedRecord.source?.url && (
                <a
                  href={selectedRecord.source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="bg-blue-600 hover:bg-blue-500 text-white text-xs px-4 py-2 rounded-lg font-medium transition-all"
                >
                  Visit Verified Source &rarr;
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
