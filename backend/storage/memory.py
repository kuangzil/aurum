import asyncio
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from backend.config import Settings
from backend.storage.cache import SemanticCache
from backend.storage.embeddings import Embeddings, FakeEmbeddings, LocalEmbeddings
from backend.storage.sqlite import Database, MessageRepository
from backend.storage.vectors import ChromaMemory
from backend.trace import Reporter, TraceEvent, logger, no_report


def time_sensitive(query: str) -> bool:
    # Conservative: all price/quote requests and temporal follow-ups bypass conversation cache.
    return bool(re.search(r'\b(price|prices|quote|spot|current|currently|latest|now|today|live|worth|cost|value)\b|最新|当前|现在|今日|今天|现价|金价', query, re.I))


def context_payload(messages: list[dict], max_chars: int) -> tuple[str, list[str]]:
    text, ids = '', []
    for message in messages:
        prefix = f"[{message['created_at_utc']} {message['role']} {message['message_id']}] "
        available = max_chars - len(text) - len(prefix) - 1
        if available <= 0:
            break
        content = message['content'][:available]
        text += prefix + content + '\n'
        ids.append(message['message_id'])
    return text, ids


@dataclass
class WorkingMemoryEntry:
    """Resolved SQLite messages plus why they entered this session's context."""
    session_id: str
    query: str
    revision: tuple
    messages: dict[str, dict]
    sources: dict[str, str]


class WorkingMemory:
    """Small, session-scoped working set; it stores text snapshots, never answers."""
    # Deliberately narrow grammar: an ordinal risk question with no new subject/scope.
    ORDINAL = re.compile(
        r"(?:what risks? (?:does|did) the (first|second|third|[1-9][0-9]*) (?:one|strategy) have[?.]?|"
        r"第([一二三四五六七八九十]|[1-9][0-9]*)个策略(?:有什么|有哪些)风险[？?]?)", re.I
    )

    @classmethod
    def coverage(cls, query: str, entry: WorkingMemoryEntry) -> str:
        match = cls.ORDINAL.fullmatch(query.strip())
        if not match:
            return 'unsupported_reference_or_new_scope'
        ordinal = match.group(1) or match.group(2)
        numbers = {'first': 1, 'second': 2, 'third': 3,
                   **dict(zip('一二三四五六七八九十', range(1, 11)))}
        number = numbers.get(ordinal.lower()) or int(ordinal)
        # An ordinal refers to an explicit numbered item, never retrieval rank.
        candidates = []
        for row in entry.messages.values():
            items = list(re.finditer(r'(?m)^\s*(\d+)[.)、]\s*(.+)$', row['content']))
            if items and [int(item.group(1)) for item in items] == list(range(1, len(items) + 1)):
                candidates.extend(item.group(2) for item in items if int(item.group(1)) == number)
        if len(candidates) != 1:
            return 'missing_or_ambiguous_ordinal'
        item = candidates[0]
        risk = re.search(r'(?:risks?|风险|風險)\s*[:：]\s*(.+)', item, re.I)
        if not risk or len(risk.group(1).strip()) < 8 or re.search(
                r'unknown|unspecified|not (?:known|provided)|missing|tbd|未知|未提供|不详', risk.group(1), re.I):
            return 'missing_risk_evidence'
        return 'covered_ordinal_risk'

    def __init__(self, max_sessions: int, max_messages: int, max_chars: int):
        self.max_sessions, self.max_messages = max_sessions, max_messages
        self.max_chars = max_chars
        self.entries: OrderedDict[str, WorkingMemoryEntry] = OrderedDict()
        self._lock = Lock()

    def get(self, session_id: str, query: str, revision: tuple) -> WorkingMemoryEntry | None:
        with self._lock:
            entry = self.entries.get(session_id)
            reason = 'missing'
            if entry:
                if entry.revision[:2] != revision[:2]:
                    reason = 'message_revision_changed'
                else:
                    reason = self.coverage(query, entry)
                if reason == 'message_revision_changed':
                    del self.entries[session_id]
                if reason == 'covered_ordinal_risk':
                    self.entries.move_to_end(session_id)
                    return entry
            logger.info('working_memory_miss reason=%s cached_revision=%s current_revision=%s',
                        reason, entry.revision if entry else None, revision)
            return None

    def put(self, session_id: str, query: str, revision: tuple, messages: list[dict],
            sources: dict[str, str]) -> None:
        unique = {row['message_id']: dict(row) for row in messages}
        selected = unique
        if (not selected or len(selected) > self.max_messages or
                sum(len(row['content']) for row in selected.values()) > self.max_chars):
            self.invalidate(session_id)
            logger.info('working_memory_miss reason=incomplete_or_oversized_context')
            return
        with self._lock:
            self.entries[session_id] = WorkingMemoryEntry(
                session_id, query, revision, selected,
                {mid: sources.get(mid, 'recent_history') for mid in selected},
            )
            self.entries.move_to_end(session_id)
            while len(self.entries) > self.max_sessions:
                self.entries.popitem(last=False)

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            self.entries.pop(session_id, None)



class MemoryService:
    def __init__(self, settings: Settings, messages: MessageRepository,
                 embeddings: Embeddings | None = None, vectors: ChromaMemory | None = None):
        self.settings, self.messages = settings, messages
        self.embeddings = embeddings or (
            FakeEmbeddings() if settings.memory_embedding_adapter == 'fake'
            else LocalEmbeddings(settings.memory_embedding_model)
        )
        if isinstance(self.embeddings, FakeEmbeddings):
            logger.warning('memory_embedding_adapter=fake: test-only vectors, not production semantic retrieval')
        self.vectors = vectors or ChromaMemory(settings.chroma_path, self.embeddings)
        self.cache = SemanticCache(settings.memory_cache_max_entries,
                                   settings.memory_cache_similarity_threshold)
        self.working = WorkingMemory(settings.memory_working_max_sessions,
                                     settings.memory_working_max_messages,
                                     settings.memory_working_max_chars)
        self.stats = {'working_memory_hits': 0, 'exact_cache_hits': 0, 'semantic_cache_hits': 0,
                      'chroma_calls': 0, 'retrieval_skips': 0}
        self._stats_lock = Lock()

    def statistics(self) -> dict[str, int]:
        with self._stats_lock:
            return dict(self.stats)

    def _increment(self, key: str) -> None:
        with self._stats_lock:
            self.stats[key] += 1

    def completed_turn(self, session_id: str, query: str, user_message_id: str,
                       assistant_message_id: str) -> None:
        # Only the expected turn's two writes may advance the working revision.
        base, revision = self.messages.turn_revisions(session_id, user_message_id, assistant_message_id)
        answer = self.messages.get(session_id, assistant_message_id)
        with self.working._lock:
            entry = self.working.entries.get(session_id)
            if not entry:
                return
            if entry.revision[:2] != base[:2]:
                self.working.entries.pop(session_id, None)
                logger.info('working_memory_miss reason=concurrent_turn')
                return
            answer_items = re.findall(r'(?m)^\s*\d+[.)、].+$', answer['content']) if answer else []
            source_lists = [re.findall(r'(?m)^\s*\d+[.)、].+$', row['content'])
                            for row in entry.messages.values()]
            same_order = any(len(items) == len(answer_items) and all(
                a.strip().startswith(b.strip()) for a, b in zip(answer_items, items))
                for items in source_lists)
            if answer_items and not same_order:
                # A generated list may reorder the retrieved strategies. Without
                # explicit item-to-source mapping, the next ordinal is ambiguous.
                self.working.entries.pop(session_id, None)
                logger.info('working_memory_miss reason=answer_changes_ordinal_context')
                return
            # Preserve the original evidence rather than replacing it with a generated answer.
            entry.revision = revision


    def index(self, message: dict) -> bool:
        try:
            self.vectors.upsert(message)
        except Exception as exc:
            # External embedding/index libraries have heterogeneous exceptions. Raw text remains durable.
            logger.warning('memory_index_failed message_id=%s error_type=%s', message['message_id'], type(exc).__name__)
            self.messages.mark_indexed(message['message_id'], False)
            return False
        self.messages.mark_indexed(message['message_id'], True)
        return True

    def reconcile(self, session_id: str | None = None, limit: int = 100) -> int:
        count = 0
        for message in self.messages.pending(session_id, limit):
            if not self.index(message):
                break  # Bound work during a model/index outage; next request/CLI can retry.
            count += 1
        return count

    async def build_context(self, session_id: str, query: str, exclude_id: str = '',
                            report: Reporter = no_report) -> dict:
        started = time.perf_counter()
        async def event(stage: str, detail: str):
            await report(TraceEvent(agent='research', stage=stage, detail=detail))

        empty = {'retrieved_context': '', 'context_source': 'empty', 'retrieved_message_ids': [],
                 'recent_history': '', 'recent_message_ids': [], 'similarity_scores': []}
        fresh_query = time_sensitive(query)

        if fresh_query:
            self.working.invalidate(session_id)
            await event('context_cache_miss', 'Freshness policy bypasses conversation memory')
            await event('context_rag_miss', 'Read current market observations separately')
            await event('memory_route', 'memory_route=market_data; retrieval_skipped=True; '
                        'retrieval_latency_ms=0; context_message_count=0')
            await event('context_build_complete', 'No historical conversation used as current evidence')
            return dict(empty, memory_route='market_data', retrieval_skipped=True,
                        retrieval_latency_ms=0, context_message_count=0, message_sources={})

        await asyncio.to_thread(self.reconcile, session_id)
        revision = await asyncio.to_thread(self.messages.revision, session_id, exclude_id)
        working = None if fresh_query else self.working.get(session_id, query, revision)
        if working:
            for mid, snapshot in working.messages.items():
                row = await asyncio.to_thread(self.messages.get, session_id, mid)
                if (row is None or mid == exclude_id or any(row[key] != snapshot[key]
                        for key in ('content', 'role', 'created_at_utc', 'session_id')) or
                        working.sources.get(mid) not in ('chroma', 'recent_history')):
                    logger.info('working_memory_miss reason=authoritative_message_changed')
                    self.working.invalidate(session_id)
                    working = None
                    break
        if working:
            required = sum(len(row['content']) + len(row['created_at_utc']) + len(row['role']) +
                           len(row['message_id']) + 6 for row in working.messages.values())
            if required > self.settings.memory_max_context_chars * 3 // 4:
                logger.info('working_memory_miss reason=context_budget_insufficient')
                working = None
        if working:
            ids = list(working.messages)
            context_rows = [working.messages[mid] for mid in ids]
            context, context_ids = context_payload(context_rows, self.settings.memory_max_context_chars * 3 // 4)
            await event('memory_route', f'memory_route=working_memory; retrieval_skipped=True; '
                        f'retrieval_latency_ms={(time.perf_counter() - started) * 1000:.3f}; '
                        f'context_message_count={len(context_ids)}')
            await event('context_build_complete', f'{len(context_ids)} messages; source=working_memory')
            self._increment('working_memory_hits')
            self._increment('retrieval_skips')
            return dict(empty, retrieved_context=context, context_source='working_memory',
                        retrieved_message_ids=context_ids,
                        recent_history='', recent_message_ids=[], similarity_scores=[],
                        memory_route='working_memory', retrieval_skipped=True,
                        retrieval_latency_ms=round((time.perf_counter() - started) * 1000, 3),
                        context_message_count=len(context_ids),
                        message_sources={mid: working.sources[mid] for mid in context_ids})

        hits, source = [], 'empty'
        force_chroma = bool(WorkingMemory.ORDINAL.fullmatch(query.strip()) or re.search(
            r'\b(?:document|source|new topic|since|between|during)\b|\d{4}|新文档|新文件|时间范围', query, re.I))
        try:
            vector = (await asyncio.to_thread(self.embeddings.embed, [query]))[0]
            cached = None if force_chroma else self.cache.get(session_id, query, vector, revision)
        except Exception as exc:
            logger.warning('memory_embedding_failed error_type=%s', type(exc).__name__)
            cached, vector = None, None
        if cached:
            hits, kind = cached
            source = f'cache_{kind}'
            self._increment('exact_cache_hits' if kind == 'exact' else 'semantic_cache_hits')
            self._increment('retrieval_skips')
            await event('context_cache_hit', f'{kind} session-scoped context match')
        else:
            await event('context_cache_miss', 'Freshness policy bypasses caches' if fresh_query
                        else 'No eligible cached context')
            if vector is not None:
                try:
                    self._increment('chroma_calls')
                    candidates = await asyncio.to_thread(self.vectors.search, session_id, vector,
                                                         self.settings.memory_top_k + 1)
                    hits = [(mid, score) for mid, score in candidates if mid != exclude_id and
                            score >= self.settings.memory_similarity_threshold][:self.settings.memory_top_k]
                except Exception as exc:
                    logger.warning('memory_retrieval_failed error_type=%s', type(exc).__name__)

        # Never trust Chroma documents or cache text: recheck session ownership in SQLite.
        authoritative, valid_hits = [], []
        for mid, score in hits:
            row = await asyncio.to_thread(self.messages.get, session_id, mid)
            if row and mid != exclude_id:
                authoritative.append(row)
                valid_hits.append((mid, score))
        if not cached:
            source = 'rag' if authoritative else 'empty'
            await event('context_rag_hit' if authoritative else 'context_rag_miss',
                        f'{len(authoritative)} relevant authoritative messages')
            if authoritative and not fresh_query:
                self.cache.put(session_id, query, vector, revision, valid_hits)

        # Share one strict character budget between semantic context and recent chronological history.
        budget = self.settings.memory_max_context_chars
        context, ids = context_payload(authoritative, budget * 3 // 4)
        recent = await asyncio.to_thread(self.messages.history, session_id,
                                        self.settings.memory_recent_messages, exclude_id)
        recent = [row for row in recent if row['message_id'] not in ids]
        history, recent_ids = context_payload(recent, budget - len(context))
        combined = authoritative + recent
        sources = {row['message_id']: 'chroma' for row in authoritative}
        sources.update({row['message_id']: 'recent_history' for row in recent})
        if not fresh_query:
            self.working.put(session_id, query, revision, combined, sources)
        route = f'{kind}_cache' if cached else 'chroma'
        await event('memory_route',
                    f'memory_route={route}; retrieval_skipped={bool(cached)}; '
                    f'retrieval_latency_ms={round((time.perf_counter() - started) * 1000, 3)}; '
                    f'context_message_count={len(ids) + len(recent_ids)}')
        await event('context_build_complete', f'{len(ids)} semantic and {len(recent_ids)} recent messages; source={source}')
        return dict(empty, retrieved_context=context, context_source=source, retrieved_message_ids=ids,
                    recent_history=history, recent_message_ids=recent_ids,
                    similarity_scores=[score for mid, score in valid_hits if mid in ids],
                    memory_route=route, retrieval_skipped=bool(cached),
                    retrieval_latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    context_message_count=len(ids) + len(recent_ids), message_sources=sources)


def make_memory(settings: Settings, db: Database | None = None) -> MemoryService:
    return MemoryService(settings, MessageRepository(db or Database(settings.sqlite_path)))
