import asyncio
import sys
import os
import json
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from app.services.agent.graph import get_compiled_graph
from app.core.config import get_settings

settings = get_settings()

TEST_CASES = [
    {
        "query": "What should I focus on today?",
        "expected_platforms": ["gmail", "google-calendar", "github"]
    },
    {
        "query": "What decisions were made recently?",
        "expected_keywords": ["decision", "approve", "agree", "conclude"]
    },
    {
        "query": "What follow-ups am I missing?",
        "expected_keywords": ["follow up", "action", "waiting"]
    },
    {
        "query": "Which tasks are blocked?",
        "expected_keywords": ["block", "stuck", "dependency"]
    },
    {
        "query": "What should I know before my next meeting?",
        "expected_platforms": ["google-calendar"]
    }
]

# Set up evaluator LLM using OpenRouter
evaluator_llm = ChatOpenAI(
    model="openai/gpt-4o-mini",
    openai_api_key=settings.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

async def evaluate_groundedness(answer: str, context: str) -> tuple[float, str]:
    if not context or "No data retrieved" in context:
        return 1.0, "No context retrieved, unable to measure hallucination."
        
    prompt = f"""You are an independent RAG evaluation judge. Your task is to evaluate the FAITHFULNESS / GROUNDEDNESS of a generated answer.
Compare the generated answer against the retrieved context chunks.
Count how many claims/facts in the answer are NOT present in the retrieved context. If any fact is fabricated (hallucinated), the score decreases.

Retrieved Context:
{context}

Generated Answer:
{answer}

Respond ONLY with a JSON object containing:
- "score": a float between 0.0 (fully hallucinated) and 1.0 (perfectly grounded in context)
- "reason": a short description of any unsupported claims found.

JSON:"""
    try:
        response = await evaluator_llm.ainvoke([SystemMessage(content=prompt)])
        clean_content = response.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_content)
        return float(data.get("score", 0.0)), data.get("reason", "")
    except Exception as e:
        return 0.0, f"Error evaluating: {e}"

async def evaluate_answer_relevance(query: str, answer: str) -> tuple[float, str]:
    prompt = f"""You are an independent RAG evaluation judge. Your task is to evaluate the ANSWER RELEVANCE.
Does the generated answer directly and completely address the user's query? 

User Query:
{query}

Generated Answer:
{answer}

Respond ONLY with a JSON object containing:
- "score": a float between 0.0 (completely irrelevant) and 1.0 (perfectly relevant and helpful)
- "reason": a short description of why the score was assigned.

JSON:"""
    try:
        response = await evaluator_llm.ainvoke([SystemMessage(content=prompt)])
        clean_content = response.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_content)
        return float(data.get("score", 0.0)), data.get("reason", "")
    except Exception as e:
        return 0.0, f"Error evaluating: {e}"

def evaluate_retrieval_relevance(chunks: list, expected_platforms: list = None, expected_keywords: list = None) -> float:
    if not chunks:
        return 0.0
    
    score = 1.0
    # Check expected platforms
    if expected_platforms:
        retrieved_platforms = {c.get("platform", "").lower() for c in chunks}
        matches = len(retrieved_platforms.intersection(set(expected_platforms)))
        score = matches / len(expected_platforms)
        
    return score

async def run_evaluation():
    print("Initializing evaluation...")
    graph = get_compiled_graph()
    
    results = []
    
    for idx, tc in enumerate(TEST_CASES, 1):
        query = tc["query"]
        print(f"\n[{idx}/{len(TEST_CASES)}] Query: {query}")
        
        # Invoke agent
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "user_query": query,
            "retrieved_context": [],
            "tool_calls_made": 0,
            "tool_error": None,
            "final_response": None,
        }
        
        t0 = time.perf_counter()
        agent_out = await graph.ainvoke(initial_state)
        elapsed = time.perf_counter() - t0
        
        answer = agent_out.get("final_response") or ""
        chunks = agent_out.get("retrieved_context") or []
        
        # Format chunks for context evaluation
        context_text = "\n\n".join([
            f"Chunk {i}: {c.get('chunk_text', '')}"
            for i, c in enumerate(chunks, 1)
        ])
        
        # 1. Retrieval Score
        retrieval_score = evaluate_retrieval_relevance(
            chunks, 
            expected_platforms=tc.get("expected_platforms"),
            expected_keywords=tc.get("expected_keywords")
        )
        
        # 2. Groundedness Score
        groundedness_score, groundedness_reason = await evaluate_groundedness(answer, context_text)
        
        # 3. Answer Relevance Score
        relevance_score, relevance_reason = await evaluate_answer_relevance(query, answer)
        
        print(f"  Execution Time    : {elapsed:.2f}s")
        print(f"  Retrieval Score   : {retrieval_score:.2f}")
        print(f"  Groundedness Score: {groundedness_score:.2f} (Reason: {groundedness_reason})")
        print(f"  Answer Relevance  : {relevance_score:.2f} (Reason: {relevance_reason})")
        
        results.append({
            "query": query,
            "retrieval_score": retrieval_score,
            "groundedness_score": groundedness_score,
            "relevance_score": relevance_score,
            "elapsed": elapsed
        })
        
    # Summarize
    avg_retrieval = sum(r["retrieval_score"] for r in results) / len(results)
    avg_groundedness = sum(r["groundedness_score"] for r in results) / len(results)
    avg_relevance = sum(r["relevance_score"] for r in results) / len(results)
    
    print("\n" + "="*40)
    print("EVALUATION SUMMARY REPORT")
    print("="*40)
    print(f"Average Retrieval Relevance: {avg_retrieval:.2f}")
    print(f"Average Groundedness       : {avg_groundedness:.2f}")
    print(f"Average Answer Relevance   : {avg_relevance:.2f}")
    print("="*40)

if __name__ == "__main__":
    asyncio.run(run_evaluation())
