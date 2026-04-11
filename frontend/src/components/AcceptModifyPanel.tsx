"use client";

type Props = {
  onAccept: () => void;
  onModify: () => void;
  loading?: boolean;
  accepted?: boolean;
  confirmationMessage?: string;
};

export default function AcceptModifyPanel({
  onAccept,
  onModify,
  loading = false,
  accepted = false,
  confirmationMessage,
}: Props) {
  if (accepted && confirmationMessage) {
    return (
      <div className="flex items-center gap-2 mt-3 text-sm text-primary bg-panel border border-border rounded-xl px-4 py-3">
        <span>✓</span>
        <span>{confirmationMessage}</span>
      </div>
    );
  }

  return (
    <div className="flex gap-3 mt-3">
      <button
        onClick={onAccept}
        disabled={loading || accepted}
        className="flex-1 bg-primary text-background font-semibold rounded-xl py-2.5 text-sm
          hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? "Saving…" : "✓ Accept Plan"}
      </button>
      <button
        onClick={onModify}
        disabled={loading || accepted}
        className="flex-1 bg-panel border border-border text-text font-medium rounded-xl py-2.5 text-sm
          hover:bg-border disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        ✎ Request Modifications
      </button>
    </div>
  );
}
