"""Train and persist a grocery category text classifier."""

from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score
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
    accuracy = accuracy_score(y_test, predictions)

    return pipeline, accuracy


def save_model(pipeline, output_path):
    joblib.dump(pipeline, output_path)


def main():
    script_dir = Path(__file__).resolve().parent
    csv_path = script_dir / "grocery_data.csv"
    model_path = script_dir / "model.pkl"

    data = load_grocery_data(csv_path)
    pipeline, accuracy = train_and_evaluate(data)
    save_model(pipeline, model_path)

    print(f"Accuracy: {accuracy:.2%}")
    print(f"Saved model to {model_path}")


if __name__ == "__main__":
    main()
