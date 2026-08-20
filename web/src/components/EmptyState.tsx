const FORMATS = [
  { name: "Bracketed", sample: "[00:00:04] Priya Raman:\nRight, let's get started." },
  { name: "Parenthesised", sample: "Priya Raman (00:00:04):\nRight, let's get started." },
  { name: "WebVTT", sample: "00:00:04.000 --> 00:00:29.500\nPriya Raman: Right, let's…" },
];

/** First run: no meetings ingested yet. */
export function EmptyState({ degraded }: { degraded: string | null }) {
  return (
    <div className="flex-grow flex flex-col">
      <div className="flex-grow flex items-center justify-center px-10">
        <div className="w-[640px] flex flex-col gap-[30px]">
          <header className="flex flex-col gap-2.5">
            <h1 className="text-[33px] font-semibold tracking-[-0.025em] leading-[1.2]">
              Ask your meetings anything.
            </h1>
            <p className="font-text text-[16px] leading-[1.62] text-muted max-w-[545px]">
              Every answer comes back with the speaker and the timestamp it came from — so you
              can check it rather than trust it.
            </p>
          </header>

          <div className="border border-dashed border-line-strong rounded-2xl bg-white
                          px-[30px] py-[34px] flex flex-col items-center gap-3.5">
            <svg
              width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#b0b0b0"
              strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden
            >
              <path d="M12 15V4" />
              <path d="M8 8l4-4 4 4" />
              <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
            </svg>
            <div className="flex flex-col items-center gap-1.5">
              <p className="font-text text-[17px]">No transcripts ingested yet</p>
              <p className="font-mono text-[10px] text-faint">.txt&nbsp;&nbsp;.vtt&nbsp;&nbsp;.md</p>
            </div>
            <code className="font-mono text-[11px] text-brand-dark bg-brand-tint px-3 py-1.5 rounded-full">
              make seed
            </code>
          </div>

          <section className="flex flex-col gap-3">
            <h2 className="font-mono text-[9.5px] font-medium tracking-[0.09em] uppercase text-faint">
              Formats recognised
            </h2>
            <div className="flex gap-2.5">
              {FORMATS.map((format) => (
                <div
                  key={format.name}
                  className="flex-grow border border-line rounded-lg px-3.5 py-3
                             flex flex-col gap-1.5 bg-white"
                >
                  <p className="text-[11.5px] font-semibold text-body">{format.name}</p>
                  <pre className="font-mono text-[9.5px] leading-[1.5] text-faint whitespace-pre-wrap">
                    {format.sample}
                  </pre>
                </div>
              ))}
            </div>
          </section>

          {degraded && (
            <div className="bg-flag-tint rounded-xl px-5 py-4 font-mono text-[10.5px]
                            leading-[1.6] text-body">
              {degraded}
            </div>
          )}
        </div>
      </div>

      <footer className="shrink-0 border-t border-line px-[30px] py-3.5 flex
                         justify-between items-center bg-white">
        <div className="flex gap-2 items-center">
          <span className="w-1.5 h-1.5 rounded-full bg-brand" aria-hidden />
          <span className="font-mono text-[9.5px] text-faint">
            gemma4:12b · embeddinggemma:300m · running on this machine
          </span>
        </div>
        <span className="font-mono text-[9.5px] text-faint">no transcript is sent anywhere</span>
      </footer>
    </div>
  );
}
