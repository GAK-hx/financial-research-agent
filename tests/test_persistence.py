from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date
from uuid import uuid4

from financial_research_agent.config import Settings
try:
    from langgraph.types import Command
    from sqlalchemy import delete, text

    from financial_research_agent.harness.spike import (
        LangGraphSpike,
        graph_config,
        initial_spike_state,
    )
    from financial_research_agent.persistence.checkpoint import (
        BoundedSerializer,
        CheckpointPayloadTooLarge,
        build_checkpoint_serializer,
        postgres_checkpointer,
    )
    from financial_research_agent.persistence.database import (
        create_business_engine,
        create_session_factory,
    )
    from financial_research_agent.persistence.executor import PersistentPlanExecutor
    from financial_research_agent.persistence.models import (
        Base,
        RunRecord,
    )
    from financial_research_agent.persistence.store import (
        BusinessStore,
        OperationInProgress,
        PersistenceConflict,
    )
    from financial_research_agent.orchestration.executor import PlanExecutor
    from financial_research_agent.orchestration.interpreter import QueryInterpreter
    from financial_research_agent.orchestration.langgraph_runtime import (
        LangGraphResearchService,
    )
    from financial_research_agent.orchestration.planner import RulePlanner, StructuredPlanner
    from financial_research_agent.orchestration.registry import ToolRegistry
    from financial_research_agent.orchestration.validator import PlanValidator
    from tests.test_langgraph_spike import CountingFinancialTool
    from tests.test_langgraph_runtime import build_services

    PERSISTENCE_AVAILABLE = True
except ModuleNotFoundError:
    PERSISTENCE_AVAILABLE = False


POSTGRES_TESTS = (
    PERSISTENCE_AVAILABLE
    and os.environ.get("RUN_POSTGRES_TESTS", "").lower() in {"1", "true", "yes"}
)


class BytesSerializer:
    def dumps_typed(self, obj):
        return "bytes", bytes(obj)

    def loads_typed(self, data):
        return data[1]


@unittest.skipUnless(PERSISTENCE_AVAILABLE, "Persistence dependencies are isolated")
class SerializerTests(unittest.TestCase):
    def test_size_limit_rejects_oversized_payload(self) -> None:
        serializer = BoundedSerializer(BytesSerializer(), max_bytes=10)
        self.assertEqual(serializer.loads_typed(serializer.dumps_typed(b"12345")), b"12345")
        with self.assertRaises(CheckpointPayloadTooLarge):
            serializer.dumps_typed(b"01234567890")

    def test_encrypted_serializer_round_trip_and_wrong_key_failure(self) -> None:
        settings = Settings(
            checkpoint_encryption_enabled=True,
            checkpoint_aes_key="0123456789abcdef",
        )
        serializer = build_checkpoint_serializer(settings)
        payload = {"run_id": "encrypted", "values": [1, 2, 3]}
        encoded = serializer.dumps_typed(payload)
        self.assertNotIn(b"encrypted", encoded[1])
        self.assertEqual(serializer.loads_typed(encoded), payload)

        wrong = build_checkpoint_serializer(
            settings.model_copy(update={"checkpoint_aes_key": "fedcba9876543210"})
        )
        with self.assertRaises(Exception):
            wrong.loads_typed(encoded)


@unittest.skipUnless(POSTGRES_TESTS, "Set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class PostgresPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = Settings(
            checkpoint_backend="postgres",
            checkpoint_database_url=os.environ["CHECKPOINT_DATABASE_URL"],
            business_database_url=os.environ["BUSINESS_DATABASE_URL"],
            evaluation_reference_date=date(2026, 7, 15),
            max_tool_retries=0,
        )
        self.engine = create_business_engine(self.settings)
        self.store = BusinessStore(
            self.engine,
            create_session_factory(self.engine),
            worker_id=f"test-{uuid4().hex}",
            lease_seconds=1,
        )
        self.run_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with create_session_factory(self.engine).begin() as session:
            if self.run_ids:
                await session.execute(
                    delete(RunRecord).where(RunRecord.id.in_(self.run_ids))
                )
        await self.store.close()

    async def create_run(self) -> str:
        run_id = f"persist-{uuid4().hex}"
        self.run_ids.append(run_id)
        await self.store.create_run(run_id, run_id, "controlled", "langgraph")
        return run_id

    async def test_business_and_checkpoint_schemas_are_separate(self) -> None:
        async with self.engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public'"
                )
            )
            tables = {row[0] for row in rows}
        business = set(Base.metadata.tables)
        checkpoint = {
            "checkpoint_migrations",
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
        }
        self.assertTrue(business.issubset(tables))
        self.assertTrue(checkpoint.issubset(tables))
        self.assertTrue(business.isdisjoint(checkpoint))

    async def test_event_sequence_attempt_and_terminal_are_consistent(self) -> None:
        run_id = await self.create_run()
        await asyncio.gather(
            *(
                self.store.append_event(run_id, "concurrent", payload={"index": index})
                for index in range(10)
            )
        )
        attempt = await self.store.start_attempt(run_id, "plan")
        await self.store.finish_attempt(attempt, status="completed")
        payload = {"success": True, "run_id": run_id}
        self.assertTrue(await self.store.write_terminal(run_id, "completed", payload))
        self.assertFalse(await self.store.write_terminal(run_id, "completed", payload))
        with self.assertRaises(PersistenceConflict):
            await self.store.write_terminal(run_id, "failed", {"success": False})
        terminal = await self.store.get_terminal(run_id)
        self.assertEqual(terminal.result_payload, payload)

        async with self.engine.connect() as connection:
            sequences = (
                await connection.execute(
                    text(
                        "SELECT sequence FROM run_events "
                        "WHERE run_id=:run_id ORDER BY sequence"
                    ),
                    {"run_id": run_id},
                )
            ).scalars().all()
        self.assertEqual(sequences, list(range(1, len(sequences) + 1)))

    async def test_completed_tool_result_is_reused_without_second_call(self) -> None:
        run_id = await self.create_run()
        tool = CountingFinancialTool(delay=0)
        registry = ToolRegistry()
        registry.register(tool)
        planner = RulePlanner(registry)
        query = QueryInterpreter(today=date(2026, 7, 15)).interpret(
            "贵州茅台最近三年营收和利润"
        )
        plan = planner.create_plan(query)
        executor = PersistentPlanExecutor(
            PlanExecutor(registry, max_parallel=2, max_retries=0),
            self.store,
        )
        first = await executor.execute(run_id, plan)
        second = await executor.execute(run_id, plan)
        self.assertEqual(tool.calls, 1)
        self.assertEqual(
            [item.model_dump(mode="json") for item in first],
            [item.model_dump(mode="json") for item in second],
        )

    async def test_cancel_is_idempotent_and_active_lease_blocks_duplicate(self) -> None:
        run_id = await self.create_run()
        self.assertTrue(await self.store.request_cancel(run_id))
        self.assertFalse(await self.store.request_cancel(run_id))
        self.assertTrue(await self.store.is_cancel_requested(run_id))

        reservation = await self.store.reserve_tool_call(
            run_id=run_id,
            node_name="execute_tools",
            task_id="financial",
            tool_name="financial_metrics",
            idempotency_key=f"{run_id}:financial",
            input_payload={"symbol": "600519"},
        )
        self.assertTrue(reservation.execute)
        with self.assertRaises(OperationInProgress):
            await self.store.reserve_tool_call(
                run_id=run_id,
                node_name="execute_tools",
                task_id="financial",
                tool_name="financial_metrics",
                idempotency_key=f"{run_id}:financial",
                input_payload={"symbol": "600519"},
            )

    async def test_postgres_checkpoint_interrupt_survives_new_graph_instance(self) -> None:
        run_id = f"checkpoint-{uuid4().hex}"
        tool_one = CountingFinancialTool(delay=0)
        registry_one = ToolRegistry()
        registry_one.register(tool_one)
        spike_one = self._spike(registry_one)
        initial = initial_spike_state("贵州茅台最近三年营收和利润", run_id)
        config = graph_config(run_id)
        async with postgres_checkpointer(self.settings) as saver:
            graph = spike_one.build(saver, require_tool_approval=True)
            paused = await graph.ainvoke(initial, config)
            self.assertIn("__interrupt__", paused)
            self.assertEqual(tool_one.calls, 0)

        tool_two = CountingFinancialTool(delay=0)
        registry_two = ToolRegistry()
        registry_two.register(tool_two)
        spike_two = self._spike(registry_two)
        async with postgres_checkpointer(self.settings) as saver:
            graph = spike_two.build(saver, require_tool_approval=True)
            resumed = await graph.ainvoke(Command(resume=True), config)
            self.assertEqual(resumed["stage"], "completed")
            self.assertEqual(tool_two.calls, 1)
            replay = await graph.ainvoke(None, config)
            self.assertEqual(replay["stage"], "completed")
            self.assertEqual(tool_two.calls, 1)

    async def test_formal_run_replays_terminal_without_model_or_tool_call(self) -> None:
        run_id = f"formal-{uuid4().hex}"
        self.run_ids.append(run_id)
        first_parts = build_services()
        first_settings = first_parts[0].model_copy(
            update={
                "checkpoint_backend": "postgres",
                "checkpoint_database_url": self.settings.checkpoint_database_url,
                "business_database_url": self.settings.business_database_url,
            }
        )
        first = LangGraphResearchService(
            first_settings,
            orchestration=first_parts[3],
            reporting=first_parts[4],
        )
        initial_result = await first.analyze(
            "分析贵州茅台最近三年的营收和利润", run_id=run_id
        )
        await first.aclose()
        self.assertTrue(initial_result.success)
        self.assertEqual(first_parts[1].calls, 1)
        self.assertEqual(first_parts[2].calls, 1)

        second_parts = build_services()
        second_settings = second_parts[0].model_copy(
            update={
                "checkpoint_backend": "postgres",
                "checkpoint_database_url": self.settings.checkpoint_database_url,
                "business_database_url": self.settings.business_database_url,
            }
        )
        second = LangGraphResearchService(
            second_settings,
            orchestration=second_parts[3],
            reporting=second_parts[4],
        )
        replayed = await second.analyze(
            "分析贵州茅台最近三年的营收和利润", run_id=run_id
        )
        await second.aclose()
        self.assertEqual(
            initial_result.model_dump(mode="json"),
            replayed.model_dump(mode="json"),
        )
        self.assertEqual(second_parts[1].calls, 0)
        self.assertEqual(second_parts[2].calls, 0)

    def _spike(self, registry: ToolRegistry) -> LangGraphSpike:
        planner = StructuredPlanner(registry, RulePlanner(registry), provider=None)
        return LangGraphSpike(
            settings=self.settings,
            interpreter=QueryInterpreter(today=date(2026, 7, 15)),
            planner=planner,
            validator=PlanValidator(self.settings, registry),
            executor=PlanExecutor(registry, max_parallel=2, max_retries=0),
        )


if __name__ == "__main__":
    unittest.main()
