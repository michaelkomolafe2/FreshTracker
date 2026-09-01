"""Train and persist a grocery category text classifier."""

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline


REQUIRED_COLUMNS = {"ingredient_name", "category"}
RANDOM_STATE = 42
TEST_SIZE = 0.2


def load_grocery_data(csv_path):
    data = pd.read_csv(csv_path)
    missing_columns = REQUIRED_COLUMNS.difference(data.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required column(s): {missing}")

    data = data.dropna(subset=["ingredient_name", "category"]).copy()
    data["ingredient_name"] = data["ingredient_name"].astype(str).str.strip()
    data["category"] = data["category"].astype(str).str.strip()
    data = data[(data["ingredient_name"] != "") & (data["category"] != "")]

    if data.empty:
        raise ValueError("No valid grocery rows found for training.")

    return data


def build_model_pipeline():
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(lowercase=True, ngram_range=(1, 2))),
            ("classifier", MultinomialNB()),
        ]
    )


def train_and_evaluate(data):
    X_train, X_test, y_train, y_test = train_test_split(
        data["ingredient_name"],
        data["category"],
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=data["category"],
    )

    pipeline = build_model_pipeline()
    pipeline.fit(X_train, y_train)
    predictions = pipeline.predict(X_test)
    metrics = {
        "dataset_row_count": len(data),
        "train_test_split_ratio": {
            "train": 1 - TEST_SIZE,
            "test": TEST_SIZE,
        },
        "overall_accuracy": float(accuracy_score(y_test, predictions)),
        "classification_report": classification_report(
            y_test,
            predictions,
            output_dict=True,
            zero_division=0,
        ),
    }

    return pipeline, metrics


def save_model(pipeline, output_path):
    joblib.dump(pipeline, output_path)


def save_metrics(metrics, output_path):
    with output_path.open("w", encoding="utf-8") as metrics_file:
        json.dump(metrics, metrics_file, indent=2, sort_keys=True)
        metrics_file.write("\n")


def main():
    script_dir = Path(__file__).resolve().parent
    csv_path = script_dir / "grocery_data.csv"
    model_path = script_dir / "model.pkl"
    metrics_path = script_dir / "metrics.json"

    data = load_grocery_data(csv_path)
    pipeline, metrics = train_and_evaluate(data)
    save_model(pipeline, model_path)
    save_metrics(metrics, metrics_path)

    print(f"Accuracy: {metrics['overall_accuracy']:.2%}")
    print(f"Saved model to {model_path}")
    print(f"Saved metrics to {metrics_path}")


if __name__ == "__main__":
    main()
