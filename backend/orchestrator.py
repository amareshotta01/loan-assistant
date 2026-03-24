# backend/orchestrator.py
import time
from backend.schemas import ChatResponse, DecisionModel, ToolResultsModel, RagMetadataModel, GuardrailsModel, LatencyModel
from backend import memory_store
from backend.adapters import guardrails_adapter, llm_adapter, rag_adapter, tools_adapter

async def handle_chat(session_id: str, message: str, metadata: dict = None) -> ChatResponse:
    t0 = time.time()
    agent_trace = []
    
    # 1. Input Guardrails
    verdict_in = guardrails_adapter.moderate_input(message)
    agent_trace.append({"step": "guardrails_input", "action": verdict_in["action"]})
    
    if verdict_in["action"] == "BLOCK":
        return _build_safe_response(session_id, "I'm sorry, I cannot process that request due to content policy.", verdict_in, t0)

    safe_message = verdict_in.get("redacted_text", message)

    # 2. Load Memory
    state = memory_store.load(session_id)
    agent_trace.append({"step": "memory_loaded", "status": "success"})

    # 3. Dummy Entity Extraction (You will replace this with an LLM call)
    # TODO: Use LLM to extract fields from safe_message and update state["entities"]
    
    missing_fields = [k for k, v in state["entities"].items() if v is None]

    # 4. Supervisor Router Logic
    rag_metadata = RagMetadataModel()
    tool_results = ToolResultsModel()
    decision = DecisionModel()
    t_retrieval_start = time.time()

    if missing_fields:
        # ROUTE A: Need More Info (Intake Agent)
        agent_trace.append({"step": "router", "decision": "INTAKE"})
        reply = f"To help you with your loan, I still need: {', '.join(missing_fields)}."
        decision.status = "NEED_MORE_INFO"
        t_llm = time.time() - t_retrieval_start 
        t_ret = 0.0

    elif "policy" in safe_message.lower() or "rule" in safe_message.lower():
        # ROUTE B: Policy Question (RAG)
        agent_trace.append({"step": "router", "decision": "RAG_QA"})
        raw_chunks = rag_adapter.retrieve(safe_message, k=4)
        t_ret = time.time() - t_retrieval_start
        
        rag_metadata = RagMetadataModel(used=True, top_k=len(raw_chunks), chunks=raw_chunks)
        reply = llm_adapter.answer_with_citations(safe_message, raw_chunks, state)
        t_llm = time.time() - (t_retrieval_start + t_ret)

    else:
        # ROUTE C: Decision & Tools
        agent_trace.append({"step": "router", "decision": "TOOLS_EVALUATION"})
        t_ret = 0.0
        t_llm_start = time.time()
        
        raw_tools = tools_adapter.run_all(state["entities"])
        tool_results = ToolResultsModel(**raw_tools)
        
        reply, decision_dict = llm_adapter.decide_and_explain(state, raw_tools)
        decision = DecisionModel(**decision_dict)
        t_llm = time.time() - t_llm_start

    # 5. Output Guardrails
    verdict_out = guardrails_adapter.moderate_output(reply)
    if verdict_out["action"] != "ALLOW":
        reply = verdict_out.get("safe_text", "Output redacted for safety.")

    # 6. Save Memory
    memory_store.save(session_id, state, summary_update=True)

    # 7. Construct Final Response
    t_total = time.time() - t0
    
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        decision=decision,
        collected_inputs=state["entities"],
        tool_results=tool_results,
        rag=rag_metadata,
        guardrails=GuardrailsModel(input_action=verdict_in["action"], output_action=verdict_out["action"], categories=verdict_in.get("categories", [])),
        agent_trace=agent_trace,
        latency_ms=LatencyModel(retrieval=round(t_ret*1000, 2), llm=round(t_llm*1000, 2), end_to_end=round(t_total*1000, 2))
    )

def _build_safe_response(session_id, reply, verdict, t0):
    """Helper to return a fast, safe response if guardrails block input."""
    t_total = time.time() - t0
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        decision=DecisionModel(),
        tool_results=ToolResultsModel(),
        rag=RagMetadataModel(),
        guardrails=GuardrailsModel(input_action=verdict["action"], categories=verdict.get("categories", [])),
        latency_ms=LatencyModel(end_to_end=round(t_total*1000, 2))
    )