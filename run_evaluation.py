import json
import asyncio
import os
import time

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,
    faithfulness,
    context_recall,
    context_precision
)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from rag_pipeline import NormIQRAGPipeline

# Disable parallel tokenizers warning
os.environ["TOKENIZERS_PARALLELISM"] = "false"

async def generate_answers(limit=None):
    print("Initializing RAG Pipeline for Evaluation...")
    pipeline = NormIQRAGPipeline()
    
    print("Loading test dataset...")
    with open("data/test_qa_pairs.json", "r", encoding="utf-8") as f:
        qa_pairs = json.load(f)
        
    if limit is not None:
        qa_pairs = qa_pairs[:int(limit)]
        
    data_samples = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": []
    }
    
    total = len(qa_pairs)
    print(f"Beginning inference on {total} questions...")
    
    start_time = time.time()
    
    for i, item in enumerate(qa_pairs):
        question = item["question"]
        ground_truth = item["answer"]
        
        print(f"[{i+1}/{total}] Querying: {question[:60]}...")
        
        try:
            result = await pipeline.query(question)
            answer = result["answer"]
            contexts = result["contexts"]
            
            if not isinstance(contexts, list):
                contexts = []
                
        except Exception as e:
            print(f"Error querying pipeline: {e}")
            answer = "Error generating answer"
            contexts = []
            
        data_samples["question"].append(question)
        data_samples["answer"].append(answer)
        data_samples["contexts"].append(contexts)
        data_samples["ground_truth"].append(ground_truth)
        
        await asyncio.sleep(0.5)
        
    print(f"\\nInference completed. Handoff to RAGAS...")
    return data_samples

def run_ragas_evaluation(data_samples):
    print("\\nRunning native RAGAS Evaluation...")
    dataset = Dataset.from_dict(data_samples)
    
    # -----------------------------------------------------
    # Explicitly define evaluator models to prevent the 'embed_query' dependency bug
    # -----------------------------------------------------
    eval_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
    eval_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    
    # Check for newer RAGAS v0.2 wrappers, fallback to v0.1 standard kwargs
    try:
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        r_llm = LangchainLLMWrapper(eval_llm)
        r_emb = LangchainEmbeddingsWrapper(eval_embeddings)
    except ImportError:
        r_llm = eval_llm
        r_emb = eval_embeddings

    metrics = [
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall
    ]
    
    # Run the evaluation with explicitly mapped dependencies
    try:
        score = evaluate(
            dataset, 
            metrics=metrics,
            llm=r_llm,
            embeddings=r_emb
        )
    except Exception as e:
        # Fallback if the legacy kwargs were required
        print(f"Ragas evaluator execution error: {e}. Attempting fallback...")
        score = evaluate(dataset, metrics=metrics)
        
    df_results = score.to_pandas()

    # Get scores from dataframe columns directly
    metric_cols = ["faithfulness", "answer_relevancy", 
               "context_precision", "context_recall"]
    summary_scores = {}
    for col in metric_cols:
        if col in df_results.columns:
            summary_scores[col] = round(float(df_results[col].mean()), 4)

    print("\n===========================================")
    print("RAGAS EVALUATION SCORES (CHAPTER 2 — HYDE ADDED)")
    print("===========================================")
    for k, v in summary_scores.items():
        print(f"{k}: {v}")

    output_data = {
        "summary_scores": summary_scores,
        "detailed_results": df_results.to_dict(orient="records")
    }
    
    with open("data/ragas_baseline_results.json", "w", encoding="utf-8") as f:
        # We use default=str for any remaining pandas nan values
        json.dump(output_data, f, indent=2, default=str)
        
    print("\\nResults saved to data/ragas_baseline_results.json")

if __name__ == "__main__":
    import sys
    limit = None
    if len(sys.argv) > 1:
        limit = int(sys.argv[1])
        
    # 1. Generate answers asynchronously
    samples = asyncio.run(generate_answers(limit))
    
    # 2. Run Ragas synchronously to prevent thread crashes
    run_ragas_evaluation(samples)
