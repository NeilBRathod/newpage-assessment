import type { Meeting } from "../api";
import { initials } from "../lib/answer";

type Filter = "all" | "cited";

interface Props {
  meetings: Meeting[];
  citedMeetingIds: Set<string>;
  citationCounts: Map<string, number>;
  selectedIds: string[];
  filter: Filter;
  onFilterChange: (filter: Filter) => void;
  onToggleSelect: (id: string) => void;
  onOpenBrief: (id: string) => void;
  totalUtterances: number;
  totalSpeakers: number;
}

const CHIP_PALETTE = ["#ececec", "#e6f4f3", "#f2f2f2"];

export function MeetingRail({
  meetings, citedMeetingIds, citationCounts, selectedIds, filter,
  onFilterChange, onToggleSelect, onOpenBrief, totalUtterances, totalSpeakers,
}: Props) {
  const visible = filter === "cited"
    ? meetings.filter((m) => citedMeetingIds.has(m.id))
    : meetings;

  return (
    <aside className="w-[278px] shrink-0 bg-white border-r border-line flex flex-col overflow-hidden">
      <div className="px-[18px] pt-5 pb-3.5 flex flex-col gap-3">
        <div className="flex flex-col gap-0.5">
          <h1 className="text-[17px] font-semibold tracking-[-0.01em]">Minutes</h1>
          <p className="font-mono text-[9.5px] text-faint">
            {meetings.length} meetings · {totalUtterances} turns · {totalSpeakers} speakers
          </p>
        </div>

        <div className="flex gap-1.5">
          <FilterPill active={filter === "all"} onClick={() => onFilterChange("all")}>
            All {meetings.length}
          </FilterPill>
          <FilterPill
            active={filter === "cited"}
            onClick={() => onFilterChange("cited")}
            disabled={citedMeetingIds.size === 0}
          >
            Cited {citedMeetingIds.size}
          </FilterPill>
        </div>
      </div>

      <div className="px-3 pb-3 flex flex-col gap-1.5 overflow-y-auto scroll-quiet">
        {visible.map((meeting) => (
          <MeetingCard
            key={meeting.id}
            meeting={meeting}
            cited={citedMeetingIds.has(meeting.id)}
            citationCount={citationCounts.get(meeting.id) ?? 0}
            selected={selectedIds.includes(meeting.id)}
            onClick={() => onToggleSelect(meeting.id)}
            onOpenBrief={() => onOpenBrief(meeting.id)}
          />
        ))}
        {visible.length === 0 && (
          <p className="px-3 py-6 text-[12px] text-faint leading-relaxed">
            No meetings fed the last answer.
          </p>
        )}
      </div>

      <div className="mt-auto px-[18px] py-3.5 border-t border-line flex gap-2 items-center">
        <span className="w-1.5 h-1.5 rounded-full bg-brand shrink-0" aria-hidden />
        <p className="font-mono text-[9px] text-faint leading-snug">
          gemma4:12b — nothing
          <br />
          leaves this machine
        </p>
      </div>
    </aside>
  );
}

function FilterPill({
  active, disabled, onClick, children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`text-[11.5px] font-medium px-3 py-[5px] rounded-full transition-colors ${
        active
          ? "bg-brand text-white"
          : disabled
            ? "bg-surface text-faint cursor-not-allowed"
            : "bg-surface text-soft hover:bg-line"
      }`}
    >
      {children}
    </button>
  );
}

function MeetingCard({
  meeting, cited, citationCount, selected, onClick, onOpenBrief,
}: {
  meeting: Meeting;
  cited: boolean;
  citationCount: number;
  selected: boolean;
  onClick: () => void;
  onOpenBrief: () => void;
}) {
  const shown = meeting.participants.slice(0, 4);
  const overflow = meeting.participants.length - shown.length;

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`text-left p-3 rounded-xl border transition-colors ${
        selected
          ? "bg-brand-tint border-brand-mid"
          : cited
            ? "bg-white border-line hover:bg-raised"
            : "bg-white border-white hover:bg-raised"
      }`}
    >
      <div className="flex justify-between items-baseline gap-2">
        <span
          className={`text-[13px] leading-snug ${
            selected || cited ? "font-semibold text-ink" : "font-medium text-muted"
          }`}
        >
          {meeting.title}
        </span>
        {cited && (
          <span className="font-mono text-[9px] font-medium text-white bg-flag px-1.5 rounded-full shrink-0">
            {citationCount}
          </span>
        )}
      </div>

      <div className="flex justify-between items-center mt-2">
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            onOpenBrief();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.stopPropagation();
              onOpenBrief();
            }
          }}
          className="font-mono text-[9px] text-faint hover:text-brand transition-colors mr-2"
        >
          brief →
        </span>
        <div className="flex" aria-label={meeting.participants.join(", ")}>
          {shown.map((name, i) => (
            <span
              key={name}
              className="w-[19px] h-[19px] rounded-full font-mono text-[8px] font-medium
                         flex items-center justify-center -mr-1 border-[1.5px] text-soft"
              style={{
                background: CHIP_PALETTE[i % CHIP_PALETTE.length],
                borderColor: selected ? "#e6f4f3" : "#fff",
              }}
            >
              {initials(name)}
            </span>
          ))}
          {overflow > 0 && (
            <span
              className="w-[19px] h-[19px] rounded-full font-mono text-[8px] font-medium
                         flex items-center justify-center -mr-1 border-[1.5px] bg-line text-soft"
              style={{ borderColor: selected ? "#e6f4f3" : "#fff" }}
            >
              +{overflow}
            </span>
          )}
        </div>
        <span className="font-mono text-[9px] text-faint">
          {formatDate(meeting.meeting_date)} · {meeting.utterance_count}
        </span>
      </div>
    </button>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(`${iso}T00:00:00`);
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}
