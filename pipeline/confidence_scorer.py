# Confidence scoring is implemented in retrieval/cohere_rerank.py
# Function: calculate_confidence
# Formula: (cohere_score x 0.50) + (retrieval_score x 0.50)