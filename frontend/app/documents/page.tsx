"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowLeft, FileText, Trash2, Upload } from "lucide-react";
import {
  clearAllDocuments,
  deleteDocument,
  deleteDocumentsBatch,
  getConsentStatus,
  grantConsent,
  listDocuments,
  uploadDocument,
  type MedicalDocument,
} from "@/src/services/api";
import Magnetic from "@/src/components/motion/Magnetic";
import { Carrot, DoodleField, Droplet, Sparkle, Squiggle } from "@/src/components/landing/Doodles";

const DOODLES = [
  { icon: Sparkle, className: "top-[8%] left-[6%] w-8 h-8", rotate: -8, opacity: 0.4 },
  { icon: Squiggle, className: "top-[14%] right-[8%] w-16 h-6", rotate: 6, opacity: 0.4 },
  { icon: Droplet, className: "bottom-[10%] left-[8%] w-6 h-8", rotate: 12, opacity: 0.35 },
  { icon: Carrot, className: "bottom-[6%] right-[10%] w-8 h-10", rotate: -16, opacity: 0.35 },
];

const ACCEPTED_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png"];
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function StatusBadge({ status, factsExtracted, errorMessage }: { status: MedicalDocument["status"]; factsExtracted: number; errorMessage: string | null }) {
  if (status === "processed") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium bg-primary/20 border border-ink rounded-full px-2.5 py-0.5">
        Processed{factsExtracted > 0 ? ` · ${factsExtracted} fact${factsExtracted === 1 ? "" : "s"}` : ""}
      </span>
    );
  }
  if (status === "processing") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium bg-panel border border-ink rounded-full px-2.5 py-0.5">
        <span className="w-1.5 h-1.5 rounded-full bg-ink animate-pulse" /> Processing
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="text-xs font-medium bg-red-100 border border-red-700 text-red-700 rounded-full px-2.5 py-0.5" title={errorMessage ?? undefined}>
        Failed
      </span>
    );
  }
  return <span className="text-xs font-medium bg-panel border border-ink rounded-full px-2.5 py-0.5">Uploaded</span>;
}

export default function DocumentsPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [consentGranted, setConsentGranted] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);
  const [granting, setGranting] = useState(false);

  const [documents, setDocuments] = useState<MedicalDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      setDocuments(await listDocuments());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
    }
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("nutribot_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const consent = await getConsentStatus();
        setConsentGranted(consent.granted);
        setConsentChecked(consent.granted);
        if (consent.granted) await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load consent status");
      } finally {
        setLoading(false);
      }
    })();
  }, [router, refresh]);

  // Poll while anything is still processing, so status/fact counts update
  // without the user having to refresh manually.
  useEffect(() => {
    if (!documents.some((d) => d.status === "processing")) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [documents, refresh]);

  async function handleGrantConsent() {
    setGranting(true);
    setError(null);
    try {
      await grantConsent();
      setConsentGranted(true);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to grant consent");
    } finally {
      setGranting(false);
    }
  }

  function validateFile(file: File): string | null {
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) return `Unsupported file type "${ext}". Allowed: PDF, JPG, PNG.`;
    if (file.size > MAX_UPLOAD_BYTES) return `File too large (max 10 MB).`;
    return null;
  }

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const file = files[0];
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setUploading(true);
    try {
      await uploadDocument(file);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleDeleteOne(id: string) {
    if (!window.confirm("Delete this document? The file will be removed, but any facts already learned from it stay.")) return;
    setBusyIds((prev) => new Set(prev).add(id));
    try {
      await deleteDocument(id);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
      setSelected((prev) => { const next = new Set(prev); next.delete(id); return next; });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete document");
    } finally {
      setBusyIds((prev) => { const next = new Set(prev); next.delete(id); return next; });
    }
  }

  async function handleDeleteSelected() {
    if (selected.size === 0) return;
    if (!window.confirm(`Delete ${selected.size} selected document${selected.size === 1 ? "" : "s"}?`)) return;
    try {
      await deleteDocumentsBatch(Array.from(selected));
      await refresh();
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete selected documents");
    }
  }

  async function handleClearAll() {
    if (documents.length === 0) return;
    if (!window.confirm("Delete ALL uploaded documents? This can't be undone.")) return;
    try {
      await clearAllDocuments();
      setDocuments([]);
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clear documents");
    }
  }

  if (loading) {
    return (
      <main className="min-h-screen flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-ink border-t-transparent rounded-full animate-spin" />
      </main>
    );
  }

  return (
    <main className="relative min-h-screen px-4 py-8 overflow-hidden">
      <DoodleField items={DOODLES} />

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="relative w-full max-w-2xl mx-auto"
      >
        <Link
          href="/chat"
          className="inline-flex items-center gap-1.5 text-sm font-medium bg-surface border-2 border-ink rounded-full pl-3 pr-4 py-2 shadow-hard-sm hover:-translate-y-0.5 transition-transform mb-6"
        >
          <ArrowLeft className="w-4 h-4" strokeWidth={2.5} />
          Back to chat
        </Link>

        <h1 className="font-display text-3xl font-extrabold text-text tracking-tight mb-1">Medical Documents</h1>
        <p className="text-muted text-sm mb-6">
          Upload a lab report or prescription and Nova will extract the factual details — never a diagnosis — to
          personalise your plans. You can delete any file, or everything, at any time.
        </p>

        {error && (
          <p className="mb-4 text-sm text-red-700 bg-red-100 border-2 border-red-700 rounded-lg px-3 py-2">{error}</p>
        )}

        {!consentGranted ? (
          <div className="bg-surface border-2 border-ink rounded-2xl p-6 shadow-hard">
            <h2 className="font-display font-bold text-text mb-2">Consent required</h2>
            <p className="text-sm text-muted mb-4">
              Uploading a medical document processes health information, so we ask for explicit consent first.
              You can revoke this later from your profile.
            </p>
            <label className="flex items-start gap-3 bg-panel border-2 border-ink rounded-xl p-3 text-sm cursor-pointer mb-4">
              <input
                type="checkbox"
                checked={consentChecked}
                onChange={(e) => setConsentChecked(e.target.checked)}
                className="mt-0.5 accent-primary"
              />
              <span className="text-muted">
                I consent to NutriBot processing medical documents I upload and using extracted facts to
                personalise nutrition guidance.
              </span>
            </label>
            <Magnetic>
              <button
                onClick={handleGrantConsent}
                disabled={!consentChecked || granting}
                className="bg-primary text-ink border-2 border-ink font-bold rounded-xl px-6 py-2.5 text-sm
                  shadow-hard-sm hover:-translate-y-0.5 transition-transform disabled:opacity-50 disabled:hover:translate-y-0"
              >
                {granting ? "Saving…" : "Grant consent & continue"}
              </button>
            </Magnetic>
          </div>
        ) : (
          <>
            {/* Upload zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
              onClick={() => fileInputRef.current?.click()}
              className={`flex flex-col items-center justify-center gap-2 border-2 border-dashed rounded-2xl p-8 mb-6 cursor-pointer text-center transition-colors
                ${dragOver ? "border-ink bg-primary/10" : "border-ink/40 bg-surface hover:border-ink"}`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_EXTENSIONS.join(",")}
                className="hidden"
                onChange={(e) => handleFiles(e.target.files)}
              />
              <span className="w-11 h-11 rounded-xl bg-ink flex items-center justify-center">
                <Upload className="w-5 h-5 text-white" strokeWidth={2} />
              </span>
              <p className="text-sm font-semibold text-text">
                {uploading ? "Uploading…" : "Click to upload, or drag a file here"}
              </p>
              <p className="text-xs text-muted">PDF, JPG, or PNG — up to 10 MB</p>
            </div>

            {/* Document list */}
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-display font-bold text-text">
                Your documents {documents.length > 0 && <span className="text-muted font-normal">({documents.length})</span>}
              </h2>
              <div className="flex items-center gap-2">
                {selected.size > 0 && (
                  <button
                    onClick={handleDeleteSelected}
                    className="text-xs font-semibold text-red-700 border-2 border-red-700 bg-red-100 rounded-full px-3 py-1.5 hover:bg-red-200 transition-colors"
                  >
                    Delete {selected.size} selected
                  </button>
                )}
                {documents.length > 0 && (
                  <button
                    onClick={handleClearAll}
                    className="text-xs font-semibold text-muted border-2 border-ink rounded-full px-3 py-1.5 hover:bg-panel transition-colors"
                  >
                    Clear all
                  </button>
                )}
              </div>
            </div>

            {documents.length === 0 ? (
              <p className="text-sm text-muted text-center py-10 bg-surface border-2 border-ink rounded-2xl">
                No documents uploaded yet.
              </p>
            ) : (
              <ul className="space-y-2">
                {documents.map((doc) => (
                  <li
                    key={doc.id}
                    className="flex items-center gap-3 bg-surface border-2 border-ink rounded-xl px-3 py-3 shadow-hard-sm"
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(doc.id)}
                      onChange={() => toggleSelected(doc.id)}
                      className="accent-primary flex-shrink-0"
                    />
                    <span className="w-9 h-9 rounded-lg bg-panel border border-ink flex items-center justify-center flex-shrink-0">
                      <FileText className="w-4 h-4 text-ink" strokeWidth={2} />
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-text truncate">{doc.filename}</p>
                      <p className="text-xs text-muted">{formatDate(doc.uploaded_at)}</p>
                    </div>
                    <StatusBadge status={doc.status} factsExtracted={doc.facts_extracted} errorMessage={doc.error_message} />
                    <button
                      onClick={() => handleDeleteOne(doc.id)}
                      disabled={busyIds.has(doc.id)}
                      title="Delete this document"
                      aria-label="Delete this document"
                      className="w-8 h-8 flex-shrink-0 flex items-center justify-center rounded-lg text-muted hover:text-red-700 hover:bg-red-100 transition-colors disabled:opacity-40"
                    >
                      <Trash2 className="w-4 h-4" strokeWidth={2} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </motion.div>
    </main>
  );
}
