"""
LangGraph StateGraph 工作流 — 完整实现
========================================
串联所有 Agent，根据 question_type 条件分流。

分流逻辑：
  ┌─────────────────────────────────────────────────────────┐
  │                        START                            │
  │                          │                              │
  │                       router                            │
  │                      ╱   │   ╲                          │
  │          concept/   │    │    │  practice                │
  │          problem    │    │    │                          │
  │                     │  review │                          │
  │                     │    │    │                          │
  │               retriever  │   ╭╯                         │
  │                     │  retriever                        │
  │                     │    │      quiz                     │
  │               explainer  │       │                      │
  │                     │  explainer  │                      │
  │                     │    │       │                      │
  │                     │   quiz     │                      │
  │                     │    │       │                      │
  │                   memory memory memory                  │
  │                          │                              │
  │                         END                             │
  └─────────────────────────────────────────────────────────┘

路径汇总：
  concept / problem → router → retriever → explainer → memory → END
  practice          → router → quiz → memory → END
  review            → router → retriever → explainer → quiz → memory → END
  meta / smalltalk  → router → meta → END

暴露接口：
  - run_workflow(state)    — 同步执行，返回最终 state
  - stream_workflow(state) — 异步流式，每个节点完成后 yield
"""

from __future__ import annotations

import time
from typing import Any, AsyncGenerator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger

from schemas.state import AgentState
from agents.router import router_agent
from agents.retriever import retriever_agent
from agents.explainer import explainer_agent
from agents.quiz import quiz_agent
from agents.memory import memory_agent
from agents.meta import meta_agent


# ============================================================
# 节点包装器：添加计时日志
# ============================================================

def _wrap_node(name: str, func):
    """
    为 Agent 函数添加前后日志和耗时统计。

    日志格式：
      [节点名] started
      [节点名] completed in X.XXs
    """

    def wrapper(state: AgentState) -> dict[str, Any]:
        logger.info(f"[{name}] started")
        t0 = time.perf_counter()

        try:
            result = func(state)
        except Exception as e:
            elapsed = time.perf_counter() - t0
            logger.error(f"[{name}] failed in {elapsed:.2f}s — {e}")
            raise

        elapsed = time.perf_counter() - t0
        logger.info(f"[{name}] completed in {elapsed:.2f}s")
        return result

    return wrapper


# ============================================================
# 条件路由函数
# ============================================================

def route_after_router(state: AgentState) -> str:
    """
    router 节点之后的条件分流。

    - concept / problem → retriever
    - practice          → quiz（跳过检索和讲解）
    - review            → retriever
    - meta / smalltalk  → meta_node
    """
    q_type = state.get("question_type", "concept")
    logger.info(f"🔀 route_after_router: question_type='{q_type}'")

    if q_type in {"meta", "smalltalk"}:
        return "meta_node"
    if q_type == "practice":
        return "quiz_gen"
    else:
        # concept / problem / review 都先走检索
        return "retriever"


def route_after_explainer(state: AgentState) -> str:
    """
    explainer 节点之后的条件分流。

    - review → quiz（复习需要出题巩固）
    - concept / problem → memory（直接收尾）
    """
    q_type = state.get("question_type", "concept")
    logger.info(f"🔀 route_after_explainer: question_type='{q_type}'")

    if q_type == "review":
        return "quiz_gen"
    else:
        return "memory_node"


# ============================================================
# 构建 StateGraph
# ============================================================

def _build_graph() -> StateGraph:
    """
    构建 LangGraph StateGraph 并编译。

    使用 MemorySaver checkpointer 实现会话持久化，
    thread_id 由调用方通过 config 传入（使用 session_id）。
    """

    graph = StateGraph(AgentState)

    # ---- 添加节点（带计时日志包装） ----
    graph.add_node("router",    _wrap_node("router",    router_agent))
    graph.add_node("retriever", _wrap_node("retriever", retriever_agent))
    graph.add_node("explain_node", _wrap_node("explain_node", explainer_agent))
    graph.add_node("quiz_gen",      _wrap_node("quiz_gen",      quiz_agent))
    graph.add_node("memory_node",    _wrap_node("memory_node",    memory_agent))
    graph.add_node("meta_node",      _wrap_node("meta_node",      meta_agent))

    # ---- 入口 ----
    graph.set_entry_point("router")

    # ---- 条件边：router → retriever / quiz ----
    graph.add_conditional_edges(
        source="router",
        path=route_after_router,
        path_map={
            "retriever": "retriever",
            "quiz_gen": "quiz_gen",
            "meta_node": "meta_node",
        },
    )

    # ---- 固定边：retriever → explainer ----
    graph.add_edge("retriever", "explain_node")

    # ---- 条件边：explainer → quiz / memory ----
    graph.add_conditional_edges(
        source="explain_node",
        path=route_after_explainer,
        path_map={
            "quiz_gen": "quiz_gen",
            "memory_node": "memory_node",
        },
    )

    # ---- 固定边：quiz → memory ----
    graph.add_edge("quiz_gen", "memory_node")

    # ---- 固定边：meta → END ----
    graph.add_edge("meta_node", END)

    # ---- 固定边：memory → END ----
    graph.add_edge("memory_node", END)

    # ---- Checkpointer（会话持久化） ----
    checkpointer = MemorySaver()

    # ---- 编译 ----
    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("✅ LangGraph 工作流编译完成（含 MemorySaver checkpointer）")

    return compiled


# ---- 模块级编译实例 ----
compiled_graph = _build_graph()


# ============================================================
# 对外接口：同步执行
# ============================================================

def run_workflow(state: AgentState) -> AgentState:
    """
    同步运行工作流，返回最终 state。

    Args:
        state: 初始 AgentState，至少包含 question, user_id, session_id

    Returns:
        完成所有节点后的最终 AgentState
    """
    session_id = state.get("session_id", "default")
    config = {
        "configurable": {
            "thread_id": session_id,
        }
    }

    logger.info(
        f"▶️ 工作流同步启动 | session={session_id} | "
        f"question='{state.get('question', '')[:60]}…'"
    )

    t0 = time.perf_counter()
    final_state = compiled_graph.invoke(state, config=config)
    elapsed = time.perf_counter() - t0

    logger.info(f"✅ 工作流同步完成 | 总耗时 {elapsed:.2f}s")
    return final_state


# ============================================================
# 对外接口：流式执行
# ============================================================

async def stream_workflow(
    state: AgentState,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    异步流式运行工作流，每个节点完成后 yield 当前增量 state。

    Yields:
        每次 yield 一个 dict:
        {
            "node": str,           # 刚完成的节点名称
            "state_update": dict,  # 该节点写入 state 的增量字段
            "elapsed": float,      # 该节点耗时（秒）
        }

    Args:
        state: 初始 AgentState，至少包含 question, user_id, session_id
    """
    session_id = state.get("session_id", "default")
    config = {
        "configurable": {
            "thread_id": session_id,
        }
    }

    logger.info(
        f"▶️ 工作流流式启动 | session={session_id} | "
        f"question='{state.get('question', '')[:60]}…'"
    )

    total_t0 = time.perf_counter()

    # astream 会在每个节点完成后 yield { node_name: state_update }
    async for chunk in compiled_graph.astream(state, config=config):
        # chunk 是 { "node_name": { ...state_update... } }
        for node_name, state_update in chunk.items():
            logger.info(
                f"📡 流式输出 | node='{node_name}' | "
                f"keys={list(state_update.keys())}"
            )

            yield {
                "node": node_name,
                "state_update": state_update,
                "elapsed": round(time.perf_counter() - total_t0, 2),
            }

    total_elapsed = time.perf_counter() - total_t0
    logger.info(f"✅ 工作流流式完成 | 总耗时 {total_elapsed:.2f}s")
