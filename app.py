from flask import Flask
from models import init_db
import pandas as pd
import sqlite3
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from model.recommender import hybrid_recommendation

# Import blueprints
from routes.main_routes import main_bp
from routes.admin_routes import admin_bp
from routes.recommendation_routes import recommend_bp

app = Flask(__name__)
app.secret_key = "secret123"

# Register blueprints
app.register_blueprint(main_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(recommend_bp)

import math

def evaluate_recommendation_model(df, conn, k=5):
    test_cases = df.head(50)
    
    accuracies = []
    precisions = []
    recalls = []
    ndcgs = []
    
    for idx, test_row in test_cases.iterrows():
        pref = {
            'type': str(test_row.get('Type', '')).strip(),
            'budget': str(test_row.get('Budget', '')).strip(),
            'season': str(test_row.get('Season', '')).strip(),
            'interest': str(test_row.get('Interest', '')).strip()
        }
        target_type = pref['type']
        
        # Total relevant items in entire dataset for this query
        df['temp_rating'] = pd.to_numeric(df['Rating'], errors='coerce').fillna(0)
        total_relevant_count = len(df[(df['Type'].str.strip() == target_type) & (df['temp_rating'] >= 4.0)])
        df.drop(columns=['temp_rating'], inplace=True, errors='ignore')

        if total_relevant_count == 0:
            continue
            
        try:
            recs_df, _ = hybrid_recommendation("eval_user", pref, df.copy(), conn)
            top_k = pd.DataFrame() if recs_df is None or recs_df.empty else recs_df.head(k)
        except Exception:
            top_k = pd.DataFrame()
            
        relevant_in_top_k = 0
        dcg = 0.0
        
        for rank, (_, rec_row) in enumerate(top_k.iterrows(), start=1):
            rec_type = str(rec_row.get('Type', '')).strip()
            rec_rating = pd.to_numeric(rec_row.get('Rating', 0), errors='coerce')
            if pd.isna(rec_rating): rec_rating = 0
            
            if rec_type == target_type and rec_rating >= 4.0:
                relevant_in_top_k += 1
                dcg += 1.0 / math.log2(rank + 1)
                
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, total_relevant_count) + 1))
        
        ndcg = (dcg / idcg) if idcg > 0 else 0
        accuracy = 1 if relevant_in_top_k > 0 else 0
        precision = relevant_in_top_k / k
        recall = (relevant_in_top_k / total_relevant_count) if total_relevant_count > 0 else 0
        
        accuracies.append(accuracy)
        precisions.append(precision)
        recalls.append(recall)
        ndcgs.append(ndcg)
        
    avg_accuracy = (sum(accuracies) / len(accuracies) * 100) if accuracies else 0
    avg_precision = (sum(precisions) / len(precisions) * 100) if precisions else 0
    avg_recall = (sum(recalls) / len(recalls) * 100) if recalls else 0
    avg_ndcg = (sum(ndcgs) / len(ndcgs) * 100) if ndcgs else 0
    
    print(f"\n📊 Recommendation Metrics:")
    print(f"Accuracy@{k}  : {avg_accuracy:.2f}")
    print(f"Precision@{k} : {avg_precision:.2f}")
    print(f"Recall@{k}    : {avg_recall:.2f}")
    print(f"NDCG@{k}      : {avg_ndcg:.2f}\n")

if __name__ == "__main__":
    init_db()   # Initialize database on startup
    
    try:
        df = pd.read_csv("maharashtra_destinations.csv")
        df.columns = df.columns.str.strip()
        conn = sqlite3.connect("users.db")
        evaluate_recommendation_model(df, conn)
        conn.close()
    except Exception as e:
        print(f"Evaluation Error: {e}")
        
    app.run(debug=True)