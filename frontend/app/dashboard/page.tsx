"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

import { AuthGuard } from "@/components/auth-guard";
import { ThemeToggle } from "@/components/theme-toggle";
import { authHeaders } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

interface ProcessedDocument {
  filename: string;
  path: string;
  processed: boolean;
  discription?: string;
  hash: string;
  "date-time"?: string;
}

export default function Dashboard() {
  return (
    <AuthGuard requireAdmin>
      {() => <DashboardContent />}
    </AuthGuard>
  );
}

function DashboardContent() {
  const router = useRouter();

  const [documents, setDocuments] = useState<ProcessedDocument[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [docSummaryInput, setDocSummaryInput] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<{ type: 'success' | 'error', text: string } | null>(null);

  const fetchDocuments = async () => {
    try {
      const res = await fetch(`${API_BASE}/documents`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        const seen = new Set<string>();
        const unique = (data as ProcessedDocument[]).filter((doc) => {
          if (seen.has(doc.hash)) return false;
          seen.add(doc.hash);
          return true;
        });
        setDocuments(unique);
      }
    } catch (err) {
      console.error("Error loading documents:", err);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, []);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) return;

    setIsUploading(true);
    setUploadStatus(null);

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("summary", docSummaryInput);

    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        headers: authHeaders(),
        body: formData,
      });

      const data = await res.json();
      if (res.ok) {
        setUploadStatus({
          type: 'success',
          text: data.message || "Document successfully indexed!"
        });
        setSelectedFile(null);
        setDocSummaryInput("");
        fetchDocuments();
      } else {
        setUploadStatus({
          type: 'error',
          text: data.detail || "Indexing failed."
        });
      }
    } catch (err) {
      setUploadStatus({
        type: 'error',
        text: "Error connecting to the backend server."
      });
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50 dark:bg-zinc-950 font-sans text-gray-900 dark:text-gray-100 p-6 md:p-12 overflow-hidden">
      <div className="max-w-4xl mx-auto w-full flex-1 flex flex-col bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl shadow-xl overflow-hidden">

        <header className="p-6 border-b border-gray-200 dark:border-zinc-800 flex items-center justify-between bg-zinc-50 dark:bg-zinc-900/50">
          <div className="flex items-center gap-3">
            <span className="text-2xl">⚙️</span>
            <h1 className="text-xl font-extrabold uppercase tracking-wider text-pership-blue dark:text-zinc-200">
              Admin Dashboard - RAG Configuration
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <button
              onClick={() => router.push('/users')}
              className="px-4 py-2 text-xs font-bold text-gray-600 dark:text-zinc-300 bg-gray-100 dark:bg-zinc-800 hover:bg-gray-200 dark:hover:bg-zinc-700 hover:text-pership-blue dark:hover:text-blue-400 border border-gray-200 dark:border-zinc-700 rounded-lg transition-colors uppercase shadow-sm"
            >
              Users
            </button>
            <button
              onClick={() => router.push('/')}
              className="px-4 py-2 text-xs font-bold text-gray-600 dark:text-zinc-300 bg-gray-100 dark:bg-zinc-800 hover:bg-gray-200 dark:hover:bg-zinc-700 hover:text-pership-red dark:hover:text-red-400 border border-gray-200 dark:border-zinc-700 rounded-lg transition-colors uppercase shadow-sm"
            >
              Go to Chat
            </button>
          </div>
        </header>

        <div className="flex flex-1 overflow-hidden flex-col md:flex-row">

          <div className="w-full md:w-1/2 p-6 border-b md:border-b-0 md:border-r border-gray-200 dark:border-zinc-800 overflow-y-auto">
            <form onSubmit={handleUpload} className="space-y-6">
              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-500 uppercase">Upload PDF Document</label>
                <div className="flex items-center justify-center w-full">
                  <label className="flex flex-col items-center justify-center w-full h-40 border-2 border-dashed border-gray-300 dark:border-zinc-700 rounded-xl cursor-pointer bg-gray-50 dark:bg-zinc-800/50 hover:bg-gray-100 dark:hover:bg-zinc-800 transition">
                    <div className="flex flex-col items-center justify-center pt-5 pb-6 px-4 text-center">
                      <span className="text-4xl mb-3">📄</span>
                      <p className="text-sm text-gray-500 font-bold truncate max-w-70">
                        {selectedFile ? selectedFile.name : "Click to select or drag PDF"}
                      </p>
                    </div>
                    <input
                      type="file"
                      accept=".pdf"
                      className="hidden"
                      onChange={(e) => {
                        if (e.target.files && e.target.files.length > 0) {
                          setSelectedFile(e.target.files[0]);
                          setUploadStatus(null);
                        }
                      }}
                    />
                  </label>
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-500 uppercase">Description / Summary (Optional)</label>
                <textarea
                  value={docSummaryInput}
                  onChange={(e) => setDocSummaryInput(e.target.value)}
                  placeholder="Write a brief overview..."
                  maxLength={100}
                  rows={3}
                  className="w-full text-sm p-3 border border-gray-300 dark:border-zinc-700 rounded-xl bg-gray-50 dark:bg-zinc-800 focus:outline-none focus:ring-2 focus:ring-pership-red"
                />
              </div>

              <button
                type="submit"
                disabled={isUploading || !selectedFile}
                className="w-full py-3 bg-pership-blue text-white text-sm font-bold rounded-xl hover:bg-opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition uppercase tracking-wider flex items-center justify-center gap-2 shadow-md"
              >
                {isUploading ? (
                  <>
                    <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                    Processing...
                  </>
                ) : (
                  "📄 Process Document"
                )}
              </button>
            </form>

            {uploadStatus && (
              <div className={`mt-6 p-4 rounded-xl text-sm font-semibold border ${uploadStatus.type === 'success'
                  ? 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950/20 dark:text-green-400 dark:border-green-900/30'
                  : 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/20 dark:text-red-400 dark:border-red-900/30'
                }`}>
                {uploadStatus.text}
              </div>
            )}
          </div>

          <div className="w-full md:w-1/2 p-6 overflow-y-auto bg-zinc-50 dark:bg-zinc-900/30">
            <div className="flex items-center justify-between mb-4">
              <label className="text-sm font-bold text-gray-500 uppercase flex items-center gap-2">
                Available Documents 📖
                <span className="text-xs bg-pership-blue/10 dark:bg-blue-500/20 text-pership-blue dark:text-blue-400 font-bold px-2 py-0.5 rounded-full">
                  {documents.length}
                </span>
              </label>
            </div>

            <div className="space-y-3">
              {documents.length === 0 ? (
                <p className="text-sm text-gray-400 italic">No indexed documents found.</p>
              ) : (
                documents.map((doc) => (
                  <div
                    key={`${doc.hash}-${doc.filename}`}
                    className="p-4 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl hover:border-pership-red/50 transition group shadow-sm"
                  >
                    <div className="flex items-start gap-3">
                      <span className="text-xl text-pership-red dark:text-red-500 flex-shrink-0 mt-0.5">📄</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-bold text-gray-800 dark:text-zinc-200 truncate group-hover:text-pership-red transition">
                          {doc.filename}
                        </p>
                        {doc.discription && (
                          <p className="text-xs text-gray-500 dark:text-zinc-400 line-clamp-2 mt-1 leading-relaxed">
                            {doc.discription}
                          </p>
                        )}
                        {doc["date-time"] && (
                          <p className="text-[10px] text-gray-400 dark:text-zinc-500 mt-2 uppercase font-extrabold tracking-wider">
                            Indexed: {doc["date-time"]}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
