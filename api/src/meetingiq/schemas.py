"""API request and response shapes."""

from pydantic import BaseModel, Field

from meetingiq.retrieval.hybrid import RetrievedChunk


class ExcerptOut(BaseModel):
    """A retrieved excerpt, as the UI's evidence panel needs it."""

    index: int
    chunk_id: str
    meeting_id: str
    meeting_title: str
    meeting_date: str | None
    speakers: list[str]
    start_s: float
    end_s: float
    utterance_seqs: list[int]
    text: str
    # Kept in the response so retrieval is inspectable from the UI rather than
    # only from the logs.
    vector_rank: int | None
    text_rank: int | None
    vector_similarity: float | None
    rrf_score: float

    @classmethod
    def from_chunk(cls, index: int, chunk: RetrievedChunk) -> "ExcerptOut":
        return cls(
            index=index,
            chunk_id=chunk.chunk_id,
            meeting_id=chunk.meeting_id,
            meeting_title=chunk.meeting_title,
            meeting_date=chunk.meeting_date,
            speakers=chunk.speakers,
            start_s=chunk.start_s,
            end_s=chunk.end_s,
            utterance_seqs=chunk.utterance_seqs,
            text=chunk.text,
            vector_rank=chunk.vector_rank,
            text_rank=chunk.text_rank,
            vector_similarity=chunk.vector_similarity,
            rrf_score=chunk.rrf_score,
        )


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # An explicit UI selection, stronger than anything inferred from wording.
    meeting_ids: list[str] = Field(default_factory=list)
    stream: bool = True


class AskResponse(BaseModel):
    question: str
    answer: str
    refused: bool
    refusal_reason: str | None
    citations: list[int]
    excerpts: list[ExcerptOut]
    filters_applied: str
    top_similarity: float | None
    retrieval_ms: int
    generation_ms: int


class MeetingSummary(BaseModel):
    id: str
    title: str
    meeting_date: str | None
    participants: list[str]
    duration_s: float | None
    utterance_count: int
    chunk_count: int
    source_format: str


class UtteranceOut(BaseModel):
    seq: int
    speaker: str
    start_s: float
    end_s: float
    text: str


class TranscriptOut(BaseModel):
    meeting: MeetingSummary
    utterances: list[UtteranceOut]


class GroundedOut(BaseModel):
    """An extracted record and where it came from.

    `utterance_seq` is null when the model's quote could not be found in the
    transcript. The UI shows that state rather than hiding it — an unverifiable
    item is exactly the one a reader should look at hardest.
    """

    quote: str
    utterance_seq: int | None
    speaker: str | None
    start_s: float | None

    @property
    def grounded(self) -> bool:
        return self.utterance_seq is not None


class DecisionOut(GroundedOut):
    id: str
    text: str


class ActionItemOut(GroundedOut):
    id: str
    description: str
    owner: str
    due: str | None
    meeting_id: str
    meeting_title: str
    meeting_date: str | None


class BriefOut(BaseModel):
    meeting: MeetingSummary
    summary: str
    decisions: list[DecisionOut]
    action_items: list[ActionItemOut]
    extracted_at: str | None
    # How many of this brief's items could be traced back to a real turn.
    grounded_count: int
    total_count: int


class OwnerActions(BaseModel):
    owner: str
    items: list[ActionItemOut]


class ActionBoard(BaseModel):
    owners: list[OwnerActions]
    total: int
    ungrounded: int
