import { useState } from "react";

interface Props {
  streaming: boolean;
  disabled: boolean;
  selectedCount: number;
  onAsk: (question: string) => void;
  onStop: () => void;
}

export function AskBar({ streaming, disabled, selectedCount, onAsk, onStop }: Props) {
  const [value, setValue] = useState("");

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const question = value.trim();
    if (!question || streaming) return;
    onAsk(question);
    setValue("");
  }

  return (
    <form onSubmit={submit} className="mt-auto px-9 pt-[18px] pb-6">
      <div className="bg-white border border-line-strong rounded-xl px-3.5 py-3 flex items-center
                      gap-3 max-w-[626px] shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={streaming || disabled}
          placeholder={
            streaming
              ? "Answering…"
              : selectedCount > 0
                ? `Ask about ${selectedCount} selected meeting${selectedCount === 1 ? "" : "s"}…`
                : "Ask about what was discussed, decided, or committed to…"
          }
          aria-label="Question"
          className="font-text text-[14.5px] text-ink placeholder:text-faint bg-transparent
                     flex-grow outline-none disabled:cursor-not-allowed"
        />
        {streaming ? (
          // A 40-second local generation the user cannot cancel is a trap.
          <button
            type="button"
            onClick={onStop}
            className="text-[12px] font-semibold text-body bg-surface hover:bg-line
                       px-[17px] py-[7px] rounded-full transition-colors"
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!value.trim() || disabled}
            className="text-[12px] font-semibold text-white bg-brand hover:bg-brand-dark
                       disabled:bg-line disabled:text-faint px-[17px] py-[7px]
                       rounded-full transition-colors"
          >
            Ask
          </button>
        )}
      </div>
    </form>
  );
}
